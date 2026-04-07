"""
InboxRelay — async message relay using AgentServer inbox delivery.

Refactored to use DockerBackend for HTTP communication with AgentServer.
The inbox delivery pattern is handled by AgentServer on the agent side.

Usage:
    relay = InboxRelay()
    relay.connect("agent-a", agent_host="172.17.0.2", agent_port=8080)
    relay.connect("agent-b", agent_host="172.17.0.3", agent_port=8080)

    # Fire and forget (async to AgentServer)
    relay.send_async(RelayMessage(to_agent="agent-b", content="do this task"))

    # Request/response
    response = relay.send(RelayMessage(to_agent="agent-b", content="what is 2+2?"))
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .base import BaseRelay, RelayMessage
from .backends import DockerBackend, AgentEndpoint

logger = logging.getLogger("inbox_relay")


@dataclass
class AgentConnection:
    id: str
    container_name: str
    name: str
    role: str
    agent_host: str = "localhost"
    agent_port: int = 8080


class InboxRelay(BaseRelay):
    """
    Async relay using AgentServer's inbox delivery pattern.

    Delegates to DockerBackend for HTTP transport to AgentServer.
    AgentServer handles the inbox queue and async processing.
    """

    def __init__(
        self,
        backend: Optional[DockerBackend] = None,
        poll_interval: float = 2.0,
        response_timeout: float = 60.0,
    ):
        self._backend = backend or DockerBackend()
        self._backend._poll_interval = poll_interval
        self._backend._default_timeout = response_timeout
        self.agents: dict[str, AgentConnection] = {}

    @property
    def backend(self):
        return self._backend

    def connect(
        self,
        agent_id: str,
        container_name: Optional[str] = None,
        name: str = "",
        role: str = "",
        agent_host: str = "localhost",
        agent_port: int = 8080,
        **kwargs,
    ) -> bool:
        """Register an agent endpoint with DockerBackend."""
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
            agent_host=agent_host,
            agent_port=agent_port,
        )
        self.agents[agent_id] = conn
        logger.info(f"Registered {agent_id} at {agent_host}:{agent_port}")
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

    def send_async(self, message: RelayMessage) -> bool:
        """Fire-and-forget: deliver message to agent via AgentServer without waiting."""
        if message.to_agent not in self.agents:
            return False
        return self._backend.send_message_async(message, message.to_agent)

    def send(
        self, message: RelayMessage, timeout: Optional[float] = None
    ) -> Optional[str]:
        """
        Request/response: deliver message via AgentServer and wait for reply.

        Uses DockerBackend.send_message() which calls POST /message on AgentServer.
        For inbox delivery, AgentServer queues and processes asynchronously.
        """
        if message.to_agent not in self.agents:
            return None

        response = self._backend.send_message(message, message.to_agent)
        return response

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
