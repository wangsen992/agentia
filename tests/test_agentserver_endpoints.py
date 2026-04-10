import io
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_side.server import AgentServerHandler


class FakeConfig:
    def __init__(self, workspace):
        self.adapter_workspace = str(workspace)
        self.host = "127.0.0.1"
        self.port = 8080
        self.delivery = "sync"
        self.responses_dir = str(Path(workspace) / "responses")
        self.poll_interval = 0.01
        self.agent_timeout = 30

    def to_dict(self):
        return {
            "adapter_workspace": self.adapter_workspace,
            "host": self.host,
            "port": self.port,
            "delivery": self.delivery,
        }


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


class FakeHarnessInner:
    def __init__(self):
        self._running = True
        self.restarted = False
        self.config = None

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
        return {"response": f"echo:{content}", "correlation_id": correlation_id}


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

    def list_sessions(self):
        return list(self.sessions.values())

    def get_session(self, name):
        return self.sessions.get(name)

    def new_session(self, name=None, title=None):
        session_name = name or title or "default"
        self.sessions[session_name] = {
            "name": session_name,
            "title": title or name or "default",
            "status": "running",
            "message_count": 0,
            "context_pct": 0,
            "last_active": "2026-04-10T00:00:00Z",
        }
        return self.sessions[session_name]

    def send_message(self, name, content):
        if name not in self.sessions:
            return {"error": f"session not found: {name}"}
        self.sessions[name]["message_count"] += 1
        return {
            "response": f"session:{name}:{content}",
            "message_count": self.sessions[name]["message_count"],
            "context_pct": self.sessions[name]["context_pct"],
        }

    def compact(self, name, message=""):
        if name not in self.sessions:
            return {"error": f"session not found: {name}"}
        return {"status": "compacted", "message_count_before": 3, "message_count_after": 1, "context_pct": 15}

    def delete_session(self, name, hard=False):
        if name not in self.sessions:
            return {"error": f"session not found: {name}"}
        del self.sessions[name]
        return {"name": name, "deleted": True, "hard": hard}


class FakeOuterHarness:
    def __init__(self, workspace):
        self.config = FakeConfig(workspace)
        self.config_manager = FakeConfigManager(self.config)
        self._harness = FakeHarnessInner()
        self._harness.config = self.config
        self._session_manager = FakeSessionManager()
        self.agent_id = "fake-agent"
        self._start_time = 0.0


class HandlerEndpointTest(unittest.TestCase):
    def make_handler(self, path="/status", method="GET", body=None, workspace=None):
        workspace = workspace or tempfile.mkdtemp()
        handler = AgentServerHandler.__new__(AgentServerHandler)
        handler.path = path
        handler.command = method
        handler.headers = {"Content-Length": str(len(body) if body else 0)}
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        handler._harness = FakeOuterHarness(workspace)
        handler._status = None
        handler._headers = []
        handler.send_response = lambda code: setattr(handler, "_status", code)
        handler.send_header = lambda k, v: handler._headers.append((k, v))
        handler.end_headers = lambda: None
        return handler

    def read_json_response(self, handler):
        handler.wfile.seek(0)
        raw = handler.wfile.read().decode()
        return json.loads(raw) if raw else None

    def test_get_status(self):
        h = self.make_handler("/status")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 200)
        body = self.read_json_response(h)
        self.assertTrue(body["ready"])
        self.assertEqual(body["adapter"], "pi-agent")

    def test_patch_config(self):
        body = json.dumps({"delivery": "inbox"}).encode()
        h = self.make_handler("/config", method="PATCH", body=body)
        AgentServerHandler.do_PATCH(h)
        self.assertEqual(h._status, 200)
        resp = self.read_json_response(h)
        self.assertEqual(resp["delivery"], "inbox")

    def test_patch_config_with_restart(self):
        body = json.dumps({"delivery": "inbox", "_restart": True}).encode()
        h = self.make_handler("/config", method="PATCH", body=body)
        AgentServerHandler.do_PATCH(h)
        self.assertEqual(h._status, 200)
        self.assertTrue(h._harness._harness.restarted)

    def test_get_sessions(self):
        h = self.make_handler("/sessions")
        AgentServerHandler.do_GET(h)
        self.assertEqual(h._status, 200)
        body = self.read_json_response(h)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["name"], "s1")

    def test_post_sessions_new(self):
        body = json.dumps({"name": "hawaii"}).encode()
        h = self.make_handler("/sessions/new", method="POST", body=body)
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 200)
        resp = self.read_json_response(h)
        self.assertEqual(resp["name"], "hawaii")

    def test_post_session_message(self):
        body = json.dumps({"content": "hello"}).encode()
        h = self.make_handler("/sessions/s1/message", method="POST", body=body)
        AgentServerHandler.do_POST(h)
        self.assertEqual(h._status, 200)
        resp = self.read_json_response(h)
        self.assertIn("session:s1:hello", resp["response"])

    def test_delete_session(self):
        h = self.make_handler("/sessions/s1", method="DELETE")
        AgentServerHandler.do_DELETE(h)
        self.assertEqual(h._status, 200)
        resp = self.read_json_response(h)
        self.assertTrue(resp["deleted"])

    def test_put_and_get_file(self):
        with tempfile.TemporaryDirectory() as td:
            body = b"hello file"
            put = self.make_handler("/files/notes.txt", method="PUT", body=body, workspace=td)
            AgentServerHandler.do_PUT(put)
            self.assertEqual(put._status, 201)

            geth = self.make_handler("/files/notes.txt", workspace=td)
            AgentServerHandler.do_GET(geth)
            self.assertEqual(geth._status, 200)
            geth.wfile.seek(0)
            self.assertEqual(geth.wfile.read().decode(), "hello file")


if __name__ == "__main__":
    unittest.main()
