"""
科研工作区执行流水线（规划—工具—观测循环）。

编排边界
----------
- 与 **深度研究六阶段编排**（``orchestrator.execute_task_pipeline``）解耦；本模块只做多轮
  LLM 规划 + ``research_agent.tools`` 下的工作区工具执行。
- **不得**由 HTTP view / 研究任务创建接口直接启动；须在 ``runtime_config.workspace_pipeline``
  已置位后，由 **Smart 科研助手编排器**（``smart_orchestrator``）或未来其它编排层调用
  ``execute_workspace_pipeline``。
- 工具动作名采用 Unix 式短名（``ls``/``read``/``write``/``rm`` …），见 ``workspace_agent_tools``。

阶段（与下方实现对应）
----------------------
1. **bootstrap**：任务状态、transcript 容器、审计字段初始化。
2. **agent_loop**：每轮 LLM 产出 JSON（finished / assistant_message / tool_calls）→ 工具批次 → 写回 transcript。
3. **finalize**：finished 时写回会话消息与 ``result_payload``。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import LLMCallResult, chat_completion, normalize_supplier_json_response
from .models import AgentTask, ResearchMessage, ResearchSession
from .prompts import WORKSPACE_AGENT_LOOP_SYSTEM_PROMPT, WORKSPACE_AGENT_LOOP_USER_PROMPT
from .tools.workspace_agent_tools import format_tools_catalog_markdown, run_llm_workspace_tool_batch


# ---------------------------------------------------------------------------
# 与 lite_orchestrator 类似的小型持久化辅助（后续可抽到公共模块）
# ---------------------------------------------------------------------------


def _iso_ts() -> str:
    dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_config(task: AgentTask) -> dict[str, Any]:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    return cfg if isinstance(cfg, dict) else {}


def _update_runtime_config(task: AgentTask, **updates: Any) -> None:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _append_step(task: AgentTask, phase: str, title: str, detail: str) -> None:
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


def _task_for_update(task_id: uuid.UUID):
    qs = AgentTask.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def _latest_user_query(task: AgentTask) -> str:
    msg = (
        ResearchMessage.objects.filter(session=task.session, role="user")
        .order_by("-created_at")
        .first()
    )
    return (msg.content if msg else "").strip() or "未提供用户请求"


def _fail_task(task: AgentTask, code: str, message: str) -> None:
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
    """供 LLM 的「执行前上下文」：优先使用上层写入的预确认摘要。"""
    summary = str(cfg.get("workspace_preflight_summary") or "").strip()
    if summary:
        return summary[:8000]
    return "（TODO：请求创建时传入 workspace_preflight_summary，记录用户已确认的高风险操作范围）"


def _emit_plan_audit(task: AgentTask, *, turn: int, latency_ms: int, ok: bool, detail: str) -> None:
    """对接管理端审计：单轮规划 LLM 调用（失败也记一条）。"""
    try:
        from research_agent.orchestrator import _append_behavior_log
    except Exception:
        return
    _append_behavior_log(
        task,
        "workspace_agent",
        f"工作区 Agent 规划 第{turn}轮",
        detail[:8000],
        audit={
            "tool_type": "llm",
            "operation_type": "workspace_agent_plan",
            "status": "ok" if ok else "error",
            "request_payload": {"turn": turn},
            "meta": {"latency_ms": latency_ms, "turn": turn},
        },
    )


def _emit_tool_batch_audit(task: AgentTask, lines: list[str]) -> None:
    try:
        from research_agent.orchestrator import _append_behavior_log
    except Exception:
        return
    body = "\n".join(lines)[:8000]
    _append_behavior_log(
        task,
        "workspace_agent",
        "工作区工具批次执行",
        body,
        audit={
            "tool_type": "workspace",
            "operation_type": "workspace_agent_tools",
            "status": "ok",
            "request_payload": {"lines": lines[:50]},
        },
    )


def _parse_llm_decision(raw: LLMCallResult) -> dict[str, Any] | None:
    if not raw.ok or not (raw.content or "").strip():
        return None
    payload, _err = normalize_supplier_json_response(raw.content or "")
    if not isinstance(payload, dict):
        return None
    return payload


def is_workspace_pipeline(task: AgentTask) -> bool:
    return bool(_runtime_config(task).get("workspace_pipeline"))


def execute_workspace_pipeline(task_id: uuid.UUID) -> None:
    """
    工作区轻量 Agent 主入口：多轮 plan → tool → 观测，直到模型声明 finished。

    调用方须在 ``runtime_config`` 中预先置位 ``workspace_pipeline``、初始化 transcript，
    并在执行前写入 ``workspace_preflight_summary``（高风险预确认，TODO 与产品对齐）。
    """
    close_old_connections()
    max_turns = 14

    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            if task.status == "pending":
                task.status = "running"
            cfg = _runtime_config(task)
            transcript = cfg.get("workspace_agent_transcript")
            if not isinstance(transcript, list):
                transcript = []
            transcript = [str(x) for x in transcript if str(x).strip()]
            _update_runtime_config(task, workspace_agent_transcript=transcript)
            task.save(update_fields=["status", "result_payload", "updated_at"])

        user_id = str(task.session.owner_id or "")
        user_query = _latest_user_query(task)

        for turn in range(1, max_turns + 1):
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                cfg = _runtime_config(task)
                transcript_list = cfg.get("workspace_agent_transcript")
                if not isinstance(transcript_list, list):
                    transcript_list = []
                transcript_list = [str(x) for x in transcript_list]

            transcript_text = "\n".join(transcript_list) if transcript_list else "（尚无执行记录）"
            tools_md = format_tools_catalog_markdown()
            execution_context = _execution_context_for_llm(cfg)
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
            with transaction.atomic():
                task = _task_for_update(task_id)
                _emit_plan_audit(task, turn=turn, latency_ms=latency_ms, ok=decision is not None, detail=llm_res.content or "")
                if not llm_res.ok:
                    _fail_task(task, llm_res.error_code or "WS_AGENT_LLM", llm_res.error_message or "规划 LLM 调用失败")
                    return
                if decision is None:
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

                _append_step(
                    task,
                    "workspace_agent",
                    f"规划第 {turn} 轮",
                    json.dumps(
                        {
                            "finished": finished,
                            "tool_calls_n": len(tool_calls),
                            "latency_ms": latency_ms,
                        },
                        ensure_ascii=False,
                    ),
                )
                task.save(update_fields=["step_seq", "steps", "updated_at"])

            if finished:
                body = assistant_message or "（模型未给出可见说明，但已标记 finished=true）"
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
                    payload.update(
                        {
                            "format": "markdown",
                            "body": body,
                            "citations": [],
                            "attachments": [],
                            "pipeline": ["plan", "workspace_agent", "write"],
                            "runtime_config": _runtime_config(task),
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
                    ResearchMessage.objects.create(session=session, role="assistant", content=body)
                    ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
                return

            if not tool_calls:
                # 模型既未结束也未给出工具调用：记入观测并进入下一轮，避免死循环空转。
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    transcript_list.append(
                        f"[轮次 {turn}] 模型未给出 tool_calls 且 finished=false，已记录并继续。"
                    )
                    _update_runtime_config(task, workspace_agent_transcript=transcript_list)
                    task.save(update_fields=["result_payload", "updated_at"])
                continue

            risk = str(_runtime_config(task).get("risk_confirmation_strategy") or "on_high_risk")
            lines = run_llm_workspace_tool_batch(
                user_id=user_id,
                tool_calls=tool_calls,
                risk_confirmation_strategy=risk,
            )

            with transaction.atomic():
                task = _task_for_update(task_id)
                _emit_tool_batch_audit(task, lines)
                transcript_list.append(f"--- 轮次 {turn} 工具输出 ---\n" + "\n".join(lines))
                _update_runtime_config(task, workspace_agent_transcript=transcript_list)
                task.save(update_fields=["result_payload", "updated_at"])

        with transaction.atomic():
            task = _task_for_update(task_id)
            _fail_task(task, "WS_AGENT_MAX_TURNS", f"超过最大规划轮次 {max_turns}，已中止")
    finally:
        close_old_connections()
