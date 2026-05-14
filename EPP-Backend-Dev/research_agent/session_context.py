"""
会话级辅助上下文：跨 basic-run 的最近多轮摘要 + 用户通过 UI 指定的工作区路径。

- ``build_recent_turns_markdown``：最多最近 3 轮完整对话（去「任务已启动」占位助手消息）。
- ``parse_and_validate_workspace_refs``：校验 ``rel_path`` 落在用户工作区内且类型与 ``kind`` 一致。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from business.utils.user_workspace import safe_resolve

from .models import ResearchMessage, ResearchSession

_ACK_STUBS = frozenset(
    {
        "已收到请求，任务已启动。",
        "已收到深度研究请求，任务已启动。",
    }
)

_MAX_ASSISTANT_CHARS = 2800
_MAX_WORKSPACE_REFS = 24


def _is_ack_stub(content: str) -> bool:
    return (content or "").strip() in _ACK_STUBS


def _strip_ack_messages(msgs: list[ResearchMessage]) -> list[ResearchMessage]:
    return [m for m in msgs if not (m.role == "assistant" and _is_ack_stub(m.content))]


def build_recent_turns_markdown(session: ResearchSession, *, max_turns: int = 3) -> str:
    """
    返回供 planner / refill / chat 使用的 Markdown 文本；不含「当前这条」用户消息正文
    （当前句由调用方单独传入）。最多 ``max_turns`` 个完整 user→assistant 轮。
    """
    if max_turns < 1:
        return ""
    raw = list(ResearchMessage.objects.filter(session=session).order_by("created_at"))
    filtered = _strip_ack_messages(raw)
    if not filtered or filtered[-1].role != "user":
        return ""
    # 去掉当前轮的用户消息（本轮 basic 刚写入的最后一条 user）
    before_current = filtered[:-1]
    if not before_current:
        return ""
    turns: list[tuple[str, str]] = []
    i = 0
    while i < len(before_current):
        if before_current[i].role != "user":
            i += 1
            continue
        u_text = (before_current[i].content or "").strip()
        i += 1
        a_parts: list[str] = []
        while i < len(before_current) and before_current[i].role == "assistant":
            a_parts.append((before_current[i].content or "").strip())
            i += 1
        a_merged = _merge_assistant_turn(a_parts)
        if u_text or a_merged:
            turns.append((u_text, a_merged))
    tail = turns[-max_turns:]
    if not tail:
        return ""
    lines: list[str] = ["### 近期对话（不含本轮最新输入，最多{}轮）".format(len(tail))]
    for idx, (u, a) in enumerate(tail, 1):
        lines.append(f"**第{idx}轮 · 用户**\n{u[:4000] or '（空）'}")
        at = a[:_MAX_ASSISTANT_CHARS] if a else "（无助手回复）"
        if len(a) > _MAX_ASSISTANT_CHARS:
            at += "\n…（已截断）"
        lines.append(f"**第{idx}轮 · 助手**\n{at}")
        lines.append("")
    return "\n".join(lines).strip()


def _merge_assistant_turn(parts: list[str]) -> str:
    substantive = [p for p in parts if p and not _is_ack_stub(p)]
    if not substantive:
        return ""
    if len(substantive) == 1:
        return substantive[0]
    return "\n\n---\n\n".join(substantive[-3:])


def parse_and_validate_workspace_refs(user_id: str, raw: Any) -> tuple[list[dict[str, str]], str | None]:
    """
    解析 ``workspace_refs`` JSON；成功返回 (规范化列表, None)，失败返回 ([], 错误信息)。
    每项: ``{"kind": "file"|"dir", "rel_path": "...", "label": "..."}``（label 可选）。
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return [], "workspace_refs must be an array"
    if len(raw) > _MAX_WORKSPACE_REFS:
        return [], f"workspace_refs too many items (max {_MAX_WORKSPACE_REFS})"
    out: list[dict[str, str]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"workspace_refs[{idx}] must be an object"
        kind = str(item.get("kind") or "").strip().lower()
        rel = str(item.get("rel_path") or item.get("path") or "").strip().lstrip("/").replace("\\", "/")
        label = str(item.get("label") or "").strip()
        if kind not in {"file", "dir"}:
            return [], f"workspace_refs[{idx}].kind must be file or dir"
        if not rel:
            return [], f"workspace_refs[{idx}].rel_path is required"
        target = safe_resolve(str(user_id), rel)
        if target is None:
            return [], f"workspace_refs[{idx}] path forbidden or invalid: {rel!r}"
        if not target.exists():
            return [], f"workspace_refs[{idx}] not found: {rel!r}"
        if kind == "file" and not target.is_file():
            return [], f"workspace_refs[{idx}] is not a file: {rel!r}"
        if kind == "dir" and not target.is_dir():
            return [], f"workspace_refs[{idx}] is not a directory: {rel!r}"
        if not label:
            label = Path(rel).name or rel
        out.append({"kind": kind, "rel_path": rel, "label": label[:256]})
    return out, None


def format_workspace_refs_markdown(refs: list[dict[str, str]] | None) -> str:
    if not refs:
        return ""
    lines = ["### 用户通过 UI 指定的工作区路径（须优先使用，勿猜测路径）"]
    for i, r in enumerate(refs, 1):
        kind = r.get("kind", "")
        rp = r.get("rel_path", "")
        lb = r.get("label", rp)
        lines.append(f"{i}. [{kind}] `{rp}`（{lb}）")
    return "\n".join(lines).strip()


def combine_session_context_blocks(*, dialog: str, workspace: str) -> str:
    parts = [p for p in (dialog.strip(), workspace.strip()) if p]
    if not parts:
        return ""
    return "\n\n".join(parts).strip()


def session_context_for_prompts(
    session: ResearchSession,
    *,
    workspace_refs: list[dict[str, str]] | None,
    max_turns: int = 3,
) -> tuple[str, str, str]:
    """
    返回 ``(dialog_block, workspace_block, combined)``；空块为空串。
    ``workspace_refs`` 通常来自本轮 ``BasicOrchestratorRun`` 的 ``runtime_config``。
    """
    dialog = build_recent_turns_markdown(session, max_turns=max_turns)
    ws = format_workspace_refs_markdown(workspace_refs or [])
    return dialog, ws, combine_session_context_blocks(dialog=dialog, workspace=ws)
