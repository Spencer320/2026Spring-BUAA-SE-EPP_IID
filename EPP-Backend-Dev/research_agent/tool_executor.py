"""
出站 HTTP 工具：仅允许对 RA_ALLOWED_HOSTS 中的主机发起 GET，并生成响应体摘要。
失败时返回与 API 任务 error 字段一致风格的 code/message（由编排器写入 AgentTask）。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from django.conf import settings


@dataclass(frozen=True)
class OutboundResult:
    ok: bool
    summary: str = ""
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
