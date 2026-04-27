from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .local_command_executor import execute_controlled_local_command
from .local_file_executor import execute_local_file_action
from .web_search_executor import execute_web_search


@dataclass(frozen=True)
class ToolRouteResult:
    ok: bool
    payload: dict[str, Any]
    error_code: str = ""
    error_message: str = ""


def route_tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    risk_confirmation_strategy: str = "on_high_risk",
) -> ToolRouteResult:
    runtime_args = args or {}
    t = (tool_name or "").strip()

    if t == "web_search":
        res = execute_web_search(
            query=str(runtime_args.get("query", "")).strip(),
            url=str(runtime_args.get("url", "")).strip(),
        )
        return ToolRouteResult(
            ok=res.ok,
            payload={
                "summary": res.summary,
                "citations": res.citations,
                "audit": {
                    "tool": res.audit.tool,
                    "status": res.audit.status,
                    "detail": res.audit.detail,
                    "meta": res.audit.metadata,
                },
            },
            error_code=res.error_code,
            error_message=res.error_message,
        )

    if t == "local_command":
        res = execute_controlled_local_command(
            template=str(runtime_args.get("template", "")).strip(),
            args=runtime_args.get("args", {}) if isinstance(runtime_args.get("args"), dict) else {},
            risk_confirmation_strategy=risk_confirmation_strategy,
        )
        return ToolRouteResult(
            ok=res.ok,
            payload={
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.exit_code,
                "requires_confirmation": res.requires_confirmation,
                "confirmation_payload": res.confirmation_payload,
                "audit": {
                    "tool": res.audit.tool,
                    "status": res.audit.status,
                    "detail": res.audit.detail,
                    "meta": res.audit.metadata,
                },
            },
            error_code=res.error_code,
            error_message=res.error_message,
        )

    if t == "local_file":
        res = execute_local_file_action(
            action=str(runtime_args.get("action", "")).strip(),
            args=runtime_args.get("args", {}) if isinstance(runtime_args.get("args"), dict) else {},
            risk_confirmation_strategy=risk_confirmation_strategy,
        )
        return ToolRouteResult(
            ok=res.ok,
            payload={
                "output": res.output,
                "requires_confirmation": res.requires_confirmation,
                "confirmation_payload": res.confirmation_payload,
                "audit": {
                    "tool": res.audit.tool,
                    "status": res.audit.status,
                    "detail": res.audit.detail,
                    "meta": res.audit.metadata,
                },
            },
            error_code=res.error_code,
            error_message=res.error_message,
        )

    return ToolRouteResult(
        ok=False,
        payload={},
        error_code="TOOL_NOT_SUPPORTED",
        error_message=f"unsupported tool: {t}",
    )

