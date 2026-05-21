"""run_registry：按 UUID 解析深度 / basic / 工作区运行实体。"""

from django.test import TestCase

from research_agent.models import AgentTask, BasicOrchestratorRun, ResearchSession, WorkspaceAgentRun
from research_agent.pipelines.registry import resolve_owned_run, resolve_run_by_id, run_kind


class RunRegistryTests(TestCase):
    def setUp(self):
        self.owner = "ra-registry-user"
        self.session = ResearchSession.objects.create(owner_id=self.owner, title="registry")

    def test_run_kind_labels(self):
        deep = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        basic = BasicOrchestratorRun.objects.create(session=self.session, status="pending", steps=[])
        ws = WorkspaceAgentRun.objects.create(session=self.session, status="pending", steps=[])
        self.assertEqual(run_kind(deep), "deep_research")
        self.assertEqual(run_kind(basic), "basic")
        self.assertEqual(run_kind(ws), "workspace")

    def test_resolve_owned_run_filters_by_owner(self):
        deep = AgentTask.objects.create(session=self.session, status="pending", steps=[])
        other_session = ResearchSession.objects.create(owner_id="other-user", title="x")
        other = AgentTask.objects.create(session=other_session, status="pending", steps=[])

        hit = resolve_owned_run(self.owner, deep.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.id, deep.id)
        self.assertIsNone(resolve_owned_run(self.owner, other.id))

    def test_resolve_run_by_id_without_owner_filter(self):
        basic = BasicOrchestratorRun.objects.create(session=self.session, status="pending", steps=[])
        hit = resolve_run_by_id(basic.id)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.id, basic.id)
