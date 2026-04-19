"""状态机与编排器单元测试（同步执行，不依赖后台线程）。"""

from django.test import TestCase, override_settings

from business.tests.helper_user import insert_user

from research_agent.models import AgentTask, ResearchSession
from research_agent.orchestrator import (
    execute_after_approve,
    execute_after_revise,
    execute_first_segment,
)


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class MockOrchestratorStateTests(TestCase):
    def setUp(self):
        self.username, self.password = insert_user()
        from business.models import User

        self.user = User.objects.get(username=self.username)
        self.session = ResearchSession.objects.create(
            user=self.user, title="测试会话"
        )

    def test_pending_to_waiting_user_first_segment(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_first_segment(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "waiting_user")
        self.assertIsNotNone(task.intervention)
        self.assertEqual(task.intervention.get("reason_code"), "external_link")
        self.assertEqual(task.step_seq, 4)

    def test_approve_to_completed(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_first_segment(task.id)
        task.refresh_from_db()
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["intervention", "status", "updated_at"])
        execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.intervention)
        self.assertIsNotNone(task.result_payload)
        self.assertEqual(task.result_payload.get("format"), "markdown")
        self.assertEqual(task.step_seq, 8)

    @override_settings(
        RESEARCH_AGENT_MOCK_DELAY=0,
        RA_OUTBOUND_DEMO_URL="https://example.com/path",
        RA_ALLOWED_HOSTS=["httpbin.org"],
    )
    def test_approve_outbound_host_denied_fails_task(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_first_segment(task.id)
        task.refresh_from_db()
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["intervention", "status", "updated_at"])
        execute_after_approve(task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_code, "OUTBOUND_HOST_DENIED")
        self.assertIsNotNone(task.error_message)

    def test_reject_path_not_in_orchestrator(self):
        """cancel 由视图处理；此处仅保证任务可被标记为终态。"""
        task = AgentTask.objects.create(
            session=self.session, status="waiting_user", intervention={"id": "x"}
        )
        task.status = "cancelled"
        task.intervention = None
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.status, "cancelled")

    def test_revise_completes(self):
        task = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        execute_first_segment(task.id)
        task.refresh_from_db()
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["intervention", "status", "updated_at"])
        execute_after_revise(task.id, "请改为关注近五年文献")
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIn("近五年", task.result_payload.get("body", ""))
