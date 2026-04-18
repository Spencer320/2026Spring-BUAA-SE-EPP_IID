"""科研智能助手 API 集成测试（JWT + APIClient）。"""

import json
import time

from django.test import TestCase, override_settings

from business.tests.helper_user import insert_user
from business.utils.jwt_provider import JwtProvider
from django.conf import settings

JWT = JwtProvider(settings.JWT_SECRET_KEY)


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class ResearchAgentAPITests(TestCase):
    def setUp(self):
        self.username, self.password = insert_user()
        from business.models import User

        self.user = User.objects.get(username=self.username)
        self.token = JWT.encode("login", {"user_id": str(self.user.user_id), "role": "user"})
        self.headers = {"HTTP_AUTHORIZATION": self.token}

    def test_sessions_create_and_list(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({"title": "API 测试"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r.status_code, 201)
        sid = r.json()["session_id"]

        r2 = self.client.get("/api/research-agent/sessions/", **self.headers)
        self.assertEqual(r2.status_code, 200)
        items = r2.json()["items"]
        self.assertTrue(any(x["session_id"] == sid for x in items))

    def test_message_task_flow_approve(self):
        r = self.client.post(
            "/api/research-agent/sessions/",
            data=json.dumps({}),
            content_type="application/json",
            **self.headers,
        )
        sid = r.json()["session_id"]
        r2 = self.client.post(
            f"/api/research-agent/sessions/{sid}/messages/",
            data=json.dumps({"content": "请调研量子计算"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r2.status_code, 202)
        tid = r2.json()["task_id"]

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            self.assertEqual(tr.status_code, 200)
            st = tr.json()["status"]
            if st == "waiting_user":
                break
            self.assertIn(st, ("pending", "running"))
            time.sleep(0.02)
        else:
            self.fail("task did not reach waiting_user")

        body = tr.json()
        self.assertIsNotNone(body.get("intervention"))

        ir = self.client.post(
            f"/api/research-agent/tasks/{tid}/intervention/",
            data=json.dumps({"decision": "approve"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(ir.status_code, 200)

        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if tr.json()["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            self.fail("task did not complete")
        self.assertIsNotNone(tr.json().get("result"))

    def test_intervention_reject(self):
        from research_agent.models import ResearchSession

        s = ResearchSession.objects.create(user=self.user, title="x")
        r = self.client.post(
            f"/api/research-agent/sessions/{s.id}/messages/",
            data=json.dumps({"content": "test"}),
            content_type="application/json",
            **self.headers,
        )
        tid = r.json()["task_id"]
        for _ in range(200):
            tr = self.client.get(f"/api/research-agent/tasks/{tid}/", **self.headers)
            if tr.json()["status"] == "waiting_user":
                break
            time.sleep(0.02)
        rr = self.client.post(
            f"/api/research-agent/tasks/{tid}/intervention/",
            data=json.dumps({"decision": "reject"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.json()["status"], "cancelled")

    def test_unauthorized_without_jwt(self):
        r = self.client.get("/api/research-agent/sessions/")
        self.assertEqual(r.status_code, 401)
