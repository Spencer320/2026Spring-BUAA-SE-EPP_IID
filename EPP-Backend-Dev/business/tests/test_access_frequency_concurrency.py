import json

from django.test import TestCase

from business.models import User
from business.models.access_frequency import (
    AccessConcurrencyRule,
    UserAccessConcurrencyOverride,
)
from business.tests.helper_user import insert_admin, insert_user, login_admin, login_user


class AccessFrequencyConcurrencyTests(TestCase):
    def setUp(self):
        self.user1_name, self.user1_pwd = insert_user()
        admin_name, admin_pwd = insert_admin()
        admin_login = login_admin(self.client, admin_name, admin_pwd)
        self.admin_headers = {"HTTP_AUTHORIZATION": admin_login.json()["token"]}

    def test_manage_concurrency_api_should_crud_and_query_stats(self):
        create_rule = self.client.post(
            "/api/manage/access-frequency/concurrency-rules",
            data=json.dumps(
                {
                    "feature": "ai_chat",
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
                    "feature": "ai_chat",
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
            data={"feature": "ai_chat"},
            **self.admin_headers,
        )
        self.assertEqual(stats_resp.status_code, 200)
        self.assertIn("running_count", stats_resp.json())
        self.assertIn("queued_count", stats_resp.json())
        self.assertEqual(stats_resp.json()["running_count"], 0)
        self.assertEqual(stats_resp.json()["queued_count"], 0)

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
