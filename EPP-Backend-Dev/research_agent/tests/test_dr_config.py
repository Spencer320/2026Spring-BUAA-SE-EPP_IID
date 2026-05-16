from django.test import SimpleTestCase

from research_agent.dr_config import (
    resolve_dr_max_reflect_rounds,
    resolve_dr_phase_llm_config,
)


class DRConfigTests(SimpleTestCase):
    def test_default_phase_configs_match_pipeline_behavior(self):
        plan = resolve_dr_phase_llm_config({}, phase="plan")
        decide = resolve_dr_phase_llm_config({}, phase="decide")
        search = resolve_dr_phase_llm_config({}, phase="search")
        read = resolve_dr_phase_llm_config({}, phase="read")
        reflect = resolve_dr_phase_llm_config({}, phase="reflect")
        write = resolve_dr_phase_llm_config({}, phase="write")

        self.assertEqual((plan.temperature, plan.max_tokens, plan.enable_thinking, plan.history_limit), (0.2, 4096, False, 2))
        self.assertEqual((decide.temperature, decide.max_tokens, decide.enable_thinking, decide.history_limit), (0.1, 4096, False, 2))
        self.assertEqual((search.temperature, search.max_tokens, search.enable_thinking, search.history_limit), (0.1, 6144, False, 2))
        self.assertEqual((read.temperature, read.max_tokens, read.enable_thinking, read.history_limit), (0.2, 6144, False, 2))
        self.assertEqual((reflect.temperature, reflect.max_tokens, reflect.enable_thinking, reflect.history_limit), (0.1, 6144, False, 2))
        self.assertEqual((write.temperature, write.max_tokens, write.enable_thinking, write.history_limit), (0.2, 6144, False, 2))

    def test_nested_dr_config_overrides_phase_params(self):
        runtime_config = {
            "dr_config": {
                "llm": {
                    "search": {
                        "temperature": "0.33",
                        "max_tokens": "1234",
                        "enable_thinking": "true",
                        "history_limit": "7",
                    }
                }
            }
        }
        search = resolve_dr_phase_llm_config(runtime_config, phase="search")
        self.assertEqual(search.temperature, 0.33)
        self.assertEqual(search.max_tokens, 1234)
        self.assertTrue(search.enable_thinking)
        self.assertEqual(search.history_limit, 7)

    def test_reflect_rounds_prefers_top_level_for_backward_compatibility(self):
        runtime_config = {
            "max_reflect_rounds": 2,
            "dr_config": {
                "max_reflect_rounds": 4,
            },
        }
        self.assertEqual(resolve_dr_max_reflect_rounds(runtime_config), 2)

    def test_reflect_rounds_accepts_nested_when_top_level_missing(self):
        runtime_config = {
            "dr_config": {
                "max_reflect_rounds": 4,
            }
        }
        self.assertEqual(resolve_dr_max_reflect_rounds(runtime_config), 4)

    def test_reflect_rounds_invalid_value_falls_back_and_clamps(self):
        self.assertEqual(resolve_dr_max_reflect_rounds({"max_reflect_rounds": "oops"}), 5)
        self.assertEqual(resolve_dr_max_reflect_rounds({"max_reflect_rounds": 0}), 1)
        self.assertEqual(resolve_dr_max_reflect_rounds({"max_reflect_rounds": 9}), 5)
