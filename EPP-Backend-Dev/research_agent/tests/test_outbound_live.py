"""M2 验收：真实 HTTP（本地 ThreadingHTTPServer，不依赖外网）。"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.models import AgentTask, ResearchSession
from research_agent.orchestrator import execute_after_approve


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
        steps = task.steps or []
        search_text = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "analyze" and str(s.get("title", "")).startswith("分析子任务：")
            ),
            "",
        )
        self.assertIn("工具检索：Use local RAG search:", search_text)
        reflect_text = next(
            (s["detail"] for s in steps if s.get("phase") == "reflect"),
            "",
        )
        self.assertIn("是否继续优化", reflect_text)
        self.assertIn("## 参考来源", task.result_payload.get("body", ""))


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
        steps = task.steps or []
        search_detail = next(
            (
                s["detail"]
                for s in steps
                if s.get("phase") == "analyze" and str(s.get("title", "")).startswith("分析子任务：")
            ),
            "",
        )
        self.assertIn("工具检索：Outbound fetch succeeded:", search_detail)
        reflect_text = next(
            (s["detail"] for s in steps if s.get("phase") == "reflect"),
            "",
        )
        self.assertIn("是否继续优化", reflect_text)
        self.assertIn("## 参考来源", task.result_payload.get("body", ""))


def _fake_llm_call(*, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int):
    if "role=plan_decider" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"alternatives":[{"plan_id":"plan-1","title":"方案A","steps":["步骤1"],"rationale":"理由A"},{"plan_id":"plan-2","title":"方案B","steps":["步骤1"],"rationale":"理由B"}],"selected_plan_id":"plan-1","decision_reason":"方案可执行","complexity":"simple","merge_attempt_note":"任务已合并","subtasks":[{"subtask_id":"s1","title":"执行子任务","goal":"完成研究","depends_on":[]}]}',
            model="mock-llm",
        )
    if "role=analyzer" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"info_groups":[{"group_title":"基础信息","relevance":"high","raw_findings":["发现1"],"sources":[{"title":"source1","url":"https://example.com","domain":"example.com","snippet":"snippet","source_type":"mock"}]}],"search_notes":"检索完成","analysis":"基于当前证据，研究方向可行","key_points":["研究方向可行"],"limitations":["证据数量有限"]}',
            model="mock-llm",
        )
    if "role=reflector" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"needs_optimization":"no","reason":"当前信息已足够完成报告","actionable_suggestions":[]}',
            model="mock-llm",
        )
    if "role=writer" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"title":"研究报告","executive_summary":"这是执行摘要。","sections":[{"heading":"研究问题","content":"测试问题"},{"heading":"结论","content":"这是来自 LLM 的测试报告。"}],"traceability":[{"subtask_id":"s1","conclusion":"结论1"}]}',
            model="mock-llm",
        )
    return LLMCallResult(
        ok=True,
        content='{"alternatives":[{"plan_id":"plan-1","title":"方案A","steps":["步骤1"],"rationale":"理由A"},{"plan_id":"plan-2","title":"方案B","steps":["步骤1"],"rationale":"理由B"}],"selected_plan_id":"plan-1","decision_reason":"方案可执行","complexity":"simple","merge_attempt_note":"任务已合并","subtasks":[{"subtask_id":"s1","title":"执行子任务","goal":"完成研究","depends_on":[]}]}',
        model="mock-llm",
    )
