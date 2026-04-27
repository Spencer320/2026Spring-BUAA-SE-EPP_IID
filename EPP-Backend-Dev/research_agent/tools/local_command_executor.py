from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from django.conf import settings

from .base import ToolAuditEvent, make_audit, truncate_text


@dataclass(frozen=True)
class CommandExecutionResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    audit: ToolAuditEvent
    requires_confirmation: bool = False
    confirmation_payload: dict[str, object] | None = None
    error_code: str = ""
    error_message: str = ""


def _allowed_command_templates() -> dict[str, list[str]]:
    configured = getattr(settings, "RA_LOCAL_COMMAND_TEMPLATES", None)
    if isinstance(configured, dict):
        cleaned: dict[str, list[str]] = {}
        for name, argv in configured.items():
            if isinstance(name, str) and isinstance(argv, list) and argv:
                cleaned[name] = [str(part) for part in argv]
        if cleaned:
            return cleaned
    return {
        "pwd": ["pwd"],
        "list_workspace": ["ls", "-1"],
        "python_version": ["python", "--version"],
    }


def _high_risk_templates() -> set[str]:
    configured = getattr(settings, "RA_LOCAL_COMMAND_HIGH_RISK_TEMPLATES", None)
    if isinstance(configured, (list, tuple, set)):
        return {str(item) for item in configured}
    return set(_allowed_command_templates().keys())


def _safe_interpolate(part: str, args: dict[str, object]) -> str:
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)\}")

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = args.get(key, "")
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"非法参数类型: {key}")
        text = str(value)
        if not re.fullmatch(r"[a-zA-Z0-9_\-./:@ ]{0,200}", text):
            raise ValueError(f"参数包含非法字符: {key}")
        return text

    return pattern.sub(_replace, part)


def execute_controlled_local_command(
    *,
    template: str,
    args: dict[str, object] | None,
    risk_confirmation_strategy: str,
) -> CommandExecutionResult:
    tpl = (template or "").strip()
    templates = _allowed_command_templates()
    if tpl not in templates:
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error_code="LOCAL_CMD_NOT_ALLOWED",
            error_message=f"命令模板不在白名单: {tpl}",
            audit=make_audit("local_command", "error", "命令模板不在白名单", template=tpl),
        )

    risk_strategy = (risk_confirmation_strategy or "on_high_risk").strip()
    if risk_strategy not in {"on_high_risk", "always", "never"}:
        risk_strategy = "on_high_risk"
    is_high_risk = tpl in _high_risk_templates()
    needs_confirm = risk_strategy == "always" or (risk_strategy == "on_high_risk" and is_high_risk)
    if needs_confirm:
        payload = {
            "type": "tool_confirmation",
            "tool": "local_command",
            "template": tpl,
            "args": args or {},
            "risk_level": "high" if is_high_risk else "medium",
            "message": f"命令模板 {tpl} 需要人工确认后执行",
        }
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            requires_confirmation=True,
            confirmation_payload=payload,
            error_code="LOCAL_CMD_CONFIRM_REQUIRED",
            error_message=payload["message"],
            audit=make_audit(
                "local_command",
                "pending_action",
                payload["message"],
                template=tpl,
                args=args or {},
                risk_strategy=risk_strategy,
            ),
        )

    runtime_args = args or {}
    try:
        argv = [_safe_interpolate(item, runtime_args) for item in templates[tpl]]
    except ValueError as exc:
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error_code="LOCAL_CMD_INVALID_ARGS",
            error_message=str(exc),
            audit=make_audit("local_command", "error", "命令参数非法", template=tpl, args=runtime_args),
        )

    timeout = float(getattr(settings, "RA_LOCAL_CMD_TIMEOUT", 8.0))
    max_output = int(getattr(settings, "RA_LOCAL_CMD_MAX_OUTPUT_CHARS", 4000))
    cwd_raw = getattr(settings, "RA_LOCAL_CMD_WORKDIR", "") or ""
    cwd = cwd_raw.strip() or str(Path.cwd())
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error_code="LOCAL_CMD_TIMEOUT",
            error_message=f"命令执行超时（{timeout}s）",
            audit=make_audit("local_command", "error", "命令执行超时", template=tpl, argv=argv, timeout=timeout),
        )
    except OSError as exc:
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error_code="LOCAL_CMD_EXEC_ERROR",
            error_message=str(exc),
            audit=make_audit("local_command", "error", "命令执行失败", template=tpl, argv=argv),
        )

    stdout = truncate_text(proc.stdout or "", max_output)
    stderr = truncate_text(proc.stderr or "", max_output)
    if proc.returncode != 0:
        return CommandExecutionResult(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode,
            error_code="LOCAL_CMD_NON_ZERO_EXIT",
            error_message=f"命令返回非零退出码：{proc.returncode}",
            audit=make_audit(
                "local_command",
                "error",
                "命令返回非零退出码",
                template=tpl,
                argv=argv,
                exit_code=proc.returncode,
            ),
        )
    return CommandExecutionResult(
        ok=True,
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode,
        audit=make_audit("local_command", "ok", "命令执行成功", template=tpl, argv=argv, exit_code=proc.returncode),
    )

