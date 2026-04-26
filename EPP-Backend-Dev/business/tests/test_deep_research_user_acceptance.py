import json

from django.test import TestCase
from django.utils import timezone

from business.models.deep_research_task import DeepResearchStep, DeepResearchTask
from business.tests.helper_user import insert_user, login_admin, login_user, insert_admin


class DeepResearchUserAcceptanceTests(TestCase):
    def setUp(self):
        self.username, self.password = insert_user()
        login_resp = login_user(self.client, self.username, self.password)
        self.assertEqual(login_resp.status_code, 200)
        self.user_token = login_resp.json()["token"]
        self.user_headers = {"HTTP_AUTHORIZATION": self.user_token}

    def _create_task(
        self,
        *,
        status=DeepResearchTask.STATUS_RUNNING,
        output_suppressed=False,
        query="验证任务",
    ):
        from business.models import User

        user = User.objects.get(username=self.username)
        task = DeepResearchTask.objects.create(
            user=user,
            query=query,
            status=status,
            output_suppressed=output_suppressed,
            current_phase=DeepResearchTask.PHASE_SEARCHING,
            progress=56,
            step_summary="正在检索论文库",
            token_used_total=1200,
            citation_coverage=0.82,
            report={"markdown": "# 报告", "citations": ["https://example.org"]},
            started_at=timezone.now(),
        )
        DeepResearchStep.objects.create(
            task=task,
            seq=1,
            phase=DeepResearchTask.PHASE_PLANNING,
            action="拆解任务",
            summary="分解为 3 个子问题",
            token_used=200,
        )
        DeepResearchStep.objects.create(
            task=task,
            seq=2,
            phase=DeepResearchTask.PHASE_SEARCHING,
            action="执行搜索",
            summary="抓取高质量来源",
            token_used=360,
        )
        return task

    def test_user_create_task_requires_auth(self):
        resp = self.client.post(
            "/api/deep-research/tasks",
            data=json.dumps({"query": "test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_user_can_poll_status_and_events(self):
        task = self._create_task(status=DeepResearchTask.STATUS_RUNNING)

        status_resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/status",
            **self.user_headers,
        )
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["status"], DeepResearchTask.STATUS_RUNNING)

        events_resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/events?since_seq=1",
            **self.user_headers,
        )
        self.assertEqual(events_resp.status_code, 200)
        events = events_resp.json()["steps"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["seq"], 2)

    def test_user_get_report_requires_completed(self):
        task = self._create_task(status=DeepResearchTask.STATUS_RUNNING)
        resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/report",
            **self.user_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("任务尚未完成", resp.json()["error"])

    def test_user_get_report_when_completed(self):
        task = self._create_task(status=DeepResearchTask.STATUS_COMPLETED)
        resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/report",
            **self.user_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["task_id"], str(task.task_id))
        self.assertEqual(resp.json()["token_used_total"], 1200)

    def test_report_suppressed_after_admin_action(self):
        task = self._create_task(status=DeepResearchTask.STATUS_COMPLETED)
        admin_name, admin_password = insert_admin()
        admin_login = login_admin(self.client, admin_name, admin_password)
        admin_token = admin_login.json()["token"]
        admin_headers = {"HTTP_AUTHORIZATION": admin_token}

        suppress = self.client.post(
            f"/api/manage/deep-research/tasks/{task.task_id}/suppress-output",
            data=json.dumps({"reason": "灰度期风控验证"}),
            content_type="application/json",
            **admin_headers,
        )
        self.assertEqual(suppress.status_code, 200)

        report_resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/report",
            **self.user_headers,
        )
        self.assertEqual(report_resp.status_code, 400)
        self.assertIn("暂时不可访问", report_resp.json()["error"])

    def test_user_abort_running_task(self):
        task = self._create_task(status=DeepResearchTask.STATUS_RUNNING)
        resp = self.client.post(
            f"/api/deep-research/tasks/{task.task_id}/abort",
            data=json.dumps({}),
            content_type="application/json",
            **self.user_headers,
        )
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, DeepResearchTask.STATUS_ABORTED)
        self.assertIsNotNone(task.finished_at)

    def test_user_abort_terminal_task_should_fail(self):
        task = self._create_task(status=DeepResearchTask.STATUS_COMPLETED)
        resp = self.client.post(
            f"/api/deep-research/tasks/{task.task_id}/abort",
            data=json.dumps({}),
            content_type="application/json",
            **self.user_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不可中止", resp.json()["error"])

    def test_user_isolation_cannot_access_others_task(self):
        other_name, other_password = insert_user()
        other_login = login_user(self.client, other_name, other_password)
        other_headers = {"HTTP_AUTHORIZATION": other_login.json()["token"]}

        task = self._create_task(status=DeepResearchTask.STATUS_COMPLETED)
        resp = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/status",
            **other_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("任务不存在", resp.json()["error"])

    def test_follow_up_and_export_return_todo_stub(self):
        task = self._create_task(status=DeepResearchTask.STATUS_COMPLETED)

        follow = self.client.post(
            f"/api/deep-research/tasks/{task.task_id}/follow-up",
            data=json.dumps({"content": "补充最新文献"}),
            content_type="application/json",
            **self.user_headers,
        )
        self.assertEqual(follow.status_code, 400)

        export_resp = self.client.post(
            "/api/deep-research/tasks/export",
            data=json.dumps({"task_ids": [str(task.task_id)], "format": "zip"}),
            content_type="application/json",
            **self.user_headers,
        )
        self.assertEqual(export_resp.status_code, 400)
