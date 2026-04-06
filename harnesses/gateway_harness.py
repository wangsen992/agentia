#!/usr/bin/env python3
"""
Gateway-Only Harness

Usage:
    python3 /workspace/runners/gateway_harness.py

Keeps the container alive while the gateway runs.
Uses OpenClawAdapter lifecycle to manage the gateway.
Press Ctrl+C to exit.

LOG=1 to enable structured logging.
"""

import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter
from observability import SessionLogger


def main():
    do_log = os.environ.get("LOG", "0") == "1"
    session_id = f"gw-{os.getpid()}"

    harness_logger = None
    if do_log:
        harness_logger = SessionLogger("openclaw", session_id=session_id)
        harness_logger.__enter__()
        print(f"[Logging to {harness_logger.path}]", flush=True)

    print("=== Gateway-Only Mode ===", flush=True)
    print("Starting adapter.setup()...", flush=True)

    adapter = get_adapter(logger=harness_logger)
    adapter.setup()

    print("Gateway running. Press Ctrl+C to exit.", flush=True)

    try:
        signal.pause()
    except KeyboardInterrupt:
        pass

    print("\n[Exiting] Running teardown...", flush=True)
    adapter.teardown()

    if harness_logger:
        harness_logger.__exit__(None, None, None)


if __name__ == "__main__":
    main()
