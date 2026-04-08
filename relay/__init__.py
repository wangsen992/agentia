"""
Relay — multi-agent message routing layer.

This module provides the HostContainerBackend interface and DockerBackend
for communicating with AgentServer instances running in containers/VMs.

For multi-agent orchestration, see examples/moderator.py.
"""

from .base import BaseRelay, RelayMessage
from .backends import DockerBackend, SSHBackend, HostContainerBackend, AgentEndpoint


__all__ = [
    "BaseRelay",
    "RelayMessage",
    "DockerBackend",
    "SSHBackend",
    "HostContainerBackend",
    "AgentEndpoint",
]
