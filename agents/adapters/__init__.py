# Agent Adapters
#
# Base interface:
#     from agents.adapters.base import AgentAdapter, AgentResponse
#
# Factory:
#     from agents.adapters.factory import get_adapter, list_adapters
#
# OpenClaw adapter (current default):
#     from agents.adapters.openclaw import OpenClawAdapter

from .base import AgentAdapter, AgentResponse
from .factory import get_adapter, list_adapters

__all__ = [
    "AgentAdapter",
    "AgentResponse",
    "get_adapter",
    "list_adapters",
]
