"""
Base Relay — abstract interface for all relay implementations.

All relays must implement these methods so harnesses and moderators
can work with any transport interchangeably.
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class RelayMessage:
    """A message sent through the relay."""

    content: str
    from_agent: Optional[str] = None
    to_agent: Optional[str] = None
    to_agents: Optional[list[str]] = None
    correlation_id: Optional[str] = None
    metadata: Optional[dict] = None
    id: Optional[str] = None
    timestamp: Optional[float] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, line: str) -> "RelayMessage":
        return cls(**json.loads(line))

    def ensure_id(self) -> str:
        if self.id is None:
            self.id = str(uuid.uuid4())
        return self.id

    def ensure_timestamp(self) -> float:
        if self.timestamp is None:
            self.timestamp = time.time()
        return self.timestamp


class BaseRelay(ABC):
    """
    Abstract base class for all relay implementations.

    Implementations:
    - ExecRelay: uses docker exec
    - InboxRelay: async inbox-based
    - WebSocketRelay: WebSocket relay
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
    def send(self, message: RelayMessage) -> Optional[str]:
        """
        Send a message and wait for response.

        Args:
            message: RelayMessage with to_agent and content

        Returns:
            Response text, or None on failure.
        """
        raise NotImplementedError

    @abstractmethod
    def send_async(self, message: RelayMessage) -> bool:
        """
        Fire-and-forget: send a message without waiting for response.

        Returns True if queued successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """
        Send a message to all agents in message.to_agents.
        Returns dict of agent_id -> success.
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
