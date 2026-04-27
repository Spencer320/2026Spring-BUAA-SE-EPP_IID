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
            "step_id": 3,
            "trace_id": "task-trace-001",
            "actor_type": "user",
            "tool_type": "web_search",
            "risk_level": "medium",
            "rule_hit": ["domain_whitelist", "timeout_guard"],
            "policy_version": "v1.0",
            "status": "error",
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
        self.assertEqual(log.step_id, 3)
        self.assertEqual(log.trace_id, "task-trace-001")
        self.assertEqual(log.actor_type, "user")
        self.assertEqual(log.tool_type, "web_search")
        self.assertEqual(log.risk_level, "medium")
        self.assertEqual(log.policy_version, "v1.0")
        self.assertEqual(log.status, "failed")
        self.assertIn("domain_whitelist", log.rule_hit)

    def test_admin_can_filter_chain_and_export_behavior_logs(self):
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="navigate",
            target_url="https://example.org/index",
            target_domain="example.org",
            step_id=1,
            trace_id="trace-abc",
            actor_type="system",
            tool_type="web_search",
            risk_level="low",
            status="succeeded",
            response_status=200,
            trace_detail="open page",
        )
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="http_request",
            target_url="https://api.test.dev/resource",
            target_domain="api.test.dev",
            step_id=2,
            trace_id="trace-abc",
            actor_type="system",
            tool_type="web_search",
            risk_level="high",
            rule_hit="domain_rate_limit",
            policy_version="v1.1",
            status="failed",
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
                "audit_status": "failed",
            },
            **self.admin_headers,
        )
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json().get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_domain"], "api.test.dev")
        self.assertEqual(items[0]["status"], "failed")
        self.assertEqual(items[0]["risk_level"], "high")
        self.assertEqual(items[0]["trace_id"], "trace-abc")

        chain_resp = self.client.get(
            f"/api/research-agent/manage/tasks/{self.task.id}/behavior-chain/",
            **self.admin_headers,
        )
        self.assertEqual(chain_resp.status_code, 200)
        chain_logs = chain_resp.json().get("logs", [])
        self.assertEqual(len(chain_logs), 2)
        self.assertEqual(chain_logs[0]["trace_id"], "trace-abc")

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
        logs = list(task.behavior_audit_logs.all())
        self.assertGreaterEqual(len(logs), 4)
        self.assertTrue(all(log.step_id is not None for log in logs))
        self.assertTrue(all(bool(log.trace_id) for log in logs))
        self.assertTrue(all(log.actor_type in {"system", "user", "admin"} for log in logs))
        self.assertTrue(all(bool(log.status) for log in logs))
        self.assertTrue(all(bool(log.tool_type) for log in logs))


def _fake_llm_call(*, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int):
    if "role=planner" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "alternatives": [
                        {
                            "plan_id": "plan-1",
                            "title": "方案一",
                            "steps": ["检索背景", "分析证据"],
                            "rationale": "覆盖核心问题",
                        },
                        {
                            "plan_id": "plan-2",
                            "title": "方案二",
                            "steps": ["先写后查"],
                            "rationale": "快速收敛",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=decider" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "selected_plan_id": "plan-1",
                    "decision_reason": "覆盖更完整",
                    "complexity": "simple",
                    "merge_attempt_note": "不需要合并",
                    "subtasks": [
                        {
                            "subtask_id": "s1",
                            "title": "背景与证据",
                            "goal": "完成基础调研",
                            "depends_on": [],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=searcher" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "info_groups": [
                        {
                            "group_title": "基础资料",
                            "relevance": "high",
                            "raw_findings": ["找到若干公开来源"],
                            "sources": [{"title": "source", "url": "https://example.org", "snippet": "snippet"}],
                        }
                    ],
                    "search_notes": "可继续阅读",
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=reader" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"analysis":"阅读分析","key_points":["点1"],"limitations":["限1"]}',
            model="mock-llm",
        )
    if "role=reflector" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "needs_optimization": "no",
                    "reason": "已满足要求",
                    "actionable_suggestions": [],
                    "accepted_reader_summary": {
                        "analysis": "阅读分析",
                        "key_points": ["点1"],
                        "limitations": ["限1"],
                    },
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=writer" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "title": "研究报告",
                    "executive_summary": "摘要",
                    "sections": [{"heading": "结论", "content": "测试"}],
                    "traceability": [{"subtask_id": "s1", "conclusion": "完成调研"}],
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    return LLMCallResult(
        ok=True,
        content="{}",
        model="mock-llm",
    )
