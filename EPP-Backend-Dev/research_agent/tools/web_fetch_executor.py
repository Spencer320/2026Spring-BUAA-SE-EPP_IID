from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from django.conf import settings

from ..site_access_control import evaluate_target_domain
from .base import truncate_text


@dataclass(frozen=True)
class OutboundResult:
    ok: bool
    summary: str = ""
    error_code: str = ""
    error_message: str = ""
    target_domain: str = ""
    rule_hit: str = ""
    policy_version: str = ""


def _normalize_host(hostname: str) -> str:
    return hostname.lower().rstrip(".")


def is_host_allowed(hostname: str, *, setting_name: str = "RA_ALLOWED_HOSTS") -> bool:
    allowed = getattr(settings, setting_name, None) or []
    if not hostname:
        return False
    host = _normalize_host(hostname)
    return any(_normalize_host(str(item)) == host for item in allowed)


def allowed_get(url: str, *, hosts_setting: str = "RA_ALLOWED_HOSTS") -> OutboundResult:
    raw = (url or "").strip()
    if not raw:
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="URL is empty")

    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="URL parse failed")

    if parsed.scheme not in ("http", "https"):
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_INVALID_URL",
            error_message="Only http/https is supported",
        )

    host = parsed.hostname
    if not host:
        return OutboundResult(ok=False, error_code="OUTBOUND_INVALID_URL", error_message="Host is missing")

    normalized_host = _normalize_host(host)
    if not is_host_allowed(normalized_host, setting_name=hosts_setting):
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_HOST_DENIED",
            error_message=f"Host denied by static allowlist: {normalized_host}",
            target_domain=normalized_host,
            rule_hit=f"static_allowlist:{hosts_setting}",
        )

    site_decision = evaluate_target_domain(normalized_host)
    if not site_decision.allowed:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_SITE_DENIED",
            error_message=site_decision.reason_message,
            target_domain=site_decision.target_domain,
            rule_hit=site_decision.rule_hit,
            policy_version=site_decision.policy_version,
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
                        target_domain=site_decision.target_domain,
                        rule_hit=site_decision.rule_hit,
                        policy_version=site_decision.policy_version,
                    )
                total = 0
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return OutboundResult(
                            ok=False,
                            error_code="OUTBOUND_BODY_TOO_LARGE",
                            error_message=f"Response body exceeds {max_bytes} bytes",
                            target_domain=site_decision.target_domain,
                            rule_hit=site_decision.rule_hit,
                            policy_version=site_decision.policy_version,
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
    except httpx.TimeoutException:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_TIMEOUT",
            error_message="Request timeout",
            target_domain=site_decision.target_domain,
            rule_hit=site_decision.rule_hit,
            policy_version=site_decision.policy_version,
        )
    except httpx.RequestError as exc:
        return OutboundResult(
            ok=False,
            error_code="OUTBOUND_HTTP_ERROR",
            error_message=str(exc) or "Network request failed",
            target_domain=site_decision.target_domain,
            rule_hit=site_decision.rule_hit,
            policy_version=site_decision.policy_version,
        )

    text = body.decode("utf-8", errors="replace")
    return OutboundResult(
        ok=True,
        summary=truncate_text(text),
        target_domain=site_decision.target_domain,
        rule_hit=site_decision.rule_hit,
        policy_version=site_decision.policy_version,
    )
