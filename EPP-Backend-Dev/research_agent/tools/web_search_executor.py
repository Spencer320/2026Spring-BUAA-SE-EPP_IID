from __future__ import annotations

import re

import httpx
from django.conf import settings

from ..llm_client import chat_completion, normalize_supplier_json_response
from ..site_access_control import evaluate_target_domain
from .base import WebSearchResult, extract_url_domain, make_audit, truncate_text
from .web_fetch_executor import allowed_get


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
    return extract_url_domain(url)


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


def _filter_citations_by_site_policy(
    citations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    allowed: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    for item in citations:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", "")).strip().lower() or _extract_domain(str(item.get("url", "")).strip())
        if not domain:
            allowed.append(item)
            continue
        decision = evaluate_target_domain(domain)
        if decision.allowed:
            tagged = dict(item)
            tagged["site_rule_hit"] = decision.rule_hit
            tagged["site_policy_version"] = decision.policy_version
            allowed.append(tagged)
            continue
        blocked.append(
            {
                "domain": decision.target_domain,
                "rule_hit": decision.rule_hit,
                "policy_version": decision.policy_version,
                "reason_code": decision.reason_code,
                "reason_message": decision.reason_message,
            }
        )
    return allowed, blocked


def _tavily_search(query: str) -> WebSearchResult:
    api_key = str(getattr(settings, "RA_TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_CONFIG_MISSING",
            error_message="Missing Tavily API Key",
            audit=make_audit("web_search", "error", "Tavily config missing"),
        )

    timeout = float(getattr(settings, "RA_WEB_SEARCH_TIMEOUT", 12.0))
    max_results = int(getattr(settings, "RA_WEB_SEARCH_MAX_RESULTS", 10))
    min_score = float(getattr(settings, "RA_WEB_SEARCH_MIN_SCORE", 0.65))
    keep_top_n = int(getattr(settings, "RA_WEB_SEARCH_KEEP_TOP_N", 6))
    fallback_keep_n = int(getattr(settings, "RA_WEB_SEARCH_FALLBACK_KEEP_N", 3))
    priority_boost = float(getattr(settings, "RA_WEB_SEARCH_WHITELIST_PRIORITY_BOOST", 0.2))
    whitelist = _academic_domain_whitelist()
    search_url = "https://api.tavily.com/search"
    queries = _bilingual_queries(query)
    if not queries:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_EMPTY_QUERY",
            error_message="Query is empty",
            audit=make_audit("web_search", "error", "Query is empty", provider="tavily"),
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
                    resp = client.post(search_url, json=body)
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
                                "Tavily http error",
                                provider="tavily",
                                response_status=resp.status_code,
                            ),
                        )
                    payload = resp.json() if resp.content else {}
                    one_results = payload.get("results", []) if isinstance(payload, dict) else []
                    if isinstance(one_results, list):
                        for item in one_results:
                            if not isinstance(item, dict):
                                continue
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
            error_message="Tavily timeout",
            audit=make_audit("web_search", "error", "Tavily timeout", provider="tavily"),
        )
    except httpx.RequestError as exc:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_UPSTREAM_ERROR",
            error_message=str(exc) or "Tavily request failed",
            audit=make_audit("web_search", "error", "Tavily request failed", provider="tavily"),
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
    allowed_citations, blocked_domains = _filter_citations_by_site_policy(citations)

    if not allowed_citations:
        if blocked_domains:
            first = blocked_domains[0]
            return WebSearchResult(
                ok=False,
                summary="",
                citations=[],
                error_code="OUTBOUND_SITE_DENIED",
                error_message=str(first.get("reason_message") or "All result domains denied by site policy"),
                audit=make_audit(
                    "web_search",
                    "rejected",
                    "All candidate domains denied by site access policy",
                    provider="tavily",
                    blocked_domains=blocked_domains,
                    rule_hit=str(first.get("rule_hit") or ""),
                    policy_version=str(first.get("policy_version") or ""),
                ),
            )
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_SEARCH_EMPTY",
            error_message="No search results",
            audit=make_audit("web_search", "error", "No search results", provider="tavily"),
        )

    return WebSearchResult(
        ok=True,
        summary=f"Tavily search succeeded: raw={len(results)}, kept={len(allowed_citations)}",
        citations=allowed_citations,
        audit=make_audit(
            "web_search",
            "ok",
            "Tavily bilingual search succeeded",
            provider="tavily",
            query_variants=queries,
            whitelist_domains=whitelist,
            raw_result_count=len(results),
            result_count=len(allowed_citations),
            blocked_result_count=len(blocked_domains),
            min_score=min_score,
            priority_boost=priority_boost,
        ),
    )


_URL_IN_QUERY = re.compile(r"https?://[^\s<>\"']+", re.I)

# (触发词或站点名片段, 起始 URL) — 用于无显式 URL 时启动 web_operator
_KNOWN_SITE_ENTRIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("知网", "cnki", "中国知网"), "https://www.cnki.net/"),
    (("ieee xplore", "ieeexplore.ieee.org", "ieee explore"), "https://ieeexplore.ieee.org/"),
    (("semantic scholar", "semanticscholar.org", "语义学者"), "https://www.semanticscholar.org/"),
)


def _known_site_start_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    ql = q.lower()
    for keys, url in _KNOWN_SITE_ENTRIES:
        for key in keys:
            if key in q or key in ql:
                return url
    return ""


def _user_hints_web_operator(query: str) -> bool:
    """用户明确需要「打开网站 / 页面操作」或提到已知需浏览器站点时，优先 web_operator。"""
    q = (query or "").strip()
    if not q:
        return False
    if _extract_url_from_query(q):
        return True
    if _known_site_start_url(q):
        return True
    ql = q.lower()
    hints = (
        "网页操作",
        "无头浏览器",
        "浏览器打开",
        "打开网站",
        "进入网站",
        "访问网站",
        "高级搜索",
        "登录后",
        "点进",
        "点击进入",
    )
    if any(h in q for h in hints):
        return True
    if any(h in ql for h in (" open ", " visit ", " browse ", " navigate ")):
        return True
    return False


def _tavily_configured() -> bool:
    return bool(str(getattr(settings, "RA_TAVILY_API_KEY", "") or "").strip())


def _allowed_search_routes() -> list[str]:
    routes = ["arxiv", "crossref"]
    if str(getattr(settings, "RA_SEMANTIC_SCHOLAR_API_KEY", "") or "").strip():
        routes.append("semantic_scholar")
    if str(getattr(settings, "RA_IEEE_XPLORE_API_KEY", "") or "").strip():
        routes.append("ieee_xplore")
    if _tavily_configured():
        routes.append("tavily")
    if getattr(settings, "RA_WEB_OPERATOR_ENABLED", True):
        from .web_operator_executor import playwright_available

        if playwright_available():
            routes.append("web_operator")
    return routes


def _fallback_route(allowed: list[str]) -> str:
    for cand in ("crossref", "arxiv", "tavily"):
        if cand in allowed:
            return cand
    return allowed[0]


def _llm_pick_search_route(query: str, allowed: list[str]) -> tuple[str, str]:
    if len(allowed) == 1:
        return allowed[0], ""
    system = (
        "Choose the best search backend for the user query. Reply with JSON only, no markdown:\n"
        '{"route":"<name>","start_url":""}\n'
        f"Allowed route values: {', '.join(allowed)}.\n"
        "Use web_operator when the user asks to open/browse a specific website, needs login/interaction, "
        "or mentions CNKI/知网/IEEE Xplore/Semantic Scholar entry pages; "
        "then start_url must be a full http(s) URL if you know it, else empty (caller may infer). "
        "For plain literature search without a specific site, prefer arxiv, crossref, semantic_scholar, or tavily."
    )
    user = f"Query:\n{(query or '').strip()[:2400]}"
    res = chat_completion(
        system_prompt=system,
        user_prompt=user,
        temperature=0.05,
        max_tokens=200,
        enable_thinking=False,
        stream=False,
    )
    if not res.ok:
        return _fallback_route(allowed), ""
    payload, _ = normalize_supplier_json_response(res.content)
    if not isinstance(payload, dict) or payload.get("_fallback_wrapped"):
        return _fallback_route(allowed), ""
    route = str(payload.get("route") or "").strip().lower().replace("-", "_")
    alias = {
        "semantic": "semantic_scholar",
        "scholar": "semantic_scholar",
        "ss": "semantic_scholar",
        "ieee": "ieee_xplore",
    }
    route = alias.get(route, route)
    start_url = str(payload.get("start_url") or "").strip()
    if route not in allowed:
        return _fallback_route(allowed), ""
    return route, start_url


def _extract_url_from_query(query: str) -> str:
    m = _URL_IN_QUERY.search(query or "")
    return m.group(0).strip() if m else ""


def _resolve_web_operator_start_url(query: str, start_url_llm: str) -> str:
    su = (start_url_llm or "").strip()
    if su.startswith("http"):
        return su
    su = _extract_url_from_query(query)
    if su.startswith("http"):
        return su
    return _known_site_start_url(query)


def _route_candidates(primary: str, allowed: list[str]) -> list[str]:
    order = [
        primary,
        "crossref",
        "arxiv",
        "semantic_scholar",
        "ieee_xplore",
        "tavily",
        "web_operator",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for r in order:
        if r in allowed and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _run_search_route(route: str, query: str, *, limit: int) -> WebSearchResult:
    if route == "tavily":
        return _tavily_search(query)
    from .academic_search_executor import (
        search_arxiv_api,
        search_crossref,
        search_ieee_xplore,
        search_semantic_scholar,
    )

    if route == "semantic_scholar":
        return search_semantic_scholar(query, limit=limit)
    if route == "arxiv":
        return search_arxiv_api(query, limit=limit)
    if route == "crossref":
        return search_crossref(query, limit=limit)
    if route == "ieee_xplore":
        return search_ieee_xplore(query, limit=limit)
    return WebSearchResult(
        ok=False,
        summary="",
        citations=[],
        error_code="WEB_SEARCH_BAD_ROUTE",
        error_message=f"unknown route: {route}",
        audit=make_audit("web_search", "error", f"bad route {route}"),
    )


def _try_search_routes(
    query: str,
    allowed: list[str],
    *,
    primary: str,
    limit: int,
    web_operator_start_url: str,
) -> WebSearchResult:
    from .web_operator_executor import run_web_operator

    candidates = _route_candidates(primary, allowed)
    tried: list[str] = []
    last_res: WebSearchResult | None = None

    for route in candidates:
        tried.append(route)
        if route == "web_operator":
            su = (web_operator_start_url or "").strip()
            if not su.startswith("http"):
                last_res = WebSearchResult(
                    ok=False,
                    summary="",
                    citations=[],
                    error_code="WEB_OPERATOR_BAD_URL",
                    error_message="web_operator skipped: no start_url",
                    audit=make_audit(
                        "web_search",
                        "error",
                        "web_operator skipped",
                        provider="web_operator",
                    ),
                )
                continue
            res = run_web_operator(query, start_url=su)
        else:
            res = _run_search_route(route, query, limit=limit)

        last_res = res
        if res.ok and res.citations:
            base_meta = dict(res.audit.metadata) if res.audit.metadata else {}
            base_meta["route_used"] = route
            base_meta["routes_tried"] = ",".join(tried)
            return WebSearchResult(
                ok=True,
                summary=res.summary,
                citations=res.citations,
                audit=make_audit(
                    res.audit.tool,
                    res.audit.status,
                    res.audit.detail,
                    **base_meta,
                ),
            )

    detail = "all routes exhausted: " + ",".join(tried)
    if last_res and last_res.error_message:
        detail += f" last={last_res.error_code}:{last_res.error_message[:200]}"
    return WebSearchResult(
        ok=False,
        summary="",
        citations=[],
        error_code="WEB_SEARCH_EMPTY",
        error_message=detail[:900],
        audit=make_audit(
            "web_search",
            "error",
            detail[:500],
            routes_tried=",".join(tried),
            last_error_code=getattr(last_res, "error_code", "") if last_res else "",
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
                    "rejected" if res.error_code == "OUTBOUND_SITE_DENIED" else "error",
                    f"Outbound fetch failed: {res.error_code}",
                    query=clean_query,
                    url=clean_url,
                    target_domain=res.target_domain,
                    rule_hit=res.rule_hit,
                    policy_version=res.policy_version,
                    error_code=res.error_code,
                ),
            )
        return WebSearchResult(
            ok=True,
            summary=f"Outbound fetch succeeded: {clean_url}",
            citations=[
                {
                    "query": clean_query,
                    "title": "Outbound fetch result summary",
                    "source": "web",
                    "url": clean_url,
                    "published_at": "",
                    "snippet": res.summary[:300],
                    "raw_content": truncate_text(res.summary, 2200),
                    "confidence": "0.7",
                    "domain": res.target_domain,
                    "site_rule_hit": res.rule_hit,
                    "site_policy_version": res.policy_version,
                }
            ],
            audit=make_audit(
                "web_search",
                "ok",
                "Outbound fetch succeeded",
                query=clean_query,
                url=clean_url,
                target_domain=res.target_domain,
                rule_hit=res.rule_hit,
                policy_version=res.policy_version,
                snippet=res.summary[:500],
            ),
        )

    provider = _provider_name()
    if provider == "tavily":
        allowed = _allowed_search_routes()
        limit = int(getattr(settings, "RA_ACADEMIC_SEARCH_LIMIT", 8))
        route, start_url_llm = _llm_pick_search_route(clean_query, allowed)
        if _user_hints_web_operator(clean_query) and "web_operator" in allowed:
            route = "web_operator"
            if not (start_url_llm or "").strip().startswith("http"):
                start_url_llm = _extract_url_from_query(clean_query) or _known_site_start_url(
                    clean_query
                )
        if route not in allowed:
            route = _fallback_route(allowed)
        start_for_op = _resolve_web_operator_start_url(clean_query, start_url_llm)
        return _try_search_routes(
            clean_query,
            allowed,
            primary=route,
            limit=limit,
            web_operator_start_url=start_for_op,
        )

    detail = f"Use local RAG search: {clean_query[:120] or 'empty query'}"
    return WebSearchResult(
        ok=True,
        summary=detail,
        citations=[
            {
                "query": clean_query,
                "title": f"{(clean_query or 'research topic')[:40]} overview",
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
