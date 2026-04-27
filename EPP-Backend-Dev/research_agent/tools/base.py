from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolAuditEvent:
    tool: str
    status: str
    detail: str
    metadata: dict[str, object]


def make_audit(tool: str, status: str, detail: str, **metadata: object) -> ToolAuditEvent:
    return ToolAuditEvent(
        tool=tool,
        status=status,
        detail=detail,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )


def truncate_text(text: str, max_len: int = 1500) -> str:
    val = (text or "").strip()
    if len(val) > max_len:
        return val[:max_len] + "…"
    return val

