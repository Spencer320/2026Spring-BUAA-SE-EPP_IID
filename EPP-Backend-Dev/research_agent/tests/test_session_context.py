"""会话上下文构建：多轮 messages 与 Markdown 摘要。"""

from django.test import TestCase

from research_agent.models import ResearchMessage, ResearchSession
from research_agent.pipelines.basic.session_context import (
    build_recent_turns_markdown,
    build_session_messages,
)


class SessionContextMessagesTests(TestCase):
    def setUp(self):
        self.session = ResearchSession.objects.create(owner_id="ctx-user", title="ctx")

    def _seed_turn(self, user: str, assistant: str, *, ack: bool = False) -> None:
        ResearchMessage.objects.create(session=self.session, role="user", content=user)
        if ack:
            ResearchMessage.objects.create(
                session=self.session,
                role="assistant",
                content="已收到请求，任务已启动。",
            )
        ResearchMessage.objects.create(session=self.session, role="assistant", content=assistant)

    def test_build_session_messages_includes_prior_turns(self):
        self._seed_turn("什么是 RAG？", "RAG 是检索增强生成。")
        ResearchMessage.objects.create(session=self.session, role="user", content="它有哪些优点？")

        messages = build_session_messages(
            self.session,
            system_prompt="sys",
            current_user_content="current prompt",
        )
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertIn("RAG", messages[1]["content"])
        self.assertIn("检索增强", messages[2]["content"])
        self.assertEqual(messages[3]["content"], "current prompt")

    def test_ack_stubs_excluded_from_messages(self):
        self._seed_turn("第一问", "第一答", ack=True)
        ResearchMessage.objects.create(session=self.session, role="user", content="第二问")

        messages = build_session_messages(
            self.session,
            system_prompt="sys",
            current_user_content="current",
        )
        contents = " ".join(m["content"] for m in messages)
        self.assertNotIn("任务已启动", contents)

    def test_messages_respect_max_turns(self):
        for i in range(4):
            self._seed_turn(f"问{i}", f"答{i}")
        ResearchMessage.objects.create(session=self.session, role="user", content="当前")

        messages = build_session_messages(
            self.session,
            system_prompt="sys",
            current_user_content="current",
            max_turns=3,
        )
        user_msgs = [m for m in messages if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 4)
        self.assertNotIn("问0", user_msgs[0]["content"])
        self.assertIn("问1", user_msgs[0]["content"])

    def test_markdown_and_messages_share_same_turn_extraction(self):
        self._seed_turn("主题 A", "回复 A")
        ResearchMessage.objects.create(session=self.session, role="user", content="主题 B")

        md = build_recent_turns_markdown(self.session)
        messages = build_session_messages(
            self.session,
            system_prompt="sys",
            current_user_content="x",
        )
        self.assertIn("主题 A", md)
        self.assertIn("回复 A", md)
        self.assertIn("主题 A", messages[1]["content"])
        self.assertIn("回复 A", messages[2]["content"])
