"""
轻量统一编排器（Lite Orchestrator）。

职责：按 :pyfile:`smart_planner.py` 给出的步骤数组顺序执行。
- ``chat``      —— 调用一次写作型 LLM，把回复累积到最终 assistant 消息；
- ``workspace`` —— 复用 :pyfile:`tools/workspace_executor.py` 执行工作区动作；
- ``research``  —— 当 deep_thinking=False 时，本编排器永远不会收到 research 步骤
                  （smart_planner 已降级）；如果 deep_thinking=True，编排入口会
                  改走旧的 :pyfile:`orchestrator.py` 深度研究流水线，因此本编排器
                  也不需要处理 research 步骤。若意外收到，统一降级为 chat。

设计原则：
- 与旧编排器共享 task.steps / task.intervention / task.result_payload 三处持久化，
  前端无须区分『轻量任务』与『深度任务』；
- 每个步骤独立一行 step 历史，方便侧边栏展示；
- 所有 LLM/工具调用都关闭 thinking，最大限度降低响应延迟。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import chat_completion
from .models import AgentTask, ResearchMessage, ResearchSession
from .prompts import LITE_CHAT_SYSTEM_PROMPT, LITE_CHAT_USER_PROMPT
from .smart_planner import fallback_chat_plan
from .tools.router import route_tool_call
from .tools.workspace_executor import inject_workspace_step_args


REPORT_MESSAGE_PREFIX = "[[RA_REPORT]]\n"


# ---------- 与 orchestrator.py 共用的小工具（重复实现以避免循环 import） ----------


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
    print(
        f"[research_agent][lite][task={task.id}] step#{task.step_seq} "
        f"phase={phase} title={title} detail={detail[:200]}",
        flush=True,
    )


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
    return (msg.content if msg else "").strip() or "未提供研究问题"


def _fail_task(task: AgentTask, code: str, message: str) -> None:
    print(
        f"[research_agent][lite][task={task.id}] 任务失败 code={code} message={message}",
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


# --------------------------------- chat 步骤 ---------------------------------


def _execute_chat_step(
    *,
    task: AgentTask,
    user_query: str,
    step: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    title = str(step.get("title") or "对话回复").strip()
    instruction = str(step.get("prompt") or "").strip()
    started = time.monotonic()
    res = chat_completion(
        system_prompt=LITE_CHAT_SYSTEM_PROMPT,
        user_prompt=LITE_CHAT_USER_PROMPT.format(
            query=user_query.strip() or "(用户原始请求未记录)",
            title=title,
            instruction=instruction or "(规划者未提供具体指令，请直接基于原始请求给出回复)",
        ),
        temperature=0.4,
        max_tokens=1600,
        enable_thinking=False,
        stream=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        print(
            f"[research_agent][lite][task={task.id}] chat 步骤失败 "
            f"latency_ms={elapsed_ms} code={res.error_code} msg={res.error_message}",
            flush=True,
        )
        return None, {
            "code": res.error_code or "LITE_CHAT_FAILED",
            "message": res.error_message or "对话生成失败",
        }
    text = (res.content or "").strip()
    if not text:
        return None, {"code": "LITE_CHAT_EMPTY", "message": "对话生成内容为空"}
    print(
        f"[research_agent][lite][task={task.id}] chat 步骤完成 "
        f"latency_ms={elapsed_ms} chars={len(text)}",
        flush=True,
    )
    return text, None


# --------------------------------- workspace 步骤 -----------------------------


def _generate_workspace_content(
    *,
    task: AgentTask,
    user_query: str,
    path: str,
    brief: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """复用旧 orchestrator 的写作策略：流式 + 关闭 thinking。"""
    from .prompts import WORKSPACE_CONTENT_SYSTEM_PROMPT, WORKSPACE_CONTENT_USER_PROMPT

    started = time.monotonic()
    res = chat_completion(
        system_prompt=WORKSPACE_CONTENT_SYSTEM_PROMPT,
        user_prompt=WORKSPACE_CONTENT_USER_PROMPT.format(
            query=user_query.strip() or "(用户原始请求未记录)",
            path=path or "(未指定路径)",
            brief=brief.strip() or "(未提供写作简述，请合理生成)",
        ),
        temperature=0.4,
        max_tokens=2400,
        enable_thinking=False,
        stream=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        print(
            f"[research_agent][lite][task={task.id}] 工作区写作失败 path={path} "
            f"latency_ms={elapsed_ms} code={res.error_code}",
            flush=True,
        )
        return None, {
            "code": res.error_code or "LITE_WORKSPACE_CONTENT_FAILED",
            "message": res.error_message or "工作区内容生成失败",
        }
    text = (res.content or "").strip()
    if not text:
        return None, {"code": "LITE_WORKSPACE_CONTENT_EMPTY", "message": "LLM 未生成内容"}
    print(
        f"[research_agent][lite][task={task.id}] 工作区写作完成 path={path} "
        f"latency_ms={elapsed_ms} chars={len(text)}",
        flush=True,
    )
    return text, None


def _execute_workspace_step(
    *,
    task: AgentTask,
    user_query: str,
    step: dict[str, Any],
    step_index: int,
    workspace_results: list[dict[str, Any]],
) -> dict[str, Any]:
    cfg = _runtime_config(task)
    action = str(step.get("action") or "").strip()
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    args = dict(args)

    # 物化 content_brief（仅写正文类动作）
    content_generated = False
    brief = str(step.get("content_brief") or "").strip()
    if action in {"write_text", "append_text"} and brief:
        path = str(args.get("path") or "").strip()
        text, err = _generate_workspace_content(
            task=task,
            user_query=user_query,
            path=path,
            brief=brief,
        )
        if err is not None:
            return {
                "ok": False,
                "requires_confirmation": False,
                "confirmation_payload": {},
                "error_code": err.get("code", "LITE_WORKSPACE_CONTENT_FAILED"),
                "error_message": err.get("message", "工作区内容生成失败"),
                "audit": {"tool": "workspace", "status": "failed", "detail": "内容生成失败"},
                "action": action,
                "output": {},
                "step_index": step_index,
                "content_generated": False,
            }
        args["content"] = text
        content_generated = True

    safe_args = inject_workspace_step_args(action, args, workspace_results)

    result = route_tool_call(
        tool_name="workspace",
        args={"action": action, "args": safe_args},
        risk_confirmation_strategy="never",
        user_id=str(task.session.owner_id),
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    audit = payload.get("audit", {})
    if not isinstance(audit, dict):
        audit = {}
    output = payload.get("output", {})
    if not isinstance(output, dict):
        output = {}
    confirmation = payload.get("confirmation_payload")
    if isinstance(confirmation, dict):
        confirmation = {**confirmation, "step_index": step_index, "smart_step": True}
    else:
        confirmation = {}

    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": confirmation,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": audit,
        "action": action,
        "output": output,
        "step_index": step_index,
        "content_generated": content_generated,
    }


# --------------------------------- 主执行循环 ---------------------------------


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
    if step_type == "workspace":
        return "search"
    return "decide"


def _render_chat_detail(step: dict[str, Any], char_count: int) -> str:
    return "\n".join(
        [
            "正在生成对话回复",
            f"步骤标题：{step.get('title', '')}",
            f"输出字符数：{char_count}",
        ]
    )


def _render_workspace_detail(step: dict[str, Any], result: dict[str, Any]) -> str:
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = [
        "正在执行工作区文件工具",
        f"步骤标题：{step.get('title', '')}",
        f"动作：{result.get('action', 'unknown')}",
        f"执行状态：{status}",
    ]
    if detail:
        lines.append(f"执行说明：{detail}")
    return "\n".join(lines)


def _conversation_body(chat_outputs: list[dict[str, Any]], workspace_results: list[dict[str, Any]]) -> str:
    """汇总成最终 assistant 消息体（markdown）。"""
    parts: list[str] = []
    if chat_outputs:
        for item in chat_outputs:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            title = str(item.get("title", "")).strip()
            if title and len(chat_outputs) > 1:
                parts.append(f"## {title}\n\n{text}")
            else:
                parts.append(text)
    if workspace_results:
        parts.append("---\n\n## 工作区操作结果\n")
        for item in workspace_results:
            index = int(item.get("step_index") or 0) + 1
            action = str(item.get("action") or "workspace").strip()
            output = item.get("output") if isinstance(item.get("output"), dict) else {}
            sub = [f"**步骤 {index}**：`{action}`"]
            if output.get("path"):
                sub.append(f"- 路径：`{output.get('path')}`")
            if output.get("output"):
                sub.append(f"- 输出：`{output.get('output')}`")
            if output.get("count") is not None:
                sub.append(f"- 数量：{output.get('count')}")
            if output.get("changed_count") is not None:
                sub.append(f"- 变更文件数：{output.get('changed_count')}")
            if output.get("bytes") is not None:
                sub.append(f"- 大小：{output.get('bytes')} 字节")
            if isinstance(output.get("items"), list) and output.get("items"):
                sub.append("- 文件列表（前 20 个）：")
                for entry in output.get("items", [])[:20]:
                    if isinstance(entry, dict):
                        sub.append(f"  - `{entry.get('rel_path') or entry.get('name')}`")
            parts.append("\n".join(sub))
    return "\n\n".join(parts).strip() or "（已完成本次请求，无需额外回复）"


def execute_lite_pipeline(task_id: uuid.UUID) -> None:
    """轻量执行入口，由 orchestrator 在 deep_thinking=False 或纯 chat/workspace 计划下调用。"""
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            task.status = "running"
            cfg = _runtime_config(task)
            steps = _smart_steps_from_config(cfg)
            if not steps:
                # 兜底：如果 smart_plan 缺失，把用户原话作为 chat 步骤跑一次。
                fallback = fallback_chat_plan(_latest_user_query(task))
                _update_runtime_config(task, smart_plan=fallback)
                steps = fallback["steps"]
                _append_step(
                    task,
                    "plan",
                    "智能拆解失败，回退为单步 chat",
                    "Smart Planner 输出无效或为空，已降级为直接对话",
                )
            else:
                summary = str(cfg.get("smart_plan", {}).get("summary", "")).strip()
                _append_step(
                    task,
                    "plan",
                    "智能任务拆解",
                    "\n".join(
                        [
                            f"总结：{summary or '(规划者未给出总结)'}",
                            f"步骤数量：{len(steps)}",
                            "类型序列：" + ",".join(step.get("type", "?") for step in steps),
                        ]
                    ),
                )
            task.save(update_fields=["status", "step_seq", "steps", "result_payload", "updated_at"])

        # 主执行循环
        while True:
            with transaction.atomic():
                task = _task_for_update(task_id)
                cfg = _runtime_config(task)
                steps = _smart_steps_from_config(cfg)
                if not steps:
                    _fail_task(task, "LITE_PLAN_MISSING", "未找到 smart_plan，无法执行")
                    return

                next_index_raw = cfg.get("smart_plan_next_index", 0)
                try:
                    next_index = int(next_index_raw)
                except (TypeError, ValueError):
                    next_index = 0

                chat_outputs = cfg.get("smart_chat_outputs", [])
                if not isinstance(chat_outputs, list):
                    chat_outputs = []
                workspace_results = cfg.get("smart_workspace_results", [])
                if not isinstance(workspace_results, list):
                    workspace_results = []

                if next_index >= len(steps):
                    body = _conversation_body(chat_outputs, workspace_results)
                    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
                    payload.update(
                        {
                            "format": "markdown",
                            "body": body,
                            "citations": [],
                            "attachments": [],
                            "pipeline": ["plan", "lite", "write"],
                            "runtime_config": _runtime_config(task),
                            "lite_chat_outputs": chat_outputs,
                            "lite_workspace_results": workspace_results,
                        }
                    )
                    task.result_payload = payload
                    task.status = "completed"
                    task.intervention = None
                    _append_step(task, "write", "汇总输出", "已生成助手回复")
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
                    ResearchMessage.objects.create(
                        session=session,
                        role="assistant",
                        content=f"{REPORT_MESSAGE_PREFIX}{body}" if workspace_results else body,
                    )
                    ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
                    return

                step = steps[next_index]
                step_type = str(step.get("type") or "").strip().lower()
                user_query = _latest_user_query(task)

                if step_type == "chat":
                    text, err = _execute_chat_step(task=task, user_query=user_query, step=step)
                    if err is not None:
                        _fail_task(task, err.get("code", "LITE_CHAT_FAILED"), err.get("message", "对话生成失败"))
                        return
                    chat_outputs.append({"title": step.get("title", ""), "text": text})
                    _append_step(
                        task,
                        _phase_for_step("chat"),
                        f"对话步骤 {next_index + 1}: {step.get('title', '')}",
                        _render_chat_detail(step, len(text or "")),
                    )
                    _update_runtime_config(
                        task,
                        smart_chat_outputs=chat_outputs,
                        smart_plan_next_index=next_index + 1,
                    )
                    task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
                    continue

                if step_type == "workspace":
                    result = _execute_workspace_step(
                        task=task,
                        user_query=user_query,
                        step=step,
                        step_index=next_index,
                        workspace_results=workspace_results,
                    )
                    if result.get("content_generated"):
                        _append_step(
                            task,
                            "read",
                            f"为步骤 {next_index + 1} 生成正文",
                            "已基于写作简述生成 Markdown / 文本内容",
                        )
                    _append_step(
                        task,
                        _phase_for_step("workspace"),
                        f"工作区步骤 {next_index + 1}: {step.get('title', '')}",
                        _render_workspace_detail(step, result),
                    )

                    if result.get("requires_confirmation"):
                        _fail_task(
                            task,
                            "FEATURE_REMOVED",
                            "高风险动作人工干预功能已移除，任务不会进入人工确认挂起状态",
                        )
                        return

                    if not result.get("ok"):
                        _fail_task(
                            task,
                            str(result.get("error_code") or "LITE_WORKSPACE_FAILED"),
                            str(result.get("error_message") or "工作区操作失败"),
                        )
                        return

                    workspace_results.append(
                        {
                            "step_index": next_index,
                            "action": result.get("action"),
                            "output": result.get("output", {}),
                        }
                    )
                    _update_runtime_config(
                        task,
                        smart_workspace_results=workspace_results,
                        smart_plan_next_index=next_index + 1,
                    )
                    task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
                    continue

                # research 步骤理论上不会进入 lite（入口已分流）；保险起见降级为 chat。
                fallback_chat = {
                    "type": "chat",
                    "title": step.get("title", "调研降级回答"),
                    "prompt": (
                        "请基于通用知识，对下面这个研究问题给出尽可能完整准确的回答；"
                        "若不确定，请如实说明：\n"
                        f"{step.get('goal', '')}"
                    ),
                }
                text, err = _execute_chat_step(task=task, user_query=user_query, step=fallback_chat)
                if err is not None:
                    _fail_task(task, err.get("code", "LITE_CHAT_FAILED"), err.get("message", "对话生成失败"))
                    return
                chat_outputs.append({"title": step.get("title", ""), "text": text})
                _append_step(
                    task,
                    _phase_for_step("chat"),
                    f"调研降级 {next_index + 1}: {step.get('title', '')}",
                    "（深度思考已关闭或不允许 research，已自动降级为 chat 回答）\n"
                    + _render_chat_detail(step, len(text or "")),
                )
                _update_runtime_config(
                    task,
                    smart_chat_outputs=chat_outputs,
                    smart_plan_next_index=next_index + 1,
                )
                task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
    finally:
        close_old_connections()


def is_lite_pipeline(task: AgentTask) -> bool:
    return bool(_runtime_config(task).get("lite_pipeline"))


def start_lite_pipeline_thread(task_id: uuid.UUID) -> None:
    import threading

    if connection.vendor == "sqlite":
        execute_lite_pipeline(task_id)
        return

    def _run() -> None:
        execute_lite_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-lite-{task_id}", daemon=True).start()
