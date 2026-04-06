#!/usr/bin/env python3
"""
IPC Harness for OpenClaw Agent Experiments
Uses two-turn relay pattern via openclaw agent (IPC path)
"""

import subprocess
import json
import time
import uuid
import os
from pathlib import Path
from typing import Optional


SESSION_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"


def get_session_trace(session_id: str) -> list:
    """Read session trace JSONL and return list of entries."""
    # Find the most recent session file matching the session_id
    sessions_dir = SESSION_DIR
    if not sessions_dir.exists():
        return []

    session_files = sorted(
        sessions_dir.glob(f"{session_id}*.jsonl"),
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
        # Check message entries
        if entry.get("type") == "message":
            msg = entry.get("message", {})
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            btype = block.get("type", "")
                            # sessions_spawn tool calls appear as "toolCall" blocks
                            if btype == "toolCall":
                                name = block.get("name", "")
                                if "spawn" in name.lower():
                                    return True
                            # Also check for "sessions_spawn" in text blocks
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


def send_turn(session_id: str, message: str, workspace: Optional[str] = None) -> dict:
    """Send a turn to the agent via openclaw agent."""
    cmd = [
        "openclaw", "agent",
        "--session-id", session_id,
        "--message", message
    ]

    env = os.environ.copy()
    if workspace:
        env["OPENCLAW_WORKSPACE"] = workspace

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env
    )

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


class IPCHarness:
    """
    Two-turn relay harness using IPC path via openclaw agent.

    Pattern:
    - Turn 1: Agent spawns subagents, exits naturally
    - Optional Turn 2: If subagents were spawned, agent reads results and synthesizes

    Detection: Inspect session trace for sessions_spawn calls.
    """

    def __init__(self, workspace: Optional[str] = None, wait_seconds: float = 30.0):
        self.workspace = workspace
        self.wait_seconds = wait_seconds

    def run(self, prompt: str, expected_files: Optional[list] = None) -> dict:
        """
        Run agent with the two-turn relay pattern.

        Args:
            prompt: The task prompt for the agent
            expected_files: Optional list of files to wait for before Turn 2
                          If None, no Turn 2 is triggered.

        Returns:
            dict with: turn1_response, turn2_needed, turn2_response, trace
        """
        session_id = f"harness-{uuid.uuid4().hex[:8]}"

        # ── Turn 1 ───────────────────────────────────────────────────────────
        result1 = send_turn(session_id, prompt, self.workspace)
        trace1 = get_session_trace(session_id)

        # ── Check if Turn 2 is needed ───────────────────────────────────────
        needs_turn2 = had_subagents(trace1)

        response = {
            "session_id": session_id,
            "turn1": result1,
            "turn2_needed": needs_turn2,
            "turn2": None,
            "trace": trace1
        }

        if not needs_turn2:
            # No subagents, return Turn 1 result
            return response

        # ── Turn 2: Wait for completion, then synthesize ───────────────────
        if expected_files:
            wait_for_files(expected_files, timeout=self.wait_seconds)
        else:
            time.sleep(self.wait_seconds)

        result2 = send_turn(
            session_id,
            "Continue where you left off",
            self.workspace
        )
        trace2 = get_session_trace(session_id)

        response["turn2"] = result2
        response["trace"] = trace2

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
