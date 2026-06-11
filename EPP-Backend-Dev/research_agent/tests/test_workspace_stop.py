from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.llm_client import LLMCallResult
from research_agent.models import ResearchSession, WorkspaceAgentRun
from research_agent.pipelines.workspace.pipeline import (
    _normalize_workspace_decision,
    execute_workspace_pipeline,
)


class WorkspaceDecisionNormalizeTests(TestCase):
    def test_empty_tool_calls_coerces_finished(self):
        finished, msg, tools, note = _normalize_workspace_decision(
            {"finished": False, "assistant_message": "任务完成", "tool_calls": []}
        )
        self.assertTrue(finished)
        self.assertEqual(msg, "任务完成")
        self.assertEqual(tools, [])
        self.assertEqual(note, "empty_tool_calls")

    def test_finished_clears_tool_calls(self):
        finished, _msg, tools, note = _normalize_workspace_decision(
            {
                "finished": True,
                "assistant_message": "ok",
                "tool_calls": [{"action": "ls", "args": {}}],
            }
        )
        self.assertTrue(finished)
        self.assertEqual(tools, [])
        self.assertEqual(note, "")

    def test_empty_tool_calls_without_message_gets_default(self):
        finished, msg, tools, note = _normalize_workspace_decision(
            {"finished": False, "assistant_message": "", "tool_calls": []}
        )
        self.assertTrue(finished)
        self.assertIn("未安排工具", msg)
        self.assertEqual(note, "empty_tool_calls")


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class WorkspacePipelineStopTests(TestCase):
    def test_pipeline_stops_in_one_turn_when_no_tool_calls(self):
        session = ResearchSession.objects.create(owner_id="u-ws-stop", title="t")
        run = WorkspaceAgentRun.objects.create(
            session=session,
            status="pending",
            steps=[],
            result_payload={"runtime_config": {"workspace_user_query_override": "测试停止"}},
        )
        with patch(
            "research_agent.pipelines.workspace.pipeline.chat_completion"
        ) as mock_llm:
            mock_llm.return_value = LLMCallResult(
                ok=True,
                content=(
                    '{"finished":false,"assistant_message":"无工具直接收尾",'
                    '"tool_calls":[]}'
                ),
                model="mock",
            )
            execute_workspace_pipeline(run.id)

        self.assertEqual(mock_llm.call_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertIn("无工具直接收尾", run.result_payload.get("body", ""))
