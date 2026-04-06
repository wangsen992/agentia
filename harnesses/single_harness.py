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
from observability import SessionLogger


def main():
    if len(sys.argv) < 2:
        print("Usage: single_harness.py [--log] <prompt>", file=sys.stderr)
        sys.exit(1)

    do_log = "--log" in sys.argv
    if do_log:
        sys.argv.remove("--log")

    if len(sys.argv) < 2:
        print("Usage: single_harness.py [--log] <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    runtime = os.environ.get("RUNTIME")
    session_id = f"single-{uuid.uuid4().hex[:8]}"
    adapter_logger = None

    print(f"[Runtime: {runtime or 'openclaw (default)'}]" + (" [LOGGING ENABLED]" if do_log else ""), file=sys.stderr)

    if do_log:
        adapter_logger = SessionLogger("openclaw", session_id=session_id)
        adapter_logger.__enter__()

    adapter = get_adapter(runtime, logger=adapter_logger)
    adapter.setup()
    adapter.start(session_id)
    response = adapter.send(prompt)

    if response.stderr:
        for line in response.stderr.splitlines():
            if any(k in line.lower() for k in ["error", "warn"]):
                print(line, file=sys.stderr)

    print(response.stdout)
    adapter.stop()
    adapter.teardown()

    if adapter_logger:
        adapter_logger.__exit__(None, None, None)
        print(f"[Log: {adapter_logger.path}]", file=sys.stderr)


if __name__ == "__main__":
    main()
