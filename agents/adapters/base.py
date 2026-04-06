"""
Agent Adapter Interface

Minimal contract that all agent runtimes must implement.
The relay and harnesses talk to this, not to specific runtimes.

Design rationale:
- setup() / teardown() handle lifecycle (e.g., gateway provisioning for OpenClaw)
- start() is non-blocking — agent runs in background (needed for async)
- send() is blocking — waits for response (simpler for harnesses)
- Both can be overridden for async-capable adapters
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentResponse:
    """Standard response from an agent."""
    stdout: str
    stderr: str = ""
    returncode: int = 0


class AgentAdapter(ABC):
    """
    Minimal interface all agent runtimes must implement.

    Lifecycle:
        adapter.setup()     # provision gateway, identity, etc. (once)
        adapter.start()     # start agent session
        adapter.send()       # send message, get response
        ... more sends ...
        adapter.stop()       # stop agent session
        adapter.teardown()   # clean up gateway, identity, etc. (once)

    Subclass this to add a new agent runtime:
        class PiAgentAdapter(AgentAdapter):
            def setup(self): ...    # nothing for pi-agent
            def start(self, session_id=None): return session_id
            def send(self, message): return AgentResponse(...)
            def stop(self): ...
            def teardown(self): ...  # nothing for pi-agent
    """

    session_id: Optional[str] = None

    def setup(self) -> None:
        """
        Lifecycle hook: called once before first use.

        For OpenClaw: provisions device identity, starts gateway, approves pairings.
        For pi-agent: typically a no-op.
        Override in subclass if needed.
        """

    def teardown(self) -> None:
        """
        Lifecycle hook: called once when done.

        For OpenClaw: kills gateway, cleans up identity.
        For pi-agent: typically a no-op.
        Override in subclass if needed.
        """

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
        """Stop the agent and clean up session."""

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
        self.setup()
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        self.teardown()
