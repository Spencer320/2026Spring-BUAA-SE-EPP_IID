import tempfile
import zipfile
from pathlib import Path

from django.test import TestCase, override_settings

from business.utils.user_workspace import get_workspace_root
from research_agent.tools.router import route_tool_call
from research_agent.tools.workspace_executor import execute_workspace_action


class WorkspaceExecutorTests(TestCase):
    def test_basic_text_write_read_and_find(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            user_id = "workspace-user"
            write = execute_workspace_action(
                user_id=user_id,
                action="write_text",
                args={"path": "notes/report.md", "content": "hello workspace"},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(write.ok)

            read = execute_workspace_action(
                user_id=user_id,
                action="read_text",
                args={"path": "notes/report.md"},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(read.ok)
            self.assertEqual(read.output["content"], "hello workspace")

            found = execute_workspace_action(
                user_id=user_id,
                action="find_files",
                args={"path": "notes", "glob": "*.md"},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(found.ok)
            self.assertEqual(found.output["count"], 1)

    def test_path_traversal_is_denied(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            res = execute_workspace_action(
                user_id="workspace-user",
                action="read_text",
                args={"path": "../secret.txt"},
                risk_confirmation_strategy="never",
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "WORKSPACE_PATH_DENIED")

    def test_replace_text_defaults_to_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            user_id = "workspace-user"
            root = get_workspace_root(user_id)
            (root / "a.txt").write_text("foo foo", encoding="utf-8")

            preview = execute_workspace_action(
                user_id=user_id,
                action="replace_text",
                args={"path": "", "glob": "*.txt", "old": "foo", "new": "bar"},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(preview.ok)
            self.assertTrue(preview.output["dry_run"])
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "foo foo")

            replaced = execute_workspace_action(
                user_id=user_id,
                action="replace_text",
                args={"path": "", "glob": "*.txt", "old": "foo", "new": "bar", "dry_run": False},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(replaced.ok)
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "bar bar")

    def test_high_risk_action_no_longer_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            user_id = "workspace-user"
            root = get_workspace_root(user_id)
            (root / "a.txt").write_text("delete me", encoding="utf-8")
            res = execute_workspace_action(
                user_id=user_id,
                action="delete_path",
                args={"path": "a.txt"},
                risk_confirmation_strategy="on_high_risk",
            )
            self.assertTrue(res.ok)
            self.assertFalse(res.requires_confirmation)
            self.assertFalse((root / "a.txt").exists())

    def test_archive_zip_plugin(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            user_id = "workspace-user"
            root = get_workspace_root(user_id)
            (root / "papers").mkdir()
            (root / "papers" / "note.txt").write_text("zip me", encoding="utf-8")

            res = execute_workspace_action(
                user_id=user_id,
                action="archive_zip",
                args={"path": "papers", "output": "papers.zip"},
                risk_confirmation_strategy="never",
            )
            self.assertTrue(res.ok)
            archive = root / "papers.zip"
            self.assertTrue(archive.exists())
            with zipfile.ZipFile(archive) as zf:
                self.assertIn("papers/note.txt", zf.namelist())

    def test_router_passes_user_id_to_workspace_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(USER_WORKSPACE_PATH=tmpdir):
            res = route_tool_call(
                tool_name="workspace",
                args={"action": "write_text", "args": {"path": "x.txt", "content": "ok"}},
                risk_confirmation_strategy="never",
                user_id="workspace-user",
            )
            self.assertTrue(res.ok)
            self.assertTrue((Path(tmpdir) / "workspace-user" / "x.txt").exists())
