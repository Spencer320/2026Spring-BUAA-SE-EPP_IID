"""M2 验收：真实 HTTP（本地 ThreadingHTTPServer，不依赖外网）。"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.test import TestCase, override_settings

from business.tests.helper_user import insert_user

from research_agent.models import AgentTask, ResearchSession
from research_agent.orchestrator import execute_after_approve, execute_first_segment


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"m2_acceptance":"ok","source":"local_http"}')

    def log_message(self, _fmt: str, *_args) -> None:
        pass


@override_settings(
    RESEARCH_AGENT_MOCK_DELAY=0,
    RA_ALLOWED_HOSTS=["127.0.0.1"],
    RA_OUTBOUND_DEMO_URL="",
)
class OutboundLiveAcceptanceTests(TestCase):
    """未设置 RA_OUTBOUND_DEMO_URL 时仍为 Mock act，不启动本地服务。"""

    def setUp(self):
        self.username, self.password = insert_user()
        from business.models import User

        self.user = User.objects.get(username=self.username)
        self.session = ResearchSession.objects.create(user=self.user, title="M2")

    def test_approve_completes_without_outbound_url(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_first_segment(task.id)
        task.refresh_from_db()
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["intervention", "status", "updated_at"])
        execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        steps = task.steps or []
        act_text = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "act" and s.get("title") == "撰写报告"
            ),
            "",
        )
        self.assertIn("Mock", act_text)


@override_settings(
    RESEARCH_AGENT_MOCK_DELAY=0,
    RA_ALLOWED_HOSTS=["127.0.0.1"],
)
class OutboundLiveHttpLocalServerTests(TestCase):
    """设置 RA_OUTBOUND_DEMO_URL 指向本机可路由 URL，走通真实 HTTP 栈。"""

    def setUp(self):
        self.username, self.password = insert_user()
        from business.models import User

        self.user = User.objects.get(username=self.username)
        self.session = ResearchSession.objects.create(user=self.user, title="M2-live")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def test_execute_after_approve_with_real_get(self):
        url = f"http://127.0.0.1:{self._port}/demo"
        with override_settings(RA_OUTBOUND_DEMO_URL=url):
            task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
            execute_first_segment(task.id)
            task.refresh_from_db()
            task.intervention = None
            task.status = "running"
            task.save(update_fields=["intervention", "status", "updated_at"])
            execute_after_approve(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.error_code)
        steps = task.steps or []
        act_detail = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "act" and s.get("title") == "撰写报告"
            ),
            "",
        )
        self.assertIn("出站 GET", act_detail)
        self.assertIn("m2_acceptance", act_detail)
        self.assertIn("local_http", act_detail)
