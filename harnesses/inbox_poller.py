#!/usr/bin/env python3
"""
Inbox Polling Agent — runs inside an agent container.

Polls the shared inbox file and processes messages.
Writes responses to the responses directory.

Usage (run inside container):
    python3 /workspace/runners/inbox_poller.py --agent-id my-agent --base-dir /workspace/inbox --poll-interval 2

This is a long-running process. Typically started once per container.
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Add workspace to path so relay module is found
# When running as `python3 /workspace/runners/inbox_poller.py`, sys.path[0] = script dir
# which doesn't include /workspace/relay. Fix by inserting /workspace explicitly.
import sys
workspace = Path(__file__).parent.parent  # parent=runners, grandparent=workspace
if str(workspace) not in sys.path:
    sys.path.insert(0, str(workspace))
from relay.inbox import Inbox, Message


class InboxPoller:
    """
    Polls an agent's inbox and processes messages.

    Subclass this and implement `process_message()` to define
    how each message is handled.
    """

    def __init__(
        self,
        agent_id: str,
        base_dir: str = "/workspace/inbox",
        responses_dir: str = "/workspace/inbox/responses",
        poll_interval: float = 2.0,
    ):
        self.agent_id = agent_id
        self.base_dir = base_dir
        self.responses_dir = responses_dir
        self.poll_interval = poll_interval
        self.inbox = Inbox(agent_id=agent_id, base_dir=base_dir)
        self.running = False

        Path(responses_dir).mkdir(parents=True, exist_ok=True)

    def process_message(self, message: Message) -> str:
        """
        Process a single message and return the response content.

        Override this in a subclass to define your message handling logic.

        Default implementation: echo the message back with a prefix.
        """
        return f"[{self.agent_id}] received: {message.content}"

    def write_response(self, correlation_id: str, content: str) -> bool:
        """Write a response to the responses directory."""
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
        """
        Poll inbox once, process all pending messages.

        Returns number of messages processed.
        """
        messages = self.inbox.read_all()
        if not messages:
            return 0

        processed_ids = []

        for msg in messages:
            print(f"[{self.agent_id}] Processing msg from {msg.from_agent}: {msg.content[:50]}...", flush=True)

            try:
                response_content = self.process_message(msg)

                # If message has a correlation_id, treat as request/response
                if msg.correlation_id:
                    self.write_response(msg.correlation_id, response_content)
                    print(f"[{self.agent_id}] Response written for {msg.correlation_id[:8]}", flush=True)

                processed_ids.append(msg.id)

            except Exception as e:
                print(f"[{self.agent_id}] Error processing message {msg.id[:8]}: {e}", flush=True)

        # Mark processed
        if processed_ids:
            self.inbox.mark_processed(processed_ids)
            print(f"[{self.agent_id}] Marked {len(processed_ids)} messages processed", flush=True)

        return len(processed_ids)

    def run(self, poll_interval: float = None) -> None:
        """
        Run the polling loop indefinitely.
        """
        interval = poll_interval or self.poll_interval
        self.running = True
        print(f"[{self.agent_id}] Inbox poller started, polling every {interval}s", flush=True)

        try:
            while self.running:
                self.poll_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            print(f"[{self.agent_id}] Shutting down...", flush=True)
            self.running = False


class AgentInboxPoller(InboxPoller):
    """
    InboxPoller that drives an OpenClaw agent.

    For each message in the inbox, starts a new OpenClaw agent session
    and returns the agent's response.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_prefix = f"inbox-{self.agent_id}"

    def process_message(self, message: Message) -> str:
        """
        Process a message by sending it to the OpenClaw agent.
        """
        import subprocess

        session_id = f"{self._session_prefix}-{uuid.uuid4().hex[:8]}"

        cmd = [
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", message.content,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "OPENCLAW_IDENTITY_TOKEN": os.environ.get("OPENCLAW_IDENTITY_TOKEN", "")},
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"[error] {result.stderr.strip()[:200]}"
        except subprocess.TimeoutExpired:
            return "[error] agent timed out"
        except Exception as e:
            return f"[error] {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="Inbox Polling Agent")
    parser.add_argument("--agent-id", required=True, help="Agent ID for this container")
    parser.add_argument("--base-dir", default="/workspace/inbox", help="Inbox base directory")
    parser.add_argument("--responses-dir", default="/workspace/inbox/responses", help="Responses directory")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument(
        "--mode",
        default="echo",
        choices=["echo", "agent"],
        help="'echo' echoes messages, 'agent' sends to OpenClaw agent",
    )

    args = parser.parse_args()

    if args.mode == "agent":
        poller = AgentInboxPoller(
            agent_id=args.agent_id,
            base_dir=args.base_dir,
            responses_dir=args.responses_dir,
            poll_interval=args.poll_interval,
        )
    else:
        poller = InboxPoller(
            agent_id=args.agent_id,
            base_dir=args.base_dir,
            responses_dir=args.responses_dir,
            poll_interval=args.poll_interval,
        )

    poller.run()


if __name__ == "__main__":
    main()
