#!/usr/bin/env python3
"""
Interactive Turn-by-Turn Harness for OpenClaw

Usage:
    python3 /workspace/runners/interactive_harness.py

Each line from stdin is sent as a turn to the agent via a persistent session.
Responses are printed to stdout.

Uses OpenClawAdapter — calls setup() to provision gateway,
then runs the interactive REPL, then teardown() on exit.
"""

import json
import os
import sys
import uuid
from pathlib import Path

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


def main():
    session_id = f"itxn-{uuid.uuid4().hex[:8]}"
    print(f"=== OpenClaw Interactive Session ===", flush=True)
    print(f"Session ID: {session_id}", flush=True)
    print(f"Setting up adapter...", flush=True)

    adapter = get_adapter("openclaw")
    adapter.setup()
    adapter.start(session_id)

    print(f"Ready. Type a message and press Enter. Ctrl+C to exit.", flush=True)
    print(f"---", flush=True)

    try:
        while True:
            message = input("[You] ")
            if not message.strip():
                print()
                continue

            result = adapter.send(message)

            if result.stderr and "error" in result.stderr.lower():
                print(f"[Error] {result.stderr[:500]}", flush=True)

            if result.stdout:
                print(f"\n[Agent] {result.stdout}", flush=True)

            print(f"---", flush=True)

    except KeyboardInterrupt:
        print(f"\n[Exiting]", flush=True)
    except Exception as e:
        print(f"[Exception] {e}", flush=True)
    finally:
        adapter.stop()
        adapter.teardown()


if __name__ == "__main__":
    main()
