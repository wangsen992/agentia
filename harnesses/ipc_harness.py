#!/usr/bin/env python3
"""
IPC Harness for OpenClaw Agent Experiments

Uses two-turn relay pattern via OpenClaw agent (IPC path).
Built on AgentAdapter — switches runtimes via get_adapter("openclaw").

Pattern:
- Turn 1: Agent spawns subagents, exits naturally
- Optional Turn 2: If subagents were spawned, agent reads results and synthesizes

Detection: Inspect session trace for sessions_spawn calls.
"""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter


SESSION_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"


def get_session_trace(session_id: str) -> list:
    """Read session trace JSONL and return list of entries."""
    if not SESSION_DIR.exists():
        return []

    session_files = sorted(
        SESSION_DIR.glob(f"{session_id}*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if not session_files:
        return []

    entries = []
    with open(session_files[0]) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def had_subagents(trace: list) -> bool:
    """Check if session trace contains sessions_spawn calls."""
    for entry in trace:
        if entry.get("type") == "message":
            msg = entry.get("message", {})
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            btype = block.get("type", "")
                            if btype == "toolCall":
                                name = block.get("name", "")
                                if "spawn" in name.lower():
                                    return True
                            elif btype == "text":
                                text = block.get("text", "")
                                if "sessions_spawn" in text:
                                    return True
    return False


def wait_for_files(expected_files: list, timeout: float = 60.0, interval: float = 2.0) -> bool:
    """Poll workspace files until all exist or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if all(Path(f).exists() for f in expected_files):
            return True
        time.sleep(interval)
    return False


class IPCHarness:
    """
    Two-turn relay harness using AgentAdapter.

    Pattern:
    - Turn 1: Agent spawns subagents, exits naturally
    - Optional Turn 2: If subagents were spawned, agent reads results and synthesizes
    """

    def __init__(self, workspace: Optional[str] = None, wait_seconds: float = 30.0):
        self.workspace = workspace
        self.wait_seconds = wait_seconds
        self._adapter = None

    def run(self, prompt: str, expected_files: Optional[list] = None) -> dict:
        """
        Run agent with the two-turn relay pattern.

        Args:
            prompt: The task prompt for the agent
            expected_files: Optional list of files to wait for before Turn 2

        Returns:
            dict with: turn1_response, turn2_needed, turn2_response, trace
        """
        self._adapter = get_adapter("openclaw", workspace=self.workspace)
        self._adapter.setup()
        session_id = self._adapter.start()

        # ── Turn 1 ───────────────────────────────────────────────────────────
        result1 = self._adapter.send(prompt)
        trace1 = get_session_trace(session_id)

        needs_turn2 = had_subagents(trace1)

        response = {
            "session_id": session_id,
            "turn1": {"stdout": result1.stdout, "stderr": result1.stderr, "returncode": result1.returncode},
            "turn2_needed": needs_turn2,
            "turn2": None,
            "trace": trace1
        }

        if not needs_turn2:
            self._adapter.stop()
            self._adapter.teardown()
            return response

        # ── Turn 2 ─────────────────────────────────────────────────────────
        if expected_files:
            wait_for_files(expected_files, timeout=self.wait_seconds)
        else:
            time.sleep(self.wait_seconds)

        result2 = self._adapter.send("Continue where you left off")
        trace2 = get_session_trace(session_id)

        response["turn2"] = {"stdout": result2.stdout, "stderr": result2.stderr, "returncode": result2.returncode}
        response["trace"] = trace2

        self._adapter.stop()
        self._adapter.teardown()
        return response


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IPC Harness for OpenClaw")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--workspace", help="Workspace directory")
    parser.add_argument("--wait", type=float, default=30.0, help="Wait seconds before Turn 2")
    parser.add_argument("--files", nargs="*", help="Expected files to poll before Turn 2")

    args = parser.parse_args()

    harness = IPCHarness(workspace=args.workspace, wait_seconds=args.wait)
    result = harness.run(args.prompt, expected_files=args.files)

    print(json.dumps(result, indent=2, default=str))
