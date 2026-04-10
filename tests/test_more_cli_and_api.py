import io
import json
import tarfile
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.host as host
from agent_side.server import AgentServerHandler


class FakeCleanupServerState:
    def __init__(self):
        self.files = {
            "root.txt": b"root",
            "nested/info.txt": b"nested",
        }


class FakeSnapshotPruneHandler(BaseHTTPRequestHandler):
    state = None
    status_code = 200

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/status":
            self._send_json(self.status_code, {
                "agent_id": "fake",
                "delivery": "sync",
                "adapter": "pi-agent",
                "model": "MiniMax-M2.7",
                "uptime": 10,
                "running": True,
                "ready": True,
            })
            return
        if path in ("/files", "/files/", "/files/."):
            entries = [
                {"name": "nested", "type": "directory"},
                {"name": "root.txt", "type": "file"},
            ]
            self._send_json(200, {"path": ".", "entries": entries})
            return
        if path == "/files/nested/":
            self._send_json(200, {"path": "nested/", "entries": [{"name": "info.txt", "type": "file"}]})
            return
        if path.startswith("/files/"):
            rel = path.removeprefix("/files/")
            if rel in self.state.files:
                data = self.state.files[rel]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


class HostCleanupSnapshotPruneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.conv_patch = patch.object(host, "CONV_BASE", self.base / "conversations")
        self.reg_patch = patch.object(host, "DEFAULT_REGISTRY", self.base / "agents.json")
        self.host_base_patch = patch.object(host, "HOST_BASE", self.base / ".agentia")
        self.conv_patch.start()
        self.reg_patch.start()
        self.host_base_patch.start()

    def tearDown(self):
        self.conv_patch.stop()
        self.reg_patch.stop()
        self.host_base_patch.stop()
        self.tmp.cleanup()

    def _capture(self, fn, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*args, **kwargs)
        return rc, buf.getvalue()

    def test_clean_audit_and_apply_safe(self):
        base = host._host_base()
        (base / "containers" / "empty-one").mkdir(parents=True)
        (base / "inbox").mkdir(parents=True)
        (base / "inbox" / "zero.jsonl").write_text("")

        rc, out = self._capture(host.cmd_clean, apply=False, safe=False, audit=True)
        self.assertEqual(rc, 0)
        self.assertIn("empty container dirs", out)
        self.assertIn("zero-byte inbox files", out)

        rc, out = self._capture(host.cmd_clean, apply=True, safe=True, audit=False)
        self.assertEqual(rc, 0)
        self.assertIn("Safe cleanup complete", out)
        self.assertFalse((base / "containers" / "empty-one").exists())
        self.assertFalse((base / "inbox" / "zero.jsonl").exists())

    def test_prune_removes_unreachable_agents(self):
        registry = {
            "version": 1,
            "agents": {
                "bad": {"url": "http://127.0.0.1:9", "name": "bad", "metadata": {}},
            },
        }
        host._save_registry(registry)
        rc, out = self._capture(host.cmd_prune)
        self.assertEqual(rc, 0)
        self.assertIn("unreachable", out)
        self.assertEqual(host._load_registry()["agents"], {})

    def test_snapshot_downloads_files_to_tarball(self):
        FakeSnapshotPruneHandler.state = FakeCleanupServerState()
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSnapshotPruneHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            host.cmd_register(url, "snap", None)
            out_path = self.base / "snap.tar.gz"
            rc, out = self._capture(host.cmd_snapshot, "snap", str(out_path))
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            with tarfile.open(out_path, "r:gz") as tar:
                names = tar.getnames()
            self.assertIn("snap/root.txt", names)
            self.assertIn("snap/nested/info.txt", names)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class DummyHarness:
    def __init__(self, workspace):
        self.config = type("Cfg", (), {"adapter_workspace": str(workspace)})()


class FilesHandlerPathTraversalTest(unittest.TestCase):
    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            outside = workspace.parent / "outside.txt"
            outside.write_text("secret")

            handler = AgentServerHandler.__new__(AgentServerHandler)
            handler._harness = DummyHarness(workspace)
            captured = {}
            handler._send_json = lambda status, data: captured.update({"status": status, "data": data})

            AgentServerHandler._handle_files(handler, "../outside.txt", "GET")
            self.assertEqual(captured["status"], 403)
            self.assertEqual(captured["data"]["error"], "forbidden")


if __name__ == "__main__":
    unittest.main()
