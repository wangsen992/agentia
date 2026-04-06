#!/usr/bin/env python3
"""
Interactive Turn-by-Turn Harness

Usage:
    python3 /workspace/runners/interactive_harness.py

Each line from stdin is sent as a turn to the agent via a persistent session.
Responses are printed to stdout.

Fully decoupled — uses AgentAdapter interface only.
Session trace logged to /workspace/logs/session_<SESSION_ID>.jsonl if LOG=1.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter
from observability import SessionLogger


def main():
    session_id = f"itxn-{uuid.uuid4().hex[:8]}"
    do_log = os.environ.get("LOG", "0") == "1"

    harness_logger = None
    if do_log:
        harness_logger = SessionLogger("openclaw", session_id=session_id)
        harness_logger.__enter__()
        print(f"[Logging to {harness_logger.path}]", flush=True)

    print(f"=== Interactive Session ===", flush=True)
    print(f"Session ID: {session_id}", flush=True)
    print(f"Setting up adapter...", flush=True)

    adapter = get_adapter(logger=harness_logger)
    adapter.setup()
    adapter.start(session_id)

    print(f"Ready. Type a message and press Enter. Ctrl+C to exit.", flush=True)
    print(f"---", flush=True)

    turn = 0
    try:
        while True:
            message = input("[You] ")
            if not message.strip():
                print()
                continue

            turn += 1
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
        if harness_logger:
            harness_logger.__exit__(None, None, None)


if __name__ == "__main__":
    main()
