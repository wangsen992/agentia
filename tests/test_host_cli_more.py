import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.host as host


class FakeHostMoreState:
    def __init__(self):
        self.config = {
            "delivery": "sync",
            "adapter_type": "pi-agent",
            "adapter_model": "MiniMax-M2.7",
            "role_goal": "initial",
            "backstory": "",
            "skills": [],
        }


class FakeHostMoreHandler(BaseHTTPRequestHandler):
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
        if self.path == "/status":
            self._send_json(200, {
                "agent_id": "fake-agent",
                "delivery": self.state.config["delivery"],
                "adapter": self.state.config["adapter_type"],
                "model": self.state.config["adapter_model"],
                "uptime": 10,
                "running": True,
                "ready": True,
            })
            return
        if self.path == "/echo":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not found"})

    def do_PATCH(self):
        if self.path == "/config":
            data = self._read_json()
            self.state.config.update(data)
            self._send_json(200, self.state.config)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/echo":
            data = self._read_json()
            self._send_json(200, {"you_sent": data})
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/echo":
            self._send_json(200, {"deleted": True})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


class FakePromptSession:
    inputs = []

    def __init__(self, *args, **kwargs):
        self._idx = 0

    def prompt(self, *args, **kwargs):
        if self._idx >= len(self.inputs):
            raise EOFError
        value = self.inputs[self._idx]
        self._idx += 1
        return value


class HostCliMoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.conv_patch = patch.object(host, "CONV_BASE", self.base / "conversations")
        self.reg_patch = patch.object(host, "DEFAULT_REGISTRY", self.base / "agents.json")
        self.conv_patch.start()
        self.reg_patch.start()

        FakeHostMoreHandler.state = FakeHostMoreState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHostMoreHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        host.cmd_register(self.url, "fake", None)

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

    def test_update_patches_restartable_fields(self):
        rc, out = self._capture(host.cmd_update, "fake", "new goal", "new story", ["skill-a", "skill-b"])
        self.assertEqual(rc, 0)
        self.assertIn("triggered restart", out)
        self.assertEqual(FakeHostMoreHandler.state.config["role_goal"], "new goal")
        self.assertEqual(FakeHostMoreHandler.state.config["backstory"], "new story")
        self.assertEqual(FakeHostMoreHandler.state.config["skills"], ["skill-a", "skill-b"])
        self.assertTrue(FakeHostMoreHandler.state.config["_restart"])

    def test_forward_get_post_delete(self):
        rc, out = self._capture(host.cmd_forward, "fake", "GET", "/echo", None)
        self.assertEqual(rc, 0)
        self.assertIn("Status: 200", out)
        self.assertIn('"ok": true', out)

        rc, out = self._capture(host.cmd_forward, "fake", "POST", "/echo", '{"x":1}')
        self.assertEqual(rc, 0)
        self.assertIn('"x": 1', out)

        rc, out = self._capture(host.cmd_forward, "fake", "DELETE", "/echo", None)
        self.assertEqual(rc, 0)
        self.assertIn('"deleted": true', out)

    def test_forward_http_error_returns_nonzero(self):
        rc, out = self._capture(host.cmd_forward, "fake", "GET", "/missing", None)
        self.assertEqual(rc, 1)
        self.assertIn("HTTP 404", out)

    def test_send_no_text_error_returns_nonzero(self):
        with patch.object(host, "_smart_route", return_value={"error": "model blew up"}):
            rc, out = self._capture(host.cmd_send, "fake", "hello", None, False)
        self.assertEqual(rc, 1)
        self.assertIn("Agent error", out)

    def test_status_missing_agent_nonzero(self):
        rc, out = self._capture(host.cmd_status, "missing")
        self.assertEqual(rc, 1)
        self.assertIn("not found", out.lower())

    def test_chat_new_session_routes_following_message_to_new_session(self):
        FakePromptSession.inputs = ["/new session-2", "hello second session", "/quit"]
        calls = []

        def fake_post(name, path, data, timeout=10):
            if path == "/sessions/new":
                return {"name": "2026-04-11T16-20-00_session-2", "title": "session-2", "status": "running"}
            return None

        def fake_post_or_409(name, path, data, timeout=120):
            calls.append((path, data))
            if path == "/sessions/2026-04-11T16-20-00_session-2/message":
                return ({"response": "ok", "message_count": 1, "context_pct": 3}, False)
            return (None, False)

        with patch.object(host, "_from_ptk_imported", True), \
             patch.object(host, "PromptSession", FakePromptSession, create=True), \
             patch.object(host, "FileHistory", lambda *a, **k: None, create=True), \
             patch.object(host, "Style", SimpleNamespace(from_dict=lambda *a, **k: None), create=True), \
             patch.object(host, "clear", lambda: None, create=True), \
             patch.object(host, "_http_post", side_effect=fake_post), \
             patch.object(host, "_http_post_or_409", side_effect=fake_post_or_409), \
             patch.object(host, "_smart_route", return_value={"response": "wrong path"}) as smart_route:
            rc, out = self._capture(host.cmd_chat, "fake", None, False)

        self.assertEqual(rc, 0)
        self.assertIn("New conversation: 'session-2'", out)
        self.assertEqual(calls, [
            ("/sessions/2026-04-11T16-20-00_session-2/message", {"content": "hello second session"})
        ])
        smart_route.assert_not_called()

    def test_chat_new_without_title_generates_random_session_name(self):
        FakePromptSession.inputs = ["/new", "/quit"]
        seen = []

        def fake_post(name, path, data, timeout=10):
            if path == "/sessions/new":
                seen.append(data["name"])
                return {"name": f"2026-04-11T18-14-00_{data['name']}", "title": data["name"], "status": "running"}
            return None

        with patch.object(host, "_from_ptk_imported", True), \
             patch.object(host, "PromptSession", FakePromptSession, create=True), \
             patch.object(host, "FileHistory", lambda *a, **k: None, create=True), \
             patch.object(host, "Style", SimpleNamespace(from_dict=lambda *a, **k: None), create=True), \
             patch.object(host, "clear", lambda: None, create=True), \
             patch.object(host, "_http_post", side_effect=fake_post):
            rc, out = self._capture(host.cmd_chat, "fake", None, False)

        self.assertEqual(rc, 0)
        self.assertEqual(len(seen), 1)
        self.assertRegex(seen[0], r"^session-[a-z0-9]{8}$")
        self.assertIn(f"New conversation: '{seen[0]}'", out)


if __name__ == "__main__":
    unittest.main()
