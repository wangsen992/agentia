import io
import json
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.host as host


class FakeAgentState:
    def __init__(self):
        self.config = {
            "delivery": "sync",
            "adapter_type": "pi-agent",
            "adapter_model": "MiniMax-M2.7",
            "role_goal": "initial",
        }
        self.sessions = {
            "2026-04-10T15-00-00_default": {
                "name": "2026-04-10T15-00-00_default",
                "title": "default",
                "status": "running",
                "message_count": 2,
                "context_pct": 10,
                "last_active": "2026-04-10T15:00:00Z",
            }
        }
        self.files = {"AGENTS.md": b"hello world"}


class FakeAgentHandler(BaseHTTPRequestHandler):
    state = None

    def _read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

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
            self._send_json(200, {
                "agent_id": "fake-agent",
                "delivery": self.state.config["delivery"],
                "adapter": self.state.config["adapter_type"],
                "model": self.state.config["adapter_model"],
                "uptime": 120,
                "running": True,
                "ready": True,
            })
            return

        if path == "/sessions":
            self._send_json(200, list(self.state.sessions.values()))
            return

        if path == "/files/" or path == "/files" or path == "/files/.":
            entries = [{"name": name, "type": "file"} for name in sorted(self.state.files)]
            self._send_json(200, {"path": ".", "entries": entries})
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
            return

        self._send_json(404, {"error": "not found"})

    def do_PATCH(self):
        if self.path == "/config":
            patch_data = self._read_json()
            self.state.config.update(patch_data)
            self._send_json(200, self.state.config)
            return
        self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        if self.path.startswith("/files/"):
            rel = self.path.removeprefix("/files/")
            existed = rel in self.state.files
            n = int(self.headers.get("Content-Length", "0"))
            self.state.files[rel] = self.rfile.read(n)
            self._send_json(200 if existed else 201, {"path": rel})
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/sessions/"):
            name = path.removeprefix("/sessions/")
            self.state.sessions.pop(name, None)
            self._send_json(200, {"name": name, "deleted": True})
            return
        if path.startswith("/files/"):
            rel = path.removeprefix("/files/")
            self.state.files.pop(rel, None)
            self._send_json(200, {"deleted": rel})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path
        if path == "/sessions/new":
            data = self._read_json()
            title = data.get("name") or data.get("title") or "default"
            name = f"2026-04-10T15-20-00_{title}"
            self.state.sessions[name] = {
                "name": name,
                "title": title,
                "status": "running",
                "message_count": 0,
                "context_pct": 0,
                "last_active": "2026-04-10T15:20:00Z",
            }
            self._send_json(200, {
                "name": name,
                "title": title,
                "status": "running",
                "session_file": f"{name}.jsonl",
                "resumed": False,
            })
            return

        if path.startswith("/sessions/") and path.endswith("/message"):
            session_name = path.split("/sessions/")[1].rsplit("/message", 1)[0]
            if session_name not in self.state.sessions:
                self._send_json(404, {"error": f"session not found: {session_name}"})
                return
            self.state.sessions[session_name]["message_count"] += 1
            self._send_json(200, {
                "response": f"echo:{session_name}",
                "message_count": self.state.sessions[session_name]["message_count"],
                "context_pct": self.state.sessions[session_name]["context_pct"],
            })
            return

        if path.startswith("/sessions/") and path.endswith("/compact"):
            session_name = path.split("/sessions/")[1].rsplit("/compact", 1)[0]
            self._send_json(200, {
                "status": "compacted",
                "message_count_before": 5,
                "message_count_after": 3,
                "context_pct": 15,
            })
            return

        if path == "/message":
            self._send_json(200, {"response": "legacy"})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


class HostCliE2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.conv_patch = patch.object(host, "CONV_BASE", self.base / "conversations")
        self.reg_patch = patch.object(host, "DEFAULT_REGISTRY", self.base / "agents.json")
        self.conv_patch.start()
        self.reg_patch.start()

        FakeAgentHandler.state = FakeAgentState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgentHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.conv_patch.stop()
        self.reg_patch.stop()
        self.tmp.cleanup()

    def _capture(self, fn, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*args, **kwargs)
        return rc, buf.getvalue()

    def test_register_and_agents_and_status(self):
        rc, out = self._capture(host.cmd_register, self.url, "fake", None)
        self.assertEqual(rc, 0)
        self.assertIn("Registered 'fake'", out)

        rc, out = self._capture(host.cmd_agents)
        self.assertEqual(rc, 0)
        self.assertIn("fake", out)
        self.assertIn(self.url, out)

        rc, out = self._capture(host.cmd_status, "fake")
        self.assertEqual(rc, 0)
        self.assertIn("model:", out)
        self.assertIn("MiniMax-M2.7", out)

    def test_configure_and_sessions(self):
        host.cmd_register(self.url, "fake", None)

        rc, out = self._capture(host.cmd_configure, "fake", "role.goal", "hello")
        self.assertEqual(rc, 0)
        self.assertIn("Updated fake.role.goal", out)

        rc, out = self._capture(host.cmd_sessions_list, "fake")
        self.assertEqual(rc, 0)
        self.assertIn("default", out)

    def test_send_explicit_conv_and_compact_and_session_delete(self):
        host.cmd_register(self.url, "fake", None)

        rc, out = self._capture(host.cmd_send, "fake", "hello there", conv="hawaii", new_conv=False)
        self.assertEqual(rc, 0)
        self.assertIn("echo:2026-04-10T15-20-00_hawaii", out)

        rc, out = self._capture(host.cmd_compact, "fake", "2026-04-10T15-20-00_hawaii")
        self.assertEqual(rc, 0)
        self.assertIn("Compacted", out)

        rc, out = self._capture(host.cmd_session_delete, "fake", "2026-04-10T15-20-00_hawaii", False)
        self.assertEqual(rc, 0)
        self.assertIn("Deleted", out)

    def test_files_roundtrip(self):
        host.cmd_register(self.url, "fake", None)

        rc, out = self._capture(host.cmd_files, "fake", "ls", ".", None)
        self.assertEqual(rc, 0)
        self.assertIn("AGENTS.md", out)

        rc, out = self._capture(host.cmd_files, "fake", "get", "AGENTS.md", None)
        self.assertEqual(rc, 0)
        self.assertIn("hello world", out)

        rc, out = self._capture(host.cmd_files, "fake", "put", "notes.md", "sample")
        self.assertEqual(rc, 0)
        self.assertIn("Written: notes.md", out)

        rc, out = self._capture(host.cmd_files, "fake", "delete", "notes.md", None)
        self.assertEqual(rc, 0)
        self.assertIn("Deleted: notes.md", out)


if __name__ == "__main__":
    unittest.main()
