# Agent Adapters
#
# Base interface:
#     from agent_runtime.adapters.base import AgentAdapter, AgentResponse
#
# Factory:
#     from agent_runtime.adapters.factory import get_adapter, list_adapters
#
# pi-agent adapter (primary):
#     from agent_runtime.adapters.pi_agent import PiAgentAdapter
#
# OpenClaw adapter (legacy):
#     from agent_runtime.adapters.openclaw import OpenClawAdapter

from .base import AgentAdapter, AgentResponse
from .factory import get_adapter, list_adapters

__all__ = [
    "AgentAdapter",
    "AgentResponse",
    "get_adapter",
    "list_adapters",
]
