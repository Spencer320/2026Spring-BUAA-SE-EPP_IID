from unittest.mock import patch

from django.test import TestCase, override_settings

from research_agent.llm_client import LLMCallResult
from research_agent.models import ResearchSession, WorkspaceAgentRun
from research_agent.pipelines.workspace.pipeline import execute_workspace_pipeline


@override_settings(RESEARCH_AGENT_MOCK_DELAY=0)
class WorkspacePipelineCancelTests(TestCase):
    def test_pipeline_keeps_cancelled_status_after_llm_returns(self):
        session = ResearchSession.objects.create(owner_id="u-ws-cancel", title="t")
        run = WorkspaceAgentRun.objects.create(
            session=session,
            status="pending",
            steps=[],
            result_payload={"runtime_config": {"workspace_user_query_override": "cancel test"}},
        )

        def cancel_during_llm(**_kwargs):
            WorkspaceAgentRun.objects.filter(id=run.id).update(status="cancelled")
            return LLMCallResult(
                ok=True,
                content='{"finished":true,"assistant_message":"should not write back","tool_calls":[]}',
                model="mock",
            )

        with patch("research_agent.pipelines.workspace.pipeline.chat_completion", side_effect=cancel_during_llm):
            execute_workspace_pipeline(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        payload = run.result_payload if isinstance(run.result_payload, dict) else {}
        self.assertNotEqual(payload.get("body"), "should not write back")
