import json
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from business.tests.helper_user import insert_admin, insert_user
from business.utils.jwt_provider import JwtProvider
from research_agent.llm_client import LLMCallResult
from research_agent.models import AgentBehaviorAuditLog, AgentTask, ResearchSession
from research_agent.orchestrator import execute_first_segment

JWT = JwtProvider(settings.JWT_SECRET_KEY)


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class ResearchAgentBehaviorAuditTests(TestCase):
    def setUp(self):
        from business.models import Admin, User

        username, _ = insert_user()
        self.user = User.objects.get(username=username)
        self.user_token = JWT.encode(
            "login", {"user_id": str(self.user.user_id), "role": "user"}
        )
        self.user_headers = {"HTTP_AUTHORIZATION": self.user_token}

        admin_name, _ = insert_admin()
        self.admin = Admin.objects.get(admin_name=admin_name)
        self.admin_headers = {
            "HTTP_X_RESEARCH_USER_ID": f"admin-{self.admin.admin_id}",
            "HTTP_X_RESEARCH_ROLE": "admin",
        }

        self.session = ResearchSession.objects.create(
            owner_id=str(self.user.user_id), title="审计测试"
        )
        self.task = AgentTask.objects.create(session=self.session, status="running", steps=[])

    def test_user_can_report_behavior_log(self):
        payload = {
            "operation_type": "http_request",
            "target_url": "https://example.org/papers?id=123",
            "request_headers": {"accept": "application/json"},
            "request_payload": {"query": "agent"},
            "response_status": 500,
            "exception_message": "upstream timeout",
            "trace_detail": "GET /papers failed",
        }
        resp = self.client.post(
            f"/api/research-agent/tasks/{self.task.id}/behavior-logs/",
            data=json.dumps(payload),
            content_type="application/json",
            **self.user_headers,
        )
        self.assertEqual(resp.status_code, 201)

        log = AgentBehaviorAuditLog.objects.get(task=self.task)
        self.assertEqual(log.operation_type, "http_request")
        self.assertEqual(log.target_domain, "example.org")
        self.assertTrue(log.is_exception)

    def test_admin_can_filter_chain_and_export_behavior_logs(self):
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="navigate",
            target_url="https://example.org/index",
            target_domain="example.org",
            response_status=200,
            trace_detail="open page",
        )
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="http_request",
            target_url="https://api.test.dev/resource",
            target_domain="api.test.dev",
            response_status=503,
            is_exception=True,
            exception_message="service unavailable",
            trace_detail="fetch resource failed",
        )

        list_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={
                "user_id": str(self.user.user_id),
                "target_domain": "test.dev",
                "exception_status": "true",
            },
            **self.admin_headers,
        )
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json().get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_domain"], "api.test.dev")

        chain_resp = self.client.get(
            f"/api/research-agent/manage/tasks/{self.task.id}/behavior-chain/",
            **self.admin_headers,
        )
        self.assertEqual(chain_resp.status_code, 200)
        self.assertEqual(len(chain_resp.json().get("logs", [])), 2)

        export_resp = self.client.post(
            "/api/research-agent/manage/behavior-logs/export/",
            data=json.dumps({"task_id": str(self.task.id)}),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(export_resp.status_code, 200)
        body = export_resp.json()
        self.assertIn("科研助手行为审计报告", body.get("content", ""))
        self.assertTrue(body.get("file_name", "").endswith(".md"))

    def test_orchestrator_step_will_write_behavior_log(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        with patch("research_agent.orchestrator.chat_completion", side_effect=_fake_llm_call):
            execute_first_segment(task.id)
        task.refresh_from_db()
        self.assertIn(task.status, {"completed", "failed", "pending_action"})
        self.assertGreaterEqual(task.behavior_audit_logs.count(), 4)


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
