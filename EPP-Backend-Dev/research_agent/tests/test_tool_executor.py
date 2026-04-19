"""出站 GET 白名单、超时与失败码。"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_agent.tool_executor import OutboundResult, allowed_get, is_host_allowed


@override_settings(
    RA_ALLOWED_HOSTS=["httpbin.org", "127.0.0.1"],
    RA_HTTP_TIMEOUT=5.0,
    RA_HTTP_MAX_BODY_BYTES=1024,
)
class ToolExecutorTests(TestCase):
    def test_is_host_allowed(self):
        self.assertTrue(is_host_allowed("httpbin.org"))
        self.assertTrue(is_host_allowed("HTTPBIN.ORG"))
        self.assertFalse(is_host_allowed("evil.com"))

    def test_invalid_scheme(self):
        r = allowed_get("ftp://httpbin.org/get")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "OUTBOUND_INVALID_URL")

    def test_host_denied(self):
        r = allowed_get("https://example.com/")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "OUTBOUND_HOST_DENIED")

    @patch("research_agent.tool_executor.httpx.Client")
    def test_get_success_summary(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_bytes = lambda: [b'{"hello": "world"}']

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: mock_response
        mock_cm.__exit__ = lambda *a: None

        mock_client = MagicMock()
        mock_client.stream = lambda method, url: mock_cm
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = lambda *a: None
        mock_client_cls.return_value = mock_client

        r = allowed_get("https://httpbin.org/get")
        self.assertIsInstance(r, OutboundResult)
        self.assertTrue(r.ok)
        self.assertIn("hello", r.summary)

    @patch("research_agent.tool_executor.httpx.Client")
    def test_http_error_status(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.iter_bytes = lambda: iter(())

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: mock_response
        mock_cm.__exit__ = lambda *a: None

        mock_client = MagicMock()
        mock_client.stream = lambda method, url: mock_cm
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = lambda *a: None
        mock_client_cls.return_value = mock_client

        r = allowed_get("https://httpbin.org/status/503")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "OUTBOUND_HTTP_ERROR")
        self.assertIn("503", r.error_message)

    @patch("research_agent.tool_executor.httpx.Client")
    def test_body_too_large(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200

        def big_chunks():
            yield b"x" * 2000

        mock_response.iter_bytes = big_chunks

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: mock_response
        mock_cm.__exit__ = lambda *a: None

        mock_client = MagicMock()
        mock_client.stream = lambda method, url: mock_cm
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = lambda *a: None
        mock_client_cls.return_value = mock_client

        r = allowed_get("https://httpbin.org/bytes/9999")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "OUTBOUND_BODY_TOO_LARGE")
