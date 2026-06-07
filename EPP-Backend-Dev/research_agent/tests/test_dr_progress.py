from types import SimpleNamespace

from django.test import SimpleTestCase

from research_agent.pipelines.deep.progress import (
    deep_research_progress_percent,
    persist_dr_progress_plan,
)


def _task(**kwargs):
    return SimpleNamespace(
        status=kwargs.get("status", "running"),
        step_seq=kwargs.get("step_seq", 0),
        steps=kwargs.get("steps", []),
        result_payload=kwargs.get("result_payload", {}),
    )


class DeepResearchProgressTests(SimpleTestCase):
    def test_before_plan_is_zero(self):
        task = _task(status="running", steps=[])
        self.assertEqual(deep_research_progress_percent(task), 0)

    def test_after_plan_conservative_with_two_subtasks(self):
        task = _task(
            steps=[
                {"phase": "plan_decide", "title": "规划与决策", "detail": ""},
            ],
            result_payload={
                "dr_progress": {
                    "subtask_count": 2,
                    "subtask_ids": ["s1", "s2"],
                    "max_reflect_rounds": 3,
                }
            },
        )
        # plan=1, total=1+2*3*2+1=14 → 7%
        self.assertEqual(deep_research_progress_percent(task), 7)

    def test_one_completed_reflect_round(self):
        task = _task(
            steps=[
                {"phase": "plan_decide", "title": "规划与决策", "detail": ""},
                {
                    "phase": "reflect",
                    "title": "反思子任务：文献综述",
                    "detail": "轮次：1",
                },
            ],
            result_payload={
                "dr_progress": {
                    "subtask_count": 1,
                    "subtask_ids": ["s1"],
                    "max_reflect_rounds": 3,
                }
            },
        )
        # completed=1+2=3, total=1+1*3*2+1=8 → 37%
        self.assertEqual(deep_research_progress_percent(task), 37)

    def test_in_progress_analyze_does_not_advance(self):
        task = _task(
            steps=[
                {"phase": "plan_decide", "title": "规划与决策", "detail": ""},
                {
                    "phase": "analyze",
                    "title": "分析子任务：文献综述",
                    "detail": "轮次：1",
                },
            ],
            result_payload={
                "dr_progress": {
                    "subtask_count": 1,
                    "subtask_ids": ["s1"],
                    "max_reflect_rounds": 3,
                }
            },
        )
        # only plan done → 1/8 = 12%
        self.assertEqual(deep_research_progress_percent(task), 12)

    def test_write_step_increases_progress(self):
        task = _task(
            steps=[
                {"phase": "plan_decide", "title": "规划与决策", "detail": ""},
                {
                    "phase": "reflect",
                    "title": "反思子任务：A",
                    "detail": "轮次：1",
                },
                {"phase": "write", "title": "生成报告", "detail": ""},
            ],
            result_payload={
                "dr_progress": {
                    "subtask_count": 1,
                    "subtask_ids": ["s1"],
                    "max_reflect_rounds": 3,
                }
            },
        )
        # completed=1+2+1=4, total=8 → 50%
        self.assertEqual(deep_research_progress_percent(task), 50)

    def test_completed_returns_100(self):
        task = _task(status="completed", steps=[{"phase": "write", "title": "生成报告", "detail": ""}])
        self.assertEqual(deep_research_progress_percent(task), 100)

    def test_failed_keeps_partial_progress(self):
        task = _task(
            status="failed",
            steps=[{"phase": "plan_decide", "title": "规划与决策", "detail": ""}],
            result_payload={"dr_progress": {"subtask_count": 2, "max_reflect_rounds": 3}},
        )
        self.assertEqual(deep_research_progress_percent(task), 7)

    def test_persist_dr_progress_plan(self):
        task = _task()
        persist_dr_progress_plan(
            task,
            [{"subtask_id": "s1", "title": "A"}, {"subtask_id": "s2", "title": "B"}],
            max_reflect_rounds=2,
        )
        self.assertEqual(task.result_payload["dr_progress"]["subtask_count"], 2)
        self.assertEqual(task.result_payload["dr_progress"]["max_reflect_rounds"], 2)
