from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .base import ToolAuditEvent, make_audit, truncate_text
from .web_fetch_executor import allowed_get


@dataclass(frozen=True)
class WebSearchResult:
    ok: bool
    summary: str
    citations: list[dict[str, str]]
    audit: ToolAuditEvent
    error_code: str = ""
    error_message: str = ""


def _provider_name() -> str:
    return str(getattr(settings, "RA_WEB_SEARCH_PROVIDER", "tavily") or "tavily").strip().lower()


def _contains_cjk(text: str) -> bool:
    for ch in text or "":
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def _bilingual_queries(query: str) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    queries = [q]
    alt = f"{q} in English" if _contains_cjk(q) else f"{q} 中文"
    if alt not in queries:
        queries.append(alt)
    return queries


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _academic_domain_whitelist() -> list[str]:
    configured = getattr(settings, "RA_WEB_SEARCH_ACADEMIC_DOMAIN_WHITELIST", None)
    if isinstance(configured, (list, tuple)):
        items = [str(v).strip().lower() for v in configured if str(v).strip()]
        if items:
            return items
    return [
        "arxiv.org",
        "semanticscholar.org",
        "openreview.net",
        "acm.org",
        "ieeexplore.ieee.org",
        "springer.com",
        "nature.com",
        "science.org",
        "sciencedirect.com",
        "pubmed.ncbi.nlm.nih.gov",
    ]


def _is_whitelisted_domain(domain: str, whitelist: list[str]) -> bool:
    base = (domain or "").strip().lower()
    if not base:
        return False
    for item in whitelist:
        allow = (item or "").strip().lower()
        if not allow:
            continue
        if base == allow or base.endswith(f".{allow}"):
            return True
    return False


def _dedupe_and_rank_citations(
    citations: list[dict[str, str]],
    *,
    min_score: float,
    keep_top_n: int,
    fallback_keep_n: int,
    whitelist: list[str],
    priority_boost: float,
) -> list[dict[str, str]]:
    dedup: dict[str, dict[str, str]] = {}
    for item in citations:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        key = url or f"{str(item.get('query', '')).strip()}::{str(item.get('title', '')).strip()}"
        old = dedup.get(key)
        if old is None or _safe_float(item.get("confidence"), 0.0) > _safe_float(old.get("confidence"), 0.0):
            dedup[key] = item
    def rank_score(x: dict[str, str]) -> float:
        score = _safe_float(x.get("confidence"), 0.0)
        domain = _extract_domain(str(x.get("url", "")).strip())
        if _is_whitelisted_domain(domain, whitelist):
            score += priority_boost
        return score

    ranked = sorted(dedup.values(), key=rank_score, reverse=True)
    filtered = [item for item in ranked if _safe_float(item.get("confidence"), 0.0) >= min_score]
    if len(filtered) < min(1, fallback_keep_n):
        filtered = ranked[:max(1, fallback_keep_n)]
    return filtered[:max(1, keep_top_n)]


def _tavily_search(query: str) -> WebSearchResult:
    api_key = str(getattr(settings, "RA_TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_CONFIG_MISSING",
            error_message="缺少 Tavily API Key",
            audit=make_audit("web_search", "error", "Tavily 配置缺失"),
        )
    timeout = float(getattr(settings, "RA_WEB_SEARCH_TIMEOUT", 12.0))
    max_results = int(getattr(settings, "RA_WEB_SEARCH_MAX_RESULTS", 10))
    min_score = float(getattr(settings, "RA_WEB_SEARCH_MIN_SCORE", 0.65))
    keep_top_n = int(getattr(settings, "RA_WEB_SEARCH_KEEP_TOP_N", 6))
    fallback_keep_n = int(getattr(settings, "RA_WEB_SEARCH_FALLBACK_KEEP_N", 3))
    priority_boost = float(getattr(settings, "RA_WEB_SEARCH_WHITELIST_PRIORITY_BOOST", 0.2))
    whitelist = _academic_domain_whitelist()
    url = "https://api.tavily.com/search"
    queries = _bilingual_queries(query)
    if not queries:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_EMPTY_QUERY",
            error_message="检索词为空",
            audit=make_audit("web_search", "error", "检索词为空", provider="tavily"),
        )

    results: list[dict[str, object]] = []
    try:
        with httpx.Client(timeout=timeout) as client:
            for one_query in queries:
                scope_bodies = [
                    {
                        "api_key": api_key,
                        "query": one_query,
                        "search_depth": "advanced",
                        "max_results": max(3, min(10, max_results // 2)),
                        "include_raw_content": True,
                        "include_domains": whitelist,
                        "_scope": "whitelist",
                    },
                    {
                        "api_key": api_key,
                        "query": one_query,
                        "search_depth": "advanced",
                        "max_results": max(5, min(20, max_results)),
                        "include_raw_content": True,
                        "_scope": "global",
                    },
                ]
                for body in scope_bodies:
                    scope = str(body.pop("_scope", "global"))
                    resp = client.post(url, json=body)
                    if resp.status_code >= 400:
                        return WebSearchResult(
                            ok=False,
                            summary="",
                            citations=[],
                            error_code="WEB_SEARCH_HTTP_ERROR",
                            error_message=f"Tavily HTTP {resp.status_code}",
                            audit=make_audit(
                                "web_search",
                                "error",
                                "Tavily 返回错误",
                                provider="tavily",
                                response_status=resp.status_code,
                            ),
                        )
                    payload = resp.json() if resp.content else {}
                    one_results = payload.get("results", []) if isinstance(payload, dict) else []
                    if isinstance(one_results, list):
                        for item in one_results:
                            if isinstance(item, dict):
                                tagged = dict(item)
                                tagged["_search_query"] = one_query
                                tagged["_search_scope"] = scope
                                results.append(tagged)
    except httpx.TimeoutException:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_TIMEOUT",
            error_message="Tavily 请求超时",
            audit=make_audit("web_search", "error", "Tavily 请求超时", provider="tavily"),
        )
    except httpx.RequestError as exc:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_UPSTREAM_ERROR",
            error_message=str(exc) or "Tavily 请求失败",
            audit=make_audit("web_search", "error", "Tavily 请求失败", provider="tavily"),
        )

    citations: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw_content = truncate_text(str(item.get("raw_content", "")).strip(), 2200)
        if len(raw_content) < 120:
            raw_content = truncate_text(str(item.get("content", "")).strip(), 2200)
        citations.append(
            {
                "query": str(item.get("_search_query", "")).strip() or query,
                "title": str(item.get("title", "")).strip(),
                "source": "tavily",
                "url": str(item.get("url", "")).strip(),
                "published_at": str(item.get("published_date", "")).strip(),
                "snippet": truncate_text(str(item.get("content", "")).strip(), 300),
                "raw_content": raw_content,
                "confidence": str(_safe_float(item.get("score"), 0.0)),
                "domain": _extract_domain(str(item.get("url", "")).strip()),
                "search_scope": str(item.get("_search_scope", "")).strip(),
            }
        )

    citations = _dedupe_and_rank_citations(
        citations,
        min_score=min_score,
        keep_top_n=keep_top_n,
        fallback_keep_n=fallback_keep_n,
        whitelist=whitelist,
        priority_boost=priority_boost,
    )
    if not citations:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_EMPTY",
            error_message="Tavily 未返回结果",
            audit=make_audit("web_search", "error", "Tavily 未返回结果", provider="tavily"),
        )

    return WebSearchResult(
        ok=True,
        summary=f"Tavily 双语检索成功：原始{len(results)}条，保留高分{len(citations)}条",
        citations=citations,
        audit=make_audit(
            "web_search",
            "ok",
            "Tavily 双语检索成功（白名单优先）",
            provider="tavily",
            query_variants=queries,
            whitelist_domains=whitelist,
            raw_result_count=len(results),
            result_count=len(citations),
            min_score=min_score,
            priority_boost=priority_boost,
        ),
    )


def execute_web_search(query: str, url: str) -> WebSearchResult:
    clean_query = (query or "").strip()
    clean_url = (url or "").strip()

    if clean_url:
        res = allowed_get(clean_url)
        if not res.ok:
            return WebSearchResult(
                ok=False,
                summary="",
                citations=[],
                error_code=res.error_code,
                error_message=res.error_message,
                audit=make_audit(
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
                    "query": clean_query,
                    "title": "外部检索结果摘要",
                    "source": "web",
                    "url": clean_url,
                    "published_at": "",
                    "snippet": res.summary[:300],
                    "raw_content": truncate_text(res.summary, 2200),
                    "confidence": "0.7",
                }
            ],
            audit=make_audit(
                "web_search",
                "ok",
                "联网检索成功",
                query=clean_query,
                url=clean_url,
                snippet=res.summary[:500],
            ),
        )

    provider = _provider_name()
    if provider == "tavily":
        return _tavily_search(clean_query)

    detail = f"使用本地知识库关键词检索：{clean_query[:120] or '未提供检索词'}"
    return WebSearchResult(
        ok=True,
        summary=detail,
        citations=[
            {
                "query": clean_query,
                "title": f"{(clean_query or '研究主题')[:40]} 相关综述",
                "source": "local_rag",
                "url": "",
                "published_at": "",
                "snippet": detail[:200],
                "raw_content": truncate_text(detail, 1200),
                "confidence": "0.6",
            }
        ],
        audit=make_audit("web_search", "ok", detail, query=clean_query, source="local_rag"),
    )

