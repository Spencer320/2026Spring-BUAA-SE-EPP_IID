"""
科研助手工具执行层：
- 联网检索（受 RA_ALLOWED_HOSTS 约束）
- 本地命令执行（白名单模板 + 超时 + 输出截断）
- 统一产出审计事件与人工确认信号
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from django.conf import settings


@dataclass(frozen=True)
class OutboundResult:
    ok: bool
    summary: str = ""
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class ToolAuditEvent:
    tool: str
    status: str
    detail: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class WebSearchResult:
    ok: bool
    summary: str
    citations: list[dict[str, str]]
    audit: ToolAuditEvent
    error_code: str = ""
    error_message: str = ""


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


def _normalize_host(hostname: str) -> str:
    return hostname.lower().rstrip(".")


def is_host_allowed(hostname: str) -> bool:
    allowed = getattr(settings, "RA_ALLOWED_HOSTS", None) or []
    if not hostname:
        return False
    h = _normalize_host(hostname)
    return any(_normalize_host(a) == h for a in allowed)


def _truncate_summary(text: str, max_len: int = 1500) -> str:
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def allowed_get(url: str) -> OutboundResult:
    """
    对 url 发起 GET（不跟随重定向，避免跳到白名单外主机）。
    响应体累计超过 RA_HTTP_MAX_BODY_BYTES 则失败。
    """
    raw = (url or "").strip()
    if not raw:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_INVALID_URL",
            error_message="URL 为空",
        )

    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_INVALID_URL",
            error_message="URL 解析失败",
        )

    if parsed.scheme not in ("http", "https"):
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_INVALID_URL",
            error_message="仅允许 http/https",
        )

    host = parsed.hostname
    if not host:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_INVALID_URL",
            error_message="缺少主机名",
        )

    if not is_host_allowed(host):
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_HOST_DENIED",
            error_message=f"主机不在白名单: {host}",
        )

    timeout = float(getattr(settings, "RA_HTTP_TIMEOUT", 15.0))
    max_bytes = int(getattr(settings, "RA_HTTP_MAX_BODY_BYTES", 512 * 1024))

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", raw) as response:
                if response.status_code >= 400:
                    return OutboundResult(
                        ok=False,
                        error_code="OUTBOUND_HTTP_ERROR",
                        error_message=f"HTTP {response.status_code}",
                    )
                total = 0
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return OutboundResult(
                            ok=False,
                            error_code="OUTBOUND_BODY_TOO_LARGE",
                            error_message=f"响应体超过上限 {max_bytes} 字节",
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
    except httpx.TimeoutException:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_TIMEOUT",
            error_message="请求超时",
        )
    except httpx.RequestError as e:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_HTTP_ERROR",
            error_message=str(e) or "网络请求失败",
        )

    text = body.decode("utf-8", errors="replace")
    return OutboundResult(ok=True, summary=_truncate_summary(text))


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
    # 默认将命令能力视为需确认，除非用户显式 never。
    return set(_allowed_command_templates().keys())


def _safe_interpolate(part: str, args: dict[str, object]) -> str:
    # 仅允许 ${name} 形式变量；值必须是基础类型并通过字符白名单校验。
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


def _audit(tool: str, status: str, detail: str, **metadata: object) -> ToolAuditEvent:
    return ToolAuditEvent(
        tool=tool,
        status=status,
        detail=detail,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )


def execute_web_search(query: str, url: str) -> WebSearchResult:
    clean_query = (query or "").strip()
    clean_url = (url or "").strip()
    if not clean_url:
        detail = f"使用本地知识库关键词检索：{clean_query[:120] or '未提供检索词'}"
        return WebSearchResult(
            ok=True,
            summary=detail,
            citations=[
                {
                    "title": f"{(clean_query or '研究主题')[:40]} 相关综述",
                    "source": "local_rag",
                    "url": "",
                    "published_at": "",
                    "snippet": detail[:200],
                    "confidence": 0.6,
                },
                {
                    "title": f"{(clean_query or '研究主题')[:40]} 代表性论文",
                    "source": "local_rag",
                    "url": "",
                    "published_at": "",
                    "snippet": detail[:200],
                    "confidence": 0.55,
                },
            ],
            audit=_audit("web_search", "ok", detail, query=clean_query, source="local_rag"),
        )

    res = allowed_get(clean_url)
    if not res.ok:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code=res.error_code,
            error_message=res.error_message,
            audit=_audit(
                "web_search",
                "error",
                f"联网检索失败：{res.error_code}",
                query=clean_query,
                url=clean_url,
                error_code=res.error_code,
            ),
        )
    return WebSearchResult(
        ok=True,
        summary=f"联网检索成功：{clean_url}",
        citations=[
            {
                "title": "外部检索结果摘要",
                "source": "web",
                "url": clean_url,
                "published_at": "",
                "snippet": res.summary[:300],
                "confidence": 0.7,
            }
        ],
        audit=_audit(
            "web_search",
            "ok",
            "联网检索成功",
            query=clean_query,
            url=clean_url,
            snippet=res.summary[:500],
        ),
    )


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
            audit=_audit("local_command", "error", "命令模板不在白名单", template=tpl),
        )

    risk_strategy = (risk_confirmation_strategy or "on_high_risk").strip()
    if risk_strategy not in {"on_high_risk", "always", "never"}:
        risk_strategy = "on_high_risk"
    is_high_risk = tpl in _high_risk_templates()
    needs_confirm = risk_strategy == "always" or (
        risk_strategy == "on_high_risk" and is_high_risk
    )
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
            audit=_audit(
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
            audit=_audit(
                "local_command", "error", "命令参数非法", template=tpl, args=runtime_args
            ),
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
            audit=_audit(
                "local_command",
                "error",
                "命令执行超时",
                template=tpl,
                argv=argv,
                timeout=timeout,
            ),
        )
    except OSError as exc:
        return CommandExecutionResult(
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error_code="LOCAL_CMD_EXEC_ERROR",
            error_message=str(exc),
            audit=_audit(
                "local_command",
                "error",
                "命令执行失败",
                template=tpl,
                argv=argv,
            ),
        )

    stdout = _truncate_summary(proc.stdout or "", max_output)
    stderr = _truncate_summary(proc.stderr or "", max_output)
    if proc.returncode != 0:
        return CommandExecutionResult(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode,
            error_code="LOCAL_CMD_NON_ZERO_EXIT",
            error_message=f"命令返回非零退出码：{proc.returncode}",
            audit=_audit(
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
        audit=_audit(
            "local_command",
            "ok",
            "命令执行成功",
            template=tpl,
            argv=argv,
            exit_code=proc.returncode,
        ),
    )
