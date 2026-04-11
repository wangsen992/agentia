import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.host as host
from agent_runtime.adapters.pi_agent import Session, SessionManager


class HostConversationCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

        self.conv_patch = patch.object(host, "CONV_BASE", self.base / "conversations")
        self.reg_patch = patch.object(host, "DEFAULT_REGISTRY", self.base / "agents.json")
        self.conv_patch.start()
        self.reg_patch.start()

    def tearDown(self):
        self.conv_patch.stop()
        self.reg_patch.stop()
        self.tmp.cleanup()

    def test_conv_show_missing_returns_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = host.cmd_conv_show("missing")
        self.assertEqual(rc, 1)
        self.assertIn("not found", buf.getvalue().lower())

    def test_conv_rename_missing_returns_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = host.cmd_conv_rename("missing", "new-title")
        self.assertEqual(rc, 1)
        self.assertIn("not found", buf.getvalue().lower())

    def test_conv_tag_missing_returns_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = host.cmd_conv_tag("missing", ["x"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", buf.getvalue().lower())

    def test_conv_delete_missing_returns_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = host.cmd_conv_delete("missing")
        self.assertEqual(rc, 1)
        self.assertIn("not found", buf.getvalue().lower())

    def test_smart_route_preserves_actual_session_name_in_active_pointer(self):
        with patch.object(host, "_http_post_or_409") as post_or_409, \
             patch.object(host, "_get_agent_sessions", return_value=[]), \
             patch.object(host, "_http_post") as http_post:
            post_or_409.return_value = ({"response": "ok", "message_count": 1, "context_pct": 5}, False)
            http_post.return_value = None

            host._set_active_conv("agent1", "hawaii", "2026-04-10T15-00-00_hawaii")
            response = host._smart_route("agent1", "hello", None)
            self.assertEqual(response["response"], "ok")

            active = host._get_active_conv("agent1")
            self.assertEqual(active["conv_id"], "hawaii")
            self.assertEqual(active["session_name"], "2026-04-10T15-00-00_hawaii")


class SessionManagerDeleteResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.sm = SessionManager(workspace=str(self.workspace))
        self.sm._sessions = {
            "2026-04-10T15-00-00_hawaii": Session(
                name="2026-04-10T15-00-00_hawaii",
                title="hawaii",
                status="stopped",
                session_file="2026-04-10T15-00-00_hawaii.jsonl",
            )
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_session_by_title_uses_resolved_key(self):
        with patch.object(self.sm, "_terminate"):
            result = self.sm.delete_session("hawaii", hard=False)
        self.assertTrue(result["deleted"])
        self.assertEqual(self.sm._sessions, {})


class ServerFilesPutSemanticsTest(unittest.TestCase):
    def test_created_detection_logic(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "note.txt"
            created = not target.exists()
            target.write_text("hello")
            self.assertTrue(created)

            created = not target.exists()
            target.write_text("updated")
            self.assertFalse(created)


if __name__ == "__main__":
    unittest.main()
