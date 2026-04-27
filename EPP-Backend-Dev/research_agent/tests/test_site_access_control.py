import json
from unittest.mock import patch

from django.db.utils import OperationalError
from django.test import TestCase, override_settings

from business.models import Admin, User
from business.tests.helper_user import insert_admin, insert_user
from research_agent.models import (
    AgentBehaviorAuditLog,
    AgentTask,
    ResearchSession,
    SiteAccessPolicyConfig,
    SiteAccessRule,
)
from research_agent.tools.web_fetch_executor import allowed_get


class SiteAccessControlApiTests(TestCase):
    def setUp(self):
        admin_name, _ = insert_admin()
        self.admin = Admin.objects.get(admin_name=admin_name)
        self.admin_headers = {
            "HTTP_X_RESEARCH_USER_ID": f"admin-{self.admin.admin_id}",
            "HTTP_X_RESEARCH_ROLE": "admin",
        }

        username, _ = insert_user()
        self.user = User.objects.get(username=username)
        self.session = ResearchSession.objects.create(owner_id=str(self.user.user_id), title="site-access")
        self.task = AgentTask.objects.create(session=self.session, status="running", steps=[])

    def test_policy_and_rule_crud(self):
        policy_resp = self.client.get(
            "/api/research-agent/manage/site-access/policy/",
            **self.admin_headers,
        )
        self.assertEqual(policy_resp.status_code, 200)
        self.assertIn("policy", policy_resp.json())

        update_resp = self.client.put(
            "/api/research-agent/manage/site-access/policy/",
            data=json.dumps({"mode": "whitelist", "description": "strict"}),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(update_resp.status_code, 200)
        policy = update_resp.json().get("policy", {})
        self.assertEqual(policy.get("mode"), "whitelist")

        create_resp = self.client.post(
            "/api/research-agent/manage/site-access/rules/",
            data=json.dumps(
                {
                    "rule_type": "allow",
                    "match_type": "suffix",
                    "pattern": "example.org",
                    "priority": 10,
                    "is_enabled": True,
                    "description": "academic source",
                }
            ),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(create_resp.status_code, 200)
        rule = create_resp.json().get("rule", {})
        self.assertEqual(rule.get("rule_type"), "allow")

        list_resp = self.client.get(
            "/api/research-agent/manage/site-access/rules/",
            **self.admin_headers,
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json().get("rules", [])), 1)

        rule_id = rule.get("rule_id")
        edit_resp = self.client.put(
            f"/api/research-agent/manage/site-access/rules/{rule_id}/",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
            **self.admin_headers,
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertFalse(edit_resp.json().get("rule", {}).get("is_enabled"))

        del_resp = self.client.delete(
            f"/api/research-agent/manage/site-access/rules/{rule_id}/",
            **self.admin_headers,
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(SiteAccessRule.objects.count(), 0)

    def test_events_and_stats_api(self):
        SiteAccessPolicyConfig.objects.create(mode="blacklist", policy_version=7)
        AgentBehaviorAuditLog.objects.create(
            task=self.task,
            operation_type="web_search",
            target_url="https://blocked.test/resource",
            target_domain="blocked.test",
            tool_type="web_search",
            status="rejected",
            rule_hit="site_access:deny:suffix:blocked.test#2",
            policy_version="7",
            trace_detail="blocked by policy",
        )
        events_resp = self.client.get(
            "/api/research-agent/manage/site-access/events/",
            **self.admin_headers,
        )
        self.assertEqual(events_resp.status_code, 200)
        items = events_resp.json().get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_domain"], "blocked.test")
        self.assertEqual(items[0]["user_name"], self.user.username)

        stats_resp = self.client.get(
            "/api/research-agent/manage/site-access/stats/",
            **self.admin_headers,
        )
        self.assertEqual(stats_resp.status_code, 200)
        stats = stats_resp.json().get("events", {})
        self.assertEqual(stats.get("blocked"), 1)
        self.assertEqual(stats.get("total"), 1)

    def test_rules_api_returns_readable_error_when_schema_unavailable(self):
        with patch(
            "research_agent.site_access_views.SiteAccessRule.objects.all",
            side_effect=OperationalError("relation does not exist"),
        ):
            response = self.client.get(
                "/api/research-agent/manage/site-access/rules/",
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 500)
        error = response.json().get("error", {})
        self.assertEqual(error.get("code"), "SITE_ACCESS_SCHEMA_UNAVAILABLE")
        self.assertIn("migrate research_agent", str(error.get("message", "")))


@override_settings(RA_ALLOWED_HOSTS=["allowed.test", "blocked.test"])
class SiteAccessControlRuntimeTests(TestCase):
    def setUp(self):
        SiteAccessPolicyConfig.objects.create(mode="whitelist", policy_version=3)
        SiteAccessRule.objects.create(
            rule_type="allow",
            match_type="exact",
            pattern="allowed.test",
            priority=1,
            is_enabled=True,
        )

    def test_allowed_get_will_be_blocked_by_site_policy(self):
        denied = allowed_get("https://blocked.test/path")
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error_code, "OUTBOUND_SITE_DENIED")
        self.assertIn("site_access", denied.rule_hit)
        self.assertEqual(denied.policy_version, "3")
