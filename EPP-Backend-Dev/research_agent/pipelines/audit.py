"""跨编排运行实体的行为审计写入（深度 / basic / 工作区）。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from research_agent.models import (
    AgentBehaviorAuditLog,
    AgentTask,
    BasicOrchestratorRun,
    WorkspaceAgentRun,
)

AnyRun = AgentTask | BasicOrchestratorRun | WorkspaceAgentRun


def extract_domain(url: str) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or "").lower()


def _normalize_audit_status(raw: object, *, is_exception: bool, response_status: int | None) -> str:
    status = str(raw or "").strip().lower()
    mapping = {
        "ok": "succeeded",
        "success": "succeeded",
        "succeeded": "succeeded",
        "error": "failed",
        "failed": "failed",
        "pending_action": "pending_action",
        "pending": "pending_action",
        "allowed": "allowed",
        "rejected": "rejected",
        "blocked": "rejected",
    }
    if status in mapping:
        return mapping[status]
    if is_exception:
        return "failed"
    if response_status is not None and response_status >= 400:
        return "failed"
    return "succeeded"


def _sanitize_actor_type(raw: object, default: str = "system") -> str:
    actor = str(raw or "").strip().lower() or default
    if actor not in {"system", "user", "admin"}:
        actor = default
    return actor


def _compact_rule_hit(raw: object) -> str:
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return ",".join(values)[:255]
    if isinstance(raw, dict):
        try:
            return json.dumps(raw, ensure_ascii=False)[:255]
        except TypeError:
            return str(raw)[:255]
    return str(raw or "").strip()[:255]


def append_behavior_log(
    task: AnyRun,
    phase: str,
    title: str,
    detail: str,
    audit: dict[str, Any] | None = None,
) -> None:
    payload = audit or {}
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}

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
    step_id_raw = payload.get("step_id")
    if step_id_raw in (None, ""):
        step_id = int(task.step_seq or 0) or None
    else:
        try:
            step_id = int(step_id_raw)
        except (TypeError, ValueError):
            step_id = int(task.step_seq or 0) or None

    trace_id = str(payload.get("trace_id") or meta.get("trace_id") or "").strip()
    if not trace_id:
        trace_id = f"{task.id}:{step_id or task.step_seq or 0}"

    actor_type = _sanitize_actor_type(payload.get("actor_type"), "system")
    tool_type = str(payload.get("tool_type") or payload.get("tool") or meta.get("tool") or "").strip().lower()
    if not tool_type:
        if phase in {"plan_decide", "analyze", "reflect", "write"}:
            tool_type = "llm"
        else:
            tool_type = "orchestrator"

    risk_level = str(payload.get("risk_level") or meta.get("risk_level") or "").strip().lower()
    if risk_level not in {"", "low", "medium", "high"}:
        risk_level = ""
    rule_hit = _compact_rule_hit(payload.get("rule_hit") or meta.get("rule_hit"))
    policy_version = str(payload.get("policy_version") or meta.get("policy_version") or "").strip()
    audit_status = _normalize_audit_status(
        payload.get("status"),
        is_exception=is_exception,
        response_status=response_status,
    )

    request_payload = payload.get("request_payload")
    if not isinstance(request_payload, dict):
        request_payload = {}
    if not request_payload and meta:
        request_payload = meta

    action_payload = payload.get("action_payload")
    if not isinstance(action_payload, dict):
        action_payload = {"title": title}
    elif "title" not in action_payload:
        action_payload["title"] = title

    log_session = task.session
    deep_task: AgentTask | None = None
    basic_run: BasicOrchestratorRun | None = None
    workspace_run: WorkspaceAgentRun | None = None
    if isinstance(task, AgentTask):
        deep_task = task
    elif isinstance(task, BasicOrchestratorRun):
        basic_run = task
    elif isinstance(task, WorkspaceAgentRun):
        workspace_run = task
    else:
        return

    AgentBehaviorAuditLog.objects.create(
        session=log_session,
        deep_task=deep_task,
        basic_run=basic_run,
        workspace_run=workspace_run,
        operation_type=str(payload.get("operation_type") or phase),
        target_url=target_url,
        target_domain=str(payload.get("target_domain") or extract_domain(target_url)),
        request_headers=payload.get("request_headers") or {},
        request_payload=request_payload,
        action_payload=action_payload,
        step_id=step_id,
        trace_id=trace_id,
        actor_type=actor_type,
        tool_type=tool_type,
        risk_level=risk_level,
        rule_hit=rule_hit,
        policy_version=policy_version,
        status=audit_status,
        response_status=response_status,
        is_exception=is_exception,
        exception_message=str(payload.get("exception_message") or ""),
        trace_detail=detail or title,
    )


# 兼容旧 import 路径
_append_behavior_log = append_behavior_log
_extract_domain = extract_domain
