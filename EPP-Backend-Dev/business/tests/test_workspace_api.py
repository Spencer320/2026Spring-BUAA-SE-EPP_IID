import io
import json
import shutil
import zipfile

from django.test import Client, TestCase, override_settings

from business.tests.helper_user import insert_user, login_user
from business.utils.user_workspace import get_workspace_root


@override_settings(USER_WORKSPACE_PATH="/tmp/epp_workspace_api_tests")
class WorkspaceApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.username, self.password = insert_user()
        login_response = login_user(self.client, self.username, self.password)
        payload = json.loads(login_response.content.decode("utf-8"))
        self.headers = {"HTTP_AUTHORIZATION": payload["token"]}
        from business.models import User

        self.user = User.objects.get(username=self.username)
        self.root = get_workspace_root(str(self.user.user_id))

    def _post(self, path: str, body: dict):
        return self.client.post(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **self.headers,
        )

    def _zip_bytes(self, members: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_copy_file_to_directory_success(self):
        src_dir = self.root / "docs"
        dst_dir = self.root / "backup"
        src_dir.mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")

        resp = self._post("/api/workspace/copy", {"src": "docs/a.txt", "dst": "backup"})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.content.decode("utf-8"))["data"]
        self.assertEqual(data["path"], "backup/a.txt")
        self.assertTrue((dst_dir / "a.txt").exists())
        self.assertEqual((dst_dir / "a.txt").read_text(encoding="utf-8"), "hello")

    def test_copy_directory_to_directory_success(self):
        src_dir = self.root / "folder"
        dst_dir = self.root / "backup"
        (src_dir / "nested").mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "nested" / "a.txt").write_text("data", encoding="utf-8")

        resp = self._post("/api/workspace/copy", {"src": "folder", "dst": "backup"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(json.loads(resp.content.decode("utf-8"))["data"]["path"], "backup/folder")
        self.assertTrue((dst_dir / "folder" / "nested" / "a.txt").exists())

    def test_move_file_to_directory_success(self):
        src_dir = self.root / "docs"
        dst_dir = self.root / "archive"
        src_dir.mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "move.txt").write_text("mv", encoding="utf-8")

        resp = self._post("/api/workspace/move", {"src": "docs/move.txt", "dst": "archive"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(json.loads(resp.content.decode("utf-8"))["data"]["path"], "archive/move.txt")
        self.assertFalse((src_dir / "move.txt").exists())
        self.assertTrue((dst_dir / "move.txt").exists())

    def test_move_directory_to_directory_success(self):
        src_dir = self.root / "folder"
        dst_dir = self.root / "archive"
        (src_dir / "nested").mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "nested" / "a.txt").write_text("ok", encoding="utf-8")

        resp = self._post("/api/workspace/move", {"src": "folder", "dst": "archive"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(json.loads(resp.content.decode("utf-8"))["data"]["path"], "archive/folder")
        self.assertFalse(src_dir.exists())
        self.assertTrue((dst_dir / "folder" / "nested" / "a.txt").exists())

    def test_copy_conflict_returns_409(self):
        src_dir = self.root / "docs"
        dst_dir = self.root / "backup"
        src_dir.mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")
        (dst_dir / "a.txt").write_text("existing", encoding="utf-8")

        resp = self._post("/api/workspace/copy", {"src": "docs/a.txt", "dst": "backup"})
        self.assertEqual(resp.status_code, 409)

    def test_move_conflict_returns_409(self):
        src_dir = self.root / "docs"
        dst_dir = self.root / "backup"
        src_dir.mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")
        (dst_dir / "a.txt").write_text("existing", encoding="utf-8")

        resp = self._post("/api/workspace/move", {"src": "docs/a.txt", "dst": "backup"})
        self.assertEqual(resp.status_code, 409)
        self.assertTrue((src_dir / "a.txt").exists())

    def test_move_directory_into_own_child_rejected(self):
        src_dir = self.root / "folder"
        (src_dir / "child").mkdir(parents=True, exist_ok=True)

        resp = self._post("/api/workspace/move", {"src": "folder", "dst": "folder/child"})
        self.assertEqual(resp.status_code, 409)

    def test_copy_path_traversal_forbidden(self):
        src_dir = self.root / "docs"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")

        resp = self._post("/api/workspace/copy", {"src": "docs/a.txt", "dst": "../evil"})
        self.assertEqual(resp.status_code, 403)

    def test_copy_source_not_found(self):
        resp = self._post("/api/workspace/copy", {"src": "missing.txt", "dst": "backup"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_empty_directory_success(self):
        empty_dir = self.root / "empty"
        empty_dir.mkdir(parents=True, exist_ok=True)

        resp = self.client.delete("/api/workspace/files/empty", **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(empty_dir.exists())

    def test_delete_non_empty_directory_rejected(self):
        non_empty_dir = self.root / "non-empty"
        non_empty_dir.mkdir(parents=True, exist_ok=True)
        (non_empty_dir / "a.txt").write_text("hello", encoding="utf-8")

        resp = self.client.delete("/api/workspace/files/non-empty", **self.headers)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(non_empty_dir.exists())

    def test_extract_zip_success(self):
        archive = self.root / "sample.zip"
        archive.write_bytes(self._zip_bytes({"notes/a.txt": b"hello", "b.txt": b"world"}))

        resp = self._post("/api/workspace/extract", {"path": "sample.zip"})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.content.decode("utf-8"))["data"]
        self.assertEqual(data["path"], ".")
        self.assertEqual(data["extracted_count"], 2)
        self.assertTrue((self.root / "notes" / "a.txt").exists())
        self.assertTrue((self.root / "b.txt").exists())

    def test_extract_non_zip_rejected(self):
        archive = self.root / "sample.txt"
        archive.write_text("not zip", encoding="utf-8")

        resp = self._post("/api/workspace/extract", {"path": "sample.txt"})
        self.assertEqual(resp.status_code, 400)

    def test_extract_unsafe_member_rejected(self):
        archive = self.root / "bad.zip"
        archive.write_bytes(self._zip_bytes({"../escape.txt": b"boom"}))

        resp = self._post("/api/workspace/extract", {"path": "bad.zip"})
        self.assertEqual(resp.status_code, 400)

    @override_settings(RA_WORKSPACE_MAX_TEXT_BYTES=1)
    def test_extract_too_large_member_rejected(self):
        archive = self.root / "large.zip"
        archive.write_bytes(self._zip_bytes({"big.txt": b"1234567890" * 10}))

        resp = self._post("/api/workspace/extract", {"path": "large.zip"})
        self.assertEqual(resp.status_code, 400)

    def tearDown(self):
        if self.root.exists():
            for child in self.root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
