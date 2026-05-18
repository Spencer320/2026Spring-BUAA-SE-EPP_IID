"""论文展示区 API 与写入逻辑测试。"""

import json
import tempfile
from unittest.mock import patch

import jwt
from django.conf import settings
from django.test import TestCase, override_settings

from business.utils.user_workspace import get_workspace_root
from research_agent.models import BasicOrchestratorRun, ResearchMessage, ResearchPaperShelfItem, ResearchSession
from research_agent.paper_shelf import append_search_citations_to_shelf
from research_agent.tools.base import WebSearchResult, make_audit


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class PaperShelfTests(TestCase):
    def setUp(self):
        self.user_id = "ra-shelf-user"
        self.token = jwt.encode(
            {"user_id": self.user_id, "role": "user"}, settings.JWT_SECRET_KEY, algorithm="HS256"
        )
        self.headers = {"HTTP_AUTHORIZATION": self.token}

    @staticmethod
    def _d(resp):
        body = resp.json()
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    def test_append_search_dedupes_by_url(self):
        cits = [
            {
                "title": "Paper A",
                "url": "https://arxiv.org/abs/1234.5678",
                "snippet": "ab",
                "source": "arxiv",
            }
        ]
        n1 = append_search_citations_to_shelf(self.user_id, cits, search_query="q")
        n2 = append_search_citations_to_shelf(self.user_id, cits, search_query="q")
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(ResearchPaperShelfItem.objects.filter(owner_id=self.user_id).count(), 1)

    def test_workspace_add_and_list_and_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            root = get_workspace_root(self.user_id)
            (root / "a.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj trailer<<>>\n%%EOF")

            r2 = self.client.post(
                "/api/research-agent/paper-shelf/workspace/",
                data=json.dumps({"workspace_rel_path": "a.pdf"}),
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(r2.status_code, 201)
            item = self._d(r2)["item"]
            self.assertEqual(item["source_kind"], "workspace_file")
            self.assertEqual(item["workspace_rel_path"], "a.pdf")
            self.assertIn("open_mode", item)

            r3 = self.client.get(
                "/api/research-agent/paper-shelf/",
                **self.headers,
            )
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(self._d(r3)["total"], 1)

            iid = item["id"]
            r4 = self.client.delete(
                f"/api/research-agent/paper-shelf/{iid}/",
                **self.headers,
            )
            self.assertEqual(r4.status_code, 200)
            r5 = self.client.get(
                "/api/research-agent/paper-shelf/",
                **self.headers,
            )
            self.assertEqual(self._d(r5)["total"], 0)

    def test_add_external_citations_api(self):
        r = self.client.post(
            "/api/research-agent/paper-shelf/external/",
            data=json.dumps(
                {
                    "search_query": "transformer",
                    "citations": [
                        {
                            "title": "T",
                            "url": "https://example.org/p/2",
                            "snippet": "s",
                            "source": "crossref",
                        }
                    ],
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self._d(r)["created"], 1)
        self.assertEqual(ResearchPaperShelfItem.objects.filter(owner_id=self.user_id).count(), 1)

    def test_search_step_does_not_auto_write_shelf(self):
        session = ResearchSession.objects.create(owner_id=self.user_id, title="s")
        ResearchMessage.objects.create(session=session, role="user", content="找 transformer 论文")
        run = BasicOrchestratorRun.objects.create(
            session=session,
            status="running",
            result_payload={
                "runtime_config": {
                    "smart_plan": {
                        "steps": [{"type": "search", "title": "检索", "query": "transformer"}]
                    },
                    "smart_plan_next_index": 0,
                }
            },
        )
        fake = WebSearchResult(
            ok=True,
            summary="ok",
            citations=[
                {
                    "title": "T",
                    "url": "https://example.org/p/1",
                    "snippet": "s",
                    "source": "crossref",
                }
            ],
            audit=make_audit("web_search", "ok", "t"),
        )
        with patch("research_agent.tool_executor.execute_web_search", return_value=fake):
            from research_agent.basic_orchestrator import _execute_search_step

            text, err, pending = _execute_search_step(
                task=run,
                prior_context="",
                step={"type": "search", "title": "检索", "query": "transformer"},
            )
        self.assertIsNone(err)
        self.assertIn("example.org", text or "")
        self.assertEqual(len(pending), 1)
        self.assertEqual(ResearchPaperShelfItem.objects.filter(owner_id=self.user_id).count(), 0)
