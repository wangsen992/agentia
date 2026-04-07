#!/usr/bin/env python3
"""
ExecRelay — uses docker exec to drive agent containers.

Implements BaseRelay for synchronous request/response via docker exec.
Each agent runs in its own container with a local gateway.
The relay uses `docker exec` to run `openclaw agent` inside each container.

Pros:
- No auth/pairing complexity
- Works with existing container setup
- Each agent stays isolated

Cons:
- Docker exec overhead per message
- Not a true persistent WebSocket connection
"""

import subprocess
import time
import logging
from dataclasses import dataclass
from typing import Optional

from .base import BaseRelay, RelayMessage

logger = logging.getLogger("exec_relay")


@dataclass
class AgentConnection:
    id: str
    container_name: str
    name: str
    role: str
    system_prompt: str = ""
    session_id: Optional[str] = None


class ExecRelay(BaseRelay):
    """
    BaseRelay implementation using docker exec.

    Each agent runs in its own container with a local gateway.
    The relay uses `docker exec` to run `openclaw agent` inside
    each container, connecting to the local gateway without auth.
    """

    def __init__(self, default_timeout: int = 120):
        self.agents: dict[str, AgentConnection] = {}
        self._default_timeout = default_timeout

    def connect(
        self,
        agent_id: str,
        container_name: Optional[str] = None,
        name: str = "",
        role: str = "",
        system_prompt: str = "",
        **kwargs,
    ) -> bool:
        """
        Register an agent connection.

        Args:
            agent_id: Unique agent identifier
            container_name: Docker container name (defaults to agentia-{agent_id})
            name: Display name for the agent
            role: Agent role description
            system_prompt: Initial system prompt for the agent
            **kwargs: Ignored (for compatibility with BaseRelay interface)
        """
        if container_name is None:
            container_name = f"agentia-{agent_id}"
        conn = AgentConnection(
            id=agent_id,
            container_name=container_name,
            name=name or agent_id,
            role=role,
            system_prompt=system_prompt,
        )
        self.agents[agent_id] = conn
        logger.info(f"Registered {agent_id} in container {container_name}")
        return True

    def disconnect(self, agent_id: str) -> None:
        """Unregister an agent."""
        self.agents.pop(agent_id, None)

    def setup_agent(self, agent_id: str) -> bool:
        """Send system prompt to establish agent role."""
        conn = self.agents.get(agent_id)
        if not conn:
            logger.error(f"Unknown agent {agent_id}")
            return False

        conn.session_id = f"mod-{int(time.time())}-{agent_id}"
        logger.info(f"Setting up {agent_id} with session {conn.session_id}")

        result = self._exec_in_container(
            conn.container_name,
            [
                "openclaw",
                "agent",
                "--session-id",
                conn.session_id,
                "--message",
                conn.system_prompt,
            ],
            timeout=self._default_timeout,
        )

        if result["returncode"] == 0:
            logger.info(f"  {agent_id} setup OK")
            return True
        else:
            logger.error(f"  {agent_id} setup failed: {result['stderr'][:200]}")
            return False

    def _exec_in_container(
        self, container: str, cmd: list[str], timeout: int = 90
    ) -> dict:
        """Run a command inside a container."""
        full_cmd = ["docker", "exec", container] + cmd
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout
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

    def send(self, message: RelayMessage) -> Optional[str]:
        """
        Send a message to an agent and wait for response.

        Args:
            message: RelayMessage with to_agent and content

        Returns:
            Response text, or None on failure.
        """
        if not message.to_agent:
            logger.error("send() requires message.to_agent")
            return None

        conn = self.agents.get(message.to_agent)
        if not conn:
            logger.error(f"Unknown agent {message.to_agent}")
            return None

        if not conn.session_id:
            logger.error(f"Agent {message.to_agent} not set up (no session)")
            return None

        result = self._exec_in_container(
            conn.container_name,
            [
                "openclaw",
                "agent",
                "--session-id",
                conn.session_id,
                "--message",
                message.content,
            ],
            timeout=self._default_timeout,
        )

        if result["returncode"] == 0:
            return result["stdout"].strip()
        else:
            logger.warning(
                f"  {message.to_agent} returned non-zero: {result['stderr'][:100]}"
            )
            return result["stdout"].strip()

    def send_async(self, message: RelayMessage) -> bool:
        """
        Fire-and-forget: send without waiting for response.

        For ExecRelay, docker exec is synchronous so we just don't wait.
        """
        if message.to_agent not in self.agents:
            return False

        conn = self.agents[message.to_agent]
        if not conn.session_id:
            logger.error(f"Agent {message.to_agent} not set up (no session)")
            return False

        cmd = [
            "openclaw",
            "agent",
            "--session-id",
            conn.session_id,
            "--message",
            message.content,
        ]

        try:
            subprocess.Popen(
                ["docker", "exec", conn.container_name] + cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to exec in {message.to_agent}: {e}")
            return False

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """Send a message to all agents in message.to_agents. Returns agent_id -> success."""
        results = {}
        for agent_id in message.to_agents or []:
            conn = self.agents.get(agent_id)
            if not conn or not conn.session_id:
                results[agent_id] = False
                continue
            result = self._exec_in_container(
                conn.container_name,
                [
                    "openclaw",
                    "agent",
                    "--session-id",
                    conn.session_id,
                    "--message",
                    message.content,
                ],
                timeout=self._default_timeout,
            )
            results[agent_id] = result["returncode"] == 0
        return results

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self.agents

    def close_all(self) -> None:
        """Clean up all connections."""
        self.agents.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close_all()


if __name__ == "__main__":
    print("ExecRelay module. Import and use in your code.")
