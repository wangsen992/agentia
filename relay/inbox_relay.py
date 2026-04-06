"""
InboxRelay — async message relay using shared inbox files.

Agents communicate by writing/reading from a shared inbox directory.
Each agent has its own inbox file: <base_dir>/<agent_id>.jsonl

Fire-and-forget:
  relay.send_async(agent_id, message) → appends to inbox

Request/response:
  relay.send(agent_id, message) → appends to inbox → waits for response in <responses_dir>/<correlation_id>.jsonl

Usage:
    relay = InboxRelay(base_dir="/workspace/inbox")
    relay.register_agent("agent-a", container_name="agentia-a")
    relay.register_agent("agent-b", container_name="agentia-b")

    # Fire and forget
    relay.send_async("agent-b", "do this task")

    # Request/response
    response = relay.send("agent-b", "what is 2+2?")
"""

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import BaseRelay, RelayMessage
from .inbox import Inbox, InboxStore


@dataclass
class AgentConnection:
    id: str
    container_name: str
    name: str
    role: str
    session_id: Optional[str] = None


class InboxRelay(BaseRelay):
    """
    Async relay using shared inbox files.

    - Each agent has an inbox: <base_dir>/<agent_id>.jsonl
    - Responses use a separate directory: <responses_dir>/<correlation_id>.jsonl
    - Agents poll their inbox via docker exec
    - Response files are written by the caller and read by the waiting send()
    """

    def __init__(
        self,
        base_dir: str = "/workspace/inbox",
        responses_dir: str = "/workspace/inbox/responses",
        poll_interval: float = 2.0,
        response_timeout: float = 60.0,
    ):
        self.base_dir = base_dir
        self.responses_dir = responses_dir
        self.poll_interval = poll_interval
        self.response_timeout = response_timeout

        # Inbox store for managing inbox files
        self._inbox_store = InboxStore(base_dir)

        # Connected agents
        self.agents: dict[str, AgentConnection] = {}

        # Response futures (correlation_id -> event)
        self._response_events: dict[str, threading.Event] = {}
        self._response_results: dict[str, dict] = {}
        self._lock = threading.Lock()

        # Ensure directories exist
        Path(responses_dir).mkdir(parents=True, exist_ok=True)

    def register_agent(
        self,
        agent_id: str,
        container_name: str,
        name: str = "",
        role: str = "",
    ) -> None:
        """Register an agent connection."""
        self.agents[agent_id] = AgentConnection(
            id=agent_id,
            container_name=container_name,
            name=name or agent_id,
            role=role,
        )

    def connect(self, agent_id: str, **kwargs) -> bool:
        """Register an agent. Always returns True (no persistent connection needed)."""
        if agent_id not in self.agents:
            container = kwargs.get("container_name", f"agentia-{agent_id}")
            self.register_agent(agent_id, container)
        return True

    def disconnect(self, agent_id: str) -> None:
        """Unregister an agent."""
        self.agents.pop(agent_id, None)

    def _exec_in_container(self, container: str, cmd: list[str], timeout: int = 90) -> dict:
        """Run a command inside a container."""
        full_cmd = ["docker", "exec", container] + cmd
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "timeout", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    def _deliver_to_inbox(self, to_agent: str, message: "RelayMessage") -> bool:
        """Append a message to an agent's inbox file via docker exec."""
        conn = self.agents.get(to_agent)
        if not conn:
            return False

        # Create the message JSON
        msg_dict = {
            "id": str(uuid.uuid4()),
            "from_agent": message.from_agent or "moderator",
            "to_agent": to_agent,
            "content": message.content,
            "timestamp": time.time(),
            "correlation_id": message.correlation_id,
            "reply_to": message.reply_to,
        }

        # Write to a temp file, then cat into the container's inbox file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(msg_dict) + "\n")
            tmp_path = f.name

        try:
            docker_cp = ["docker", "cp", tmp_path, f"{conn.container_name}:/tmp/msg.jsonl"]
            result = subprocess.run(docker_cp, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return False

            # Append to inbox file via docker exec
            mkdir_cmd = ["sh", "-c", f"mkdir -p {self.base_dir} && cat /tmp/msg.jsonl >> {self.base_dir}/{to_agent}.jsonl"]
            exec_result = self._exec_in_container(conn.container_name, mkdir_cmd)
            return exec_result["returncode"] == 0
        finally:
            os.unlink(tmp_path)

    def send_async(
        self,
        agent_id: str,
        content: str,
        correlation_id: Optional[str] = None,
        from_agent: str = "moderator",
    ) -> bool:
        """
        Fire-and-forget: deliver message to agent's inbox without waiting.
        """
        if agent_id not in self.agents:
            return False

        message = RelayMessage(
            to_agent=agent_id,
            content=content,
            from_agent=from_agent,
            correlation_id=correlation_id,
        )
        return self._deliver_to_inbox(agent_id, message)

    def _wait_for_response(self, correlation_id: str) -> Optional[dict]:
        """Poll for a response file until timeout."""
        response_path = Path(self.responses_dir) / f"{correlation_id}.jsonl"
        start = time.time()

        while time.time() - start < self.response_timeout:
            if response_path.exists():
                try:
                    with open(response_path, "r") as f:
                        content = f.read().strip()
                    response_path.unlink()  # clean up
                    return json.loads(content)
                except Exception:
                    return None
            time.sleep(self.poll_interval)

        return None

    def send(
        self,
        agent_id: str,
        content: str,
        from_agent: str = "moderator",
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """
        Request/response: deliver message and wait for reply.

        Uses correlation_id to match the response.
        Response is written to <responses_dir>/<correlation_id>.jsonl by the agent.
        """
        if agent_id not in self.agents:
            return None

        correlation_id = str(uuid.uuid4())
        message = RelayMessage(
            to_agent=agent_id,
            content=content,
            from_agent=from_agent,
            correlation_id=correlation_id,
        )

        # Deliver to inbox
        if not self._deliver_to_inbox(agent_id, message):
            return None

        # Wait for response
        old_timeout = self.response_timeout
        if timeout is not None:
            self.response_timeout = timeout

        response = self._wait_for_response(correlation_id)

        self.response_timeout = old_timeout

        if response:
            return response.get("content", "")
        return None

    def broadcast(self, agent_ids: list[str], content: str) -> dict[str, bool]:
        """Send a message to all agents. Returns agent_id -> success."""
        results = {}
        for agent_id in agent_ids:
            results[agent_id] = self.send_async(agent_id, content)
        return results

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self.agents

    def close_all(self) -> None:
        """Clean up all connections."""
        self.agents.clear()
        self._response_events.clear()
        self._response_results.clear()

    # ─── Agent-side helpers (used by agent containers) ─────────────────────────

    def agent_poll_inbox(
        self,
        agent_id: str,
        container_name: str,
        max_messages: int = 10,
    ) -> list[dict]:
        """
        Called by an agent container via docker exec to poll its inbox.
        Returns up to max_messages without marking them processed.
        """
        inbox = self._inbox_store.get_inbox(agent_id)
        messages = inbox.read_all()
        return [m.__dict__ for m in messages[:max_messages]]

    def agent_write_response(
        self,
        correlation_id: str,
        content: str,
        from_agent: str = "agent",
    ) -> bool:
        """
        Called by an agent to write a response to a request.
        """
        response_path = Path(self.responses_dir) / f"{correlation_id}.jsonl"
        response_data = {
            "correlation_id": correlation_id,
            "from_agent": from_agent,
            "content": content,
            "timestamp": time.time(),
        }
        try:
            with open(response_path, "w") as f:
                json.dump(response_data, f)
                f.write("\n")
            return True
        except Exception:
            return False
