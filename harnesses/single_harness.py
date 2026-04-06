#!/usr/bin/env python3
"""
Single-Shot Harness

Usage:
    python3 /workspace/runners/single_harness.py "Your prompt here"

Sends one prompt, prints the response, exits.

To switch agent runtime:
    RUNTIME=pi python3 single_harness.py "Your prompt here"

Fully decoupled — uses AgentAdapter interface only.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter


def main():
    if len(sys.argv) < 2:
        print("Usage: single_harness.py <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    runtime = os.environ.get("RUNTIME")  # None → defaults to "openclaw"

    print(f"[Runtime: {runtime or 'openclaw (default)'}] Sending prompt...", file=sys.stderr)

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
