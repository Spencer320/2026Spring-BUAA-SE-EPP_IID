"""学术文献 HTTP/API 检索，统一返回 WebSearchResult 形态。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import arxiv
import httpx
import requests
from django.conf import settings

from .base import WebSearchResult, extract_url_domain, make_audit, truncate_text

logger = logging.getLogger(__name__)

_LATIN_PHRASE = re.compile(
    r"[A-Za-z][A-Za-z0-9\-_.]*(?:\s+[A-Za-z0-9\-_.]+)*"
)


def _http_timeout() -> float:
    return float(getattr(settings, "RA_HTTP_TIMEOUT", 15.0))


def compact_academic_query(query: str, *, max_len: int = 320) -> str:
    """将过长中文任务描述压缩为适合学术 API 的检索词（保留英文/拉丁短语）。"""
    raw = (query or "").strip()
    if not raw:
        return ""
    if len(raw) <= 80 and raw.isascii():
        return raw
    phrases = _LATIN_PHRASE.findall(raw)
    if phrases:
        seen: set[str] = set()
        parts: list[str] = []
        for phrase in sorted(phrases, key=len, reverse=True):
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            parts.append(phrase.strip())
        compact = " ".join(parts)
        if compact:
            return compact[:max_len].strip()
    return raw[:max_len].strip()


def _arxiv_delay_seconds() -> float:
    return float(getattr(settings, "RA_ARXIV_DELAY_SECONDS", 3.0))


def _arxiv_num_retries() -> int:
    return max(0, int(getattr(settings, "RA_ARXIV_NUM_RETRIES", 1)))


def _arxiv_page_size() -> int:
    return max(1, int(getattr(settings, "RA_ARXIV_PAGE_SIZE", 100)))


def _get_arxiv_client() -> arxiv.Client:
    """构造带 HTTP 超时的 arXiv 客户端（export.arxiv.org 无 API Key，受速率与 IP 限制）。"""
    client = arxiv.Client(
        page_size=_arxiv_page_size(),
        delay_seconds=_arxiv_delay_seconds(),
        num_retries=_arxiv_num_retries(),
    )
    timeout = _http_timeout()
    session = client._session
    original_get = session.get

    def get_with_timeout(url: str, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return original_get(url, **kwargs)

    session.get = get_with_timeout  # type: ignore[method-assign]
    return client


def _arxiv_error_result(
    *,
    query: str,
    error_code: str,
    error_message: str,
    detail: str,
    response_status: int | None = None,
) -> WebSearchResult:
    meta: dict[str, Any] = {"provider": "arxiv", "query": query[:200]}
    if response_status is not None:
        meta["response_status"] = response_status
    return WebSearchResult(
        ok=False,
        summary="",
        citations=[],
        error_code=error_code,
        error_message=error_message,
        audit=make_audit("web_search", "error", detail, **meta),
    )


def _crossref_mailto() -> str:
    return str(getattr(settings, "RA_CROSSREF_POLITE_EMAIL", "") or "").strip()


def search_semantic_scholar(query: str, *, limit: int) -> WebSearchResult:
    q = (query or "").strip()
    if not q:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY_QUERY",
            error_message="Query is empty",
            audit=make_audit("web_search", "error", "empty query", provider="semantic_scholar"),
        )
    api_key = str(getattr(settings, "RA_SEMANTIC_SCHOLAR_API_KEY", "") or "").strip()
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={quote(q)}&limit={max(1, min(limit, 100))}"
        "&fields=title,authors,year,abstract,url,externalIds"
    )
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    with httpx.Client(timeout=_http_timeout()) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code >= 400:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_HTTP_ERROR",
            error_message=f"Semantic Scholar HTTP {resp.status_code}",
            audit=make_audit(
                "web_search",
                "error",
                "Semantic Scholar http error",
                provider="semantic_scholar",
                response_status=resp.status_code,
            ),
        )
    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_BAD_RESPONSE",
            error_message="Semantic Scholar: invalid payload",
            audit=make_audit("web_search", "error", "bad json", provider="semantic_scholar"),
        )
    citations: list[dict[str, str]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        abstract = str(item.get("abstract") or "").strip()
        year = item.get("year")
        year_s = str(year) if year is not None else ""
        authors_raw = item.get("authors")
        author_names: list[str] = []
        if isinstance(authors_raw, list):
            for a in authors_raw:
                if isinstance(a, dict) and a.get("name"):
                    author_names.append(str(a["name"]).strip())
                elif isinstance(a, str):
                    author_names.append(a.strip())
        authors_s = ", ".join(author_names[:12])
        paper_url = str(item.get("url") or "").strip()
        ext = item.get("externalIds")
        doi = ""
        if isinstance(ext, dict):
            doi = str(ext.get("DOI") or "").strip()
        if not paper_url and doi:
            paper_url = f"https://doi.org/{doi}"
        conf = max(0.35, 0.92 - idx * 0.04)
        raw = "\n".join(
            x for x in (title, authors_s, year_s, abstract) if x
        )
        citations.append(
            {
                "query": q,
                "title": title or "(no title)",
                "source": "semantic_scholar",
                "url": paper_url,
                "published_at": year_s,
                "snippet": truncate_text(abstract, 300) if abstract else truncate_text(title, 300),
                "raw_content": truncate_text(raw, 2200),
                "confidence": f"{conf:.2f}",
                "domain": extract_url_domain(paper_url),
            }
        )
    if not citations:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY",
            error_message="Semantic Scholar: no papers",
            audit=make_audit("web_search", "error", "no results", provider="semantic_scholar"),
        )
    return WebSearchResult(
        ok=True,
        summary=f"Semantic Scholar: {len(citations)} papers",
        citations=citations,
        audit=make_audit(
            "web_search",
            "ok",
            "Semantic Scholar search",
            provider="semantic_scholar",
            result_count=len(citations),
        ),
    )


def search_arxiv_api(query: str, *, limit: int) -> WebSearchResult:
    q = compact_academic_query((query or "").strip())
    if not q:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY_QUERY",
            error_message="Query is empty",
            audit=make_audit("web_search", "error", "empty query", provider="arxiv"),
        )
    max_r = max(1, min(limit, 50))
    client = _get_arxiv_client()
    search = arxiv.Search(query=q, max_results=max_r, sort_by=arxiv.SortCriterion.Relevance)
    citations: list[dict[str, str]] = []
    try:
        for idx, r in enumerate(client.results(search)):
            title = (r.title or "").replace("\n", " ").strip()
            summary = (r.summary or "").replace("\n", " ").strip()
            authors_s = ", ".join(a.name for a in (r.authors or [])[:12])
            published = r.published.strftime("%Y-%m-%d") if r.published else ""
            link = (r.entry_id or r.pdf_url or "").strip()
            conf = max(0.35, 0.92 - idx * 0.04)
            raw = "\n".join(x for x in (title, authors_s, published, summary) if x)
            citations.append(
                {
                    "query": q,
                    "title": title or "(no title)",
                    "source": "arxiv",
                    "url": link,
                    "published_at": published,
                    "snippet": truncate_text(summary, 300) if summary else truncate_text(title, 300),
                    "raw_content": truncate_text(raw, 2200),
                    "confidence": f"{conf:.2f}",
                    "domain": extract_url_domain(link),
                }
            )
    except arxiv.HTTPError as exc:
        status = int(getattr(exc, "status", 0) or 0)
        logger.warning("arXiv HTTP error status=%s query=%r", status, q[:120])
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_HTTP_ERROR",
            error_message=f"arXiv HTTP {status}" if status else "arXiv HTTP error",
            detail=f"arXiv http {status}" if status else "arXiv http error",
            response_status=status or None,
        )
    except arxiv.UnexpectedEmptyPageError as exc:
        logger.warning("arXiv empty page query=%r: %s", q[:120], exc)
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_BAD_RESPONSE",
            error_message="arXiv: empty result page",
            detail="arXiv empty page",
        )
    except arxiv.ArxivError as exc:
        logger.warning("arXiv API error query=%r: %s", q[:120], exc)
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_UPSTREAM_ERROR",
            error_message=f"arXiv: {exc}",
            detail=str(exc)[:500],
        )
    except requests.exceptions.Timeout as exc:
        logger.warning("arXiv timeout query=%r: %s", q[:120], exc)
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_TIMEOUT",
            error_message="arXiv: request timeout",
            detail="arXiv timeout",
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("arXiv connection error query=%r: %s", q[:120], exc)
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_CONNECTION_ERROR",
            error_message=f"arXiv: {type(exc).__name__}",
            detail=str(exc)[:500],
        )
    except Exception as exc:
        logger.exception("arXiv unexpected error query=%r", q[:120])
        return _arxiv_error_result(
            query=q,
            error_code="ACADEMIC_UPSTREAM_ERROR",
            error_message=f"arXiv: {type(exc).__name__}",
            detail=str(exc)[:500],
        )
    if not citations:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY",
            error_message="arXiv: no papers",
            audit=make_audit("web_search", "error", "no results", provider="arxiv"),
        )
    return WebSearchResult(
        ok=True,
        summary=f"arXiv: {len(citations)} papers",
        citations=citations,
        audit=make_audit(
            "web_search",
            "ok",
            "arXiv search",
            provider="arxiv",
            result_count=len(citations),
        ),
    )


def _crossref_title(item: dict[str, Any]) -> str:
    t = item.get("title")
    if isinstance(t, list) and t:
        return str(t[0] or "").strip()
    if isinstance(t, str):
        return t.strip()
    return ""


def _crossref_year(item: dict[str, Any]) -> str:
    issued = item.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return str(parts[0][0])
    return ""


def _crossref_url(item: dict[str, Any]) -> str:
    doi = str(item.get("DOI") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    links = item.get("link")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and str(link.get("URL") or "").strip():
                return str(link["URL"]).strip()
    return ""


def search_crossref(query: str, *, limit: int) -> WebSearchResult:
    q = (query or "").strip()
    if not q:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY_QUERY",
            error_message="Query is empty",
            audit=make_audit("web_search", "error", "empty query", provider="crossref"),
        )
    rows = max(1, min(limit, 40))
    url = f"https://api.crossref.org/works?query={quote(q)}&rows={rows}"
    mail = _crossref_mailto()
    headers = {"User-Agent": f"ResearchAgent/1.0 (mailto:{mail})" if mail else "ResearchAgent/1.0"}
    with httpx.Client(timeout=_http_timeout()) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code >= 400:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_HTTP_ERROR",
            error_message=f"Crossref HTTP {resp.status_code}",
            audit=make_audit(
                "web_search",
                "error",
                "Crossref http error",
                provider="crossref",
                response_status=resp.status_code,
            ),
        )
    payload = resp.json() if resp.content else {}
    msg = payload.get("message") if isinstance(payload, dict) else None
    items = msg.get("items") if isinstance(msg, dict) else None
    if not isinstance(items, list):
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_BAD_RESPONSE",
            error_message="Crossref: invalid payload",
            audit=make_audit("web_search", "error", "bad json", provider="crossref"),
        )
    citations: list[dict[str, str]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = _crossref_title(item)
        year = _crossref_year(item)
        abstract = str(item.get("abstract") or "").strip()
        if len(abstract) > 20 and abstract.startswith("<"):
            abstract = ""
        container = item.get("container-title")
        venue = ""
        if isinstance(container, list) and container:
            venue = str(container[0] or "").strip()
        elif isinstance(container, str):
            venue = container.strip()
        paper_url = _crossref_url(item)
        conf = max(0.35, 0.92 - idx * 0.04)
        extra = " — ".join(x for x in (venue, year) if x)
        raw = "\n".join(x for x in (title, extra, abstract) if x)
        citations.append(
            {
                "query": q,
                "title": title or "(no title)",
                "source": "crossref",
                "url": paper_url,
                "published_at": year,
                "snippet": truncate_text(abstract, 300) if abstract else truncate_text(title, 300),
                "raw_content": truncate_text(raw, 2200),
                "confidence": f"{conf:.2f}",
                "domain": extract_url_domain(paper_url),
            }
        )
    if not citations:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY",
            error_message="Crossref: no works",
            audit=make_audit("web_search", "error", "no results", provider="crossref"),
        )
    return WebSearchResult(
        ok=True,
        summary=f"Crossref: {len(citations)} works",
        citations=citations,
        audit=make_audit(
            "web_search",
            "ok",
            "Crossref search",
            provider="crossref",
            result_count=len(citations),
        ),
    )


def search_ieee_xplore(query: str, *, limit: int) -> WebSearchResult:
    q = (query or "").strip()
    api_key = str(getattr(settings, "RA_IEEE_XPLORE_API_KEY", "") or "").strip()
    if not q:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY_QUERY",
            error_message="Query is empty",
            audit=make_audit("web_search", "error", "empty query", provider="ieee_xplore"),
        )
    if not api_key:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_CONFIG_MISSING",
            error_message="Missing IEEE Xplore API key",
            audit=make_audit("web_search", "error", "ieee key missing", provider="ieee_xplore"),
        )
    max_r = max(1, min(limit, 25))
    url = (
        "https://ieeexploreapi.ieee.org/api/v1/search/articles"
        f"?format=json&apikey={quote(api_key)}&querytext={quote(q)}&max_records={max_r}"
    )
    with httpx.Client(timeout=_http_timeout()) as client:
        resp = client.get(url)
    if resp.status_code >= 400:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_HTTP_ERROR",
            error_message=f"IEEE Xplore HTTP {resp.status_code}",
            audit=make_audit(
                "web_search",
                "error",
                "IEEE http error",
                provider="ieee_xplore",
                response_status=resp.status_code,
            ),
        )
    payload = resp.json() if resp.content else {}
    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_BAD_RESPONSE",
            error_message="IEEE Xplore: invalid payload",
            audit=make_audit("web_search", "error", "bad json", provider="ieee_xplore"),
        )
    citations: list[dict[str, str]] = []
    for idx, item in enumerate(articles):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        abstract = str(item.get("abstract") or "").strip()
        html_url = str(item.get("html_url") or "").strip()
        pdf_url = str(item.get("pdf_url") or "").strip()
        paper_url = html_url or pdf_url
        authors = item.get("authors")
        author_s = ""
        if isinstance(authors, dict):
            names = authors.get("authors")
            if isinstance(names, list):
                author_s = ", ".join(
                    str(x.get("full_name") or x.get("name") or "").strip()
                    for x in names
                    if isinstance(x, dict)
                )[:500]
        pub = str(item.get("publication_year") or item.get("publication_date") or "").strip()
        conf = max(0.35, 0.92 - idx * 0.04)
        raw = "\n".join(x for x in (title, author_s, pub, abstract) if x)
        citations.append(
            {
                "query": q,
                "title": title or "(no title)",
                "source": "ieee_xplore",
                "url": paper_url,
                "published_at": pub,
                "snippet": truncate_text(abstract, 300) if abstract else truncate_text(title, 300),
                "raw_content": truncate_text(raw, 2200),
                "confidence": f"{conf:.2f}",
                "domain": extract_url_domain(paper_url),
            }
        )
    if not citations:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="ACADEMIC_EMPTY",
            error_message="IEEE Xplore: no articles",
            audit=make_audit("web_search", "error", "no results", provider="ieee_xplore"),
        )
    return WebSearchResult(
        ok=True,
        summary=f"IEEE Xplore: {len(citations)} articles",
        citations=citations,
        audit=make_audit(
            "web_search",
            "ok",
            "IEEE Xplore search",
            provider="ieee_xplore",
            result_count=len(citations),
        ),
    )
