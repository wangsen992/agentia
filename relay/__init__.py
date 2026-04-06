"""
Relay — multi-agent message routing layer.

Exports:
    BaseRelay    — abstract interface
    RelayMessage — message dataclass
    Relay        — WebSocket relay (legacy)
    ExecRelay    — docker exec relay
    InboxRelay   — async inbox-based relay
    Inbox        — message inbox per agent
    InboxStore   — manages all agent inboxes
    Moderator    — conversation orchestration
"""

from .base import BaseRelay, RelayMessage
from .inbox import Inbox, InboxStore, Message
from .relay import Relay
from .exec_relay import ExecRelay
from .inbox_relay import InboxRelay
from .moderator import Moderator, ModeratorConfig, AgentConfig, TurnRecord


__all__ = [
    "BaseRelay",
    "RelayMessage",
    "Relay",
    "ExecRelay",
    "InboxRelay",
    "Inbox",
    "InboxStore",
    "Message",
    "Moderator",
    "ModeratorConfig",
    "AgentConfig",
    "TurnRecord",
]
