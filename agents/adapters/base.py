"""
Agent Adapter Interface

Minimal contract that all agent runtimes must implement.
The relay and harnesses talk to this, not to specific runtimes.

Design rationale:
- start() is non-blocking — agent runs in background (needed for async)
- send() is blocking — waits for response (simpler for harnesses)
- Both can be overridden for async-capable adapters
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class AgentResponse:
    """Standard response from an agent."""
    stdout: str
    stderr: str = ""
    returncode: int = 0


class AgentAdapter(ABC):
    """
    Minimal interface all agent runtimes must implement.

    Subclass this to add a new agent runtime:
        class PiAgentAdapter(AgentAdapter):
            def start(self, session_id, **opts): ...
            def send(self, message: str) -> AgentResponse: ...
            def stop(self): ...
            def is_running(self) -> bool: ...
    """

    session_id: Optional[str] = None

    @abstractmethod
    def start(self, session_id: Optional[str] = None, **opts) -> str:
        """
        Start agent with given (or generated) session ID.

        Returns:
            The session_id used (generated if not provided).
        """

    @abstractmethod
    def send(self, message: str) -> AgentResponse:
        """
        Send a message to the running agent and wait for response.

        Returns:
            AgentResponse with stdout, stderr, returncode.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop the agent and clean up."""

    def is_running(self) -> bool:
        """
        Check if agent is still running.

        Default: False (synchronous adapters are done after send).
        Override if your adapter is truly async.
        """
        return False

    def get_session_id(self) -> Optional[str]:
        """Return current session ID."""
        return self.session_id

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
