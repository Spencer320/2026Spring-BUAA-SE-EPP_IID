from django.test import SimpleTestCase

from research_agent.llm_client import usage_total_tokens


class LlmUsageParsingTests(SimpleTestCase):
    def test_total_tokens_field(self):
        self.assertEqual(usage_total_tokens({"total_tokens": 12, "prompt_tokens": 10}), 12)

    def test_prompt_plus_completion(self):
        self.assertEqual(
            usage_total_tokens({"prompt_tokens": 10, "completion_tokens": 2}),
            12,
        )

    def test_modelarts_shape(self):
        usage = {
            "prompt_tokens": 10,
            "total_tokens": 12,
            "completion_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
        self.assertEqual(usage_total_tokens(usage), 12)

    def test_empty_usage(self):
        self.assertEqual(usage_total_tokens(None), 0)
