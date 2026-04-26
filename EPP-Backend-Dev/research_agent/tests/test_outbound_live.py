"""M2 验收：真实 HTTP（本地 ThreadingHTTPServer，不依赖外网）。"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.llm_client import LLMCallResult
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
    """未设置 RA_OUTBOUND_DEMO_URL 时走本地检索路径。"""

    def setUp(self):
        self.session = ResearchSession.objects.create(owner_id="ra-live-user", title="M2")
        self._llm_patcher = patch(
            "research_agent.orchestrator.chat_completion",
            side_effect=_fake_llm_call,
        )
        self._llm_patcher.start()
        self.addCleanup(self._llm_patcher.stop)

    def test_approve_completes_without_outbound_url(self):
        task = AgentTask.objects.create(session=self.session, status="running", steps=[])
        execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        steps = task.steps or []
        search_text = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "search" and s.get("title") == "执行检索"
            ),
            "",
        )
        self.assertIn("本地知识库关键词检索", search_text)
        reflect_text = next(
            (s["detail"] for s in steps if s.get("phase") == "reflect"),
            "",
        )
        self.assertIn('"needs_optimization"', reflect_text)


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
            side_effect=_fake_llm_call,
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
        steps = task.steps or []
        search_detail = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "search" and s.get("title") == "执行检索"
            ),
            "",
        )
        self.assertIn("联网检索成功", search_detail)
        reflect_text = next(
            (s["detail"] for s in steps if s.get("phase") == "reflect"),
            "",
        )
        self.assertIn('"needs_optimization"', reflect_text)


def _fake_llm_call(*, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int):
    if "反思裁决器" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"needs_optimization":"no","suggestions":[],"reason":"ok"}',
            model="mock-llm",
        )
    if "科研写作助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"title":"研究报告","sections":[{"heading":"结论","content":"测试"}],"citations":[]}',
            model="mock-llm",
        )
    if "科研阅读分析助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"analysis":"阅读分析","key_points":["点1"],"limitations":["限1"]}',
            model="mock-llm",
        )
    if "科研检索规划助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"search_summary":"检索规划","evidence_need":["综述"],"query_rewrite":"测试问题 检索"}',
            model="mock-llm",
        )
    return LLMCallResult(
        ok=True,
        content='{"plans":[{"index":1,"item":"计划"}]}',
        model="mock-llm",
    )
