#!/usr/bin/env python3
"""
Agent Harness — subprocess-based message processing.

Each message spawns `openclaw agent --message` as a subprocess.
No gateway needed. No WebSocket. Simple and reliable.

Usage:
    python3 /workspace/runners/agent_harness.py --agent-id <id> --poll-interval <secs>

This is the recommended harness for containerized agents.
For a persistent gateway with WebSocket messaging, see gateway_harness.py.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from observability import SessionLogger
from relay.inbox import Inbox
from relay.base import RelayMessage

import constants


class SubprocessPoller:
    """
    Poller that sends each message to `openclaw agent --message` as a subprocess.
    No gateway needed — each call is a fresh agent invocation.
    """

    def __init__(
        self,
        agent_id: str,
        base_dir: str,
        responses_dir: str,
        poll_interval: float,
        gateway_token: str,
    ):
        self.agent_id = agent_id
        self.base_dir = base_dir
        self.responses_dir = responses_dir
        self.poll_interval = poll_interval
        self.gateway_token = gateway_token
        self.inbox = Inbox(agent_id=agent_id, base_dir=base_dir)
        self.running = False
        self._session_prefix = f"agent-{agent_id}"

        Path(responses_dir).mkdir(parents=True, exist_ok=True)

    def process_message(self, message: RelayMessage) -> str:
        """Call openclaw agent --message as subprocess, return response."""
        session_id = f"{self._session_prefix}-{uuid.uuid4().hex[:8]}"
        env = {
            **os.environ,
            "OPENCLAW_WORKSPACE": "/workspace",
            "OPENCLAW_IDENTITY_TOKEN": self.gateway_token,
            "OPENCLAW_GATEWAY_TOKEN": self.gateway_token,
        }

        cmd = [
            "openclaw",
            "agent",
            "--session-id",
            session_id,
            "--message",
            message.content,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            if result.returncode != 0:
                return f"[error] exit {result.returncode}: {result.stderr[:200]}"
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return "[error] timeout after 120s"
        except Exception as e:
            return f"[error] {e}"

    def write_response(self, correlation_id: str, content: str) -> bool:
        if not correlation_id:
            return False
        response_path = Path(self.responses_dir) / f"{correlation_id}.jsonl"
        response_data = {
            "correlation_id": correlation_id,
            "from_agent": self.agent_id,
            "content": content,
            "timestamp": time.time(),
        }
        try:
            with open(response_path, "w") as f:
                json.dump(response_data, f)
                f.write("\n")
            return True
        except Exception as e:
            print(f"[{self.agent_id}] Failed to write response: {e}", flush=True)
            return False

    def poll_once(self) -> int:
        messages = self.inbox.read_all()
        if not messages:
            return 0
        processed_ids = []
        for msg in messages:
            print(
                f"[{self.agent_id}] Processing msg from {msg.from_agent}: {msg.content[:50]}...",
                flush=True,
            )
            try:
                response_content = self.process_message(msg)
                print(
                    f"[{self.agent_id}] Response: {response_content[:80]}...",
                    flush=True,
                )
                if msg.correlation_id:
                    self.write_response(msg.correlation_id, response_content)
                processed_ids.append(msg.id)
            except Exception as e:
                msg_id_str = (msg.id or "unknown")[:8]
                print(
                    f"[{self.agent_id}] Error processing message {msg_id_str}: {e}",
                    flush=True,
                )
        if processed_ids:
            self.inbox.mark_processed(processed_ids)
        return len(processed_ids)

    def run(self):
        print(
            f"[{self.agent_id}] Subprocess poller started, polling every {self.poll_interval}s",
            flush=True,
        )
        try:
            while self.running:
                self.poll_once()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print(f"[{self.agent_id}] Shutting down...", flush=True)
            self.running = False


def main():
    parser = argparse.ArgumentParser(description="Agent Harness — subprocess-based")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--base-dir", default="/workspace/inbox")
    parser.add_argument("--responses-dir", default="/workspace/inbox/responses")
    parser.add_argument(
        "--poll-interval", type=float, default=constants.POLL_INTERVAL_DEFAULT
    )
    args = parser.parse_args()

    do_log = os.environ.get("LOG", "0") == "1"
    session_id = f"agent-{args.agent_id}"
    harness_logger = None
    if do_log:
        harness_logger = SessionLogger("openclaw", session_id=session_id)
        harness_logger.__enter__()

    print(
        f"=== Starting AGENT HARNESS for '{args.agent_id}' (subprocess mode) ===",
        flush=True,
    )

    gateway_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", constants.GATEWAY_TOKEN)

    poller = SubprocessPoller(
        agent_id=args.agent_id,
        base_dir=args.base_dir,
        responses_dir=args.responses_dir,
        poll_interval=args.poll_interval,
        gateway_token=gateway_token,
    )
    poller.running = True

    def shutdown(signum, frame):
        print(f"[AgentHarness] Shutting down...", flush=True)
        poller.running = False
        if harness_logger:
            harness_logger.__exit__(None, None, None)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        poller.run()
    except Exception as e:
        print(f"[AgentHarness] Error: {e}", flush=True)
    finally:
        if harness_logger:
            harness_logger.__exit__(None, None, None)


if __name__ == "__main__":
    main()
