"""
InboxRelay — async message relay using shared inbox files.

Agents communicate by writing/reading from a shared inbox directory.
Each agent has its own inbox file: <base_dir>/<agent_id>.jsonl

Fire-and-forget:
  relay.send_async(message) → appends to inbox

Request/response:
  relay.send(message) → appends to inbox → waits for response in <responses_dir>/<correlation_id>.jsonl

Usage:
    relay = InboxRelay(base_dir="/workspace/inbox")
    relay.connect("agent-a", container_name="agentia-a")
    relay.connect("agent-b", container_name="agentia-b")

    # Fire and forget
    relay.send_async(RelayMessage(to_agent="agent-b", content="do this task"))

    # Request/response
    response = relay.send(RelayMessage(to_agent="agent-b", content="what is 2+2?"))
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

        self._inbox_store = InboxStore(base_dir)
        self.agents: dict[str, AgentConnection] = {}

        self._response_events: dict[str, threading.Event] = {}
        self._response_results: dict[str, dict] = {}
        self._lock = threading.Lock()

        Path(responses_dir).mkdir(parents=True, exist_ok=True)

    def connect(
        self,
        agent_id: str,
        container_name: Optional[str] = None,
        name: str = "",
        role: str = "",
        **kwargs,
    ) -> bool:
        """Register an agent. Always returns True (no persistent connection needed)."""
        if agent_id not in self.agents:
            container = container_name or kwargs.get(
                "container_name", f"agentia-{agent_id}"
            )
            self.agents[agent_id] = AgentConnection(
                id=agent_id,
                container_name=container,
                name=name or agent_id,
                role=role,
            )
        return True

    def register_agent(
        self,
        agent_id: str,
        container_name: str,
        name: str = "",
        role: str = "",
    ) -> None:
        """Legacy alias for connect()."""
        self.connect(agent_id, container_name, name, role)

    def disconnect(self, agent_id: str) -> None:
        """Unregister an agent."""
        self.agents.pop(agent_id, None)

    def _exec_in_container(
        self, container: str, cmd: list[str], timeout: int = 90
    ) -> dict:
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

    def _deliver_to_inbox(self, message: RelayMessage) -> bool:
        """Append a message to an agent's inbox file via docker exec."""
        if not message.to_agent:
            return False
        conn = self.agents.get(message.to_agent)
        if not conn:
            return False

        message.ensure_id()
        message.ensure_timestamp()

        msg_dict = {
            "id": message.id,
            "from_agent": message.from_agent or "moderator",
            "to_agent": message.to_agent,
            "content": message.content,
            "timestamp": message.timestamp,
            "correlation_id": message.correlation_id,
        }

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(msg_dict) + "\n")
            tmp_path = f.name

        try:
            docker_cp = [
                "docker",
                "cp",
                tmp_path,
                f"{conn.container_name}:/tmp/msg.jsonl",
            ]
            result = subprocess.run(
                docker_cp, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return False

            mkdir_cmd = [
                "sh",
                "-c",
                f"mkdir -p {self.base_dir} && cat /tmp/msg.jsonl >> {self.base_dir}/{message.to_agent}.jsonl",
            ]
            exec_result = self._exec_in_container(conn.container_name, mkdir_cmd)
            return exec_result["returncode"] == 0
        finally:
            os.unlink(tmp_path)

    def _wait_for_response(self, correlation_id: str) -> Optional[dict]:
        """Poll for a response file until timeout."""
        response_path = Path(self.responses_dir) / f"{correlation_id}.jsonl"
        start = time.time()

        while time.time() - start < self.response_timeout:
            if response_path.exists():
                try:
                    with open(response_path, "r") as f:
                        content = f.read().strip()
                    response_path.unlink()
                    return json.loads(content)
                except Exception:
                    return None
            time.sleep(self.poll_interval)

        return None

    def send_async(self, message: RelayMessage) -> bool:
        """Fire-and-forget: deliver message to agent's inbox without waiting."""
        if message.to_agent not in self.agents:
            return False
        return self._deliver_to_inbox(message)

    def send(
        self, message: RelayMessage, timeout: Optional[float] = None
    ) -> Optional[str]:
        """
        Request/response: deliver message and wait for reply.

        Uses correlation_id to match the response.
        Response is written to <responses_dir>/<correlation_id>.jsonl by the agent.
        """
        if message.to_agent not in self.agents:
            return None

        correlation_id = message.correlation_id or str(uuid.uuid4())
        message.correlation_id = correlation_id

        if not self._deliver_to_inbox(message):
            return None

        old_timeout = self.response_timeout
        if timeout is not None:
            self.response_timeout = timeout

        response = self._wait_for_response(correlation_id)

        self.response_timeout = old_timeout

        if response:
            return response.get("content", "")
        return None

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """Send a message to all agents in message.to_agents. Returns agent_id -> success."""
        results = {}
        for agent_id in message.to_agents or []:
            results[agent_id] = self._deliver_to_inbox(
                RelayMessage(
                    to_agent=agent_id,
                    content=message.content,
                    from_agent=message.from_agent,
                    correlation_id=message.correlation_id,
                )
            )
        return results

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self.agents

    def close_all(self) -> None:
        """Clean up all connections."""
        self.agents.clear()
        self._response_events.clear()
        self._response_results.clear()

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
        """Called by an agent to write a response to a request."""
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
