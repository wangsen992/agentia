#!/usr/bin/env python3
"""
Interactive Turn-by-Turn Harness for OpenClaw

Usage:
    python3 /workspace/runners/interactive_harness.py

Each line from stdin is sent as a turn to the agent via a persistent session.
Responses are printed to stdout.

Requires the container gateway to be running (started by the container CMD).
"""

import subprocess
import uuid
import sys
import os
import time

SESSION_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")


def get_session_trace(session_id: str) -> list:
    """Read session trace JSONL and return list of entries."""
    sessions_dir = SESSION_DIR
    if not os.path.exists(sessions_dir):
        return []

    session_files = sorted(
        [f for f in os.listdir(sessions_dir) if f.startswith(session_id) and f.endswith(".jsonl")],
        key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
        reverse=True
    )

    if not session_files:
        return []

    entries = []
    with open(os.path.join(sessions_dir, session_files[0])) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(__import__("json").loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def send_turn(session_id: str, message: str) -> dict:
    """Send a turn to the agent via openclaw agent CLI."""
    cmd = [
        "openclaw", "agent",
        "--session-id", session_id,
        "--message", message
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120
    )

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


def main():
    import json

    session_id = f"itxn-{uuid.uuid4().hex[:8]}"
    print(f"=== OpenClaw Interactive Session ===", flush=True)
    print(f"Session ID: {session_id}", flush=True)
    print(f"Type a message and press Enter. Ctrl+C to exit.", flush=True)
    print(f"---", flush=True)

    while True:
        try:
            message = input("[You] ")
            if not message.strip():
                print()
                continue

            result = send_turn(session_id, message)

            if result["stderr"] and "error" in result["stderr"].lower():
                print(f"[Error] {result['stderr'][:500]}", flush=True)

            if result["stdout"]:
                print(f"\n[Agent] {result['stdout']}", flush=True)

            print(f"---", flush=True)

        except KeyboardInterrupt:
            print(f"\n[Exiting]", flush=True)
            break
        except Exception as e:
            print(f"[Exception] {e}", flush=True)
            break


if __name__ == "__main__":
    main()
