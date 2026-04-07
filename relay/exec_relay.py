#!/usr/bin/env python3
"""
ExecRelay — BaseRelay implementation using DockerBackend.

Delegates to HostContainerBackend (DockerBackend) for transport.
Each agent's AgentServer is expected to be running at agent_host:agent_port.

This is the HostContainerBackend-based refactor of the original docker-exec relay.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseRelay, RelayMessage
from .backends import DockerBackend, AgentEndpoint

logger = logging.getLogger("exec_relay")


@dataclass
class AgentConnection:
    id: str
    container_name: str
    name: str
    role: str
    system_prompt: str = ""
    agent_host: str = "localhost"
    agent_port: int = 8080


class ExecRelay(BaseRelay):
    """
    BaseRelay implementation using DockerBackend.

    Registers agent endpoints with DockerBackend, which makes HTTP calls
    to each agent's AgentServer. This refactor replaces the original
    docker-exec approach with HTTP-based communication to AgentServer.
    """

    def __init__(
        self,
        backend: Optional[DockerBackend] = None,
        default_timeout: int = 120,
    ):
        self._backend = backend or DockerBackend()
        self.agents: dict[str, AgentConnection] = {}
        self._default_timeout = default_timeout

    @property
    def backend(self):
        return self._backend

    def connect(
        self,
        agent_id: str,
        container_name: Optional[str] = None,
        name: str = "",
        role: str = "",
        system_prompt: str = "",
        agent_host: str = "localhost",
        agent_port: int = 8080,
        **kwargs,
    ) -> bool:
        """
        Register an agent connection and endpoint with DockerBackend.

        Args:
            agent_id: Unique agent identifier
            container_name: Docker container name (defaults to agentia-{agent_id})
            name: Display name for the agent
            role: Agent role description
            system_prompt: Initial system prompt for the agent
            agent_host: AgentServer host IP (for HTTP calls)
            agent_port: AgentServer port
            **kwargs: Ignored (for compatibility with BaseRelay interface)
        """
        if container_name is None:
            container_name = f"agentia-{agent_id}"

        endpoint = AgentEndpoint(
            agent_id=agent_id,
            host=agent_host,
            port=agent_port,
            container_name=container_name,
        )
        self._backend.register_endpoint(endpoint)

        conn = AgentConnection(
            id=agent_id,
            container_name=container_name,
            name=name or agent_id,
            role=role,
            system_prompt=system_prompt,
            agent_host=agent_host,
            agent_port=agent_port,
        )
        self.agents[agent_id] = conn
        logger.info(
            f"Registered {agent_id} at {agent_host}:{agent_port} (container: {container_name})"
        )
        return True

    def disconnect(self, agent_id: str) -> None:
        """Unregister an agent."""
        self.agents.pop(agent_id, None)

    def setup_agent(self, agent_id: str) -> bool:
        """Send system prompt to establish agent role via AgentServer."""
        conn = self.agents.get(agent_id)
        if not conn:
            logger.error(f"Unknown agent {agent_id}")
            return False

        msg = RelayMessage(
            to_agent=agent_id,
            content=conn.system_prompt,
            from_agent="moderator",
            metadata={"type": "system", "setup": True},
        )
        response = self._backend.send_message(msg, agent_id)
        if response is not None:
            logger.info(f"  {agent_id} setup OK")
            return True
        else:
            logger.error(f"  {agent_id} setup failed")
            return False

    def send(self, message: RelayMessage) -> Optional[str]:
        """
        Send a message to an agent and wait for response via DockerBackend.
        """
        if not message.to_agent:
            logger.error("send() requires message.to_agent")
            return None

        if message.to_agent not in self.agents:
            logger.error(f"Unknown agent {message.to_agent}")
            return None

        return self._backend.send_message(message, message.to_agent)

    def send_async(self, message: RelayMessage) -> bool:
        """Fire-and-forget: send without waiting for response."""
        if message.to_agent not in self.agents:
            return False
        return self._backend.send_message_async(message, message.to_agent)

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """Send a message to all agents in message.to_agents."""
        return self._backend.broadcast(message)

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self.agents

    def close_all(self) -> None:
        """Clean up all connections."""
        self.agents.clear()
        self._backend.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close_all()


if __name__ == "__main__":
    print("ExecRelay module. Import and use in your code.")
