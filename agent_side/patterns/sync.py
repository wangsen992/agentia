"""
Sync delivery pattern for AgentServer.

Messages are delivered directly to the agent subprocess.
The harness calls OpenClawAdapter.send() immediately and returns the response.
"""

import time
import uuid
from typing import Optional

from agents.adapters import get_adapter
from agents.adapters.base import AgentAdapter


class SyncDelivery:
    """
    Synchronous delivery pattern.

    Messages are delivered directly to the OpenClawAdapter subprocess.
    The harness calls adapter.send() immediately and returns the response.
    """

    def __init__(
        self,
        agent_id: str,
        agent_timeout: int = 120,
    ):
        self.agent_id = agent_id
        self.agent_timeout = agent_timeout
        self._adapter: Optional[AgentAdapter] = None

    def _ensure_adapter(self) -> AgentAdapter:
        """Lazily create and setup the agent adapter."""
        if self._adapter is None:
            self._adapter = get_adapter(timeout=self.agent_timeout)
            self._adapter.setup()
        return self._adapter

    def send(self, content: str, correlation_id: Optional[str] = None) -> dict:
        """
        Deliver message directly to agent and return response.

        Args:
            content: Message content string.
            correlation_id: Optional correlation ID for tracking.

        Returns:
            dict with content, from_agent, correlation_id, timestamp.
        """
        adapter = self._ensure_adapter()
        session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
        adapter.start(session_id=session_id)

        try:
            response = adapter.send(content)
            if response.returncode == 0:
                return {
                    "content": response.stdout.strip(),
                    "from_agent": self.agent_id,
                    "correlation_id": correlation_id,
                    "timestamp": time.time(),
                }
            return {
                "content": f"[error] exit {response.returncode}: {response.stderr[:200]}",
                "from_agent": self.agent_id,
                "correlation_id": correlation_id,
                "timestamp": 0,
            }
        except Exception as e:
            return {
                "content": f"[error] {e}",
                "from_agent": self.agent_id,
                "correlation_id": correlation_id,
                "timestamp": 0,
            }

    def teardown(self):
        """Teardown the agent adapter."""
        if self._adapter is not None:
            self._adapter.teardown()
            self._adapter = None
