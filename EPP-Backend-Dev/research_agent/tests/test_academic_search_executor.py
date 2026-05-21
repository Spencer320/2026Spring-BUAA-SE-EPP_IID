from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import arxiv

from research_agent.tools.academic_search_executor import (
    compact_academic_query,
    search_arxiv_api,
)
class CompactAcademicQueryTests(SimpleTestCase):
    def test_extracts_latin_terms_from_long_chinese_goal(self):
        raw = (
            "从用户提供的文献中准确提取并阐述 Lookahead Decoding 的方法原理、"
            "关键步骤和技术特点。"
        )
        q = compact_academic_query(raw)
        self.assertIn("Lookahead Decoding", q)
        self.assertLessEqual(len(q), 320)

    def test_short_query_unchanged(self):
        q = compact_academic_query("transformer attention")
        self.assertEqual(q, "transformer attention")


class SearchArxivApiTests(SimpleTestCase):
    @patch("research_agent.tools.academic_search_executor._get_arxiv_client")
    def test_http_429_returns_error_result_not_raise(self, mock_get_client):
        client = MagicMock()
        client.results.side_effect = arxiv.HTTPError("http://export.arxiv.org/", 3, 429)
        mock_get_client.return_value = client

        with patch("research_agent.tools.academic_search_executor.time.sleep"):
            res = search_arxiv_api("Lookahead Decoding", limit=5)

        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "ACADEMIC_HTTP_ERROR")
        self.assertIn("429", res.error_message)

    @patch("research_agent.tools.academic_search_executor._get_arxiv_client")
    def test_success_maps_paper_fields(self, mock_get_client):
        paper = MagicMock()
        paper.title = "Test Paper"
        paper.summary = "Abstract text"
        author = MagicMock()
        author.name = "Alice"
        paper.authors = [author]
        paper.published.strftime.return_value = "2024-01-01"
        paper.entry_id = "https://arxiv.org/abs/2401.00001"
        paper.pdf_url = ""

        client = MagicMock()
        client.results.return_value = iter([paper])
        mock_get_client.return_value = client

        res = search_arxiv_api("transformer", limit=3)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.citations), 1)
        self.assertEqual(res.citations[0]["source"], "arxiv")
