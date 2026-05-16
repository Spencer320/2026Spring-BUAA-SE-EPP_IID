"""状态机与编排器单元测试（同步执行，不依赖后台线程）。"""

from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.models import AgentTask, ResearchSession
from research_agent.orchestrator import (
    execute_after_approve,
    execute_after_revise,
    execute_deep_research_pipeline,
)
from research_agent.tests._llm_mocks import (
    fake_deep_research_llm_call,
    fake_deep_research_llm_invalid_reflect,
)
from research_agent.views import _mark_local_command_approved


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0, RA_OUTBOUND_DEMO_URL="")
class MockOrchestratorStateTests(TestCase):
    def setUp(self):
        self.user_id = "ra-state-user"
        self.session = ResearchSession.objects.create(owner_id=self.user_id, title="测试会话")
        self.deep_rc = {"runtime_config": {"deep_research_pipeline": True}}

    def test_pending_to_completed_pipeline(self):
        task = AgentTask.objects.create(
            session=self.session, status="pending", steps=[], result_payload=dict(self.deep_rc)
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_deep_research_pipeline(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.intervention)
        self.assertGreaterEqual(task.step_seq, 5)
        phases = [s.get("phase") for s in task.steps]
        self.assertEqual(phases[-1], "write")
        self.assertGreaterEqual(phases.count("reflect"), 1)

    def test_approve_to_completed(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload=dict(self.deep_rc),
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.intervention)
        self.assertIsNotNone(task.result_payload)
        self.assertEqual(task.result_payload.get("format"), "markdown")
        self.assertGreaterEqual(task.step_seq, 5)
        self.assertIn("reflect_rounds", task.result_payload)

    @override_settings(RA_OUTBOUND_DEMO_URL="https://example.com/path", RA_ALLOWED_HOSTS=["httpbin.org"])
    def test_approve_outbound_host_denied_fails_task(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload=dict(self.deep_rc),
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_code, "OUTBOUND_HOST_DENIED")
        self.assertIsNotNone(task.error_message)

    def test_reject_path_not_in_orchestrator(self):
        """cancel 由视图处理；此处仅保证任务可被标记为终态。"""
        task = AgentTask.objects.create(
            session=self.session, status="pending_action", intervention={"id": "x"}
        )
        task.status = "cancelled"
        task.intervention = None
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.status, "cancelled")

    def test_revise_completes(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload=dict(self.deep_rc),
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_revise(task.id, "请改为关注近五年文献")
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIn("研究报告", task.result_payload.get("body", ""))
        self.assertGreaterEqual(task.result_payload.get("reflect_rounds", 0), 1)

    @override_settings(
        RESEARCH_AGENT_MOCK_DELAY=0,
        RA_LOCAL_COMMAND_TEMPLATES={"echo_query": ["python", "-c", "print('hello')"]},
        RA_LOCAL_COMMAND_HIGH_RISK_TEMPLATES=["echo_query"],
    )
    def test_local_command_high_risk_enters_pending_action(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload={
                "runtime_config": {
                    "deep_research_pipeline": True,
                    "risk_confirmation_strategy": "on_high_risk",
                    "local_command": {"template": "echo_query", "args": {"query": "hello"}},
                }
            },
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "pending_action")
        self.assertIsNotNone(task.intervention)
        self.assertEqual(task.intervention.get("tool"), "local_command")

    @override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
    def test_local_command_not_allowed_fails(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload={
                "runtime_config": {
                    "deep_research_pipeline": True,
                    "risk_confirmation_strategy": "never",
                    "local_command": {"template": "not_in_whitelist", "args": {}},
                }
            },
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_code, "LOCAL_CMD_NOT_ALLOWED")

    @override_settings(
        RESEARCH_AGENT_MOCK_DELAY=0,
        RA_LOCAL_COMMAND_TEMPLATES={"echo_query": ["python", "-c", "print('hello')"]},
        RA_LOCAL_COMMAND_HIGH_RISK_TEMPLATES=["echo_query"],
    )
    def test_local_command_approved_then_executes(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            intervention={"tool": "local_command", "template": "echo_query"},
            result_payload={
                "runtime_config": {
                    "deep_research_pipeline": True,
                    "risk_confirmation_strategy": "on_high_risk",
                    "local_command": {"template": "echo_query", "args": {"query": "hello"}},
                }
            },
        )
        _mark_local_command_approved(task)
        task.intervention = None
        task.save(update_fields=["result_payload", "intervention", "updated_at"])
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        runtime = task.result_payload.get("runtime_config", {})
        self.assertTrue(runtime.get("local_command_executed"))

    def test_mvp_text_only_has_no_image_attachment(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload={"runtime_config": {"deep_research_pipeline": True, "enable_image": True}},
        )
        from research_agent.models import ResearchMessage

        ResearchMessage.objects.create(
            session=self.session, role="user", content="请给我输出流程图"
        )
        with patch("research_agent.orchestrator.chat_completion", side_effect=fake_deep_research_llm_call):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        attachments = task.result_payload.get("attachments", [])
        self.assertEqual(attachments, [])

    def test_invalid_reflect_json_is_healed_and_pipeline_completes(self):
        task = AgentTask.objects.create(
            session=self.session,
            status="running",
            steps=[],
            result_payload=dict(self.deep_rc),
        )
        with patch(
            "research_agent.orchestrator.chat_completion",
            side_effect=fake_deep_research_llm_invalid_reflect,
        ):
            execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        phases = [s.get("phase") for s in task.steps if isinstance(s, dict)]
        self.assertIn("reflect", phases)
        self.assertIn("write", phases)
