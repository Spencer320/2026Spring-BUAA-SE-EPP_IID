"""
轻量研究编排器（Lite Orchestrator）。

职责：响应用户**研究任务**中「非深度六阶段流水线」的路径——按
:pyfile:`smart_planner.py` 给出的步骤数组顺序执行，仅含 **chat** 与 **research**
（后者在关闭深度思考时会降级为 chat）。**不**执行工作区磁盘工具链。

设计原则：
- 与深度研究编排器共享 task.steps / task.intervention / task.result_payload；
- 每步独立一行 step 历史；
- LLM 调用关闭 thinking，降低延迟。

科研助手侧若仅需对话，可由 ``smart_orchestrator`` 复用本模块（在写入 ``lite_pipeline`` 等
runtime 标记后调用 ``execute_lite_pipeline``）。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import chat_completion
from .models import AgentTask, ResearchMessage, ResearchSession
from .prompts import LITE_CHAT_SYSTEM_PROMPT, LITE_CHAT_USER_PROMPT
from .smart_planner import fallback_chat_plan


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
    return "decide"


def _render_chat_detail(step: dict[str, Any], char_count: int) -> str:
    return "\n".join(
        [
            "正在生成对话回复",
            f"步骤标题：{step.get('title', '')}",
            f"输出字符数：{char_count}",
        ]
    )


def _conversation_body(chat_outputs: list[dict[str, Any]]) -> str:
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
    return "\n\n".join(parts).strip() or "（已完成本次请求，无需额外回复）"


def execute_lite_pipeline(task_id: uuid.UUID) -> None:
    """轻量研究链路入口：由深度研究编排器在「浅层研究」分支调用；亦可由 smart_orchestrator 复用。"""
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

                if next_index >= len(steps):
                    body = _conversation_body(chat_outputs)
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
                        content=body,
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

                if step_type == "research":
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
                    continue

                _fail_task(
                    task,
                    "LITE_UNSUPPORTED_STEP",
                    f"Smart Planner 不应产出 type={step_type!r}；请检查路由配置",
                )
                return
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
