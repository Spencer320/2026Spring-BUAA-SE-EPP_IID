from unittest.mock import patch

from django.test import TestCase

from research_agent.tools.web_operator_executor import run_web_operator


class WebOperatorExecutorTests(TestCase):
    @patch("research_agent.tools.web_operator_executor.playwright_available", return_value=False)
    def test_playwright_not_available(self, _mock_pa):
        res = run_web_operator("查找论文", start_url="https://example.com/")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "WEB_OPERATOR_PLAYWRIGHT_MISSING")

    @patch("research_agent.tools.web_operator_executor.playwright_available", return_value=True)
    @patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("launch failed"))
    def test_playwright_runtime_error(self, _mock_sp, _mock_pa):
        res = run_web_operator("查找论文", start_url="https://example.com/")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "WEB_OPERATOR_RUNTIME_ERROR")
        self.assertIn("launch failed", res.error_message)
