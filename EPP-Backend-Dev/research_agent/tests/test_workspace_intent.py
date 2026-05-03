from django.test import SimpleTestCase
from unittest.mock import patch

from research_agent.llm_client import LLMCallResult

from research_agent.workspace_intent import detect_workspace_plan


class WorkspaceIntentTests(SimpleTestCase):
    def test_detect_list_files(self):
        plan = detect_workspace_plan("查看目录 papers 下的文件")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "list_files")
        self.assertEqual(plan["steps"][0]["args"]["path"], "papers")

    def test_detect_archive_zip(self):
        plan = detect_workspace_plan("压缩 papers 为 papers.zip")
        self.assertIsNotNone(plan)
        step = plan["steps"][0]
        self.assertEqual(step["action"], "archive_zip")
        self.assertEqual(step["args"]["path"], "papers")
        self.assertEqual(step["args"]["output"], "papers.zip")

    def test_detect_replace_text(self):
        plan = detect_workspace_plan("把目录 notes 中 txt 文件里的“foo”替换为“bar”")
        self.assertIsNotNone(plan)
        self.assertEqual([step["action"] for step in plan["steps"]], ["find_files", "replace_text"])
        self.assertEqual(plan["steps"][1]["args"]["old"], "foo")
        self.assertEqual(plan["steps"][1]["args"]["new"], "bar")

    def test_detect_create_file_with_intro_text(self):
        plan = detect_workspace_plan("新建一个文件，名为xxx.md，写入一段介绍yyy的文本")
        self.assertIsNotNone(plan)
        step = plan["steps"][0]
        self.assertEqual(step["action"], "write_text")
        self.assertEqual(step["args"]["path"], "xxx.md")
        self.assertIn("yyy", step["args"]["content"])

    def test_non_workspace_request_returns_none(self):
        self.assertIsNone(detect_workspace_plan("请调研大模型多智能体系统的发展趋势"))

    @patch("research_agent.workspace_intent.chat_completion")
    def test_llm_fallback_detects_workspace_plan(self, mock_chat):
        mock_chat.return_value = LLMCallResult(
            ok=True,
            content='{"is_workspace":true,"confidence":0.9,"reason":"文件操作","plan":{"steps":[{"tool":"workspace","action":"list_files","args":{"path":"papers"}}]}}',
            model="mock",
        )
        plan = detect_workspace_plan("帮我看看 papers 里面有什么", use_llm=True)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "list_files")
        self.assertEqual(plan["steps"][0]["args"]["path"], "papers")

    @patch("research_agent.workspace_intent.chat_completion")
    def test_llm_fallback_rejects_non_workspace(self, mock_chat):
        mock_chat.return_value = LLMCallResult(
            ok=True,
            content='{"is_workspace":false,"confidence":0.95,"reason":"研究请求","plan":{"steps":[]}}',
            model="mock",
        )
        self.assertIsNone(detect_workspace_plan("分析多智能体科研助手的研究进展", use_llm=True))
