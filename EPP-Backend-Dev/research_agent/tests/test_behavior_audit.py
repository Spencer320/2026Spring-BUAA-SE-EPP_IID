import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

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
        task_completed = AgentTask.objects.create(session=self.session, status="completed", steps=[])
        AgentBehaviorAuditLog.objects.create(
            task=task_completed,
            operation_type="http_request",
            target_url="https://api.test.dev/other",
            target_domain="api.test.dev",
            step_id=3,
            trace_id="trace-xyz",
            actor_type="system",
            tool_type="web_search",
            risk_level="medium",
            status="failed",
            response_status=500,
            is_exception=True,
            exception_message="other failed request",
            trace_detail="fetch other failed",
        )

        list_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={
                "user_name": self.user.username[:2],
                "task_name": "审计",
                "target_domain": "test.dev",
                "exception_status": "true",
                "audit_status": "failed",
                "task_status": "running",
            },
            **self.admin_headers,
        )
        self.assertEqual(list_resp.status_code, 200)
        list_body = list_resp.json()
        items = list_body.get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_domain"], "api.test.dev")
        self.assertEqual(items[0]["status"], "failed")
        self.assertEqual(items[0]["risk_level"], "high")
        self.assertEqual(items[0]["trace_id"], "trace-abc")
        self.assertEqual(items[0]["user_name"], self.user.username)
        self.assertEqual(items[0]["task_name"], "审计测试")
        self.assertEqual(list_body.get("operation_type_options"), ["http_request"])

        chain_resp = self.client.get(
            f"/api/research-agent/manage/tasks/{self.task.id}/behavior-chain/",
            **self.admin_headers,
        )
        self.assertEqual(chain_resp.status_code, 200)
        chain_task = chain_resp.json().get("task", {})
        self.assertEqual(chain_task.get("user_name"), self.user.username)
        self.assertEqual(chain_task.get("task_name"), "审计测试")
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
        content = body.get("content", "")
        self.assertIn("科研助手行为审计报告", content)
        self.assertIn("| 时间 | 用户名 | 任务名 |", content)
        self.assertIn(self.user.username, content)
        self.assertIn("审计测试", content)
        self.assertIn("## 分布统计", content)
        self.assertIn("### task_status 分布", content)
        self.assertIn("- running: 2", content)
        self.assertIn("### operation_type 分布", content)
        self.assertIn("- http_request: 1", content)
        self.assertIn("- navigate: 1", content)
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

    def test_admin_behavior_logs_sorting_supports_step_user_task_and_time(self):
        from business.models import User

        username_2, _ = insert_user()
        user_2 = User.objects.get(username=username_2)

        self.session.title = "任务-Z"
        self.session.save(update_fields=["title"])
        session_2 = ResearchSession.objects.create(owner_id=str(user_2.user_id), title="任务-A")
        task_2 = AgentTask.objects.create(session=session_2, status="completed", steps=[])

        now = timezone.now()
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="search",
            target_domain="example.org",
            step_id=30,
            status="succeeded",
            occurred_at=now - timedelta(minutes=3),
        )
        AgentBehaviorAuditLog.objects.create(
            task=task_2,
            operation_type="search",
            target_domain="example.org",
            step_id=10,
            status="succeeded",
            occurred_at=now - timedelta(minutes=2),
        )
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="search",
            target_domain="example.org",
            step_id=20,
            status="succeeded",
            occurred_at=now - timedelta(minutes=1),
        )

        step_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={"page_size": 50, "sort_by": "step_id", "sort_order": "asc"},
            **self.admin_headers,
        )
        self.assertEqual(step_resp.status_code, 200)
        step_items = step_resp.json().get("items", [])
        self.assertEqual([item["step_id"] for item in step_items], [10, 20, 30])

        time_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={"page_size": 50, "sort_by": "occurred_at", "sort_order": "asc"},
            **self.admin_headers,
        )
        self.assertEqual(time_resp.status_code, 200)
        time_items = time_resp.json().get("items", [])
        self.assertEqual([item["step_id"] for item in time_items], [30, 10, 20])

        user_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={"page_size": 50, "sort_by": "user_name", "sort_order": "asc"},
            **self.admin_headers,
        )
        self.assertEqual(user_resp.status_code, 200)
        user_items = user_resp.json().get("items", [])
        user_names = [item["user_name"] for item in user_items]
        self.assertEqual(len(user_names), 3)
        self.assertIn(self.user.username, user_names)
        self.assertIn(user_2.username, user_names)

        task_resp = self.client.get(
            "/api/research-agent/manage/behavior-logs/",
            data={"page_size": 50, "sort_by": "task_name", "sort_order": "asc"},
            **self.admin_headers,
        )
        self.assertEqual(task_resp.status_code, 200)
        task_items = task_resp.json().get("items", [])
        task_names = [item["task_name"] for item in task_items]
        self.assertEqual(task_names, sorted(task_names, key=lambda name: str(name).lower()))


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
