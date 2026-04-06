#!/usr/bin/env python3
"""
Single-Shot Harness for OpenClaw

Usage:
    python3 /workspace/runners/single_harness.py "Your prompt here"

Sends one prompt, prints the response, exits.
"""

import subprocess
import sys
import uuid


def main():
    if len(sys.argv) < 2:
        print("Usage: single_harness.py <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    session_id = f"single-{uuid.uuid4().hex[:8]}"

    print(f"[Session {session_id}] Sending prompt...", file=sys.stderr)

    result = subprocess.run(
        [
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", prompt
        ],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.stderr:
        # Filter out verbose gateway logs, keep errors
        for line in result.stderr.splitlines():
            if any(k in line.lower() for k in ["error", "warn"]):
                print(line, file=sys.stderr)

    print(result.stdout)


if __name__ == "__main__":
    main()
