"""
Relay backends — host-side transport adapters.

Each backend implements HostContainerBackend to adapt BaseRelay calls
to specific transport mechanisms (Docker, SSH, WebSocket).
"""

from .base import HostContainerBackend, AgentEndpoint
from .docker import DockerBackend
from .ssh import SSHBackend

__all__ = [
    "HostContainerBackend",
    "AgentEndpoint",
    "DockerBackend",
    "SSHBackend",
]
