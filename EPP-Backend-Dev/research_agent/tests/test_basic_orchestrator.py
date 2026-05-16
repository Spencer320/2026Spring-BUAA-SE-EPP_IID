"""basic 编排器单元测试（Smart Planner + 单步 chat，同步执行）。"""

from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.basic_orchestrator import execute_basic_pipeline
from research_agent.models import BasicOrchestratorRun, ResearchMessage, ResearchSession
from research_agent.tests._llm_mocks import fake_basic_chat_llm_call, fake_smart_planner_llm_call


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0, RA_OUTBOUND_DEMO_URL="")
class BasicOrchestratorTests(TestCase):
    def setUp(self):
        self.session = ResearchSession.objects.create(owner_id="ra-basic-user", title="basic 测试")
        ResearchMessage.objects.create(session=self.session, role="user", content="请简要介绍 RAG")

    def test_execute_basic_pipeline_completes_with_chat_plan(self):
        run = BasicOrchestratorRun.objects.create(
            session=self.session,
            status="pending",
            steps=[],
            result_payload={"runtime_config": {}},
        )
        with (
            patch("research_agent.smart_planner.chat_completion", side_effect=fake_smart_planner_llm_call),
            patch("research_agent.basic_orchestrator.chat_completion", side_effect=fake_basic_chat_llm_call),
            patch("research_agent.step_refill.chat_completion", side_effect=fake_basic_chat_llm_call),
        ):
            execute_basic_pipeline(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertIsNone(run.intervention)
        phases = [s.get("phase") for s in run.steps if isinstance(s, dict)]
        self.assertIn("plan", phases)
        self.assertIn("write", phases)
        payload = run.result_payload if isinstance(run.result_payload, dict) else {}
        self.assertEqual(payload.get("format"), "markdown")
        self.assertTrue(str(payload.get("body", "")).strip())
        self.assertEqual(payload.get("pipeline"), ["plan", "basic", "write"])
