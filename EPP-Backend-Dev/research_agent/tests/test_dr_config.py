from django.test import SimpleTestCase

from research_agent.dr_config import (
    resolve_dr_max_reflect_rounds,
    resolve_dr_phase_llm_config,
)


class DRConfigTests(SimpleTestCase):
    def test_default_phase_configs_match_pipeline_behavior(self):
        plan_decide = resolve_dr_phase_llm_config({}, phase="plan_decide")
        analyze = resolve_dr_phase_llm_config({}, phase="analyze")
        reflect = resolve_dr_phase_llm_config({}, phase="reflect")
        write = resolve_dr_phase_llm_config({}, phase="write")

        self.assertEqual((plan_decide.temperature, plan_decide.max_tokens, plan_decide.enable_thinking, plan_decide.history_limit), (0.2, 4096, False, 2))
        self.assertEqual((analyze.temperature, analyze.max_tokens, analyze.enable_thinking, analyze.history_limit), (0.2, 6144, False, 2))
        self.assertEqual((reflect.temperature, reflect.max_tokens, reflect.enable_thinking, reflect.history_limit), (0.1, 6144, False, 2))
        self.assertEqual((write.temperature, write.max_tokens, write.enable_thinking, write.history_limit), (0.2, 6144, False, 2))

    def test_nested_dr_config_overrides_phase_params(self):
        runtime_config = {
            "dr_config": {
                "llm": {
                    "analyze": {
                        "temperature": "0.33",
                        "max_tokens": "1234",
                        "enable_thinking": "true",
                        "history_limit": "7",
                    }
                }
            }
        }
        analyze = resolve_dr_phase_llm_config(runtime_config, phase="analyze")
        self.assertEqual(analyze.temperature, 0.33)
        self.assertEqual(analyze.max_tokens, 1234)
        self.assertTrue(analyze.enable_thinking)
        self.assertEqual(analyze.history_limit, 7)

    def test_legacy_phase_keys_are_ignored(self):
        runtime_config = {
            "dr_config": {
                "llm": {
                    "plan": {"temperature": 0.35},
                    "decide": {"max_tokens": 3333},
                    "search": {"history_limit": 5},
                    "read": {"enable_thinking": True},
                }
            }
        }
        plan_decide = resolve_dr_phase_llm_config(runtime_config, phase="plan_decide")
        analyze = resolve_dr_phase_llm_config(runtime_config, phase="analyze")
        self.assertEqual((plan_decide.temperature, plan_decide.max_tokens), (0.2, 4096))
        self.assertEqual((analyze.history_limit, analyze.enable_thinking), (2, False))

    def test_unknown_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_dr_phase_llm_config({}, phase="search")

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
