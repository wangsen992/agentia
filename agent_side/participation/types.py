"""
Shared types for the participation evaluator subsystem.

These dataclasses are used across all three evaluator approaches.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ParticipationLevel(str, Enum):
    """
    The output of the evaluate() function.

    - active  : agent should fully engage (process + respond)
    - observer: agent sees the message but does not respond (read-only)
    - skip    : agent ignores the message entirely
    """

    ACTIVE = "active"
    OBSERVER = "observer"
    SKIP = "skip"


# ---------------------------------------------------------------------------
# Relay message
# ---------------------------------------------------------------------------

@dataclass
class RelayMessage:
    """
    A message travelling through the relay / AgentServer.

    Fields mirror what the HTTP handler already builds in server.py plus
    extra metadata that the evaluator may inspect.
    """

    message_id: str
    from_agent: str
    to_agent: str
    content: str
    conversation_id: str
    correlation_id: str
    timestamp: str          # ISO-8601 string (e.g. from time.time())
    metadata: dict = field(default_factory=dict)   # free-form; may contain
                                                   # topic tags, intent, etc.


# ---------------------------------------------------------------------------
# Agent context
# ---------------------------------------------------------------------------

@dataclass
class RoleConfig:
    """Role / persona configuration for an agent (loaded from agent.json)."""

    name: str
    description: str = ""
    topics: list[str] = field(default_factory=list)   # topic keywords
    keywords: list[str] = field(default_factory=list)  # additional keyword
                                                       # triggers


@dataclass
class AgentContext:
    """
    Everything the evaluator needs to know about the receiving agent.

    Passed to evaluate() so each approach can make an informed decision.
    """

    agent_id: str
    role: RoleConfig
    skills: list[str]                   # names of skills this agent has
    memory_state: str                   # free-form summary of current state
    conversation_history: list[str]     # recent content strings in this thread
