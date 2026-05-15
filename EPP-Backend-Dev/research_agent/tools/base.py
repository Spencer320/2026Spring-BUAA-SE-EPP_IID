from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


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


def make_audit(tool: str, status: str, detail: str, **metadata: object) -> ToolAuditEvent:
    return ToolAuditEvent(
        tool=tool,
        status=status,
        detail=detail,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )


def truncate_text(text: str, max_len: int = 30000) -> str:
    val = (text or "").strip()
    if len(val) > max_len:
        return val[:max_len] + "…"
    return val


def extract_url_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
