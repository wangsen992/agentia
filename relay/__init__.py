"""
Relay — multi-agent message routing layer.

Exports:
    BaseRelay      — abstract interface
    RelayMessage   — message dataclass
    WebSocketRelay — WebSocket relay
    ExecRelay      — docker exec relay (uses DockerBackend)
    InboxRelay     — async inbox-based relay (uses DockerBackend)
    Inbox          — message inbox per agent
    InboxStore     — manages all agent inboxes
    Moderator      — conversation orchestration
    DockerBackend  — host-side HTTP backend
    SSHBackend     — host-side SSH backend
"""

from .base import BaseRelay, RelayMessage
from .inbox import Inbox, InboxStore
from .websocket_relay import WebSocketRelay
from .exec_relay import ExecRelay
from .inbox_relay import InboxRelay
from .moderator import Moderator, ModeratorConfig, AgentConfig, TurnRecord
from .backends import DockerBackend, SSHBackend, HostContainerBackend, AgentEndpoint


__all__ = [
    "BaseRelay",
    "RelayMessage",
    "WebSocketRelay",
    "ExecRelay",
    "InboxRelay",
    "Inbox",
    "InboxStore",
    "Moderator",
    "ModeratorConfig",
    "AgentConfig",
    "TurnRecord",
    "DockerBackend",
    "SSHBackend",
    "HostContainerBackend",
    "AgentEndpoint",
]
