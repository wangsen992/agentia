#!/usr/bin/env python3
"""
Gateway-Only Harness for OpenClaw

Usage:
    python3 /workspace/runners/gateway_harness.py

Keeps the container alive while the gateway runs.
Uses OpenClawAdapter lifecycle to manage the gateway.

Press Ctrl+C to exit.
"""

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter


def main():
    print("=== Gateway-Only Mode ===", flush=True)
    print("Starting adapter.setup()...", flush=True)

    adapter = get_adapter("openclaw")
    adapter.setup()

    print("Gateway running. Press Ctrl+C to exit.", flush=True)

    try:
        signal.pause()
    except KeyboardInterrupt:
        pass

    print("\n[Exiting] Running teardown...", flush=True)
    adapter.teardown()


if __name__ == "__main__":
    main()
