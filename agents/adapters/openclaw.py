"""
OpenClaw Agent Adapter

Implements AgentAdapter using `openclaw agent` subprocess.
This is the current production adapter.
"""

import os
import subprocess
import uuid
from typing import Optional

from .base import AgentAdapter, AgentResponse


class OpenClawAdapter(AgentAdapter):
    """
    AgentAdapter backed by `openclaw agent`.

    Uses subprocess to call `openclaw agent --session-id <id> --message <msg>`.
    Each send() is a blocking subprocess call.

    Args:
        workspace: OPENCLAW_WORKSPACE env var for the agent
        timeout: seconds before subprocess times out (default 120)
    """

    def __init__(self, workspace: Optional[str] = None, timeout: int = 120):
        self._workspace = workspace
        self._timeout = timeout
        self._proc = None

    def start(self, session_id: Optional[str] = None, **opts) -> str:
        if session_id is None:
            session_id = f"agent-{uuid.uuid4().hex[:8]}"
        self.session_id = session_id
        return self.session_id

    def send(self, message: str) -> AgentResponse:
        if self.session_id is None:
            self.start()

        cmd = [
            "openclaw", "agent",
            "--session-id", self.session_id,
            "--message", message
        ]

        env = os.environ.copy()
        if self._workspace:
            env["OPENCLAW_WORKSPACE"] = self._workspace

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            env=env
        )

        return AgentResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode
        )

    def stop(self) -> None:
        """Stop is a no-op for subprocess-based adapter (process exits after send)."""
        self._proc = None

    def is_running(self) -> bool:
        """Always False — subprocess exits after each send."""
        return False


# Alias for convenience
AgentAdapter = OpenClawAdapter
