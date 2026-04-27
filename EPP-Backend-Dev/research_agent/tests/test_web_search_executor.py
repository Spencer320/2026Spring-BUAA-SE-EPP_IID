from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_agent.tools.web_search_executor import execute_web_search


class WebSearchExecutorTests(TestCase):
    @override_settings(RA_WEB_SEARCH_PROVIDER="tavily", RA_TAVILY_API_KEY="")
    def test_tavily_missing_key(self):
        res = execute_web_search(query="agent", url="")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "WEB_SEARCH_CONFIG_MISSING")

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
    def test_tavily_success(self, mock_client_cls):
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

