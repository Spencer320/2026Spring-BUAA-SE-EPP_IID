"""科研智能助手 API 集成测试（JWT + APIClient）。"""

import json
import time
from unittest.mock import patch

import jwt
from django.conf import settings
from django.test import TestCase, override_settings

from research_agent.llm_client import LLMCallResult


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0, RA_OUTBOUND_DEMO_URL="")
class ResearchAgentAPITests(TestCase):
    def setUp(self):
        self.user_id = "ra-test-user"
        self.token = jwt.encode(
            {"user_id": self.user_id, "role": "user"}, settings.JWT_SECRET_KEY, algorithm="HS256"
        )
        self.headers = {"HTTP_AUTHORIZATION": self.token}
        self._llm_patcher = patch(
            "research_agent.orchestrator.chat_completion",
            side_effect=_fake_llm_call,
        )
        self._llm_patcher.start()
        self.addCleanup(self._llm_patcher.stop)

    @staticmethod
    def _d(resp):
        body = resp.json()
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    def test_sessions_create_and_list(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({"title": "API 测试"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 201)
        sid = self._d(r)["session_id"]

        r2 = self.client.get("/api/research-agent/sessions/", **self.headers)
        self.assertEqual(r2.status_code, 200)
        items = self._d(r2)["items"]
        self.assertTrue(any(x["session_id"] == sid for x in items))

    def test_delete_session(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({"title": "待删除会话"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 201)
        sid = self._d(r)["session_id"]

        r2 = self.client.delete(f"/api/research-agent/sessions/{sid}/", **self.headers)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(self._d(r2)["deleted"])

        r3 = self.client.get(f"/api/research-agent/sessions/{sid}/", **self.headers)
        self.assertEqual(r3.status_code, 404)

    def test_rename_session_title(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({"title": "旧标题"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 201)
        sid = self._d(r)["session_id"]

        r2 = self.client.patch(
            f"/api/research-agent/sessions/{sid}/",
            data=json.dumps({"title": "新标题"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self._d(r2)["title"], "新标题")

        r3 = self.client.get(f"/api/research-agent/sessions/{sid}/", **self.headers)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(self._d(r3)["title"], "新标题")

    def test_create_session_on_first_message(self):
        r = self.client.post(
            "/api/research-agent/sessions/messages/",
            data=json.dumps({"content": "请调研测试主题"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        sid = self._d(r)["session_id"]
        tid = self._d(r)["task_id"]
        self.assertTrue(sid)
        self.assertTrue(tid)

        r2 = self.client.get(f"/api/research-agent/sessions/{sid}/", **self.headers)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(len(self._d(r2).get("messages", [])) >= 2)

    def test_batch_delete_sessions(self):
        sid_list = []
        for i in range(2):
            r = self.client.post(
                "/api/research-agent/sessions/",
                data=json.dumps({"title": f"待批量删除{i}"}),
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(r.status_code, 201)
            sid_list.append(self._d(r)["session_id"])

        r2 = self.client.post(
            "/api/research-agent/sessions/batch-delete/",
            data=json.dumps({"session_ids": sid_list}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertGreaterEqual(self._d(r2)["deleted_count"], 2)

        for sid in sid_list:
            r3 = self.client.get(f"/api/research-agent/sessions/{sid}/", **self.headers)
            self.assertEqual(r3.status_code, 404)

    def test_message_task_flow_approve(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({}),
            content_type="application/json",
            **self.headers,
        )
        sid = self._d(r)["session_id"]
        r2 = self.client.post(
            f"/api/research-agent/sessions/{sid}/messages/",
            data=json.dumps({"content": "请调研量子计算"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r2.status_code, 202)
        tid = self._d(r2)["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            self.assertEqual(tr.status_code, 200)
            st = self._d(tr)["status"]
            if st in ("completed", "failed"):
                break
            self.assertIn(st, ("pending", "running"))
            time.sleep(0.02)
        else:
            self.fail("task did not finish")

        body = self._d(tr)
        self.assertEqual(body["status"], "completed")
        self.assertIsNotNone(body.get("result"))
        phases = [step["phase"] for step in body.get("steps", [])]
        self.assertGreaterEqual(phases.count("plan"), 1)
        self.assertGreaterEqual(phases.count("reflect"), 1)
        self.assertEqual(phases[-1], "write")
        self.assertIn("reflect_rounds", body["result"])

    def test_create_task_with_max_reflect_rounds(self):
        r = self.client.post(
            "/api/research-agent/sessions/messages/",
            data=json.dumps({"content": "请调研测试主题", "max_reflect_rounds": 1}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        tid = self._d(r)["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if self._d(tr)["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("task did not complete")
        self.assertEqual(self._d(tr)["result"]["reflect_rounds"], 1)

    def test_image_output_enabled_generates_attachment(self):
        r = self.client.post(
            "/api/research-agent/sessions/messages/",
            data=json.dumps({"content": "请给我一份该主题的流程图", "enable_image": True}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        tid = self._d(r)["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if self._d(tr)["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("task did not complete")

        result = self._d(tr)["result"]
        self.assertEqual(result.get("attachments"), [])

    def test_follow_up_and_download_report(self):
        r = self.client.post(
            "/api/research-agent/sessions/messages/",
            data=json.dumps({"content": "请调研测试主题"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 202)
        tid = self._d(r)["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if self._d(tr)["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("seed task did not complete")

        follow = self.client.post(
            f"/api/research-agent/tasks/{tid}/follow-up/",
            data=json.dumps({"content": "请补充近三年研究趋势"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(follow.status_code, 202)
        follow_tid = self._d(follow)["task_id"]
        self.assertNotEqual(follow_tid, tid)

        for _ in range(200):
            tr2 = self.client.get(f"/api/research-agent/tasks/{follow_tid}/", **self.headers)
            if self._d(tr2)["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("follow up task did not complete")

        download = self.client.get(
            f"/api/research-agent/tasks/{follow_tid}/download/", **self.headers
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn("text/markdown", download["Content-Type"])

    def test_intervention_reject(self):
        from research_agent.models import ResearchSession

        s = ResearchSession.objects.create(owner_id=self.user_id, title="x")
        r = self.client.post(
            f"/api/research-agent/sessions/{s.id}/messages/",
            data=json.dumps({"content": "test"}),
            content_type="application/json",
            **self.headers,
        )
        tid = self._d(r)["task_id"]
        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if self._d(tr)["status"] in ("completed", "failed"):
                break
            time.sleep(0.02)
        rr = self.client.post(
            f"/api/research-agent/tasks/{tid}/intervention/",
            data=json.dumps({"decision": "reject"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(rr.status_code, 409)

    def test_unauthorized_without_jwt(self):
        r = self.client.get("/api/research-agent/sessions/")
        self.assertEqual(r.status_code, 401)

    def test_new_actions_and_report_and_events_api(self):
        created = self.client.post(
            "/api/research-agent/tasks/",
            data=json.dumps({"query": "请调研独立化接口"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(created.status_code, 202)
        tid = self._d(created)["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/status/", **self.headers)
            self.assertEqual(tr.status_code, 200)
            if self._d(tr)["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("task did not complete")

        events = self.client.get(
            f"/api/research-agent/tasks/{tid}/events/?since_seq=0", **self.headers
        )
        self.assertEqual(events.status_code, 200)
        self.assertIn("events", self._d(events))

        report = self.client.get(f"/api/research-agent/tasks/{tid}/report/", **self.headers)
        self.assertEqual(report.status_code, 200)
        self.assertIn("report", self._d(report))

        exported = self.client.post(
            "/api/research-agent/tasks/export/",
            data=json.dumps({"task_ids": [tid]}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(self._d(exported)["total"], 1)

    def test_get_session_returns_latest_task(self):
        created = self.client.post(
            "/api/research-agent/sessions/messages/",
            data=json.dumps({"content": "请调研 latest_task 展示"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(created.status_code, 202)
        sid = self._d(created)["session_id"]
        tid = self._d(created)["task_id"]
        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if self._d(tr)["status"] == "completed":
                break
            time.sleep(0.02)
        session_resp = self.client.get(f"/api/research-agent/sessions/{sid}/", **self.headers)
        self.assertEqual(session_resp.status_code, 200)
        body = self._d(session_resp)
        self.assertIn("latest_task", body)
        self.assertIsNotNone(body["latest_task"])
        self.assertEqual(body["latest_task"]["task_id"], tid)


def _fake_llm_call(*, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int):
    if "反思裁决器" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"needs_optimization":"no","suggestions":[],"reason":"可以进入写作"}',
            model="mock-llm",
        )
    if "科研写作助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"title":"研究报告","sections":[{"heading":"研究问题","content":"测试"},{"heading":"结论","content":"该内容来自 mock LLM。"}],"citations":[]}',
            model="mock-llm",
        )
    if "科研阅读分析助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"analysis":"这是阅读分析阶段的 mock 输出。","key_points":["关键点A"],"limitations":["局限A"]}',
            model="mock-llm",
        )
    if "科研检索规划助手" in system_prompt:
        return LLMCallResult(
            ok=True,
            content='{"search_summary":"建议覆盖综述与实验论文","evidence_need":["近五年综述"],"query_rewrite":"测试问题 近五年"}',
            model="mock-llm",
        )
    return LLMCallResult(
        ok=True,
        content='{"plans":[{"index":1,"item":"计划A"},{"index":2,"item":"计划B"}]}',
        model="mock-llm",
    )
