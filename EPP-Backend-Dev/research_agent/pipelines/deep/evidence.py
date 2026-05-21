"""深度研究综述链路：用户选定文献种子证据与外搜结果合并。"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

_SEED_SOURCE = "user_selected"
_MAX_QUERIES_PER_SUBTASK = 4


def _strip_query(q: str) -> str:
    return (q or "").strip()


def _dedupe_key_for_citation(c: dict[str, Any]) -> str:
    url = _strip_query(str(c.get("url") or ""))
    if url:
        return url.lower()
    title = _strip_query(str(c.get("title") or ""))
    snippet = _strip_query(str(c.get("snippet") or ""))[:200]
    raw = f"{title}|{snippet}|{c.get('source', '')}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:48]


def is_effective_external_citation(c: dict[str, Any]) -> bool:
    """可核验的外搜命中：有 URL 且非 local_rag 占位。"""
    if not isinstance(c, dict):
        return False
    src = _strip_query(str(c.get("source", ""))).lower()
    if src in {"local_rag", "user_selected"}:
        return False
    if _strip_query(str(c.get("url") or "")):
        return True
    if _strip_query(str(c.get("snippet") or "")) or _strip_query(str(c.get("raw_content") or "")):
        return True
    return False


def count_effective_hits(citations: list[Any]) -> int:
    n = 0
    for c in citations:
        if is_effective_external_citation(c):
            n += 1
    return n


def build_seed_citations(selected_papers: list[Any]) -> list[dict[str, str]]:
    """将展示区选定文献转为 analyze / 引用包装可用的 citation 列表。"""
    out: list[dict[str, str]] = []
    if not isinstance(selected_papers, list):
        return out
    for idx, paper in enumerate(selected_papers):
        if not isinstance(paper, dict):
            continue
        title = _strip_query(str(paper.get("title") or "")) or "(无标题)"
        url = _strip_query(str(paper.get("primary_url") or ""))
        abstract = _strip_query(str(paper.get("abstract") or ""))
        authors = _strip_query(str(paper.get("authors") or ""))
        shelf_id = _strip_query(str(paper.get("shelf_item_id") or ""))
        snippet_parts: list[str] = []
        if authors:
            snippet_parts.append(f"作者：{authors[:240]}")
        if abstract:
            snippet_parts.append(abstract[:1200])
        elif _strip_query(str(paper.get("search_query") or "")):
            snippet_parts.append(f"入库检索词：{str(paper.get('search_query'))[:200]}")
        snippet = "\n".join(snippet_parts) or f"用户选定文献：{title[:120]}"
        domain = ""
        if url:
            try:
                domain = urlparse(url).netloc or ""
            except ValueError:
                domain = ""
        entry: dict[str, str] = {
            "query": _strip_query(str(paper.get("search_query") or "")) or title[:120],
            "title": title[:512],
            "source": _SEED_SOURCE,
            "url": url[:2048],
            "published_at": "",
            "snippet": snippet[:2000],
            "confidence": "1.0",
            "shelf_item_id": shelf_id,
        }
        if domain:
            entry["domain"] = domain[:256]
        if not url:
            entry["dedupe_key"] = f"seed:{shelf_id or idx}:{hashlib.sha256(snippet.encode('utf-8', errors='ignore')).hexdigest()[:16]}"
        out.append(entry)
    return out


def merge_citations(seed: list[Any], external: list[Any]) -> list[dict[str, str]]:
    """合并种子与外搜结果，seed 优先；按 dedupe_key / url 去重。"""
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for batch in (seed, external):
        if not isinstance(batch, list):
            continue
        for item in batch:
            if not isinstance(item, dict):
                continue
            row = {str(k): str(v) if v is not None else "" for k, v in item.items()}
            key = _strip_query(str(row.get("url") or "")).lower() or str(
                row.get("dedupe_key") or _dedupe_key_for_citation(row)
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def _title_keywords(title: str, *, max_len: int = 80) -> str:
    t = _strip_query(title)
    if not t:
        return ""
    t = re.sub(r"[「」【】\(\)（）\[\]]+", " ", t)
    return t[:max_len].strip()


def fallback_search_queries_for_subtask(
    subtask: dict[str, Any],
    *,
    user_query: str,
    selected_papers: list[Any],
) -> list[dict[str, str]]:
    """plan_decide 无 search_queries 时的规则化检索词（硬兜底）。"""
    queries: list[dict[str, str]] = []
    q_user = _strip_query(user_query)[:200]
    papers = [p for p in (selected_papers or []) if isinstance(p, dict)]

    for paper in papers[:3]:
        title = _strip_query(str(paper.get("title") or ""))
        if not title:
            continue
        kw = _title_keywords(title)
        if kw:
            queries.append(
                {
                    "q": kw[:120],
                    "intent": "extend",
                    "rationale": f"锚定选定文献《{title[:60]}》",
                }
            )
        sq = _strip_query(str(paper.get("search_query") or ""))
        if sq and sq not in {x["q"] for x in queries}:
            queries.append(
                {
                    "q": sq[:120],
                    "intent": "background",
                    "rationale": "沿用该文献入库时的检索词",
                }
            )

    if q_user:
        queries.append(
            {
                "q": q_user[:120],
                "intent": "background",
                "rationale": "用户研究问题",
            }
        )

    goal = _strip_query(str(subtask.get("goal") or ""))
    if goal and len(queries) < 2:
        queries.append(
            {
                "q": goal[:120],
                "intent": "compare",
                "rationale": "子任务研究意图提炼",
            }
        )

    if not queries:
        queries.append(
            {
                "q": "research survey",
                "intent": "background",
                "rationale": "无可用检索词时的最小占位",
            }
        )

    seen_q: set[str] = set()
    out: list[dict[str, str]] = []
    for item in queries:
        q = _strip_query(str(item.get("q") or ""))
        if not q or q in seen_q:
            continue
        seen_q.add(q)
        out.append(
            {
                "q": q,
                "intent": _strip_query(str(item.get("intent") or "background")) or "background",
                "rationale": _strip_query(str(item.get("rationale") or ""))[:240],
            }
        )
        if len(out) >= _MAX_QUERIES_PER_SUBTASK:
            break
    return out


def normalize_search_queries_from_subtask(
    subtask: dict[str, Any],
    *,
    user_query: str,
    selected_papers: list[Any],
) -> list[dict[str, str]]:
    """从 subtask.search_queries 解析或回退生成检索计划。"""
    raw = subtask.get("search_queries")
    parsed: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = _strip_query(str(item.get("q") or ""))
            if not q:
                continue
            parsed.append(
                {
                    "q": q[:240],
                    "intent": _strip_query(str(item.get("intent") or "background")) or "background",
                    "rationale": _strip_query(str(item.get("rationale") or ""))[:240],
                }
            )
    if parsed:
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for item in parsed:
            if item["q"] in seen:
                continue
            seen.add(item["q"])
            out.append(item)
            if len(out) >= _MAX_QUERIES_PER_SUBTASK:
                break
        return out
    return fallback_search_queries_for_subtask(
        subtask, user_query=user_query, selected_papers=selected_papers
    )
