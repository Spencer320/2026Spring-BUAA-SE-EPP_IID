from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .base import truncate_text


@dataclass(frozen=True)
class OutboundResult:
    ok: bool
    summary: str = ""
    error_code: str = ""
    error_message: str = ""


def _normalize_host(hostname: str) -> str:
    return hostname.lower().rstrip(".")


def is_host_allowed(hostname: str, *, setting_name: str = "RA_ALLOWED_HOSTS") -> bool:
    allowed = getattr(settings, setting_name, None) or []
    if not hostname:
        return False
    h = _normalize_host(hostname)
    return any(_normalize_host(str(a)) == h for a in allowed)


def allowed_get(url: str, *, hosts_setting: str = "RA_ALLOWED_HOSTS") -> OutboundResult:
    raw = (url or "").strip()
    if not raw:
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="URL 为空")
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="URL 解析失败")
    if parsed.scheme not in ("http", "https"):
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="仅允许 http/https")
    host = parsed.hostname
    if not host:
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="缺少主机名")
    if not is_host_allowed(host, setting_name=hosts_setting):
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
        return OutboundResult(ok=False, error_code="OUTBOUND_TIMEOUT", error_message="请求超时")
    except httpx.RequestError as exc:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_HTTP_ERROR",
            error_message=str(exc) or "网络请求失败",
        )
    text = body.decode("utf-8", errors="replace")
    return OutboundResult(ok=True, summary=truncate_text(text))

