"""
用户级「论文展示区」：统一收录检索外链与工作区文件条目。

- 外链条目由用户在前端确认后写入（``added_via=user_manual`` 或 ``search``）。
- 工作区条目由用户通过 API 手动添加；路径经 ``safe_resolve`` 校验。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from django.db import IntegrityError, transaction
from business.utils.user_workspace import get_workspace_root, safe_resolve

from .models import ResearchPaperShelfItem

SOURCE_EXTERNAL = "external_link"
SOURCE_WORKSPACE = "workspace_file"

TIER_ABSTRACT_ONLY = "abstract_only"
TIER_LINK_ONLY = "link_only"
TIER_FULL_TEXT = "full_text_available"
TIER_WORKSPACE_OPAQUE = "workspace_opaque"

TEXT_VIEW_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".tex",
        ".log",
        ".rst",
        ".yaml",
        ".yml",
        ".py",
        ".pyw",
        ".pyi",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".java",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".sql",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".less",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".vue",
        ".swift",
        ".kt",
        ".gradle",
        ".ini",
        ".cfg",
        ".toml",
        ".properties",
        ".sh",
        ".ps1",
        ".bat",
        ".cmd",
        ".r",
        ".m",
        ".pl",
        ".lua",
    }
)

IMAGE_VIEW_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


def _norm_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return ""
    try:
        p = urlparse(s)
        if not p.scheme and s.startswith("//"):
            p = urlparse("https:" + s)
        if p.scheme not in {"http", "https"}:
            return s
        netloc = (p.hostname or "").lower()
        path = (p.path or "").rstrip("/") or "/"
        q = p.query
        return urlunparse((p.scheme.lower(), netloc, path, "", q, ""))
    except Exception:
        return s


def dedupe_key_external(url: str) -> str:
    n = _norm_url(url)
    if n:
        return f"url:{n}"
    return ""


def dedupe_key_workspace(rel_path: str) -> str:
    clean = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    if not clean:
        return ""
    return f"ws:{clean}"


def _tier_for_external_citation(c: dict[str, Any]) -> str:
    snip = str(c.get("snippet") or "").strip()
    raw = str(c.get("raw_content") or "").strip()
    if snip or raw:
        return TIER_ABSTRACT_ONLY
    return TIER_LINK_ONLY


def _abstract_from_citation(c: dict[str, Any]) -> str:
    snip = str(c.get("snippet") or "").strip()
    raw = str(c.get("raw_content") or "").strip()
    if len(raw) > len(snip):
        return raw[:8000]
    return snip[:8000]


def filter_citations_for_shelf(citations: list[Any]) -> list[dict[str, Any]]:
    """过滤占位/无信息条目（如 local_rag 占位）。"""
    out: list[dict[str, Any]] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        src = str(c.get("source", "")).lower().strip()
        if src == "local_rag":
            continue
        if str(c.get("url", "")).strip():
            out.append(c)
            continue
        if str(c.get("snippet", "")).strip() or str(c.get("raw_content", "")).strip():
            out.append(c)
    return out


def _fields_from_citation(c: dict[str, Any], *, search_query: str = "", added_via: str = "user_manual") -> dict[str, Any] | None:
    url = str(c.get("url") or "").strip()
    title = str(c.get("title") or "").strip() or "(无标题)"
    dk = dedupe_key_external(url)
    if not dk:
        h = hashlib.sha256(
            f"{title}|{c.get('source', '')}|{str(c.get('snippet', ''))[:400]}|{str(c.get('raw_content', ''))[:400]}".encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()[:48]
        dk = f"nourl:{h}"
    authors = ""
    abstract = _abstract_from_citation(c)
    tier = _tier_for_external_citation(c)
    extra = {k: str(v)[:2000] for k, v in c.items() if isinstance(v, (str, int, float))}
    return {
        "source_kind": SOURCE_EXTERNAL,
        "display_title": title[:512],
        "authors": authors,
        "abstract": abstract,
        "primary_url": url[:2048],
        "workspace_rel_path": "",
        "file_extension": "",
        "context_tier": tier,
        "dedupe_key": dk[:512],
        "added_via": added_via[:32],
        "search_query": (search_query or "").strip()[:512],
        "source_detail": extra,
    }


def append_search_citations_to_shelf(
    owner_id: str,
    citations: list[Any],
    *,
    search_query: str = "",
    max_per_call: int = 32,
    added_via: str = "search",
) -> int:
    """
    将检索 citations 写入用户展示区（按 dedupe_key 跳过已存在项）。

    返回本次新插入条数。
    """
    if not citations or not (owner_id or "").strip():
        return 0
    owner = str(owner_id).strip()
    created = 0
    q = (search_query or "").strip()[:512]
    for c in citations[:max_per_call]:
        if not isinstance(c, dict):
            continue
        fields = _fields_from_citation(c, search_query=q, added_via=added_via)
        if fields is None:
            continue
        dk = fields["dedupe_key"]
        with transaction.atomic():
            if ResearchPaperShelfItem.objects.filter(owner_id=owner, dedupe_key=dk).exists():
                continue
            try:
                ResearchPaperShelfItem.objects.create(owner_id=owner, **fields)
                created += 1
            except IntegrityError:
                continue
    return created


def _try_pdf_meta(path: Path) -> tuple[str, str]:
    title, authors = "", ""
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        return "", ""
    try:
        with fitz.open(str(path)) as doc:
            meta = doc.metadata or {}
            title = (meta.get("title") or "").strip()
            authors = (meta.get("author") or "").strip()
    except Exception:
        return "", ""
    return title, authors


def _first_text_preview(path: Path, max_bytes: int = 12000) -> str:
    try:
        raw = path.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def build_workspace_shelf_fields(user_id: str, rel_path: str) -> dict[str, Any] | None:
    """
    校验工作区路径并生成待写入 ``ResearchPaperShelfItem`` 的字段 dict；非法返回 None。
    """
    clean = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    if not clean:
        return None
    target = safe_resolve(str(user_id), clean)
    if target is None or not target.exists() or target.is_dir():
        return None
    root = get_workspace_root(str(user_id))
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return None
    suffix = target.suffix.lower()
    display_title = target.stem
    authors = ""
    abstract = ""
    if suffix == ".pdf":
        t, a = _try_pdf_meta(target)
        if t:
            display_title = t[:512]
        authors = a[:2000]
        tier = TIER_FULL_TEXT
    elif suffix in TEXT_VIEW_SUFFIXES:
        tier = TIER_FULL_TEXT
        abstract = _first_text_preview(target)[:8000]
    elif suffix in IMAGE_VIEW_SUFFIXES:
        tier = TIER_WORKSPACE_OPAQUE
        abstract = ""
    else:
        tier = TIER_WORKSPACE_OPAQUE
    return {
        "display_title": display_title[:512] or target.name[:512],
        "authors": authors,
        "abstract": abstract,
        "workspace_rel_path": rel,
        "file_extension": suffix[:32],
        "context_tier": tier,
        "dedupe_key": dedupe_key_workspace(rel),
    }


def workspace_open_hints(rel_path: str) -> dict[str, Any]:
    """供前端决定打开方式（不写库，仅 API 组装）。"""
    suffix = Path(rel_path).suffix.lower()
    enc = quote(rel_path, safe="/")
    base = f"/api/workspace/files/{enc}"
    if suffix == ".pdf":
        return {"open_mode": "pdf_viewer", "workspace_file_url": base, "hint": "可用内嵌 PDF 查看器加载该 URL"}
    if suffix in IMAGE_VIEW_SUFFIXES:
        return {"open_mode": "image_preview", "workspace_file_url": base, "hint": "可在前端以图片方式预览"}
    if suffix in TEXT_VIEW_SUFFIXES:
        return {"open_mode": "text_preview", "workspace_file_url": base, "hint": "可拉取文本后在前端渲染"}
    return {
        "open_mode": "download_only",
        "workspace_file_url": base,
        "hint": "非 PDF/纯文本/图片，建议下载或用外部应用打开",
    }


def shelf_item_to_api_dict(item: ResearchPaperShelfItem) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(item.id),
        "source_kind": item.source_kind,
        "title": item.display_title,
        "authors": item.authors,
        "abstract": item.abstract,
        "primary_url": item.primary_url,
        "context_tier": item.context_tier,
        "added_via": item.added_via,
        "search_query": item.search_query,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }
    if item.source_kind == SOURCE_WORKSPACE and item.workspace_rel_path:
        out["workspace_rel_path"] = item.workspace_rel_path
        out["file_extension"] = item.file_extension
        out.update(workspace_open_hints(item.workspace_rel_path))
    elif item.source_kind == SOURCE_EXTERNAL:
        out["external_jump_url"] = item.primary_url
        src = (item.source_detail or {}).get("source", "")
        if src:
            out["citation_source"] = src
    return out


def add_workspace_item(owner_id: str, user_id: str, rel_path: str) -> ResearchPaperShelfItem | None:
    fields = build_workspace_shelf_fields(user_id, rel_path)
    if fields is None:
        return None
    owner = str(owner_id).strip()
    dk = fields["dedupe_key"]
    with transaction.atomic():
        if ResearchPaperShelfItem.objects.filter(owner_id=owner, dedupe_key=dk).exists():
            return ResearchPaperShelfItem.objects.filter(owner_id=owner, dedupe_key=dk).first()
        try:
            return ResearchPaperShelfItem.objects.create(
                owner_id=owner,
                source_kind=SOURCE_WORKSPACE,
                display_title=fields["display_title"],
                authors=fields.get("authors") or "",
                abstract=fields.get("abstract") or "",
                primary_url="",
                workspace_rel_path=fields["workspace_rel_path"],
                file_extension=fields.get("file_extension") or "",
                context_tier=fields["context_tier"],
                dedupe_key=dk[:512],
                added_via="user_manual",
                search_query="",
                source_detail={},
            )
        except IntegrityError:
            return ResearchPaperShelfItem.objects.filter(owner_id=owner, dedupe_key=dk).first()
