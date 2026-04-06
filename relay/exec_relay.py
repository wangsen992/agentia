#!/usr/bin/env python3
"""
ExecRelay — uses docker exec to drive agent containers.

Simpler than WebSocket auth: uses `docker exec` to run `openclaw agent`
inside each agent container, where it connects to the local gateway
without needing external auth.

Pros:
- No auth/pairing complexity
- Works with existing container setup
- Each agent stays isolated

Cons:
- Docker exec overhead per message
- Not a true persistent WebSocket connection
"""

import subprocess
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("exec_relay")


@dataclass
class AgentConnection:
    id: str
    container_name: str
    name: str
    role: str
    system_prompt: str = ""
    session_id: Optional[str] = None


class ExecRelay:
    """
    Relay that uses docker exec to send messages to agent containers.

    Each agent runs in its own container with a local gateway.
    The relay uses `docker exec` to run `openclaw agent` inside
    each container, connecting to the local gateway without auth.
    """

    def __init__(self):
        self.agents: dict[str, AgentConnection] = {}

    def register_agent(self, agent_id: str, container_name: str,
                       name: str = "", role: str = "", system_prompt: str = ""):
        conn = AgentConnection(
            id=agent_id,
            container_name=container_name,
            name=name or agent_id,
            role=role,
            system_prompt=system_prompt
        )
        self.agents[agent_id] = conn
        logger.info(f"Registered {agent_id} in container {container_name}")

    def _exec_in_container(self, container: str, cmd: list[str], timeout: int = 90) -> dict:
        """Run a command inside a container."""
        full_cmd = ["docker", "exec", container] + cmd
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }

    def setup_agent(self, agent_id: str) -> bool:
        """Send system prompt to establish agent role."""
        conn = self.agents.get(agent_id)
        if not conn:
            logger.error(f"Unknown agent {agent_id}")
            return False

        # Create a new session for this agent
        conn.session_id = f"mod-{int(time.time())}-{agent_id}"
        logger.info(f"Setting up {agent_id} with session {conn.session_id}")

        # Send system prompt as first message
        result = self._exec_in_container(
            conn.container_name,
            [
                "openclaw", "agent",
                "--session-id", conn.session_id,
                "--message", conn.system_prompt
            ],
            timeout=120
        )

        if result["returncode"] == 0:
            logger.info(f"  {agent_id} setup OK")
            return True
        else:
            logger.error(f"  {agent_id} setup failed: {result['stderr'][:200]}")
            return False

    def send(self, agent_id: str, message: str) -> Optional[str]:
        """Send a message to an agent and return the response."""
        conn = self.agents.get(agent_id)
        if not conn:
            logger.error(f"Unknown agent {agent_id}")
            return None

        if not conn.session_id:
            logger.error(f"Agent {agent_id} not set up (no session)")
            return None

        result = self._exec_in_container(
            conn.container_name,
            [
                "openclaw", "agent",
                "--session-id", conn.session_id,
                "--message", message
            ],
            timeout=120
        )

        if result["returncode"] == 0:
            return result["stdout"].strip()
        else:
            # Fall back to embedded mode (gateway unreachable)
            logger.warning(f"  {agent_id} returned non-zero: {result['stderr'][:100]}")
            return result["stdout"].strip()

    def close(self):
        """Clean up (no-op for exec relay)."""
        pass


if __name__ == "__main__":
    print("ExecRelay module. Import and use in your code.")
