from django.test import TestCase

from business.models import User
from business.models.access_frequency import (
    FEATURE_DEEP_RESEARCH,
    FEATURE_RESEARCH_ASSISTANT,
    AccessFrequencyRule,
    FeatureAccessLog,
)
from business.tests.helper_user import insert_user
from business.utils.rate_limit import (
    check_quota_before_start,
    get_user_feature_usage,
    record_research_assistant_usage,
)


class AccessFrequencyQuotaTests(TestCase):
    def setUp(self):
        self.username, _ = insert_user()
        self.user = User.objects.get(username=self.username)

    def test_deep_research_count_quota_blocks_second_task(self):
        AccessFrequencyRule.objects.create(
            feature=FEATURE_DEEP_RESEARCH,
            window="daily",
            max_count=1,
            is_enabled=True,
        )
        allowed1, _ = check_quota_before_start(self.user, FEATURE_DEEP_RESEARCH)
        self.assertTrue(allowed1)
        allowed2, msg = check_quota_before_start(self.user, FEATURE_DEEP_RESEARCH)
        self.assertFalse(allowed2)
        self.assertIn("深度研究", msg)

    def test_research_assistant_token_quota_precheck_and_record(self):
        AccessFrequencyRule.objects.create(
            feature=FEATURE_RESEARCH_ASSISTANT,
            window="daily",
            max_count=100,
            is_enabled=True,
        )
        allowed, _ = check_quota_before_start(self.user, FEATURE_RESEARCH_ASSISTANT)
        self.assertTrue(allowed)
        self.assertEqual(
            FeatureAccessLog.objects.filter(
                user=self.user, feature=FEATURE_RESEARCH_ASSISTANT
            ).count(),
            0,
        )

        record_research_assistant_usage(
            self.user,
            60,
            run_id="run-1",
            session_id="sess-1",
        )
        usage = get_user_feature_usage(self.user, FEATURE_RESEARCH_ASSISTANT)
        self.assertEqual(usage["quota_unit"], "tokens")
        self.assertEqual(usage["used"], 60)
        self.assertEqual(usage["remaining"], 40)

        record_research_assistant_usage(
            self.user,
            50,
            run_id="run-2",
            session_id="sess-1",
        )
        allowed2, msg = check_quota_before_start(self.user, FEATURE_RESEARCH_ASSISTANT)
        self.assertFalse(allowed2)
        self.assertIn("Token", msg)
