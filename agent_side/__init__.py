"""
AgentServer — agent-side HTTP/WebSocket server.

Exposes control plane and host messaging plane endpoints.
Owns AgentAdapter lifecycle and configurable delivery patterns.
"""

from .server import AgentServer

__all__ = ["AgentServer"]
