"""
Agent Adapter Factory

Usage:
    from agents.adapters.factory import get_adapter

    adapter = get_adapter("pi-agent", workspace="/path/to/workspace", provider="minimax", model="MiniMax-M2.7")
    # or
    adapter = get_adapter()  # defaults to pi-agent

To add a new adapter:
    1. Create agents/adapters/<name>.py implementing AgentAdapter
    2. Import it and add to ADAPTERS dict below
"""

from typing import Optional, Type

from .base import AgentAdapter


ADAPTERS: dict[str, Type[AgentAdapter]] = {}


def _register_adapters():
    """Lazy-register adapters to avoid circular imports."""
    global ADAPTERS
    if ADAPTERS:
        return

    try:
        from .pi_agent import PiAgentAdapter

        ADAPTERS["pi-agent"] = PiAgentAdapter
    except ImportError:
        pass

    try:
        from .openclaw import OpenClawAdapter

        ADAPTERS["openclaw"] = OpenClawAdapter
    except ImportError:
        pass


def get_adapter(
    runtime: Optional[str] = None,
    **opts,
) -> AgentAdapter:
    """
    Return an AgentAdapter for the specified runtime.

    Args:
        runtime: Adapter name (e.g., "pi-agent", "openclaw"). Defaults to "pi-agent".
        **opts: Passed to the adapter constructor (e.g., workspace, provider, model, timeout).

    Returns:
        An instance of the requested AgentAdapter subclass.

    Raises:
        ValueError: If the runtime is unknown or unavailable.
    """
    _register_adapters()

    if runtime is None:
        runtime = "pi-agent"

    if runtime not in ADAPTERS:
        available = ", ".join(sorted(ADAPTERS.keys())) or "none"
        raise ValueError(f"Unknown agent runtime: {runtime!r}. Available: {available}")

    return ADAPTERS[runtime](**opts)


def list_adapters() -> list[str]:
    """Return list of available agent runtime names."""
    _register_adapters()
    return sorted(ADAPTERS.keys())
