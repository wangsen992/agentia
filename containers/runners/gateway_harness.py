#!/usr/bin/env python3
"""
Gateway-Only Harness for OpenClaw

Usage:
    python3 /workspace/runners/gateway_harness.py

Keeps the container alive while the gateway runs. No agent session is started.
An external harness or tool connects to the gateway directly.
Press Ctrl+C to exit.
"""

import signal
import sys


def main():
    print("=== Gateway-Only Mode ===", flush=True)
    print(
        "Gateway is running. Connect an external harness to drive the agent.",
        flush=True,
    )
    print("Press Ctrl+C to exit.", flush=True)

    try:
        signal.pause()
    except KeyboardInterrupt:
        pass

    print("\n[Exiting]", flush=True)


if __name__ == "__main__":
    main()
