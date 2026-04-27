"""科研助手任务编排引擎：真实 LLM 驱动。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import chat_completion, normalize_supplier_json_response
from .models import AgentBehaviorAuditLog, AgentTask, ResearchMessage, ResearchSession
from .prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_DECIDE,
    USER_PROMPT_PLAN,
    USER_PROMPT_READ,
    USER_PROMPT_REFLECT,
    USER_PROMPT_SEARCH,
    USER_PROMPT_WRITE,
)
from .tools.router import route_tool_call

ACTIVE_STATUSES = frozenset({"pending", "running", "pending_action"})
REPORT_MESSAGE_PREFIX = "[[RA_REPORT]]\n"
PIPELINE_PHASES = ("plan", "decide", "search", "read", "reflect", "write")


def _iso_ts(dt: datetime | None = None) -> str:
    if dt is None:
        dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _append_behavior_log(
    task: AgentTask,
    phase: str,
    title: str,
    detail: str,
    audit: dict[str, Any] | None = None,
) -> None:
    payload = audit or {}
    target_url = str(payload.get("target_url", "") or "").strip()
    response_status = payload.get("response_status")
    if response_status is not None:
        try:
            response_status = int(response_status)
        except (TypeError, ValueError):
            response_status = None
    is_exception = bool(payload.get("is_exception", False))
    if response_status is not None and response_status >= 400:
        is_exception = True
    AgentBehaviorAuditLog.objects.create(
        task=task,
        operation_type=str(payload.get("operation_type") or phase),
        target_url=target_url,
        target_domain=str(payload.get("target_domain") or _extract_domain(target_url)),
        request_headers=payload.get("request_headers") or {},
        request_payload=payload.get("request_payload") or {},
        action_payload=payload.get("action_payload") or {"title": title},
        response_status=response_status,
        is_exception=is_exception,
        exception_message=str(payload.get("exception_message") or ""),
        trace_detail=detail or title,
    )


def _append_step(
    task: AgentTask,
    phase: str,
    title: str,
    detail: str,
    audit: dict[str, Any] | None = None,
) -> None:
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
    _append_behavior_log(task, phase, title, detail, audit=audit)


def _runtime_config(task: AgentTask) -> dict[str, object]:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    return cfg if isinstance(cfg, dict) else {}


def _update_runtime_config(task: AgentTask, **updates: object) -> None:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _max_reflect_rounds(task: AgentTask) -> int:
    raw = _runtime_config(task).get("max_reflect_rounds", 2)
    try:
        rounds = int(raw)
    except (TypeError, ValueError):
        rounds = 2
    return max(1, min(5, rounds))


def _latest_user_query(task: AgentTask) -> str:
    msg = (
        ResearchMessage.objects.filter(session=task.session, role="user")
        .order_by("-created_at")
        .first()
    )
    return (msg.content if msg else "").strip() or "未提供研究问题"


def _build_conversation_messages(
    *,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
    history_limit: int = 12,
) -> list[dict[str, str]]:
    history = list(ResearchMessage.objects.filter(session=task.session).order_by("-created_at")[:history_limit])
    history.reverse()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = str(msg.role or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(msg.content or "").strip()
        if not content:
            continue
        if content.startswith(REPORT_MESSAGE_PREFIX):
            content = "上一轮已生成研究报告。"
        messages.append({"role": role, "content": content[:1200]})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _llm_call(
    *,
    phase: str,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str | None, dict[str, object] | None]:
    messages = _build_conversation_messages(task=task, system_prompt=system_prompt, user_prompt=user_prompt)
    try:
        res = chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except TypeError as exc:
        if "messages" not in str(exc):
            raise
        res = chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    if not res.ok:
        return None, {
            "code": res.error_code or "LLM_CALL_FAILED",
            "message": res.error_message or "LLM 调用失败",
            "phase": phase,
        }
    _update_runtime_config(
        task,
        llm_last_call={
            "phase": phase,
            "model": res.model,
            "latency_ms": res.latency_ms,
            "usage": res.usage if isinstance(res.usage, dict) else {},
        },
    )
    return res.content, None


def _normalize_json(raw: str, phase: str) -> tuple[dict[str, object] | None, str | None]:
    payload, parse_err = normalize_supplier_json_response(raw or "")
    if payload is None:
        return None, f"{phase}阶段JSON无效: {parse_err}"
    return payload, None


def _validate_planner_json(payload: dict[str, object]) -> tuple[bool, str]:
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not (2 <= len(alternatives) <= 4):
        return False, "alternatives must be list with length 2-4"
    for item in alternatives:
        if not isinstance(item, dict):
            return False, "alternative must be object"
        if not isinstance(item.get("plan_id"), str) or not str(item.get("plan_id")).strip():
            return False, "plan_id must be non-empty string"
        if not isinstance(item.get("title"), str) or not str(item.get("title")).strip():
            return False, "title must be non-empty string"
        steps = item.get("steps")
        if not isinstance(steps, list) or not steps or any(not isinstance(s, str) or not s.strip() for s in steps):
            return False, "steps must be non-empty string list"
        if not isinstance(item.get("rationale"), str) or not str(item.get("rationale")).strip():
            return False, "rationale must be non-empty string"
    return True, ""


def _validate_decider_json(payload: dict[str, object], alternatives: list[dict[str, object]]) -> tuple[bool, str]:
    if payload.get("complexity") not in ("simple", "complex"):
        return False, "complexity must be simple or complex"
    if not isinstance(payload.get("selected_plan_id"), str) or not str(payload.get("selected_plan_id")).strip():
        return False, "selected_plan_id must be non-empty string"
    if not isinstance(payload.get("decision_reason"), str) or not str(payload.get("decision_reason")).strip():
        return False, "decision_reason must be non-empty string"
    if not isinstance(payload.get("merge_attempt_note"), str) or not str(payload.get("merge_attempt_note")).strip():
        return False, "merge_attempt_note must be non-empty string"
    valid_plan_ids = {str(item.get("plan_id", "")).strip() for item in alternatives if isinstance(item, dict)}
    if str(payload.get("selected_plan_id", "")).strip() not in valid_plan_ids:
        return False, "selected_plan_id not found in alternatives"
    subtasks = payload.get("subtasks")
    if not isinstance(subtasks, list):
        return False, "subtasks must be list"
    if payload.get("complexity") == "simple" and len(subtasks) != 1:
        return False, "simple complexity requires exactly one subtask"
    if payload.get("complexity") == "complex" and len(subtasks) < 2:
        return False, "complex complexity requires at least two subtasks"
    seen: set[str] = set()
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            return False, "subtask must be object"
        sid = subtask.get("subtask_id")
        if not isinstance(sid, str) or not sid.strip():
            return False, "subtask_id must be non-empty string"
        if sid in seen:
            return False, "subtask_id must be unique"
        seen.add(sid)
        if not isinstance(subtask.get("title"), str) or not str(subtask.get("title")).strip():
            return False, "subtask.title must be non-empty string"
        if not isinstance(subtask.get("goal"), str) or not str(subtask.get("goal")).strip():
            return False, "subtask.goal must be non-empty string"
        deps = subtask.get("depends_on")
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            return False, "subtask.depends_on must be string list"
    prior: set[str] = set()
    for subtask in subtasks:
        sid = str(subtask.get("subtask_id", ""))
        for dep in subtask.get("depends_on", []):
            if dep not in seen:
                return False, f"depends_on unknown id: {dep}"
            if dep not in prior:
                return False, f"depends_on must reference previous subtask: {dep}"
        prior.add(sid)
    return True, ""


def _validate_searcher_json(payload: dict[str, object]) -> tuple[bool, str]:
    groups = payload.get("info_groups")
    if not isinstance(groups, list) or not groups:
        return False, "info_groups must be non-empty list"
    if not isinstance(payload.get("search_notes"), str):
        return False, "search_notes must be string"
    for group in groups:
        if not isinstance(group, dict):
            return False, "info_group must be object"
        if group.get("relevance") not in ("high", "medium", "low"):
            return False, "relevance must be high|medium|low"
        if not isinstance(group.get("group_title"), str) or not str(group.get("group_title")).strip():
            return False, "group_title must be non-empty string"
        findings = group.get("raw_findings")
        if not isinstance(findings, list) or not findings or any(not isinstance(x, str) or not x.strip() for x in findings):
            return False, "raw_findings must be non-empty string list"
    return True, ""


def _validate_read_json(payload: dict[str, object]) -> tuple[bool, str]:
    if not isinstance(payload.get("analysis"), str) or not str(payload.get("analysis")).strip():
        return False, "analysis must be non-empty string"
    if not isinstance(payload.get("key_points"), list) or any(not isinstance(x, str) for x in payload.get("key_points", [])):
        return False, "key_points must be string list"
    if not isinstance(payload.get("limitations"), list) or any(not isinstance(x, str) for x in payload.get("limitations", [])):
        return False, "limitations must be string list"
    return True, ""


def _validate_reflector_json(payload: dict[str, object]) -> tuple[bool, str]:
    if payload.get("needs_optimization") not in ("yes", "no"):
        return False, "needs_optimization must be yes|no"
    if not isinstance(payload.get("reason"), str) or not str(payload.get("reason")).strip():
        return False, "reason must be non-empty string"
    suggestions = payload.get("actionable_suggestions")
    if not isinstance(suggestions, list) or any(not isinstance(item, str) for item in suggestions):
        return False, "actionable_suggestions must be string list"
    if payload.get("needs_optimization") == "yes" and not suggestions:
        return False, "actionable_suggestions must be non-empty when needs_optimization=yes"
    accepted = payload.get("accepted_reader_summary")
    if not isinstance(accepted, dict):
        return False, "accepted_reader_summary must be object"
    ok, msg = _validate_read_json(accepted)
    if not ok:
        return False, f"accepted_reader_summary invalid: {msg}"
    return True, ""


def _validate_write_json(payload: dict[str, object], subtasks: list[dict[str, object]]) -> tuple[bool, str]:
    if not isinstance(payload.get("title"), str) or not str(payload.get("title")).strip():
        return False, "title must be non-empty string"
    if not isinstance(payload.get("executive_summary"), str) or not str(payload.get("executive_summary")).strip():
        return False, "executive_summary must be non-empty string"
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return False, "sections must be non-empty list"
    for section in sections:
        if not isinstance(section, dict):
            return False, "section must be object"
        if not isinstance(section.get("heading"), str) or not str(section.get("heading")).strip():
            return False, "section heading must be non-empty string"
        if not isinstance(section.get("content"), str) or not str(section.get("content")).strip():
            return False, "section content must be non-empty string"
    traceability = payload.get("traceability")
    if not isinstance(traceability, list) or not traceability:
        return False, "traceability must be non-empty list"
    trace_ids: set[str] = set()
    for item in traceability:
        if not isinstance(item, dict):
            return False, "traceability item must be object"
        if not isinstance(item.get("subtask_id"), str) or not str(item.get("subtask_id")).strip():
            return False, "traceability.subtask_id must be non-empty string"
        if not isinstance(item.get("conclusion"), str) or not str(item.get("conclusion")).strip():
            return False, "traceability.conclusion must be non-empty string"
        trace_ids.add(str(item.get("subtask_id")).strip())
    subtask_ids = {str(item.get("subtask_id", "")).strip() for item in subtasks if isinstance(item, dict)}
    if not subtask_ids.issubset(trace_ids):
        return False, "traceability must cover all subtasks"
    return True, ""


def _render_citations(citations: list[dict[str, str]]) -> str:
    if not citations:
        return "- 无可用引用"
    rows: list[str] = []
    for item in citations:
        title = str(item.get("title", "")).strip() or "未命名来源"
        source = str(item.get("source", "")).strip() or "unknown"
        url = str(item.get("url", "")).strip()
        if url:
            rows.append(f"- {title}（来源：{source}，URL：{url}）")
        else:
            rows.append(f"- {title}（来源：{source}）")
    return "\n".join(rows)


def _markdown_from_write_json(payload: dict[str, object]) -> str:
    title = str(payload.get("title", "研究报告")).strip() or "研究报告"
    executive_summary = str(payload.get("executive_summary", "")).strip()
    sections = payload.get("sections", [])
    parts = [f"# {title}"]
    if executive_summary:
        parts.append(f"\n## 执行摘要\n{executive_summary}")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "")).strip()
            content = str(section.get("content", "")).strip()
            if heading and content:
                parts.append(f"\n## {heading}\n{content}")
    return "\n".join(parts).strip()


def _search_context(query: str) -> tuple[str, list[dict[str, str]], dict[str, str] | None, dict[str, object]]:
    url = (getattr(settings, "RA_OUTBOUND_DEMO_URL", "") or "").strip()
    routed = route_tool_call(tool_name="web_search", args={"query": query, "url": url})
    if not routed.ok:
        if str(routed.error_code).startswith("WEB_SEARCH_"):
            detail = f"联网检索降级为本地检索：{query[:120] or '未提供检索词'}"
            audit = routed.payload.get("audit", {})
            return (
                detail,
                [{
                    "query": query,
                    "title": f"{(query or '研究主题')[:40]} 相关综述",
                    "source": "local_rag",
                    "url": "",
                    "published_at": "",
                    "snippet": detail[:200],
                    "confidence": "0.5",
                }],
                None,
                audit if isinstance(audit, dict) else {},
            )
        return (
            f"联网检索失败：{routed.error_code} - {routed.error_message}",
            [],
            {"code": routed.error_code, "message": routed.error_message},
            routed.payload.get("audit", {}),
        )
    summary = str(routed.payload.get("summary", "")).strip()
    citations = routed.payload.get("citations", [])
    return summary, citations if isinstance(citations, list) else [], None, routed.payload.get("audit", {})


def _render_search_detail(
    subtask: dict[str, object],
    round_no: int,
    search_payload: dict[str, object],
    search_detail: str,
    search_audit: dict[str, object],
) -> str:
    lines = ["正在执行检索", f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}"]
    groups = search_payload.get("info_groups", [])
    if isinstance(groups, list):
        lines.append(f"信息分组数：{len(groups)}")
    lines.append(f"工具检索：{search_detail}")
    lines.append(f"工具状态：{str(search_audit.get('status', '')).strip() or 'unknown'}")
    lines.append(f"轮次：{round_no}")
    return "\n".join(lines)


def _render_read_detail(subtask: dict[str, object], round_no: int, read_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "正在阅读与分析证据",
            f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}",
            f"核心结论：{str(read_payload.get('analysis', '')).strip()}",
            f"轮次：{round_no}",
        ]
    )


def _render_reflect_detail(subtask: dict[str, object], round_no: int, reflect_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "正在反思与校验",
            f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}",
            f"是否继续优化：{'是' if str(reflect_payload.get('needs_optimization', '')).strip() == 'yes' else '否'}",
            f"裁决原因：{str(reflect_payload.get('reason', '')).strip()}",
            f"轮次：{round_no}",
        ]
    )


def _render_write_detail(write_payload: dict[str, object], total_rounds: int) -> str:
    title = str(write_payload.get("title", "")).strip() or "研究报告"
    sections = write_payload.get("sections", [])
    return "\n".join(
        [
            "正在生成研究报告",
            f"报告标题：{title}",
            f"章节数：{len(sections) if isinstance(sections, list) else 0}",
            f"总反思轮次：{total_rounds}",
        ]
    )


def _render_local_command_detail(round_no: int, audit: dict[str, object]) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = ["正在执行本地命令工具", f"执行状态：{status}"]
    if detail:
        lines.append(f"执行说明：{detail}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_local_file_detail(round_no: int, audit: dict[str, object], action: str) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = ["正在执行本地文件工具", f"执行状态：{status}", f"动作：{action or 'unknown'}"]
    if detail:
        lines.append(f"执行说明：{detail}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _maybe_run_local_command(task: AgentTask, query: str) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("local_command_executed")):
        return None
    local_cmd = cfg.get("local_command")
    if not isinstance(local_cmd, dict):
        return None
    template = str(local_cmd.get("template", "")).strip()
    if not template:
        return None
    args = local_cmd.get("args", {})
    runtime_args = dict(args) if isinstance(args, dict) else {}
    runtime_args.setdefault("query", query[:200])
    approved_raw = cfg.get("approved_local_command_templates", [])
    approved = set(str(item) for item in approved_raw) if isinstance(approved_raw, list) else set()
    risk_strategy = str(cfg.get("risk_confirmation_strategy", "on_high_risk"))
    if template in approved:
        risk_strategy = "never"
    result = route_tool_call(
        tool_name="local_command",
        args={"template": template, "args": runtime_args},
        risk_confirmation_strategy=risk_strategy,
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": payload.get("confirmation_payload"),
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": payload.get("audit", {}),
    }


def _maybe_run_local_file_action(task: AgentTask) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("local_file_action_executed")):
        return None
    action_cfg = cfg.get("local_file_action")
    if not isinstance(action_cfg, dict):
        return None
    action = str(action_cfg.get("action", "")).strip()
    if not action:
        return None
    args = action_cfg.get("args", {})
    safe_args = args if isinstance(args, dict) else {}
    approved_raw = cfg.get("approved_local_file_actions", [])
    approved = set(str(item) for item in approved_raw) if isinstance(approved_raw, list) else set()
    risk_strategy = str(cfg.get("risk_confirmation_strategy", "on_high_risk"))
    if action in approved:
        risk_strategy = "never"
    result = route_tool_call(
        tool_name="local_file",
        args={"action": action, "args": safe_args},
        risk_confirmation_strategy=risk_strategy,
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": payload.get("confirmation_payload"),
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": payload.get("audit", {}),
        "action": action,
    }


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


def _task_for_update(task_id: uuid.UUID):
    qs = AgentTask.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def execute_task_pipeline(task_id: uuid.UUID) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            if task.status == "pending":
                task.status = "running"
                task.save(update_fields=["status", "updated_at"])

        with transaction.atomic():
            task = _task_for_update(task_id)
            query = _latest_user_query(task)
            max_rounds = _max_reflect_rounds(task)

        all_citations: list[dict[str, str]] = []
        all_reflector_conclusions: list[dict[str, object]] = []
        final_subtask_summaries: list[dict[str, object]] = []
        reflector_history_suggestions: list[str] = []
        total_reflect_rounds = 0

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="plan",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_PLAN.format(
                    query=query,
                    suggestions=json.dumps(reflector_history_suggestions, ensure_ascii=False),
                ),
                temperature=0.2,
                max_tokens=900,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            planner_payload, parse_err = _normalize_json(raw or "", "plan")
            if planner_payload is None:
                _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                return
            ok, err_msg = _validate_planner_json(planner_payload)
            if not ok:
                _fail_task(task, "LLM_JSON_INVALID", f"plan阶段JSON校验失败: {err_msg}")
                return
            _append_step(task, "plan", "规划研究任务", "已输出多方案规划")
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        alternatives = planner_payload.get("alternatives", [])
        assert isinstance(alternatives, list)

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="decide",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_DECIDE.format(
                    query=query,
                    alternatives_json=json.dumps(alternatives, ensure_ascii=False),
                ),
                temperature=0.1,
                max_tokens=1000,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            decision_payload, parse_err = _normalize_json(raw or "", "decide")
            if decision_payload is None:
                _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                return
            ok, err_msg = _validate_decider_json(decision_payload, alternatives)
            if not ok:
                _fail_task(task, "LLM_JSON_INVALID", f"decide阶段JSON校验失败: {err_msg}")
                return
            _append_step(task, "decide", "方案决策与拆解", "已输出复杂度与子任务列表")
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        subtasks = decision_payload.get("subtasks", [])
        assert isinstance(subtasks, list)

        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            subtask_id = str(subtask.get("subtask_id", "")).strip() or "unknown"
            subtask_title = str(subtask.get("title", "")).strip() or "未命名子任务"
            subtask_goal = str(subtask.get("goal", "")).strip() or subtask_title
            feedback = ""
            round_no = 1

            while True:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    search_prompt = USER_PROMPT_SEARCH.format(
                        query=query,
                        plan_text=subtask_title,
                        reflect_round=round_no,
                        max_rounds=max_rounds,
                    )
                    if feedback:
                        search_prompt += f"\nprevious_reflector_feedback: {feedback}"
                    raw, err = _llm_call(
                        phase="search",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=search_prompt,
                        temperature=0.1,
                        max_tokens=900,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    search_payload, parse_err = _normalize_json(raw or "", "search")
                    if search_payload is None:
                        _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                        return
                    ok, err_msg = _validate_searcher_json(search_payload)
                    if not ok:
                        _fail_task(task, "LLM_JSON_INVALID", f"search阶段JSON校验失败: {err_msg}")
                        return

                search_detail, citations, fatal, search_audit = _search_context(subtask_goal)
                if fatal:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _append_step(task, "search", f"检索失败：{subtask_title}", str(fatal.get("message", "")))
                        _fail_task(task, str(fatal["code"]), str(fatal["message"]))
                    return

                all_citations.extend(citations)
                info_groups = search_payload.get("info_groups")
                assert isinstance(info_groups, list)
                if citations:
                    info_groups.append(
                        {
                            "group_title": "工具检索补充",
                            "relevance": "medium",
                            "raw_findings": [search_detail or "无补充"],
                            "sources": [
                                {
                                    "title": str(item.get("title", "")).strip(),
                                    "url": str(item.get("url", "")).strip(),
                                    "snippet": str(item.get("snippet", "")).strip(),
                                    "raw_content": str(item.get("raw_content", "")).strip(),
                                }
                                for item in citations
                                if isinstance(item, dict)
                            ],
                        }
                    )

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    _append_step(
                        task,
                        "search",
                        f"检索子任务：{subtask_title}",
                        _render_search_detail(subtask, round_no, search_payload, search_detail, search_audit),
                    )
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                local_cmd_result = _maybe_run_local_command(task, subtask_goal)
                if local_cmd_result:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _append_step(task, "search", "执行本地命令工具", _render_local_command_detail(round_no, local_cmd_result["audit"]))
                        if local_cmd_result["requires_confirmation"]:
                            task.status = "pending_action"
                            task.intervention = local_cmd_result["confirmation_payload"]
                            task.save(update_fields=["status", "intervention", "step_seq", "steps", "updated_at"])
                            return
                        if not local_cmd_result["ok"]:
                            _fail_task(task, str(local_cmd_result.get("error_code") or "LOCAL_CMD_FAILED"), str(local_cmd_result.get("error_message") or "本地命令执行失败"))
                            return
                        _update_runtime_config(task, local_command_executed=True)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

                local_file_result = _maybe_run_local_file_action(task)
                if local_file_result:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _append_step(
                            task,
                            "search",
                            "执行本地文件工具",
                            _render_local_file_detail(round_no, local_file_result["audit"], str(local_file_result.get("action", ""))),
                        )
                        if local_file_result["requires_confirmation"]:
                            task.status = "pending_action"
                            task.intervention = local_file_result["confirmation_payload"]
                            task.save(update_fields=["status", "intervention", "step_seq", "steps", "updated_at"])
                            return
                        if not local_file_result["ok"]:
                            _fail_task(task, str(local_file_result.get("error_code") or "LOCAL_FILE_FAILED"), str(local_file_result.get("error_message") or "本地文件执行失败"))
                            return
                        _update_runtime_config(task, local_file_action_executed=True)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    raw, err = _llm_call(
                        phase="read",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=USER_PROMPT_READ.format(
                            query=query,
                            search_detail=json.dumps(info_groups, ensure_ascii=False),
                            citations=_render_citations(citations),
                        ),
                        temperature=0.2,
                        max_tokens=900,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    read_payload, parse_err = _normalize_json(raw or "", "read")
                    if read_payload is None:
                        _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                        return
                    ok, err_msg = _validate_read_json(read_payload)
                    if not ok:
                        _fail_task(task, "LLM_JSON_INVALID", f"read阶段JSON校验失败: {err_msg}")
                        return
                    _append_step(task, "read", f"阅读子任务：{subtask_title}", _render_read_detail(subtask, round_no, read_payload))
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    raw, err = _llm_call(
                        phase="reflect",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=USER_PROMPT_REFLECT.format(
                            plan_text=json.dumps(subtask, ensure_ascii=False),
                            analysis_text=json.dumps(read_payload, ensure_ascii=False),
                            reflect_round=round_no,
                            max_rounds=max_rounds,
                        ),
                        temperature=0.1,
                        max_tokens=700,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    reflect_payload, parse_err = _normalize_json(raw or "", "reflect")
                    if reflect_payload is None:
                        _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                        return
                    ok, err_msg = _validate_reflector_json(reflect_payload)
                    _append_step(task, "reflect", f"反思子任务：{subtask_title}", _render_reflect_detail(subtask, round_no, reflect_payload))
                    if not ok:
                        _fail_task(task, "LLM_JSON_INVALID", f"reflect阶段JSON校验失败: {err_msg}")
                        return
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                total_reflect_rounds += 1
                suggestions = reflect_payload.get("actionable_suggestions", [])
                assert isinstance(suggestions, list)
                reflector_history_suggestions.extend([str(s).strip() for s in suggestions if str(s).strip()])
                all_reflector_conclusions.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "round": round_no,
                        "needs_optimization": reflect_payload.get("needs_optimization"),
                        "reason": reflect_payload.get("reason"),
                        "actionable_suggestions": suggestions,
                    }
                )
                accepted = reflect_payload.get("accepted_reader_summary")
                assert isinstance(accepted, dict)
                if reflect_payload.get("needs_optimization") == "yes" and round_no < max_rounds:
                    feedback = "; ".join(suggestions)
                    round_no += 1
                    continue
                final_subtask_summaries.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "subtask_goal": subtask_goal,
                        "accepted_reader_summary": accepted,
                        "final_round": round_no,
                    }
                )
                break

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="write",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_WRITE.format(
                    query=query,
                    plan_text=json.dumps(decision_payload, ensure_ascii=False),
                    analysis_text=json.dumps(final_subtask_summaries, ensure_ascii=False),
                    citations=json.dumps(all_reflector_conclusions, ensure_ascii=False),
                ),
                temperature=0.2,
                max_tokens=2200,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            write_payload, parse_err = _normalize_json(raw or "", "write")
            if write_payload is None:
                _fail_task(task, "LLM_JSON_INVALID", str(parse_err))
                return
            ok, err_msg = _validate_write_json(write_payload, subtasks)
            if not ok:
                _fail_task(task, "LLM_JSON_INVALID", f"write阶段JSON校验失败: {err_msg}")
                return
            report_body = _markdown_from_write_json(write_payload)
            _append_step(task, "write", "生成报告", _render_write_detail(write_payload, total_reflect_rounds))
            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": report_body,
                "citations": all_citations,
                "attachments": [],
                "pipeline": list(PIPELINE_PHASES),
                "reflect_rounds": total_reflect_rounds,
                "applied_suggestions": reflector_history_suggestions,
                "planner_alternatives": alternatives,
                "decider_decision": decision_payload,
                "subtask_summaries": final_subtask_summaries,
                "all_reflector_conclusions": all_reflector_conclusions,
                "runtime_config": _runtime_config(task),
            }
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
            content=f"{REPORT_MESSAGE_PREFIX}{report_body}",
        )
        ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
    finally:
        close_old_connections()


def execute_after_approve(task_id: uuid.UUID) -> None:
    close_old_connections()
    try:
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_after_revise(task_id: uuid.UUID, message: str) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            _append_step(task, "decide", "按修订指令调整", f"已记录修订：{message[:200]}")
            task.save(update_fields=["step_seq", "steps", "updated_at"])
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_first_segment(task_id: uuid.UUID) -> None:
    execute_task_pipeline(task_id)


def start_first_segment_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_task_pipeline(task_id)
        return

    def _run() -> None:
        execute_task_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-mock-{task_id}", daemon=True).start()


def start_after_approve_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_after_approve(task_id)
        return

    def _run() -> None:
        execute_after_approve(task_id)

    threading.Thread(target=_run, name=f"ra-approve-{task_id}", daemon=True).start()


def start_after_revise_thread(task_id: uuid.UUID, message: str) -> None:
    if connection.vendor == "sqlite":
        execute_after_revise(task_id, message)
        return

    def _run() -> None:
        execute_after_revise(task_id, message)

    threading.Thread(target=_run, name=f"ra-revise-{task_id}", daemon=True).start()
