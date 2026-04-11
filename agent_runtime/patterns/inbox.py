"""
Inbox delivery pattern for AgentServer.

Messages are queued in a file-based inbox.
The harness polls the inbox file, processes messages via an AgentAdapter,
and writes responses to the responses directory.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from agent_runtime.adapters import get_adapter
from agent_runtime.adapters.base import AgentAdapter


class InboxDelivery:
    """
    File-based inbox delivery pattern.

    Messages are appended to <inbox_dir>/<agent_id>.jsonl.
    The harness polls this file, processes each message via an AgentAdapter,
    and writes responses to <responses_dir>/<correlation_id>.jsonl.
    """

    def __init__(
        self,
        agent_id: str,
        inbox_dir: str = "/workspace/inbox",
        responses_dir: str = "/workspace/inbox/responses",
        poll_interval: float = 2.0,
        agent_timeout: int = 120,
        adapter_type: str = "pi-agent",
        adapter_provider: str = "minimax",
        adapter_model: str = "MiniMax-M2.7",
        adapter_workspace: str = "/workspace",
    ):
        self.agent_id = agent_id
        self.inbox_dir = Path(inbox_dir)
        self.responses_dir = Path(responses_dir)
        self.poll_interval = poll_interval
        self.agent_timeout = agent_timeout
        self._adapter_type = adapter_type
        self._adapter_provider = adapter_provider
        self._adapter_model = adapter_model
        self._adapter_workspace = adapter_workspace

        self._inbox_path = self.inbox_dir / f"{agent_id}.jsonl"
        self._adapter: Optional[AgentAdapter] = None
        self._running = False

        self.responses_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_adapter(self) -> AgentAdapter:
        """Lazily create and setup the agent adapter."""
        if self._adapter is None:
            self._adapter = get_adapter(
                runtime=self._adapter_type,
                provider=self._adapter_provider,
                model=self._adapter_model,
                workspace=self._adapter_workspace,
                timeout=self.agent_timeout,
            )
            self._adapter.setup()
        return self._adapter

    def append_message(self, message: dict) -> bool:
        """Append a message dict to the inbox file."""
        try:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            with open(self._inbox_path, "a") as f:
                f.write(json.dumps(message) + "\n")
            return True
        except Exception as e:
            print(f"[InboxDelivery] Failed to append message: {e}")
            return False

    def read_inbox(self) -> list[dict]:
        """Read all pending messages from inbox (does NOT mark processed)."""
        if not self._inbox_path.exists():
            return []
        messages = []
        try:
            with open(self._inbox_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            print(f"[InboxDelivery] Failed to read inbox: {e}")
        return messages

    def mark_processed(self, message_ids: list[str]) -> int:
        """Rewrite inbox file without the given message IDs. Returns count removed."""
        if not self._inbox_path.exists():
            return 0

        remaining = []
        removed = 0
        try:
            with open(self._inbox_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if msg.get("id") in message_ids:
                            removed += 1
                        else:
                            remaining.append(line)
                    except json.JSONDecodeError:
                        pass

            with open(self._inbox_path, "w") as f:
                f.write("\n".join(remaining) + ("\n" if remaining else ""))

        except Exception as e:
            print(f"[InboxDelivery] Failed to mark processed: {e}")

        return removed

    def write_response(
        self, correlation_id: str, content: str, from_agent: str = "agent"
    ) -> bool:
        """Write a response to the responses directory."""
        resp_path = self.responses_dir / f"{correlation_id}.jsonl"
        entry = {
            "correlation_id": correlation_id,
            "from_agent": from_agent,
            "content": content,
            "timestamp": time.time(),
        }
        try:
            with open(resp_path, "w") as f:
                json.dump(entry, f)
                f.write("\n")
            return True
        except Exception as e:
            print(f"[InboxDelivery] Failed to write response: {e}")
            return False

    def process_message(self, message: dict) -> Optional[str]:
        """
        Process a single message via the configured AgentAdapter.

        Returns response content string, or None on error.
        """
        session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
        adapter = self._ensure_adapter()
        adapter.start(session_id=session_id)

        try:
            response = adapter.send(message.get("content", ""))
            if response.returncode == 0:
                return response.stdout.strip()
            return f"[error] exit {response.returncode}: {response.stderr[:200]}"
        except Exception as e:
            return f"[error] {e}"

    def poll_once(self) -> int:
        """
        Read all pending inbox messages and process them.

        Returns number of messages processed.
        """
        messages = self.read_inbox()
        if not messages:
            return 0

        processed_ids = []
        for msg in messages:
            msg_id = msg.get("id", "")
            correlation_id = msg.get("correlation_id")
            print(
                f"[{self.agent_id}] Processing: {msg.get('content', '')[:50]}...",
                flush=True,
            )

            try:
                response = self.process_message(msg)
                print(
                    f"[{self.agent_id}] Response: {str(response)[:80]}...", flush=True
                )
                if correlation_id:
                    self.write_response(correlation_id, str(response))
                if msg_id:
                    processed_ids.append(msg_id)
            except Exception as e:
                print(
                    f"[{self.agent_id}] Error processing {msg_id[:8] if msg_id else 'unknown'}: {e}",
                    flush=True,
                )

        if processed_ids:
            self.mark_processed(processed_ids)

        return len(processed_ids)

    def run(self):
        """Poll loop (called in a background thread by AgentServer)."""
        print(f"[{self.agent_id}] InboxDelivery poller started", flush=True)
        self._running = True
        while self._running:
            self.poll_once()
            time.sleep(self.poll_interval)

    def stop(self):
        """Stop the poll loop."""
        self._running = False

    def teardown(self):
        """Teardown the agent adapter."""
        if self._adapter is not None:
            self._adapter.teardown()
            self._adapter = None
