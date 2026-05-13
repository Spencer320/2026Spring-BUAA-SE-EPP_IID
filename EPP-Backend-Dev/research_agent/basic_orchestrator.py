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

import time
import uuid
from typing import Any

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from . import step_refill
from .agent_orchestrator import run_workspace_delegate
from .llm_client import chat_completion
from .models import BasicOrchestratorRun, ResearchMessage, ResearchSession
from .prompts import BASIC_CHAT_SYSTEM_PROMPT, BASIC_CHAT_USER_PROMPT
from .smart_planner import detect_smart_plan, fallback_chat_plan


def _iso_ts() -> str:
    dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_config(task: BasicOrchestratorRun) -> dict[str, Any]:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    return cfg if isinstance(cfg, dict) else {}


def _update_runtime_config(task: BasicOrchestratorRun, **updates: Any) -> None:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _append_step(task: BasicOrchestratorRun, phase: str, title: str, detail: str) -> None:
    task.step_seq += 1
    steps = list(task.steps or [])
    steps.append(
        {
            "seq": task.step_seq,
            "phase": phase,
            "title": title,
            "detail": detail,
            "ts": _iso_ts(),
        }
    )
    task.steps = steps
    print(
        f"[research_agent][basic][task={task.id}] step#{task.step_seq} "
        f"phase={phase} title={title} detail={detail[:200]}",
        flush=True,
    )


def _task_for_update(task_id: uuid.UUID):
    qs = BasicOrchestratorRun.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def _latest_user_query(task: BasicOrchestratorRun) -> str:
    msg = (
        ResearchMessage.objects.filter(session=task.session, role="user")
        .order_by("-created_at")
        .first()
    )
    return (msg.content if msg else "").strip() or "未提供用户请求"


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
) -> tuple[str | None, dict[str, Any] | None]:
    title = str(step.get("title") or "对话回复").strip()
    instruction = str(step.get("prompt") or "").strip()
    started = time.monotonic()
    res = chat_completion(
        system_prompt=BASIC_CHAT_SYSTEM_PROMPT,
        user_prompt=BASIC_CHAT_USER_PROMPT.format(
            query=user_query.strip() or "(用户原始请求未记录)",
            prior_context=prior_context or "（无）",
            title=title,
            instruction=instruction or "(规划者未提供具体指令，请直接基于原始请求与前置结果给出回复)",
        ),
        temperature=0.4,
        max_tokens=1600,
        enable_thinking=False,
        stream=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        return None, {
            "code": res.error_code or "BASIC_CHAT_FAILED",
            "message": res.error_message or "对话生成失败",
        }
    text = (res.content or "").strip()
    if not text:
        return None, {"code": "BASIC_CHAT_EMPTY", "message": "对话生成内容为空"}
    print(
        f"[research_agent][basic][task={task.id}] chat 步骤完成 latency_ms={elapsed_ms} chars={len(text)}",
        flush=True,
    )
    return text, None


def _filter_citations_for_shelf(citations: list[Any]) -> list[dict[str, Any]]:
    """不向展示区写入占位/无信息条目（如 local_rag 占位）。"""
    out: list[dict[str, Any]] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        src = str(c.get("source", "")).lower().strip()
        if src == "local_rag":
            continue
        if str(c.get("url", "")).strip():
            out.append(c)
            continue
        if str(c.get("snippet", "")).strip() or str(c.get("raw_content", "")).strip():
            out.append(c)
    return out


def _search_result_markdown(
    *,
    step_title: str,
    query: str,
    res: Any,
    shelf_added: int,
) -> str:
    from .tools.base import WebSearchResult

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
    if shelf_added > 0:
        body += f"\n\n（已将其中 {shelf_added} 条新文献写入本会话的论文展示区）"
    return body


def _execute_search_step(
    *,
    task: BasicOrchestratorRun,
    prior_context: str,
    step: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """
    调用 ``execute_web_search``，将结构化 citations 写入论文展示区，并生成 markdown 供后续子任务使用。
    """
    _ = prior_context
    title = str(step.get("title") or "文献检索").strip()
    query = str(step.get("query") or "").strip()
    if not query:
        query = _latest_user_query(task).strip()
    if not query:
        return None, {"code": "BASIC_SEARCH_EMPTY_QUERY", "message": "search 步骤缺少 query 且无用户消息可参考"}

    from .paper_shelf import append_search_citations_to_shelf
    from .tool_executor import execute_web_search

    started = time.monotonic()
    res = execute_web_search(query, "")
    elapsed_ms = int((time.monotonic() - started) * 1000)

    shelf_added = 0
    if res.ok and res.citations:
        to_store = _filter_citations_for_shelf(res.citations)
        shelf_added = append_search_citations_to_shelf(
            task.session_id,
            to_store,
            search_query=query,
        )

    body = _search_result_markdown(step_title=title, query=query, res=res, shelf_added=shelf_added)
    print(
        f"[research_agent][basic][task={task.id}] search 步骤完成 latency_ms={elapsed_ms} "
        f"ok={res.ok} citations={len(res.citations or [])} shelf_added={shelf_added}",
        flush=True,
    )
    if not res.ok:
        return None, {
            "code": res.error_code or "BASIC_SEARCH_FAILED",
            "message": res.error_message or "文献检索失败",
        }
    return body, None


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


def execute_basic_pipeline(task_id: uuid.UUID) -> None:
    """会话主入口：Smart Planner → 顺序子任务（chat / search / agent）。"""
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            task.status = "running"
            _update_runtime_config(task, basic_pipeline=True)
            cfg = _runtime_config(task)
            user_q = _latest_user_query(task)
            if not _smart_steps_from_config(cfg):
                route_started = time.monotonic()
                plan = detect_smart_plan(user_q)
                route_ms = int((time.monotonic() - route_started) * 1000)
                if plan is None:
                    plan = fallback_chat_plan(user_q)
                    _append_step(
                        task,
                        "plan",
                        "Smart Planner 回退",
                        f"已降级为单步 chat latency_ms={route_ms}",
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
                _update_runtime_config(task, smart_plan=plan, smart_plan_next_index=0, basic_chain_context="")
            task.save(update_fields=["status", "step_seq", "steps", "result_payload", "updated_at"])

        while True:
            with transaction.atomic():
                task = _task_for_update(task_id)
                cfg = _runtime_config(task)
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
                            "runtime_config": _runtime_config(task),
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
                user_query = _latest_user_query(task)
                prior = _chain_context_from_cfg(cfg)
                n_plan_steps = len(steps)

            # —— 步间补参（LLM + 规则兜底），锁外调用 ——
            if step_refill.step_needs_param_refill(next_index, step):
                lt, lti, ltx = _last_step_output(step_outputs)
                fill = step_refill.fill_deferred_step_params(
                    step=step,
                    user_query=user_query,
                    prior_chain=prior,
                    last_step_type=lt,
                    last_step_title=lti,
                    last_output=ltx,
                )
                mstep = step_refill.merge_refill_into_step(step, fill)
                if step_refill.step_needs_param_refill(next_index, mstep):
                    mstep = step_refill.merge_refill_into_step(
                        mstep, step_refill.rule_based_fill_step(mstep)
                    )
                step = mstep
                step_type = str(step.get("type") or "").strip().lower()
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    cfg = _runtime_config(task)
                    smart = cfg.get("smart_plan")
                    if isinstance(smart, dict):
                        raw_steps = smart.get("steps")
                        if isinstance(raw_steps, list) and next_index < len(raw_steps):
                            new_steps = [dict(x) if isinstance(x, dict) else {} for x in raw_steps]
                            new_steps[next_index] = step
                            new_smart = {**smart, "steps": new_steps}
                            _update_runtime_config(task, smart_plan=new_smart)
                            _append_step(
                                task,
                                "plan",
                                "子任务参数补全",
                                f"步骤 {next_index + 1}/{len(new_steps)} type={step_type}",
                            )
                            task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

            # —— 锁外执行可能较慢的步骤 ——
            if step_type == "chat":
                text, err = _execute_chat_step(
                    task=task, user_query=user_query, prior_context=prior, step=step
                )
                if err is not None:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _fail_task(task, str(err["code"]), str(err["message"]))
                    return
                out_text = text or ""
            elif step_type == "search":
                text, err = _execute_search_step(task=task, prior_context=prior, step=step)
                if err is not None:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _fail_task(task, str(err["code"]), str(err["message"]))
                    return
                out_text = text or ""
            elif step_type == "agent":
                delegate = str(step.get("delegate_prompt") or "").strip()
                out_text = run_workspace_delegate(
                    task_id,
                    delegate_prompt=delegate or user_query,
                    prior_context=prior,
                )
            else:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    _fail_task(
                        task,
                        "BASIC_UNSUPPORTED_STEP",
                        f"不支持的子任务类型 type={step_type!r}",
                    )
                return

            with transaction.atomic():
                task = _task_for_update(task_id)
                cfg = _runtime_config(task)
                new_chain = _append_chain_segment(
                    cfg,
                    title=str(step.get("title") or ""),
                    step_type=step_type,
                    body=out_text,
                )
                step_outputs = cfg.get("basic_step_outputs", [])
                if not isinstance(step_outputs, list):
                    step_outputs = []
                step_outputs.append(
                    {
                        "step_type": step_type,
                        "title": step.get("title", ""),
                        "text": out_text,
                    }
                )
                _append_step(
                    task,
                    _phase_for_step(step_type),
                    f"子任务 {next_index + 1}/{n_plan_steps}: {step.get('title', '')}",
                    _render_step_detail(step, len(out_text)),
                )
                _update_runtime_config(
                    task,
                    basic_step_outputs=step_outputs,
                    basic_chain_context=new_chain,
                    smart_plan_next_index=next_index + 1,
                )
                task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
    finally:
        close_old_connections()
