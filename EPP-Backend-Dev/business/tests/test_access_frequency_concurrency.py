import json

from django.test import TestCase

from business.models import User
from business.models.access_frequency import (
    AccessConcurrencyRule,
    AccessFrequencyRule,
    UserAccessConcurrencyOverride,
)
from business.models.deep_research_task import DeepResearchTask
from business.tests.helper_user import insert_admin, insert_user, login_admin, login_user


class AccessFrequencyConcurrencyTests(TestCase):
    def setUp(self):
        self.user1_name, self.user1_pwd = insert_user()
        self.user2_name, self.user2_pwd = insert_user()

        login1 = login_user(self.client, self.user1_name, self.user1_pwd)
        login2 = login_user(self.client, self.user2_name, self.user2_pwd)
        self.user1_headers = {"HTTP_AUTHORIZATION": login1.json()["token"]}
        self.user2_headers = {"HTTP_AUTHORIZATION": login2.json()["token"]}

        admin_name, admin_pwd = insert_admin()
        admin_login = login_admin(self.client, admin_name, admin_pwd)
        self.admin_headers = {"HTTP_AUTHORIZATION": admin_login.json()["token"]}

        # 放开频次，避免影响并发测试
        AccessFrequencyRule.objects.create(
            feature="deep_research",
            window="daily",
            max_count=-1,
            is_enabled=True,
        )

    def _create_task(self, headers, query: str):
        return self.client.post(
            "/api/deep-research/tasks",
            data=json.dumps({"query": query, "max_rounds": 3}),
            content_type="application/json",
            **headers,
        )

    def test_user_concurrency_limit_should_queue_second_task(self):
        AccessConcurrencyRule.objects.create(
            feature="deep_research",
            max_global_running=10,
            max_user_running=1,
            is_enabled=True,
        )

        first = self._create_task(self.user1_headers, "并发测试任务1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], DeepResearchTask.STATUS_RUNNING)

        second = self._create_task(self.user1_headers, "并发测试任务2")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], DeepResearchTask.STATUS_QUEUED)

    def test_global_concurrency_limit_should_queue_other_user(self):
        AccessConcurrencyRule.objects.create(
            feature="deep_research",
            max_global_running=1,
            max_user_running=-1,
            is_enabled=True,
        )

        first = self._create_task(self.user1_headers, "全局并发测试任务1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], DeepResearchTask.STATUS_RUNNING)

        second = self._create_task(self.user2_headers, "全局并发测试任务2")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], DeepResearchTask.STATUS_QUEUED)

    def test_abort_running_task_will_promote_queued_task(self):
        AccessConcurrencyRule.objects.create(
            feature="deep_research",
            max_global_running=1,
            max_user_running=-1,
            is_enabled=True,
        )

        first = self._create_task(self.user1_headers, "释放槽位任务1")
        second = self._create_task(self.user2_headers, "释放槽位任务2")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["status"], DeepResearchTask.STATUS_RUNNING)
        self.assertEqual(second.json()["status"], DeepResearchTask.STATUS_QUEUED)

        first_task_id = first.json()["task_id"]
        second_task_id = second.json()["task_id"]

        abort_resp = self.client.post(
            f"/api/deep-research/tasks/{first_task_id}/abort",
            data=json.dumps({}),
            content_type="application/json",
            **self.user1_headers,
        )
        self.assertEqual(abort_resp.status_code, 200)

        second_task = DeepResearchTask.objects.get(task_id=second_task_id)
        self.assertEqual(second_task.status, DeepResearchTask.STATUS_RUNNING)

    def test_manage_concurrency_api_should_crud_and_query_stats(self):
        create_rule = self.client.post(
            "/api/manage/access-frequency/concurrency-rules",
            data=json.dumps(
                {
                    "feature": "deep_research",
                    "max_global_running": 2,
                    "max_user_running": 1,
                    "is_enabled": True,
                    "description": "测试规则",
                }
            ),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(create_rule.status_code, 200)
        rule_id = create_rule.json()["rule"]["rule_id"]

        list_rule = self.client.get(
            "/api/manage/access-frequency/concurrency-rules",
            **self.admin_headers,
        )
        self.assertEqual(list_rule.status_code, 200)
        self.assertGreaterEqual(len(list_rule.json().get("rules", [])), 1)

        user = User.objects.get(username=self.user1_name)
        create_override = self.client.post(
            "/api/manage/access-frequency/concurrency-overrides",
            data=json.dumps(
                {
                    "user_id": str(user.user_id),
                    "feature": "deep_research",
                    "max_user_running": 2,
                    "reason": "测试提额",
                }
            ),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(create_override.status_code, 200)
        override_id = create_override.json()["override"]["override_id"]

        list_override = self.client.get(
            "/api/manage/access-frequency/concurrency-overrides",
            data={"keyword": self.user1_name[:4]},
            **self.admin_headers,
        )
        self.assertEqual(list_override.status_code, 200)
        self.assertTrue(
            any(item["override_id"] == override_id for item in list_override.json().get("overrides", []))
        )

        stats_resp = self.client.get(
            "/api/manage/access-frequency/concurrency-stats",
            data={"feature": "deep_research"},
            **self.admin_headers,
        )
        self.assertEqual(stats_resp.status_code, 200)
        self.assertIn("running_count", stats_resp.json())
        self.assertIn("queued_count", stats_resp.json())

        delete_override = self.client.delete(
            f"/api/manage/access-frequency/concurrency-overrides/{override_id}",
            **self.admin_headers,
        )
        self.assertEqual(delete_override.status_code, 200)

        delete_rule = self.client.delete(
            f"/api/manage/access-frequency/concurrency-rules/{rule_id}",
            **self.admin_headers,
        )
        self.assertEqual(delete_rule.status_code, 200)

        self.assertEqual(
            UserAccessConcurrencyOverride.objects.filter(pk=override_id).count(), 0
        )
