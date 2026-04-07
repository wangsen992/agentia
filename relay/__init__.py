"""
Relay — multi-agent message routing layer.

Exports:
    BaseRelay      — abstract interface
    RelayMessage   — message dataclass
    WebSocketRelay — WebSocket relay
    ExecRelay      — docker exec relay
    InboxRelay     — async inbox-based relay
    Inbox          — message inbox per agent
    InboxStore     — manages all agent inboxes
    Moderator      — conversation orchestration
"""

from .base import BaseRelay, RelayMessage
from .inbox import Inbox, InboxStore
from .websocket_relay import WebSocketRelay
from .exec_relay import ExecRelay
from .inbox_relay import InboxRelay
from .moderator import Moderator, ModeratorConfig, AgentConfig, TurnRecord


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
]
