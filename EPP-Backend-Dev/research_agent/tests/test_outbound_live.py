"""M2 验收：真实 HTTP（本地 ThreadingHTTPServer，不依赖外网）。"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.models import AgentTask, ResearchSession
from research_agent.orchestrator import execute_after_approve, execute_deep_research_pipeline
from research_agent.tests._llm_mocks import fake_deep_research_llm_call


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"m2_acceptance":"ok","source":"local_http"}')

    def log_message(self, _fmt: str, *_args) -> None:
        pass


def _search_step_detail(task: AgentTask) -> str:
    steps = task.steps or []
    for step in steps:
        if isinstance(step, dict) and step.get("phase") == "search":
            return str(step.get("detail", ""))
    return ""


def _reflect_step_detail(task: AgentTask) -> str:
    steps = task.steps or []
    for step in steps:
        if isinstance(step, dict) and step.get("phase") == "reflect":
            return str(step.get("detail", ""))
    return ""


@override_settings(
    RESEARCH_AGENT_MOCK_DELAY=0,
    RA_ALLOWED_HOSTS=["127.0.0.1"],
    RA_OUTBOUND_DEMO_URL="",
    RA_WEB_SEARCH_PROVIDER="local_rag",
)
class OutboundLiveAcceptanceTests(TestCase):
    """未设置 RA_OUTBOUND_DEMO_URL 时走 local_rag 检索路径。"""

    def setUp(self):
        self.session = ResearchSession.objects.create(owner_id="ra-live-user", title="M2")
        self._llm_patcher = patch(
            "research_agent.orchestrator.chat_completion",
            side_effect=fake_deep_research_llm_call,
        )
        self._llm_patcher.start()
        self.addCleanup(self._llm_patcher.stop)

    def test_deep_research_completes_with_local_rag_search(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_deep_research_pipeline(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        search_text = _search_step_detail(task)
        self.assertTrue(
            "local_rag" in search_text.lower() or "local rag" in search_text.lower(),
            msg=search_text,
        )
        reflect_text = _reflect_step_detail(task)
        self.assertIn("是否继续优化", reflect_text)


@override_settings(
    RESEARCH_AGENT_MOCK_DELAY=0,
    RA_ALLOWED_HOSTS=["127.0.0.1"],
)
class OutboundLiveHttpLocalServerTests(TestCase):
    """设置 RA_OUTBOUND_DEMO_URL 指向本机可路由 URL，走通真实 HTTP 栈。"""

    def setUp(self):
        self.session = ResearchSession.objects.create(owner_id="ra-live-user", title="M2-live")
        self._llm_patcher = patch(
            "research_agent.orchestrator.chat_completion",
            side_effect=fake_deep_research_llm_call,
        )
        self._llm_patcher.start()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._llm_patcher.stop()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def test_execute_after_approve_with_real_get(self):
        url = f"http://127.0.0.1:{self._port}/demo"
        with override_settings(RA_OUTBOUND_DEMO_URL=url):
            task = AgentTask.objects.create(session=self.session, status="running", steps=[])
            execute_after_approve(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.error_code)
        search_detail = _search_step_detail(task)
        self.assertIn("Outbound fetch succeeded", search_detail)
        reflect_text = _reflect_step_detail(task)
        self.assertIn("是否继续优化", reflect_text)
