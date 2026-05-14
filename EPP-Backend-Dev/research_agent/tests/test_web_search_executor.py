from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_agent.tools.base import WebSearchResult, make_audit
from research_agent.tools.web_search_executor import execute_web_search


def _fail_academic(code: str = "ACADEMIC_EMPTY") -> WebSearchResult:
    return WebSearchResult(
        ok=False,
        summary="",
        citations=[],
        error_code=code,
        error_message="empty",
        audit=make_audit("web_search", "error", "empty", provider="academic"),
    )


def _ok_citation(url: str, source: str) -> WebSearchResult:
    return WebSearchResult(
        ok=True,
        summary="ok",
        citations=[
            {
                "query": "q",
                "title": "T",
                "source": source,
                "url": url,
                "published_at": "",
                "snippet": "s",
                "raw_content": "raw " * 80,
                "confidence": "0.8",
                "domain": "example.org",
            }
        ],
        audit=make_audit("web_search", "ok", "ok", provider=source),
    )


@override_settings(RA_WEB_SEARCH_ACADEMIC_FIRST=False)
class WebSearchExecutorTests(TestCase):
    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("tavily", ""),
    )
    @patch("research_agent.tools.academic_search_executor.search_arxiv_api")
    @patch("research_agent.tools.academic_search_executor.search_crossref")
    @override_settings(
        RA_WEB_SEARCH_PROVIDER="tavily",
        RA_TAVILY_API_KEY="",
        RA_WEB_OPERATOR_ENABLED=False,
    )
    def test_exhausted_without_tavily(self, mock_crossref, mock_arxiv, _mock_route):
        mock_crossref.return_value = _fail_academic()
        mock_arxiv.return_value = _fail_academic()
        res = execute_web_search(query="agent", url="")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "WEB_SEARCH_EMPTY")

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("tavily", ""),
    )
    @override_settings(
        RA_WEB_SEARCH_PROVIDER="tavily",
        RA_TAVILY_API_KEY="test-key",
        RA_WEB_SEARCH_TIMEOUT=5.0,
        RA_WEB_SEARCH_MAX_RESULTS=10,
        RA_WEB_SEARCH_MIN_SCORE=0.7,
        RA_WEB_SEARCH_KEEP_TOP_N=3,
        RA_WEB_SEARCH_FALLBACK_KEEP_N=2,
        RA_WEB_SEARCH_ACADEMIC_DOMAIN_WHITELIST=["arxiv.org", "acm.org"],
        RA_WEB_SEARCH_WHITELIST_PRIORITY_BOOST=0.2,
    )
    @patch("research_agent.tools.web_search_executor.httpx.Client")
    def test_tavily_success(self, mock_client_cls, _mock_route):
        mock_resp_zh_whitelist = MagicMock()
        mock_resp_zh_whitelist.status_code = 200
        mock_resp_zh_whitelist.content = b"{}"
        mock_resp_zh_whitelist.json.return_value = {
            "results": [
                {"title": "Arxiv A", "url": "https://arxiv.org/abs/1234", "content": "content-a", "raw_content": "raw-a " * 30, "score": 0.74},
            ]
        }
        mock_resp_zh_global = MagicMock()
        mock_resp_zh_global.status_code = 200
        mock_resp_zh_global.content = b"{}"
        mock_resp_zh_global.json.return_value = {
            "results": [
                {"title": "General B", "url": "https://x.test/b", "content": "content-b", "raw_content": "short", "score": 0.76},
            ]
        }
        mock_resp_en_whitelist = MagicMock()
        mock_resp_en_whitelist.status_code = 200
        mock_resp_en_whitelist.content = b"{}"
        mock_resp_en_whitelist.json.return_value = {
            "results": [
                {"title": "Arxiv A2", "url": "https://arxiv.org/abs/1234", "content": "content-a2", "raw_content": "raw-a2 " * 30, "score": 0.78},
            ]
        }
        mock_resp_en_global = MagicMock()
        mock_resp_en_global.status_code = 200
        mock_resp_en_global.content = b"{}"
        mock_resp_en_global.json.return_value = {
            "results": [
                {"title": "General C", "url": "https://x.test/c", "content": "content-c", "raw_content": "raw-c " * 30, "score": 0.82},
            ]
        }
        mock_client = MagicMock()
        mock_client.post.side_effect = [mock_resp_zh_whitelist, mock_resp_zh_global, mock_resp_en_whitelist, mock_resp_en_global]
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = lambda *a: None
        mock_client_cls.return_value = mock_client

        res = execute_web_search(query="智能体系统", url="")
        self.assertTrue(res.ok)
        self.assertEqual(res.audit.tool, "web_search")
        self.assertEqual(mock_client.post.call_count, 4)
        self.assertEqual(len(res.citations), 3)
        self.assertEqual(res.citations[0]["url"], "https://arxiv.org/abs/1234")
        self.assertTrue(len(res.citations[0]["raw_content"]) >= 120)
        self.assertEqual(res.citations[0]["source"], "tavily")

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("crossref", ""),
    )
    @patch("research_agent.tools.academic_search_executor.search_crossref")
    @override_settings(RA_WEB_SEARCH_PROVIDER="tavily", RA_TAVILY_API_KEY="", RA_WEB_OPERATOR_ENABLED=False)
    def test_crossref_primary(self, mock_cr, _mock_route):
        mock_cr.return_value = _ok_citation("https://doi.org/10.1000/xyz", "crossref")
        res = execute_web_search(query="transformer survey", url="")
        self.assertTrue(res.ok)
        self.assertEqual(res.citations[0]["source"], "crossref")
        mock_cr.assert_called_once()

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("semantic_scholar", ""),
    )
    @patch("research_agent.tools.academic_search_executor.search_crossref")
    @patch("research_agent.tools.academic_search_executor.search_semantic_scholar")
    @override_settings(
        RA_WEB_SEARCH_PROVIDER="tavily",
        RA_TAVILY_API_KEY="",
        RA_SEMANTIC_SCHOLAR_API_KEY="k",
        RA_WEB_OPERATOR_ENABLED=False,
    )
    def test_fallback_semantic_scholar_to_crossref(self, mock_ss, mock_cr, _mock_route):
        mock_ss.return_value = _fail_academic()
        mock_cr.return_value = _ok_citation("https://doi.org/10.1000/abc", "crossref")
        res = execute_web_search(query="paper", url="")
        self.assertTrue(res.ok)
        self.assertEqual(mock_ss.call_count, 1)
        self.assertEqual(mock_cr.call_count, 1)
        self.assertEqual(res.audit.metadata.get("route_used"), "crossref")

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("web_operator", ""),
    )
    @patch("research_agent.tools.web_operator_executor.playwright_available", return_value=True)
    @patch("research_agent.tools.academic_search_executor.search_crossref")
    @patch("research_agent.tools.web_operator_executor.run_web_operator")
    @override_settings(RA_WEB_SEARCH_PROVIDER="tavily", RA_TAVILY_API_KEY="", RA_WEB_OPERATOR_ENABLED=True)
    def test_web_operator_fails_then_crossref(self, mock_wo, mock_cr, _pa, _mock_route):
        mock_wo.return_value = WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_OPERATOR_NO_RESULTS",
            error_message="none",
            audit=make_audit("web_search", "error", "none", provider="web_operator"),
        )
        mock_cr.return_value = _ok_citation("https://doi.org/10.1000/wo", "crossref")
        res = execute_web_search(
            query="search https://example.org/scholar?q=ai papers",
            url="",
        )
        self.assertTrue(res.ok)
        mock_wo.assert_called_once()
        self.assertIn("example.org", mock_wo.call_args.kwargs["start_url"])
        self.assertEqual(res.citations[0]["source"], "crossref")

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("arxiv", ""),
    )
    @patch("research_agent.tools.web_operator_executor.playwright_available", return_value=True)
    @patch("research_agent.tools.web_operator_executor.run_web_operator")
    @override_settings(RA_WEB_SEARCH_PROVIDER="tavily", RA_TAVILY_API_KEY="test-key", RA_WEB_OPERATOR_ENABLED=True)
    def test_cnki_heuristic_uses_known_start_url(self, mock_wo, _pa, _mock_route):
        mock_wo.return_value = _ok_citation("https://www.cnki.net/foo", "web_operator")
        res = execute_web_search(query="去知网搜索深度学习论文", url="")
        self.assertTrue(res.ok)
        mock_wo.assert_called_once()
        self.assertIn("cnki.net", mock_wo.call_args.kwargs["start_url"])

    @patch(
        "research_agent.tools.web_search_executor._llm_pick_search_route",
        return_value=("tavily", ""),
    )
    @patch("research_agent.tools.web_search_executor._tavily_search")
    @patch("research_agent.tools.academic_search_executor.search_semantic_scholar")
    @patch("research_agent.tools.academic_search_executor.search_crossref")
    @patch("research_agent.tools.academic_search_executor.search_arxiv_api")
    @override_settings(
        RA_WEB_SEARCH_PROVIDER="tavily",
        RA_TAVILY_API_KEY="tv-key",
        RA_SEMANTIC_SCHOLAR_API_KEY="ss-key",
        RA_WEB_OPERATOR_ENABLED=False,
        RA_WEB_SEARCH_ACADEMIC_FIRST=True,
    )
    def test_academic_first_prefers_semantic_scholar_before_tavily(
        self, mock_arxiv, mock_crossref, mock_ss, mock_tavily, _mock_route
    ):
        mock_arxiv.return_value = _fail_academic()
        mock_crossref.return_value = _fail_academic()
        mock_ss.return_value = _ok_citation("https://semanticscholar.org/paper/abc", "semantic_scholar")
        mock_tavily.return_value = _ok_citation("https://example.com/t", "tavily")
        res = execute_web_search(query="neural architecture search", url="")
        self.assertTrue(res.ok)
        self.assertEqual(res.citations[0]["source"], "semantic_scholar")
        mock_tavily.assert_not_called()
