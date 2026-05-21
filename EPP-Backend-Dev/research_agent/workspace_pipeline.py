"""
科研工作区执行流水线（规划—工具—观测循环）。

编排边界
----------
- 与 **深度研究六阶段编排**（``orchestrator.execute_deep_research_pipeline``）解耦；本模块只做多轮
  LLM 规划 + ``research_agent.tools`` 下的工作区工具执行。
- **不得**由普通会话 HTTP 直连启动；须在 ``runtime_config`` 中由 ``agent_orchestrator.run_workspace_delegate``
  （持久化为 ``WorkspaceAgentRun``）或其它编排层调用 ``execute_workspace_pipeline``。
- 子任务可设 ``workspace_user_query_override``，避免误用会话内「最近一条用户消息」作为规划输入。
- 工具动作名采用 Unix 式短名（``ls``/``read``/``write``/``rm`` …），见 ``workspace_agent_tools``。

阶段（与下方实现对应）
----------------------
1. **bootstrap**：任务状态、transcript 容器、审计字段初始化。
2. **agent_loop**：每轮 LLM 产出 JSON（finished / assistant_message / tool_calls）→ 工具批次 → 写回 transcript。
3. **finalize**：finished 时写回会话消息与 ``result_payload``。

与前端工作区面板同步
--------------------
每轮 **工具批次** 持久化后，在子运行 ``runtime_config.workspace_fs_generation`` 自增；若存在
``parent_basic_run``，同步在父 ``BasicOrchestratorRun.runtime_config`` 上自增。前端轮询
``GET /api/research-agent/tasks/<task_id>/status/``（或会话里的 ``active_task``）发现该整数变化后，
再请求 ``GET /api/workspace/files`` 即可刷新文件树（HTTP 后端无法主动推送浏览器）。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

from .llm_client import LLMCallResult, chat_completion, normalize_supplier_json_response
from .models import BasicOrchestratorRun, ResearchSession, WorkspaceAgentRun
from .prompts import WORKSPACE_AGENT_LOOP_SYSTEM_PROMPT, WORKSPACE_AGENT_LOOP_USER_PROMPT
from .run_helpers import (
    iso_ts,
    latest_user_query,
    runtime_config,
    task_for_update,
    update_runtime_config,
)
from .tools.workspace_agent_tools import format_tools_catalog_markdown, run_llm_workspace_tool_batch

# 工作区 Agent 规划—工具循环上限（每轮一次规划 LLM；过小易截断复杂任务）
WORKSPACE_AGENT_MAX_TURNS = 24


def _next_workspace_fs_generation(cfg: dict[str, Any]) -> int:
    raw = cfg.get("workspace_fs_generation")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    return n + 1


def _bump_parent_basic_workspace_fs_generation(parent_basic_run_id: uuid.UUID) -> None:
    """在父 basic 任务上标记「工作区目录内容可能已变」，供前端轮询 status 后刷新文件列表。"""
    parent = BasicOrchestratorRun.objects.select_for_update().filter(pk=parent_basic_run_id).first()
    if parent is None:
        return
    pp = dict(parent.result_payload) if isinstance(parent.result_payload, dict) else {}
    pc = dict(pp.get("runtime_config") or {})
    pc["workspace_fs_generation"] = _next_workspace_fs_generation(pc)
    pp["runtime_config"] = pc
    parent.result_payload = pp
    parent.save(update_fields=["result_payload", "updated_at"])


def _append_step(task: WorkspaceAgentRun, phase: str, title: str, detail: str) -> None:
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


def _workspace_user_query_for_task(task: WorkspaceAgentRun) -> str:
    """优先使用 ``workspace_user_query_override``（basic→agent 子任务），否则取会话最近用户消息。"""
    cfg = runtime_config(task)
    override = str(cfg.get("workspace_user_query_override") or "").strip()
    if override:
        return override
    return latest_user_query(task.session)


def _fail_task(task: WorkspaceAgentRun, code: str, message: str) -> None:
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


def _execution_context_for_llm(cfg: dict[str, Any]) -> str:
    """供 LLM 的「执行前上下文」：可选备注（如会话策略说明）；开发阶段不强制风险预检。"""
    summary = str(cfg.get("workspace_preflight_summary") or "").strip()
    if summary:
        return summary[:8000]
    return "（开发阶段：工作区工具将直接按模型规划执行；无单独风险预检。）"


def _json_pretty(obj: object) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except TypeError:
        return str(obj)


def _format_tool_record_line(idx: int, rec: dict[str, Any]) -> str:
    st = rec.get("status")
    if st == "ok":
        action = rec.get("action", "")
        return f"{idx}. `{action}`\n\n```json\n{_json_pretty(rec.get('args', {}))}\n```\n\n"
    if st == "error":
        action = rec.get("action", "")
        err = rec.get("error_code", "")
        msg = rec.get("error_message", "")
        return (
            f"{idx}. `{action}` **失败**（{err}） {msg}\n\n"
            f"```json\n{_json_pretty(rec.get('args', {}))}\n```\n\n"
        )
    if st == "skipped_invalid":
        la = rec.get("llm_action", "")
        return (
            f"{idx}. 未执行（模型输出无法落地为合法工具调用） `{la}`\n\n"
            f"```json\n{_json_pretty(rec.get('llm_args', {}))}\n```\n\n"
        )
    if st == "skipped":
        return f"{idx}. 跳过：{rec.get('reason', '')} — `{rec.get('raw_preview', '')}`\n\n"
    return ""


def _format_workspace_tool_execution_appendix(log: list[Any]) -> str:
    """将 ``workspace_tool_execution_log`` 渲染为附在助手消息后的 Markdown。"""
    if not log:
        return ""
    parts: list[str] = ["\n\n---\n\n### 已执行工作区工具\n"]
    for entry in log:
        if not isinstance(entry, dict):
            continue
        turn = entry.get("turn", "?")
        tools = entry.get("executed")
        if not isinstance(tools, list) or not tools:
            continue
        parts.append(f"\n**第 {turn} 轮**\n\n")
        for idx, rec in enumerate(tools, start=1):
            if not isinstance(rec, dict):
                continue
            line = _format_tool_record_line(idx, rec)
            if line:
                parts.append(line)
    return "".join(parts)


def _emit_workspace_turn_audit(
    task: WorkspaceAgentRun,
    *,
    turn: int,
    plan_detail: str,
    tool_lines: list[str],
    latency_ms: int,
    finished: bool,
    tool_calls_n: int,
) -> None:
    """管理端：单轮「规划 → 执行 → 结果」合并为一条审计（step_id = 轮次）。"""
    try:
        from research_agent.orchestrator import _append_behavior_log

        parts = [f"## 规划（第 {turn} 轮）\n{(plan_detail or '').strip()[:4000]}"]
        if tool_lines:
            parts.append("## 执行结果\n" + "\n".join(tool_lines)[:4000])
        elif finished:
            parts.append("## 执行结果\n（本轮直接结束，无工具调用）")
        body = "\n\n".join(parts)[:8000]
        _append_behavior_log(
            task,
            "workspace_agent",
            f"工作区 Agent 第 {turn} 轮",
            body,
            audit={
                "tool_type": "workspace_agent",
                "operation_type": "workspace_turn",
                "status": "ok",
                "step_id": turn,
                "request_payload": {
                    "turn": turn,
                    "finished": finished,
                    "tool_calls_n": tool_calls_n,
                    "latency_ms": latency_ms,
                },
            },
        )
    except Exception:  # noqa: BLE001 — 审计写入失败不得中断编排
        pass


def _tool_actions_preview(tool_calls: list[dict[str, Any]], *, limit: int = 12) -> str:
    names: list[str] = []
    for tc in tool_calls[:limit]:
        a = str(tc.get("action") or tc.get("tool") or "?").strip() or "?"
        names.append(a)
    if len(tool_calls) > limit:
        names.append(f"+{len(tool_calls) - limit}")
    return ",".join(names) if names else "(none)"


def _parse_llm_decision(raw: LLMCallResult) -> dict[str, Any] | None:
    if not raw.ok or not (raw.content or "").strip():
        return None
    payload, _err = normalize_supplier_json_response(raw.content or "")
    if not isinstance(payload, dict):
        return None
    return payload


def execute_workspace_pipeline(task_id: uuid.UUID) -> None:
    """
    工作区轻量 Agent 主入口：多轮 plan → tool → 观测，直到模型声明 finished。

    调用方须在 ``runtime_config`` 中初始化 ``workspace_agent_transcript`` 等；单轮上限为
    ``WORKSPACE_AGENT_MAX_TURNS``（规划 LLM 与工具交替，直至 ``finished`` 或触顶失败）。
    """
    close_old_connections()
    max_turns = WORKSPACE_AGENT_MAX_TURNS

    try:
        with transaction.atomic():
            task = task_for_update(WorkspaceAgentRun, task_id)
            if task.status not in ("pending", "running"):
                print(
                    f"[research_agent][workspace_pipeline] skip run_id={task_id} "
                    f"status={getattr(task, 'status', '?')} (expected pending|running)",
                    flush=True,
                )
                return
            if task.status == "pending":
                task.status = "running"
            cfg = runtime_config(task)
            transcript = cfg.get("workspace_agent_transcript")
            if not isinstance(transcript, list):
                transcript = []
            transcript = [str(x) for x in transcript if str(x).strip()]
            exec_log = cfg.get("workspace_tool_execution_log")
            if not isinstance(exec_log, list):
                exec_log = []
            update_runtime_config(
                task, workspace_agent_transcript=transcript, workspace_tool_execution_log=exec_log
            )
            task.save(update_fields=["status", "result_payload", "updated_at"])

        user_id = str(task.session.owner_id or "")
        user_query = _workspace_user_query_for_task(task)
        parent_id = getattr(task, "parent_basic_run_id", None)
        print(
            f"[research_agent][workspace_pipeline] start run_id={task_id} session_id={task.session_id} "
            f"parent_basic_run_id={parent_id} user_id={user_id or '(empty)'} "
            f"query_chars={len(user_query)} max_turns={max_turns}",
            flush=True,
        )

        for turn in range(1, max_turns + 1):
            with transaction.atomic():
                task = task_for_update(WorkspaceAgentRun, task_id)
                if task.status != "running":
                    print(
                        f"[research_agent][workspace_pipeline] stop run_id={task_id} "
                        f"after_turn={turn - 1} status={task.status}",
                        flush=True,
                    )
                    return
                cfg = runtime_config(task)
                transcript_list = cfg.get("workspace_agent_transcript")
                if not isinstance(transcript_list, list):
                    transcript_list = []
                transcript_list = [str(x) for x in transcript_list]

            transcript_text = "\n".join(transcript_list) if transcript_list else "（尚无执行记录）"
            tools_md = format_tools_catalog_markdown()
            execution_context = _execution_context_for_llm(cfg)
            print(
                f"[research_agent][workspace_pipeline] plan_turn run_id={task_id} turn={turn}/{max_turns} "
                f"transcript_chars={len(transcript_text)}",
                flush=True,
            )
            user_block = WORKSPACE_AGENT_LOOP_USER_PROMPT.format(
                tools_catalog=tools_md,
                query=user_query,
                execution_context=execution_context,
                transcript=transcript_text,
            )

            started = time.monotonic()
            llm_res = chat_completion(
                system_prompt=WORKSPACE_AGENT_LOOP_SYSTEM_PROMPT,
                user_prompt=user_block,
                temperature=0.2,
                max_tokens=2048,
                enable_thinking=False,
                stream=False,
            )
            latency_ms = int((time.monotonic() - started) * 1000)

            decision = _parse_llm_decision(llm_res)
            plan_detail = (llm_res.content or "").strip()
            with transaction.atomic():
                task = task_for_update(WorkspaceAgentRun, task_id)
                if not llm_res.ok:
                    _emit_workspace_turn_audit(
                        task,
                        turn=turn,
                        plan_detail=plan_detail or (llm_res.error_message or ""),
                        tool_lines=[],
                        latency_ms=latency_ms,
                        finished=False,
                        tool_calls_n=0,
                    )
                    print(
                        f"[research_agent][workspace_pipeline] plan_llm_fail run_id={task_id} turn={turn} "
                        f"code={llm_res.error_code} latency_ms={latency_ms} "
                        f"msg={(llm_res.error_message or '')[:300]}",
                        flush=True,
                    )
                    _fail_task(task, llm_res.error_code or "WS_AGENT_LLM", llm_res.error_message or "规划 LLM 调用失败")
                    return
                if decision is None:
                    _emit_workspace_turn_audit(
                        task,
                        turn=turn,
                        plan_detail=plan_detail,
                        tool_lines=[],
                        latency_ms=latency_ms,
                        finished=False,
                        tool_calls_n=0,
                    )
                    print(
                        f"[research_agent][workspace_pipeline] plan_bad_json run_id={task_id} turn={turn} "
                        f"latency_ms={latency_ms} preview={(llm_res.content or '')[:400]}",
                        flush=True,
                    )
                    _fail_task(task, "WS_AGENT_BAD_JSON", "规划 LLM 输出不是可用的 JSON 对象")
                    return

                finished = bool(decision.get("finished"))
                assistant_message = str(decision.get("assistant_message") or "").strip()
                raw_calls = decision.get("tool_calls")
                tool_calls: list[dict[str, Any]] = []
                if isinstance(raw_calls, list):
                    for item in raw_calls:
                        if isinstance(item, dict):
                            tool_calls.append(dict(item))

            preview = _tool_actions_preview(tool_calls)
            msg_head = (assistant_message or "")[:160].replace("\n", " ")
            print(
                f"[research_agent][workspace_pipeline] plan_done run_id={task_id} turn={turn} "
                f"latency_ms={latency_ms} finished={finished} tool_calls={len(tool_calls)} "
                f"actions=[{preview}] assistant_preview={msg_head!r}",
                flush=True,
            )

            if finished:
                body = assistant_message or "（模型未给出可见说明，但已标记 finished=true）"
                with transaction.atomic():
                    task = task_for_update(WorkspaceAgentRun, task_id)
                    _emit_workspace_turn_audit(
                        task,
                        turn=turn,
                        plan_detail=plan_detail,
                        tool_lines=[f"assistant_message:\n{body[:2000]}"],
                        latency_ms=latency_ms,
                        finished=True,
                        tool_calls_n=0,
                    )
                    cfg_done = runtime_config(task)
                    raw_log = cfg_done.get("workspace_tool_execution_log")
                    exec_log_done = list(raw_log) if isinstance(raw_log, list) else []
                    appendix = _format_workspace_tool_execution_appendix(exec_log_done)
                    visible_body = (body + appendix).strip()
                    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
                    payload.update(
                        {
                            "format": "markdown",
                            "body": visible_body,
                            "citations": [],
                            "attachments": [],
                            "pipeline": ["plan", "workspace_agent", "write"],
                            "workspace_tool_execution_log": exec_log_done,
                            "runtime_config": runtime_config(task),
                        }
                    )
                    task.result_payload = payload
                    task.status = "completed"
                    task.intervention = None
                    _append_step(task, "write", "工作区任务汇总", "已完成工作区 Agent 管道")
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
                    # 由 basic 委托的 agent 子运行：最终助手消息由 basic 编排器汇总写入（含本段 out_text），
                    # 此处再写一条会导致前端同一会话下出现两份相同的「已执行工作区工具」列表。
                    if getattr(task, "parent_basic_run_id", None) is None:
                        ResearchMessage.objects.create(session=session, role="assistant", content=visible_body)
                    ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
                print(
                    f"[research_agent][workspace_pipeline] completed run_id={task_id} "
                    f"turns_used={turn} body_chars={len(visible_body)}",
                    flush=True,
                )
                return

            if not tool_calls:
                # 模型既未结束也未给出工具调用：记入观测并进入下一轮，避免死循环空转。
                print(
                    f"[research_agent][workspace_pipeline] no_tool_calls run_id={task_id} turn={turn} "
                    "finished=false, append note and continue",
                    flush=True,
                )
                with transaction.atomic():
                    task = task_for_update(WorkspaceAgentRun, task_id)
                    _emit_workspace_turn_audit(
                        task,
                        turn=turn,
                        plan_detail=plan_detail,
                        tool_lines=["（模型未给出 tool_calls，无执行结果）"],
                        latency_ms=latency_ms,
                        finished=False,
                        tool_calls_n=0,
                    )
                    transcript_list.append(
                        f"[轮次 {turn}] 模型未给出 tool_calls 且 finished=false，已记录并继续。"
                    )
                    update_runtime_config(task, workspace_agent_transcript=transcript_list)
                    task.save(update_fields=["result_payload", "updated_at"])
                continue

            print(
                f"[research_agent][workspace_pipeline] tools_execute run_id={task_id} turn={turn} "
                f"batch_size={len(tool_calls)} actions=[{preview}]",
                flush=True,
            )
            risk = str(cfg.get("risk_confirmation_strategy") or "on_high_risk")
            tb_started = time.monotonic()
            lines, executed_records = run_llm_workspace_tool_batch(
                user_id=user_id,
                tool_calls=tool_calls,
                risk_confirmation_strategy=risk,
            )

            with transaction.atomic():
                task = task_for_update(WorkspaceAgentRun, task_id)
                _emit_workspace_turn_audit(
                    task,
                    turn=turn,
                    plan_detail=plan_detail,
                    tool_lines=lines,
                    latency_ms=latency_ms,
                    finished=False,
                    tool_calls_n=len(tool_calls),
                )
                transcript_list.append(f"--- 轮次 {turn} 工具输出 ---\n" + "\n".join(lines))
                cfg_after = runtime_config(task)
                raw_log = cfg_after.get("workspace_tool_execution_log")
                exec_log = list(raw_log) if isinstance(raw_log, list) else []
                exec_log.append({"turn": turn, "executed": executed_records})
                child_gen = _next_workspace_fs_generation(cfg_after)
                update_runtime_config(
                    task,
                    workspace_agent_transcript=transcript_list,
                    workspace_tool_execution_log=exec_log,
                    workspace_fs_generation=child_gen,
                )
                task.save(update_fields=["result_payload", "updated_at"])
                pid = getattr(task, "parent_basic_run_id", None)
                if pid:
                    _bump_parent_basic_workspace_fs_generation(pid)
            tb_ms = int((time.monotonic() - tb_started) * 1000)
            ok_n = sum(1 for r in executed_records if isinstance(r, dict) and r.get("status") == "ok")
            print(
                f"[research_agent][workspace_pipeline] tools_done run_id={task_id} turn={turn} "
                f"latency_ms={tb_ms} lines={len(lines)} ok_tools={ok_n}/{len(executed_records)}",
                flush=True,
            )

        with transaction.atomic():
            task = task_for_update(WorkspaceAgentRun, task_id)
            print(
                f"[research_agent][workspace_pipeline] max_turns run_id={task_id} limit={max_turns}",
                flush=True,
            )
            _fail_task(task, "WS_AGENT_MAX_TURNS", f"超过最大规划轮次 {max_turns}，已中止")
    finally:
        close_old_connections()
