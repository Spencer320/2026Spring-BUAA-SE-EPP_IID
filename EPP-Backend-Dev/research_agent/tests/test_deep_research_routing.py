"""深度研究入口分流：无文献走 Basic，有文献走综述四阶段。"""

import json
import uuid
from unittest.mock import patch

import jwt
from django.conf import settings
from django.test import TestCase, override_settings

from research_agent.models import AgentTask, BasicOrchestratorRun, ResearchSession
from research_agent.search_evidence import build_seed_citations, count_effective_hits


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0, RA_OUTBOUND_DEMO_URL="")
class DeepResearchRoutingTests(TestCase):
    def setUp(self):
        self.user_id = "ra-routing-user"
        self.token = jwt.encode(
            {"user_id": self.user_id, "role": "user"},
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        self.headers = {"HTTP_AUTHORIZATION": self.token}
        self._quota = patch("research_agent.views._quota_precheck", return_value=None)
        self._quota.start()
        self.addCleanup(self._quota.stop)

    @staticmethod
    def _d(resp):
        body = resp.json()
        return body["data"] if isinstance(body, dict) and "data" in body else body

    def test_deep_research_without_papers_routes_to_basic(self):
        r = self.client.post(
            "/api/research-agent/tasks/deep-research/",
            data=json.dumps({"content": "开放式研究问题"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        data = self._d(r)
        self.assertEqual(data["pipeline_mode"], "assistant")
        self.assertEqual(data["orchestrator"], "basic")
        tid = uuid.UUID(data["task_id"])
        self.assertTrue(BasicOrchestratorRun.objects.filter(id=tid).exists())
        self.assertFalse(AgentTask.objects.filter(id=tid).exists())

    @patch("research_agent.views.start_deep_research_thread")
    @patch("research_agent.views._validate_selected_papers_from_shelf")
    def test_deep_research_with_papers_routes_to_synthesis(
        self, mock_validate, _mock_thread
    ):
        session = ResearchSession.objects.create(owner_id=self.user_id, title="综述会话")
        paper_id = str(uuid.uuid4())
        mock_validate.return_value = (
            [
                {
                    "shelf_item_id": paper_id,
                    "source_kind": "external_link",
                    "dedupe_key": "https://doi.org/10.1000/xyz",
                    "title": "Test Paper on Transformers",
                    "primary_url": "https://doi.org/10.1000/xyz",
                    "workspace_rel_path": "",
                    "context_tier": "full_text_available",
                    "added_via": "search",
                    "authors": "A Author",
                    "abstract": "We study attention mechanisms.",
                    "search_query": "transformer attention",
                    "file_extension": "",
                }
            ],
            None,
        )
        r = self.client.post(
            "/api/research-agent/tasks/deep-research/",
            data=json.dumps(
                {
                    "session_id": str(session.id),
                    "content": "请基于选定文献写综述",
                    "selected_papers": [paper_id],
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        data = self._d(r)
        self.assertEqual(data["pipeline_mode"], "synthesis")
        self.assertEqual(data["orchestrator"], "deep_research")
        tid = uuid.UUID(data["task_id"])
        self.assertTrue(AgentTask.objects.filter(id=tid).exists())
        task = AgentTask.objects.get(id=tid)
        papers = task.result_payload.get("runtime_config", {}).get("selected_papers", [])
        self.assertEqual(len(papers), 1)
        self.assertIn("abstract", papers[0])
        self.assertEqual(papers[0]["authors"], "A Author")


class SearchEvidenceUnitTests(TestCase):
    def test_build_seed_and_effective_hits(self):
        papers = [
            {
                "shelf_item_id": "x",
                "title": "Paper A",
                "primary_url": "https://example.com/a",
                "abstract": "Abstract A",
                "authors": "Author",
                "search_query": "paper a",
            }
        ]
        seeds = build_seed_citations(papers)
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["source"], "user_selected")
        self.assertFalse(count_effective_hits(seeds))
        external = [
            {
                "title": "Ext",
                "url": "https://arxiv.org/abs/1",
                "source": "arxiv",
                "snippet": "snip",
            }
        ]
        self.assertEqual(count_effective_hits(external), 1)
