import io
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime.server import AgentServerHandler
from agent_runtime.config import AgentServerConfig


class FakeDelivery:
    def __init__(self):
        self.messages = [{"id": "m1", "content": "hi"}]
        self.appended = []

    def read_inbox(self):
        return self.messages

    def append_message(self, message):
        self.appended.append(message)


class FakeHarnessInner:
    def __init__(self):
        self._running = True
        self._delivery = FakeDelivery()
        self.config = None
        self.restarted = False

    def get_status(self):
        return {
            "agent_id": "fake-agent",
            "delivery": "sync",
            "adapter": "pi-agent",
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "uptime": 5,
            "running": True,
        }

    def restart_agent(self):
        self.restarted = True

    def process_message_sync(self, content, correlation_id):
        return {"response": f"sync:{content}", "correlation_id": correlation_id}


class FakeConfigManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def update(self, patch):
        for k, v in patch.items():
            setattr(self.cfg, k, v)
        return self.cfg

    def replace(self, config):
        self.cfg = config
        return config


class FakeSessionManager:
    def __init__(self):
        self.sessions = {
            "s1": {
                "name": "s1",
                "title": "default",
                "status": "running",
                "message_count": 1,
                "context_pct": 10,
                "last_active": "2026-04-10T00:00:00Z",
            }
        }
        self.send_error = None
        self.compact_error = None

    def list_sessions(self):
        return list(self.sessions.values())

    def get_session(self, name):
        return self.sessions.get(name)

    def new_session(self, name=None, title=None):
        actual = name or title or "default"
        self.sessions[actual] = {
            "name": actual,
            "title": title or name or "default",
            "status": "running",
            "message_count": 0,
            "context_pct": 0,
            "last_active": "2026-04-10T00:00:00Z",
        }
        return self.sessions[actual]

    def send_message(self, name, content):
        if self.send_error:
            return self.send_error
        return {"response": f"session:{name}:{content}", "message_count": 2, "context_pct": 11}

    def compact(self, name, message=""):
        if self.compact_error:
            return self.compact_error
        return {"status": "compacted", "message_count_before": 3, "message_count_after": 1, "context_pct": 15}

    def delete_session(self, name, hard=False):
        if name not in self.sessions:
            return {"error": f"session not found: {name}"}
        del self.sessions[name]
        return {"name": name, "deleted": True, "hard": hard}


class FakeOuterHarness:
    def __init__(self, workspace, delivery="sync"):
        self.config = AgentServerConfig(
            adapter_workspace=str(workspace),
            delivery=delivery,
            inbox_dir=str(Path(workspace) / "inbox"),
            responses_dir=str(Path(workspace) / "inbox" / "responses"),
        )
        self.config_manager = FakeConfigManager(self.config)
        self._harness = FakeHarnessInner()
        self._harness.config = self.config
        self._session_manager = FakeSessionManager()
        self.agent_id = "fake-agent"
        self._start_time = 0.0


class AgentServerMoreTest(unittest.TestCase):
    def make_handler(self, path="/status", method="GET", body=None, workspace=None, delivery="sync"):
        workspace = workspace or tempfile.mkdtemp()
        handler = AgentServerHandler.__new__(AgentServerHandler)
        handler.path = path
        handler.command = method
        handler.headers = {"Content-Length": str(len(body) if body else 0)}
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        handler._harness = FakeOuterHarness(workspace, delivery=delivery)
        handler._status = None
        handler._headers = []
        handler.send_response = lambda code: setattr(handler, "_status", code)
        handler.send_header = lambda k, v: handler._headers.append((k, v))
        handler.end_headers = lambda: None
        return handler

    def read_json(self, handler):
        handler.wfile.seek(0)
        raw = handler.wfile.read().decode()
        return json.loads(raw) if raw else None

    def test_get_config(self):
        h = self.make_handler("/config")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertEqual(body["delivery"], "sync")

    def test_put_config(self):
        cfg = {
            "host": "0.0.0.0",
            "port": 9999,
            "delivery": "inbox",
            "adapter_workspace": "/tmp/ws",
        }
        h = self.make_handler("/config", method="PUT", body=json.dumps(cfg).encode())
        AgentServerHandler.do_PUT(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertEqual(body["delivery"], "inbox")
        self.assertEqual(body["port"], 9999)

    def test_get_metrics(self):
        h = self.make_handler("/metrics")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertEqual(body["agent_id"], "fake-agent")
        self.assertIn("uptime", body)

    def test_get_inbox(self):
        h = self.make_handler("/inbox")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertEqual(body["messages"][0]["id"], "m1")

    def test_post_message_sync(self):
        h = self.make_handler("/message", method="POST", body=json.dumps({"content": "hello"}).encode())
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertEqual(body["response"], "sync:hello")

    def test_post_message_async(self):
        h = self.make_handler("/message/async", method="POST", body=json.dumps({"content": "hello"}).encode(), delivery="inbox")
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertTrue(body["queued"])
        self.assertEqual(len(h._harness._harness._delivery.appended), 1)

    def test_get_async_response_not_found(self):
        h = self.make_handler("/response/abc")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 404)

    def test_get_async_response_found(self):
        with tempfile.TemporaryDirectory() as td:
            h = self.make_handler("/response/abc", workspace=td)
            resp_dir = Path(h._harness.config.responses_dir)
            resp_dir.mkdir(parents=True, exist_ok=True)
            (resp_dir / "abc.jsonl").write_text(json.dumps({"response": "done"}))
            AgentServerHandler.do_GET(h)
            self.assertEqual(h._status, 200)
            body = self.read_json(h)
            self.assertEqual(body["response"], "done")

    def test_get_session_not_found(self):
        h = self.make_handler("/sessions/missing")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 404)

    def test_post_session_message_not_found_maps_404(self):
        h = self.make_handler("/sessions/missing/message", method="POST", body=json.dumps({"content": "x"}).encode())
        h._harness._session_manager.send_error = {"error": "session not found: missing"}
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 404)

    def test_post_session_message_not_running_maps_409(self):
        h = self.make_handler("/sessions/s1/message", method="POST", body=json.dumps({"content": "x"}).encode())
        h._harness._session_manager.send_error = {"error": "session not running: s1"}
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 409)

    def test_post_session_compact_error_maps_400(self):
        h = self.make_handler("/sessions/s1/compact", method="POST", body=json.dumps({"message": "m"}).encode())
        h._harness._session_manager.compact_error = {"error": "session not found: s1"}
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 400)

    def test_delete_session_hard_true(self):
        h = self.make_handler("/sessions/s1?hard=true", method="DELETE")
        AgentServerHandler.do_DELETE(h)
        self.assertEqual(h._status, 200)
        body = self.read_json(h)
        self.assertTrue(body["hard"])


if __name__ == "__main__":
    unittest.main()
