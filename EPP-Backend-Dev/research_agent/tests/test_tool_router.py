from unittest.mock import patch

from django.test import TestCase

from research_agent.tools.router import route_tool_call


class ToolRouterTests(TestCase):
    @patch("research_agent.tools.router.execute_web_search")
    def test_route_web_search(self, mock_search):
        audit = type("Audit", (), {"tool": "web_search", "status": "ok", "detail": "ok", "metadata": {}})
        mock_search.return_value = type(
            "WebResult",
            (),
            {"ok": True, "summary": "s", "citations": [], "audit": audit, "error_code": "", "error_message": ""},
        )()
        res = route_tool_call(tool_name="web_search", args={"query": "q", "url": ""})
        self.assertTrue(res.ok)
        self.assertIn("audit", res.payload)

    def test_route_unknown_tool(self):
        res = route_tool_call(tool_name="unknown_tool", args={})
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "TOOL_NOT_SUPPORTED")

