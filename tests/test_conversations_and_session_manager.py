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
from agents.adapters.pi_agent import SessionManager, Session, slugify_title


class ConversationRegistryPositiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.conv_patch = patch.object(host, "CONV_BASE", self.base / "conversations")
        self.reg_patch = patch.object(host, "DEFAULT_REGISTRY", self.base / "agents.json")
        self.conv_patch.start()
        self.reg_patch.start()

        host._upsert_conv_from_send(
            "agent1",
            "hawaii",
            "2026-04-10T10-00-00_hawaii",
            message_count=3,
            context_pct=12,
        )

    def tearDown(self):
        self.conv_patch.stop()
        self.reg_patch.stop()
        self.tmp.cleanup()

    def _capture(self, fn, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*args, **kwargs)
        return rc, buf.getvalue()

    def test_conv_show_existing(self):
        rc, out = self._capture(host.cmd_conv_show, "hawaii")
        self.assertEqual(rc, 0)
        self.assertIn("hawaii", out)
        self.assertIn("agent1", out)

    def test_conv_tag_and_rename_and_delete(self):
        rc, out = self._capture(host.cmd_conv_tag, "hawaii", ["travel", "budget"])
        self.assertEqual(rc, 0)
        self.assertIn("travel", out)

        rc, out = self._capture(host.cmd_conv_rename, "hawaii", "Hawaii Trip")
        self.assertEqual(rc, 0)
        self.assertIn("Hawaii Trip", out)

        conv = host._load_conv("hawaii")
        self.assertEqual(conv["title"], "Hawaii Trip")
        self.assertEqual(sorted(conv["tags"]), ["budget", "travel"])

        rc, out = self._capture(host.cmd_conv_delete, "hawaii")
        self.assertEqual(rc, 0)
        self.assertIn("Deleted conversation registry", out)
        self.assertFalse(host._conv_file("hawaii").exists())

    def test_conv_use_sets_active_pointer(self):
        rc, out = self._capture(host.cmd_conv_use, "hawaii", "agent1")
        self.assertEqual(rc, 0)
        self.assertIn("Active conversation", out)
        active = host._get_active_conv("agent1")
        self.assertEqual(active["conv_id"], "hawaii")
        self.assertEqual(active["session_name"], "2026-04-10T10-00-00_hawaii")

    def test_conv_list_filters_by_agent(self):
        host._upsert_conv_from_send("agent2", "taxes", "2026-04-10T11-00-00_taxes", message_count=1, context_pct=1)
        rc, out = self._capture(host.cmd_conv_list, "agent1")
        self.assertEqual(rc, 0)
        self.assertIn("hawaii", out)
        self.assertNotIn("taxes", out)


class SessionManagerBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.sm = SessionManager(workspace=str(self.workspace), max_sessions=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_slugify_title(self):
        self.assertEqual(slugify_title("Hawaii Trip 2026!"), "hawaii-trip-2026")

    def test_get_session_resolves_by_title(self):
        self.sm._sessions = {
            "2026-04-10T10-00-00_hawaii": Session(
                name="2026-04-10T10-00-00_hawaii",
                title="hawaii",
                status="stopped",
                session_file="2026-04-10T10-00-00_hawaii.jsonl",
            )
        }
        result = self.sm.get_session("hawaii")
        self.assertEqual(result["name"], "2026-04-10T10-00-00_hawaii")

    def test_new_session_with_title_generates_timestamped_name(self):
        with patch.object(self.sm, "_spawn") as spawn, patch.object(self.sm, "_reset_idle_timer"):
            spawn.side_effect = lambda s: s
            result = self.sm.new_session(title="Hawaii Trip")
        self.assertEqual(result["title"], "Hawaii Trip")
        self.assertIn("hawaii-trip", result["name"])

    def test_new_session_existing_manifest_entry_resumes_by_title(self):
        existing = Session(
            name="2026-04-10T10-00-00_hawaii",
            title="hawaii",
            status="stopped",
            session_file="2026-04-10T10-00-00_hawaii.jsonl",
        )
        self.sm._sessions = {existing.name: existing}
        self.sm._save_manifest()
        with patch.object(self.sm, "_spawn") as spawn, patch.object(self.sm, "_reset_idle_timer"):
            spawn.side_effect = lambda s: s
            result = self.sm.new_session(name="hawaii")
        self.assertTrue(result["resumed"])
        self.assertEqual(result["name"], "2026-04-10T10-00-00_hawaii")

    def test_load_manifest_rehydrates_sessions_as_stopped(self):
        existing = Session(name="old", title="old", status="running", last_active="2026-04-10T00:00:00Z")
        self.sm._sessions = {existing.name: existing}
        self.sm._save_manifest()
        self.sm._load_manifest()
        self.assertEqual(self.sm._sessions["old"].status, "stopped")

    def test_delete_session_hard_true_removes_directory(self):
        session_dir = self.workspace / ".pi" / "sessions" / "s1"
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl").write_text("data")
        self.sm._sessions = {
            "s1": Session(name="s1", title="default", status="stopped", session_file="s1")
        }
        with patch.object(self.sm, "_terminate"):
            result = self.sm.delete_session("s1", hard=True)
        self.assertTrue(result["hard"])
        self.assertFalse(session_dir.exists())

    def test_build_pi_args_binds_session_to_explicit_file(self):
        s1 = Session(name="2026-04-11T17-30-00_session-1", title="session-1")
        s2 = Session(name="2026-04-11T17-31-00_session-2", title="session-2")
        args1 = self.sm._build_pi_args(s1)
        args2 = self.sm._build_pi_args(s2)
        self.assertIn("--session", args1)
        self.assertIn("--session", args2)
        p1 = args1[args1.index("--session") + 1]
        p2 = args2[args2.index("--session") + 1]
        self.assertTrue(p1.endswith("2026-04-11T17-30-00_session-1.jsonl"))
        self.assertTrue(p2.endswith("2026-04-11T17-31-00_session-2.jsonl"))
        self.assertNotEqual(p1, p2)
        self.assertNotIn("--continue", args1)


if __name__ == "__main__":
    unittest.main()
