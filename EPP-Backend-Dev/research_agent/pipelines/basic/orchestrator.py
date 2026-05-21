"""
Basic 编排器 — 用户请求的唯一直接编排入口。

职责概要
--------
1. 使用 **Smart Planner**（``smart_planner``）将用户输入拆解为有序子任务：
   ``chat`` | ``search`` | ``agent``（首轮可只写 ``intent``，将 ``query`` / ``delegate_prompt`` / ``prompt`` 留空）。
2. **顺序执行**子任务；从第 2 步起，若当前步缺少可执行参数，则调用 **步间轻量补参**
   （``step_refill``）结合 ``basic_chain_context`` 与上一步输出写入 ``smart_plan``。
3. 每一步将前面所有步骤的文本结果写入 ``basic_chain_context``，
   供后续 LLM / 检索 / agent 子任务使用。
4. ``agent`` 步骤：调用 ``agent_orchestrator.run_workspace_delegate``，同步等待结束后
   再继续下一步。

与 **深度研究**（``orchestrator.execute_deep_research_pipeline``）无调用关系；
深度研究仅通过独立 API 启动。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

from research_agent.llm_client import (
    bind_usage_accumulator,
    chat_completion,
    reset_usage_accumulator,
    usage_total_tokens,
)
from research_agent.models import BasicOrchestratorRun, ResearchMessage, ResearchSession
from research_agent.pipelines.audit import append_behavior_log
from research_agent.pipelines.common import (
    iso_ts,
    latest_user_query,
    runtime_config,
    task_for_update,
    update_runtime_config,
)
from research_agent.pipelines.workspace.agent import run_workspace_delegate
from research_agent.prompts import BASIC_CHAT_SYSTEM_PROMPT, BASIC_CHAT_USER_PROMPT

from . import step_refill
from .planner import detect_smart_plan, fallback_chat_plan
from .session_context import session_context_for_prompts


def _append_step(task: BasicOrchestratorRun, phase: str, title: str, detail: str) -> None:
    task.step_seq += 1
    steps = list(task.steps or [])
    steps.append(
        {
            "seq": task.step_seq,
            "phase": phase,
            "title": title,
            "detail": detail,
            "ts": iso_ts(),
        }
    )
    task.steps = steps
    print(
        f"[research_agent][basic][task={task.id}] step#{task.step_seq} "
        f"phase={phase} title={title} detail={detail[:200]}",
        flush=True,
    )


def _emit_basic_admin_audit(
    task: BasicOrchestratorRun,
    *,
    operation_type: str,
    title: str,
    detail: str,
    step_index: int | None = None,
    request_payload: dict | None = None,
    status: str = "ok",
) -> None:
    """管理端专用：记录用户不可见的编排内部过程（不写用户可见 steps 镜像）。"""
    try:
        audit: dict[str, Any] = {
            "operation_type": operation_type,
            "tool_type": "basic_orchestrator",
            "status": status,
        }
        if step_index is not None:
            audit["step_id"] = step_index
        if request_payload:
            audit["request_payload"] = request_payload
        append_behavior_log(task, "basic_admin", title, detail[:8000], audit=audit)
    except Exception:  # noqa: BLE001 — 审计写入失败不得中断编排
        pass


def _fail_task(task: BasicOrchestratorRun, code: str, message: str) -> None:
    print(
        f"[research_agent][basic][task={task.id}] 任务失败 code={code} message={message}",
        flush=True,
    )
    task.status = "failed"
    task.error_code = code
    task.error_message = message
    task.save(
        update_fields=[
            "status",
            "error_code",
            "error_message",
            "step_seq",
            "steps",
            "result_payload",
            "updated_at",
        ]
    )


def _last_step_output(step_outputs: list[Any]) -> tuple[str, str, str]:
    if not step_outputs:
        return "", "", ""
    last = step_outputs[-1]
    if not isinstance(last, dict):
        return "", "", ""
    return (
        str(last.get("step_type") or "").strip(),
        str(last.get("title") or "").strip(),
        str(last.get("text") or "").strip(),
    )


def _workspace_refs_list(cfg: dict[str, Any]) -> list[dict[str, str]]:
    raw = cfg.get("workspace_refs")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for x in raw:
        if isinstance(x, dict) and str(x.get("rel_path") or "").strip():
            out.append(
                {
                    "kind": str(x.get("kind") or "file").strip().lower(),
                    "rel_path": str(x.get("rel_path") or "").strip(),
                    "label": str(x.get("label") or "").strip(),
                }
            )
    return out


def _chain_context_from_cfg(cfg: dict[str, Any]) -> str:
    raw = cfg.get("basic_chain_context")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "（尚无前置子任务输出）"


def _append_chain_segment(cfg: dict[str, Any], *, title: str, step_type: str, body: str) -> str:
    prev = _chain_context_from_cfg(cfg)
    seg = f"\n\n### [{step_type}] {title}\n{body.strip()}"
    return (prev + seg).strip() if prev != "（尚无前置子任务输出）" else seg.strip()


def _execute_chat_step(
    *,
    task: BasicOrchestratorRun,
    user_query: str,
    prior_context: str,
    step: dict[str, Any],
    session_context: str = "",
    step_index: int | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    title = str(step.get("title") or "对话回复").strip()
    instruction = str(step.get("prompt") or "").strip()
    started = time.monotonic()
    sc = (session_context or "").strip() or "（无）"
    user_prompt = BASIC_CHAT_USER_PROMPT.format(
        query=user_query.strip() or "(用户原始请求未记录)",
        session_context=sc,
        prior_context=prior_context or "（无）",
        title=title,
        instruction=instruction or "(规划者未提供具体指令，请直接基于原始请求与前置结果给出回复)",
    )
    res = chat_completion(
        system_prompt=BASIC_CHAT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.4,
        max_tokens=1600,
        enable_thinking=False,
        stream=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        _emit_basic_admin_audit(
            task,
            operation_type="basic_chat",
            title=f"Chat 子任务：{title}",
            detail=(
                f"【系统提示】\n{BASIC_CHAT_SYSTEM_PROMPT}\n\n"
                f"【用户提示】\n{user_prompt}\n\n"
                f"【失败】{res.error_code}: {res.error_message}"
            ),
            request_payload={"latency_ms": elapsed_ms, "title": title},
            step_index=step_index,
            status="failed",
        )
        return None, {
            "code": res.error_code or "BASIC_CHAT_FAILED",
            "message": res.error_message or "对话生成失败",
        }
    text = (res.content or "").strip()
    if not text:
        _emit_basic_admin_audit(
            task,
            operation_type="basic_chat",
            title=f"Chat 子任务：{title}",
            detail=f"【用户提示】\n{user_prompt}\n\n【失败】输出为空",
            request_payload={"latency_ms": elapsed_ms},
            step_index=step_index,
            status="failed",
        )
        return None, {"code": "BASIC_CHAT_EMPTY", "message": "对话生成内容为空"}
    _emit_basic_admin_audit(
        task,
        operation_type="basic_chat",
        title=f"Chat 子任务：{title}",
        detail=(
            f"【系统提示】\n{BASIC_CHAT_SYSTEM_PROMPT}\n\n"
            f"【用户提示】\n{user_prompt}\n\n"
            f"【模型输出】\n{text}"
        ),
        request_payload={"latency_ms": elapsed_ms, "title": title, "output_chars": len(text)},
        step_index=step_index,
    )
    print(
        f"[research_agent][basic][task={task.id}] chat 步骤完成 latency_ms={elapsed_ms} chars={len(text)}",
        flush=True,
    )
    return text, None


def _search_result_markdown(
    *,
    step_title: str,
    query: str,
    res: Any,
    citation_count: int,
) -> str:
    from research_agent.tools.base import WebSearchResult

    if not isinstance(res, WebSearchResult):
        return f"## {step_title}\n\n- 查询：{query}\n\n（检索返回格式异常）"
    lines = [f"## {step_title}", "", f"- 检索查询：{query}", ""]
    if res.summary:
        lines.extend([str(res.summary).strip(), ""])
    if not res.ok:
        lines.append(f"检索未成功：{res.error_message or res.error_code or 'unknown'}")
        return "\n".join(lines).strip()
    cites = res.citations or []
    if not cites:
        lines.append("（未返回文献条目；可尝试更换关键词或检查 RA_WEB_SEARCH_PROVIDER 等配置。）")
        body = "\n".join(lines).strip()
    else:
        lines.append("### 候选文献")
        for i, c in enumerate(cites[:40], 1):
            if not isinstance(c, dict):
                continue
            t = str(c.get("title") or "").strip() or "(无标题)"
            u = str(c.get("url") or "").strip()
            sn = str(c.get("snippet") or "").strip()
            src = str(c.get("source") or "").strip()
            lines.append(f"{i}. **{t}**")
            if src:
                lines.append(f"   - 来源：{src}")
            if u:
                lines.append(f"   - 链接：{u}")
            if sn:
                lines.append(f"   - 摘录：{sn[:600]}")
            lines.append("")
        body = "\n".join(lines).strip()
    if citation_count > 0:
        body += (
            f"\n\n（共 {citation_count} 条候选文献；请在右侧论文展示区确认后手动加入，"
            "可逐条添加或批量添加。）"
        )
    return body


def _execute_search_step(
    *,
    task: BasicOrchestratorRun,
    prior_context: str,
    step: dict[str, Any],
    step_index: int | None = None,
) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """
    调用 ``execute_web_search``，返回结构化 citations 供前端确认写入展示区，并生成 markdown 供后续子任务使用。
    """
    title = str(step.get("title") or "文献检索").strip()
    query = str(step.get("query") or "").strip()
    if not query:
        query = latest_user_query(task.session).strip()
    if not query:
        return None, {"code": "BASIC_SEARCH_EMPTY_QUERY", "message": "search 步骤缺少 query 且无用户消息可参考"}, []

    from research_agent.paper_shelf import filter_citations_for_shelf
    from research_agent.tool_executor import execute_web_search

    started = time.monotonic()
    res = execute_web_search(query, "")
    elapsed_ms = int((time.monotonic() - started) * 1000)

    pending_citations: list[dict[str, Any]] = []
    if res.ok and res.citations:
        pending_citations = filter_citations_for_shelf(res.citations)

    body = _search_result_markdown(
        step_title=title, query=query, res=res, citation_count=len(pending_citations)
    )
    provider = ""
    if getattr(res, "audit", None) and isinstance(res.audit.metadata, dict):
        provider = str(res.audit.metadata.get("provider") or "")
    if not provider:
        from django.conf import settings

        provider = str(getattr(settings, "RA_WEB_SEARCH_PROVIDER", "tavily") or "tavily")
    cite_preview = []
    for i, c in enumerate((res.citations or [])[:8], 1):
        if not isinstance(c, dict):
            continue
        cite_preview.append(
            f"{i}. {c.get('title', '')} | source={c.get('source', '')} | {c.get('url', '')}"
        )
    _emit_basic_admin_audit(
        task,
        operation_type="basic_search",
        title=f"Search 子任务：{title}",
        detail=(
            f"检索 query：{query}\n"
            f"API/Provider：{provider}\n"
            f"耗时 ms：{elapsed_ms}\n"
            f"成功：{res.ok}\n"
            f"返回条目数：{len(res.citations or [])}\n"
            f"待确认加入展示区：{len(pending_citations)}\n\n"
            f"摘要：{str(res.summary or '').strip()[:2000]}\n\n"
            f"候选文献（前若干条）：\n" + ("\n".join(cite_preview) if cite_preview else "（无）")
        ),
        request_payload={
            "query": query,
            "provider": provider,
            "latency_ms": elapsed_ms,
            "citation_count": len(res.citations or []),
        },
        step_index=step_index,
        status="ok" if res.ok else "failed",
    )
    print(
        f"[research_agent][basic][task={task.id}] search 步骤完成 latency_ms={elapsed_ms} "
        f"ok={res.ok} citations={len(res.citations or [])} pending_shelf={len(pending_citations)}",
        flush=True,
    )
    if not res.ok:
        return None, {
            "code": res.error_code or "BASIC_SEARCH_FAILED",
            "message": res.error_message or "文献检索失败",
        }, []
    return body, None, pending_citations


def _smart_steps_from_config(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    plan = cfg.get("smart_plan")
    if not isinstance(plan, dict):
        return []
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw_steps:
        if isinstance(item, dict):
            cleaned.append(dict(item))
    return cleaned


def _phase_for_step(step_type: str) -> str:
    if step_type == "chat":
        return "read"
    if step_type == "search":
        return "search"
    return "workspace_agent"


def _render_step_detail(step: dict[str, Any], char_count: int) -> str:
    return "\n".join(
        [
            f"type={step.get('type', '')}",
            f"标题：{step.get('title', '')}",
            f"输出字符数：{char_count}",
        ]
    )


def _conversation_body(step_outputs: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in step_outputs:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        title = str(item.get("title", "")).strip()
        st = str(item.get("step_type", "")).strip()
        header = f"## [{st}] {title}\n\n" if title else ""
        parts.append(header + text)
    return "\n\n".join(parts).strip() or "（已完成本次请求，无需额外回复）"


def _finalize_assistant_quota(task: BasicOrchestratorRun, tokens: int) -> None:
    """一轮 basic 编排结束后写入科研助手 Token 用量。"""
    try:
        from business.models import User
        from business.utils.rate_limit import record_research_assistant_usage

        owner_id = str(task.session.owner_id)
        user = User.objects.filter(user_id=owner_id).first()
        if user is None:
            return
        record_research_assistant_usage(
            user,
            tokens,
            run_id=str(task.id),
            session_id=str(task.session_id),
        )
        payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        payload["quota_usage"] = {"tokens": max(0, int(tokens))}
        task.result_payload = payload
        task.save(update_fields=["result_payload", "updated_at"])
    except Exception:
        pass


def execute_basic_pipeline(task_id: uuid.UUID) -> None:
    """会话主入口：Smart Planner → 顺序子任务（chat / search / agent）。"""
    close_old_connections()
    token_bucket = {"total": 0}

    def _accum_usage(usage: dict) -> None:
        token_bucket["total"] += usage_total_tokens(usage)

    accum_token = bind_usage_accumulator(_accum_usage)
    try:
        with transaction.atomic():
            task = task_for_update(BasicOrchestratorRun, task_id)
            if task.status not in ("pending", "running"):
                return
            task.status = "running"
            update_runtime_config(task, basic_pipeline=True)
            cfg = runtime_config(task)
            user_q = latest_user_query(task.session)
            refs = _workspace_refs_list(cfg)
            dialog, ws, session_snap = session_context_for_prompts(task.session, workspace_refs=refs)
            if not _smart_steps_from_config(cfg):
                route_started = time.monotonic()
                plan = detect_smart_plan(
                    user_q,
                    dialog_context=dialog,
                    workspace_context=ws,
                )
                route_ms = int((time.monotonic() - route_started) * 1000)
                if plan is None:
                    plan = fallback_chat_plan(user_q)
                    _append_step(
                        task,
                        "plan",
                        "Smart Planner 回退",
                        f"已降级为单步 chat latency_ms={route_ms}",
                    )
                    _emit_basic_admin_audit(
                        task,
                        operation_type="basic_smart_plan_fallback",
                        title="Smart Planner 回退为单步 chat",
                        detail=json.dumps(plan, ensure_ascii=False, indent=2),
                        request_payload={"latency_ms": route_ms, "user_query": user_q[:500]},
                    )
                else:
                    type_seq = ",".join(s.get("type", "?") for s in plan.get("steps", []))
                    _append_step(
                        task,
                        "plan",
                        "Smart Planner 拆解",
                        f"steps={len(plan.get('steps', []))} types=[{type_seq}] latency_ms={route_ms}\n"
                        f"总结：{plan.get('summary', '')}",
                    )
                    _emit_basic_admin_audit(
                        task,
                        operation_type="basic_smart_plan",
                        title="Smart Planner 拆解结果",
                        detail=json.dumps(plan, ensure_ascii=False, indent=2),
                        request_payload={
                            "latency_ms": route_ms,
                            "step_count": len(plan.get("steps", [])),
                            "step_types": type_seq,
                        },
                    )
                update_runtime_config(
                    task,
                    smart_plan=plan,
                    smart_plan_next_index=0,
                    basic_chain_context="",
                    session_context_snapshot=session_snap,
                )
            elif not str(cfg.get("session_context_snapshot") or "").strip():
                update_runtime_config(task, session_context_snapshot=session_snap)
            task.save(update_fields=["status", "step_seq", "steps", "result_payload", "updated_at"])

        while True:
            with transaction.atomic():
                task = task_for_update(BasicOrchestratorRun, task_id)
                cfg = runtime_config(task)
                steps = _smart_steps_from_config(cfg)
                if not steps:
                    _fail_task(task, "BASIC_PLAN_MISSING", "未找到 smart_plan，无法执行")
                    return

                next_index_raw = cfg.get("smart_plan_next_index", 0)
                try:
                    next_index = int(next_index_raw)
                except (TypeError, ValueError):
                    next_index = 0

                step_outputs = cfg.get("basic_step_outputs", [])
                if not isinstance(step_outputs, list):
                    step_outputs = []

                if next_index >= len(steps):
                    body = _conversation_body(step_outputs)
                    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
                    payload.update(
                        {
                            "format": "markdown",
                            "body": body,
                            "citations": [],
                            "attachments": [],
                            "pipeline": ["plan", "basic", "write"],
                            "runtime_config": runtime_config(task),
                            "basic_step_outputs": step_outputs,
                        }
                    )
                    task.result_payload = payload
                    task.status = "completed"
                    task.intervention = None
                    _append_step(task, "write", "汇总输出", "basic 编排器已完成")
                    task.save(
                        update_fields=[
                            "status",
                            "intervention",
                            "result_payload",
                            "step_seq",
                            "steps",
                            "updated_at",
                        ]
                    )
                    session = ResearchSession.objects.get(id=task.session_id)
                    ResearchMessage.objects.create(session=session, role="assistant", content=body)
                    ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
                    return

                step = dict(steps[next_index]) if isinstance(steps[next_index], dict) else {}
                step_type = str(step.get("type") or "").strip().lower()
                user_query = latest_user_query(task.session)
                prior = _chain_context_from_cfg(cfg)
                session_snap = str(cfg.get("session_context_snapshot") or "").strip()
                n_plan_steps = len(steps)

            # —— 步间补参（LLM + 规则兜底），锁外调用 ——
            session_ctx_llm = session_snap or "（无）"
            if step_refill.step_needs_param_refill(next_index, step):
                lt, lti, ltx = _last_step_output(step_outputs)
                fill = step_refill.fill_deferred_step_params(
                    step=step,
                    user_query=user_query,
                    prior_chain=prior,
                    last_step_type=lt,
                    last_step_title=lti,
                    last_output=ltx,
                    session_context=session_ctx_llm,
                )
                mstep = step_refill.merge_refill_into_step(step, fill)
                if step_refill.step_needs_param_refill(next_index, mstep):
                    mstep = step_refill.merge_refill_into_step(
                        mstep, step_refill.rule_based_fill_step(mstep)
                    )
                step = mstep
                step_type = str(step.get("type") or "").strip().lower()
                with transaction.atomic():
                    task = task_for_update(BasicOrchestratorRun, task_id)
                    cfg = runtime_config(task)
                    smart = cfg.get("smart_plan")
                    if isinstance(smart, dict):
                        raw_steps = smart.get("steps")
                        if isinstance(raw_steps, list) and next_index < len(raw_steps):
                            new_steps = [dict(x) if isinstance(x, dict) else {} for x in raw_steps]
                            new_steps[next_index] = step
                            new_smart = {**smart, "steps": new_steps}
                            update_runtime_config(task, smart_plan=new_smart)
                            _append_step(
                                task,
                                "plan",
                                "子任务参数补全",
                                f"步骤 {next_index + 1}/{len(new_steps)} type={step_type}",
                            )
                            _emit_basic_admin_audit(
                                task,
                                operation_type="basic_step_refill",
                                title=f"子任务参数补全（步骤 {next_index + 1}/{len(new_steps)}）",
                                detail=json.dumps(step, ensure_ascii=False, indent=2),
                                step_index=next_index + 1,
                                request_payload={"step_type": step_type},
                            )
                            task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

            search_citations_out: list[dict[str, Any]] = []

            # —— 锁外执行可能较慢的步骤 ——
            if step_type == "chat":
                text, err = _execute_chat_step(
                    task=task,
                    user_query=user_query,
                    prior_context=prior,
                    step=step,
                    session_context=session_ctx_llm,
                    step_index=next_index + 1,
                )
                if err is not None:
                    with transaction.atomic():
                        task = task_for_update(BasicOrchestratorRun, task_id)
                        _fail_task(task, str(err["code"]), str(err["message"]))
                    return
                out_text = text or ""
            elif step_type == "search":
                text, err, search_citations = _execute_search_step(
                    task=task, prior_context=prior, step=step, step_index=next_index + 1
                )
                if err is not None:
                    with transaction.atomic():
                        task = task_for_update(BasicOrchestratorRun, task_id)
                        _fail_task(task, str(err["code"]), str(err["message"]))
                    return
                out_text = text or ""
                search_citations_out = search_citations
            elif step_type == "agent":
                delegate = str(step.get("delegate_prompt") or "").strip()
                prior_agent = (
                    f"{session_snap}\n\n--- 本 basic run 内已完成子任务 ---\n{prior}".strip()
                    if session_snap
                    else prior
                )
                out_text = run_workspace_delegate(
                    task_id,
                    delegate_prompt=delegate or user_query,
                    prior_context=prior_agent,
                )
            else:
                with transaction.atomic():
                    task = task_for_update(BasicOrchestratorRun, task_id)
                    _fail_task(
                        task,
                        "BASIC_UNSUPPORTED_STEP",
                        f"不支持的子任务类型 type={step_type!r}",
                    )
                return

            with transaction.atomic():
                task = task_for_update(BasicOrchestratorRun, task_id)
                cfg = runtime_config(task)
                new_chain = _append_chain_segment(
                    cfg,
                    title=str(step.get("title") or ""),
                    step_type=step_type,
                    body=out_text,
                )
                step_outputs = cfg.get("basic_step_outputs", [])
                if not isinstance(step_outputs, list):
                    step_outputs = []
                step_out: dict[str, Any] = {
                    "step_type": step_type,
                    "title": step.get("title", ""),
                    "text": out_text,
                }
                if step_type == "search" and search_citations_out:
                    step_out["citations"] = search_citations_out[:40]
                    step_out["search_query"] = str(step.get("query") or "").strip()
                step_outputs.append(step_out)
                _append_step(
                    task,
                    _phase_for_step(step_type),
                    f"子任务 {next_index + 1}/{n_plan_steps}: {step.get('title', '')}",
                    _render_step_detail(step, len(out_text)),
                )
                update_runtime_config(
                    task,
                    basic_step_outputs=step_outputs,
                    basic_chain_context=new_chain,
                    smart_plan_next_index=next_index + 1,
                )
                task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
    finally:
        reset_usage_accumulator(accum_token)
        try:
            task_row = (
                BasicOrchestratorRun.objects.filter(id=task_id)
                .select_related("session")
                .first()
            )
            if task_row is not None:
                _finalize_assistant_quota(task_row, token_bucket["total"])
        except Exception:
            pass
        close_old_connections()
