"""Agent provision adapters — one per framework."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ProvisionAdapter(ABC):
    """
    Framework-specific agent provisioning.

    Each adapter knows how to:
    - Generate/load identity for its framework
    - Configure the agent inside the container
    - Verify the agent is ready
    """

    @abstractmethod
    def setup_identity(self, openclaw_dir: Path, reuse: bool = True) -> None:
        """
        Set up the agent's identity/config directory.

        Args:
            openclaw_dir: Path to the mounted .openclaw/ directory on the host
            reuse: If True, reuse existing identity if present; if False, regenerate
        """

    @abstractmethod
    def verify_ready(self, container_name: str) -> bool:
        """
        Check if the agent container is running and ready to receive messages.

        Returns True if ready, False otherwise.
        """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """Return the framework name, e.g. 'openclaw', 'anthropic', 'llama'."""
