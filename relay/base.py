"""
Base Relay — abstract interface for all relay implementations.

All relays must implement these methods so harnesses and moderators
can work with any transport interchangeably.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class RelayMessage:
    """A message sent through the relay."""
    to_agent: str
    content: str
    from_agent: Optional[str] = None
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    metadata: Optional[dict] = None


class BaseRelay(ABC):
    """
    Abstract base class for all relay implementations.

    Implementations:
    - ExecRelay: uses docker exec (existing)
    - InboxRelay: async inbox-based (new)
    - WebSocketRelay: persistent WS connections (future)
    """

    @abstractmethod
    def connect(self, agent_id: str, **kwargs) -> bool:
        """Connect to an agent. Returns True on success."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self, agent_id: str) -> None:
        """Disconnect from an agent."""
        raise NotImplementedError

    @abstractmethod
    def send(self, agent_id: str, message: str) -> Optional[str]:
        """
        Send a message to an agent and wait for response (request/response).

        Returns the response text, or None on failure.
        """
        raise NotImplementedError

    @abstractmethod
    def send_async(self, agent_id: str, message: str, correlation_id: Optional[str] = None) -> bool:
        """
        Fire-and-forget: send a message without waiting for response.

        Returns True if queued successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, agent_ids: list[str], message: str) -> dict[str, bool]:
        """
        Send a message to all agents. Returns dict of agent_id -> success.
        """
        raise NotImplementedError

    @abstractmethod
    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is connected."""
        raise NotImplementedError

    @abstractmethod
    def close_all(self) -> None:
        """Clean up all connections."""
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close_all()
