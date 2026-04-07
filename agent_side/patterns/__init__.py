"""
Delivery patterns for AgentServer.

Each pattern defines how messages are delivered to the agent subprocess
and how responses are collected.
"""

from .inbox import InboxDelivery
from .sync import SyncDelivery

__all__ = ["InboxDelivery", "SyncDelivery"]
