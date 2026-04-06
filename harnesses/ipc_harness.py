#!/usr/bin/env python3
"""
IPC Harness — two-turn relay pattern.

Built on AgentAdapter — decoupled from OpenClaw specifics.
Session trace read via adapter.get_session_trace().

Pattern:
- Turn 1: Agent spawns subagents, exits naturally
- Optional Turn 2: If subagents were spawned, agent reads results and synthesizes
"""

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter


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

    def run(self, prompt: str, expected_files: Optional[list] = None) -> dict:
        self._adapter = get_adapter(workspace=self.workspace)
        self._adapter.setup()
        session_id = self._adapter.start()

        # ── Turn 1 ───────────────────────────────────────────────────────────
        result1 = self._adapter.send(prompt)
        trace1 = self._adapter.get_session_trace(session_id)

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
        trace2 = self._adapter.get_session_trace(session_id)

        response["turn2"] = {"stdout": result2.stdout, "stderr": result2.stderr, "returncode": result2.returncode}
        response["trace"] = trace2

        self._adapter.stop()
        self._adapter.teardown()
        return response


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IPC Harness")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--workspace", help="Workspace directory")
    parser.add_argument("--wait", type=float, default=30.0, help="Wait seconds before Turn 2")
    parser.add_argument("--files", nargs="*", help="Expected files to poll before Turn 2")

    args = parser.parse_args()

    harness = IPCHarness(workspace=args.workspace, wait_seconds=args.wait)
    result = harness.run(args.prompt, expected_files=args.files)

    print(json.dumps(result, indent=2, default=str))
