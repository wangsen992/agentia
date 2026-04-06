#!/usr/bin/env python3
"""
Single-Shot Harness for OpenClaw

Usage:
    python3 /workspace/runners/single_harness.py "Your prompt here"

Sends one prompt, prints the response, exits.

To switch agent runtime:
    RUNTIME=pi python3 single_harness.py "Your prompt here"
"""

import os
import sys
import uuid
from pathlib import Path

# Agent adapter
sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter, AgentResponse


def main():
    if len(sys.argv) < 2:
        print("Usage: single_harness.py <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    runtime = os.environ.get("RUNTIME", "openclaw")

    print(f"[Runtime: {runtime}] Sending prompt...", file=sys.stderr)

    adapter = get_adapter(runtime)
    adapter.setup()
    adapter.start(f"single-{uuid.uuid4().hex[:8]}")
    response = adapter.send(prompt)

    if response.stderr:
        for line in response.stderr.splitlines():
            if any(k in line.lower() for k in ["error", "warn"]):
                print(line, file=sys.stderr)

    print(response.stdout)
    adapter.stop()
    adapter.teardown()


if __name__ == "__main__":
    main()
