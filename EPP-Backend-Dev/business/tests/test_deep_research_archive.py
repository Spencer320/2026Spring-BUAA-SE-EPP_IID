import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from business.models import DeepResearchTask, DeepResearchTaskArchive, User
from business.tests.helper_user import (
    insert_admin,
    insert_user,
    login_admin,
    login_user,
)


class TestDeepResearchArchive(TestCase):
    def setUp(self):
        self.client = Client()
        self.audit_report_patcher = patch("business.signals.audit_report_async", return_value=None)
        self.audit_step_patcher = patch("business.signals.audit_step_async", return_value=None)
        self.audit_report_patcher.start()
        self.audit_step_patcher.start()
        self.username, self.password = insert_user()
        self.user = User.objects.get(username=self.username)

    def tearDown(self):
        self.audit_report_patcher.stop()
        self.audit_step_patcher.stop()

    def _create_completed_task(self):
        task = DeepResearchTask.objects.create(
            user=self.user,
            query="测试 Deep Research 归档",
            status=DeepResearchTask.STATUS_RUNNING,
            token_used_total=1234,
        )
        task.report = {
            "title": "测试报告",
            "sections": [
                {
                    "heading": "背景",
                    "content": "内容",
                    "citations": [{"title": "Paper A", "url": "https://example.com"}],
                }
            ],
        }
        task.status = DeepResearchTask.STATUS_COMPLETED
        task.finished_at = timezone.now()
        task.save(update_fields=["report", "status", "finished_at"])
        task.refresh_from_db()
        return task

    def test_task_auto_archived_after_completed(self):
        task = self._create_completed_task()
        self.assertEqual(task.status, DeepResearchTask.STATUS_ARCHIVED)

        archive = DeepResearchTaskArchive.objects.filter(task=task).first()
        self.assertIsNotNone(archive)
        self.assertEqual(archive.terminal_status, DeepResearchTask.STATUS_COMPLETED)
        self.assertTrue(isinstance(archive.resource_audit_report, dict))
        self.assertEqual(archive.resource_audit_report.get("token_used_total"), 1234)
        self.assertGreaterEqual(len(archive.citation_traces or []), 1)

    def test_user_report_available_after_archived(self):
        task = self._create_completed_task()
        login_response = login_user(self.client, self.username, self.password)
        user_token = json.loads(login_response.content.decode("utf-8")).get("token")

        response = self.client.get(
            f"/api/deep-research/tasks/{task.task_id}/report",
            HTTP_AUTHORIZATION=user_token,
        )
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("status"), DeepResearchTask.STATUS_ARCHIVED)
        self.assertEqual(payload.get("report", {}).get("title"), "测试报告")

    def test_admin_can_query_archive_detail(self):
        task = self._create_completed_task()
        admin_name, admin_password = insert_admin()
        login_response = login_admin(self.client, admin_name, admin_password)
        admin_token = json.loads(login_response.content.decode("utf-8")).get("token")

        response = self.client.get(
            f"/api/manage/deep-research/tasks/{task.task_id}/archive",
            HTTP_AUTHORIZATION=admin_token,
        )
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.content.decode("utf-8"))
        archive = payload.get("archive", {})
        self.assertEqual(archive.get("task_id"), str(task.task_id))
        self.assertEqual(
            archive.get("terminal_status"), DeepResearchTask.STATUS_COMPLETED
        )
