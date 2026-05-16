import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from research_agent.tools.local_file_executor import execute_local_file_action


class _FileHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(b"hello-file")

    def log_message(self, _fmt, *_args):
        pass


class LocalFileExecutorTests(TestCase):
    @override_settings(
        RA_LOCAL_FILE_ALLOWED_ACTIONS=["download_file_to_dir"],
        RA_LOCAL_FILE_ALLOWED_TARGET_DIRS={"workspace_downloads": "/tmp"},
    )
    def test_non_whitelisted_action_requires_confirmation(self):
        res = execute_local_file_action(
            action="delete_file",
            args={"path": "/tmp/a"},
            risk_confirmation_strategy="on_high_risk",
        )
        self.assertFalse(res.ok)
        self.assertTrue(res.requires_confirmation)
        self.assertEqual(res.error_code, "LOCAL_FILE_CONFIRM_REQUIRED")

    def test_download_success(self):
        with TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), _FileHandler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
            self.addCleanup(lambda: t.join(timeout=2))

            with override_settings(
                RA_ALLOWED_HOSTS=["127.0.0.1"],
                RA_LOCAL_FILE_ALLOWED_HOSTS=[],
                RA_LOCAL_FILE_ALLOWED_ACTIONS=["download_file_to_dir"],
                RA_LOCAL_FILE_ALLOWED_TARGET_DIRS={"workspace_downloads": tmpdir},
            ):
                res = execute_local_file_action(
                    action="download_file_to_dir",
                    args={
                        "url": f"http://127.0.0.1:{port}/a.bin",
                        "target_dir_key": "workspace_downloads",
                        "filename": "sample.bin",
                    },
                    risk_confirmation_strategy="never",
                )
            self.assertTrue(res.ok)
            saved_path = Path(str(res.output["saved_path"]))
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), b"hello-file")

