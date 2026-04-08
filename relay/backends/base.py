"""
HostContainerBackend — abstract interface for host-side transport adapters.

Adapts BaseRelay calls to AgentServer HTTP/WebSocket endpoints.
Each backend implementation (Docker, SSH, WebSocket) maps this interface
to its specific transport mechanism.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from relay.base import RelayMessage


@dataclass
class AgentEndpoint:
    """Static configuration for an agent's AgentServer endpoint."""

    agent_id: str
    host: str
    port: int
    container_name: Optional[str] = None

    def url(self, path: str = "") -> str:
        return f"http://{self.host}:{self.port}{path}"


class HostContainerBackend(ABC):
    """
    Abstract base for host-side transport adapters.

    Adapts BaseRelay calls to AgentServer endpoints.
    Implementations: DockerBackend, SSHBackend, WebSocketBackend.
    """

    @abstractmethod
    def send_message(self, message: RelayMessage, agent_id: str) -> Optional[str]:
        """
        Sync: deliver message to AgentServer, block until response.

        Args:
            message: RelayMessage with content, to_agent, correlation_id, etc.
            agent_id: Target agent identifier.

        Returns:
            Response content string, or None on failure.
        """
        raise NotImplementedError

    @abstractmethod
    def send_message_async(self, message: RelayMessage, agent_id: str) -> bool:
        """
        Fire-and-forget: deliver message without waiting.

        Args:
            message: RelayMessage to deliver.
            agent_id: Target agent identifier.

        Returns:
            True if queued successfully, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def poll_response(
        self, correlation_id: str, agent_id: str, timeout: float
    ) -> Optional[dict]:
        """
        Poll for an async response by correlation_id from a specific agent.

        Args:
            correlation_id: The correlation ID from send_message_async.
            agent_id: Which agent's AgentServer to poll.
            timeout: Max seconds to wait.

        Returns:
            Response dict with content, from_agent, timestamp, or None on timeout.
        """
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """
        Fan-out: send to each agent in message.to_agents.

        Args:
            message: RelayMessage with to_agents list populated.

        Returns:
            dict of agent_id -> success bool.
        """
        raise NotImplementedError

    @abstractmethod
    def get_status(self, agent_id: str) -> dict:
        """
        Get AgentServer health and readiness.

        Args:
            agent_id: Target agent identifier.

        Returns:
            dict with status, ready, uptime fields.
        """
        raise NotImplementedError

    @abstractmethod
    def discover(self) -> list[str]:
        """
        List configured agent IDs.

        Returns:
            List of agent_id strings (from registered endpoints).
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Cleanup all connections and resources."""
        raise NotImplementedError
