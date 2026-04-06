"""
Agent Adapter Factory

Usage:
    from agents.adapters.factory import get_adapter

    adapter = get_adapter("openclaw", workspace="/path/to/workspace")
    # or
    adapter = get_adapter("pi", model="claude-sonnet")
    # or
    adapter = get_adapter()  # defaults to openclaw

To add a new adapter:
    1. Create agents/adapters/<name>.py implementing AgentAdapter
    2. Import it and add to ADAPTERS dict below
"""

from typing import Optional, Type

from .base import AgentAdapter


# Registry of available adapters
ADAPTERS: dict[str, Type[AgentAdapter]] = {}


def _register_adapters():
    """Lazy-register adapters to avoid circular imports."""
    global ADAPTERS
    if ADAPTERS:
        return

    # Import known adapters
    try:
        from .openclaw import OpenClawAdapter
        ADAPTERS["openclaw"] = OpenClawAdapter
    except ImportError as e:
        pass

    # Future adapters:
    # try:
    #     from .pi import PiAgentAdapter
    #     ADAPTERS["pi"] = PiAgentAdapter
    # except ImportError:
    #     pass


def get_adapter(
    runtime: Optional[str] = None,
    **opts,
) -> AgentAdapter:
    """
    Return an AgentAdapter for the specified runtime.

    Args:
        runtime: Adapter name (e.g., "openclaw", "pi"). Defaults to "openclaw".
        **opts: Passed to the adapter constructor (e.g., workspace, timeout).

    Returns:
        An instance of the requested AgentAdapter subclass.

    Raises:
        ValueError: If the runtime is unknown or unavailable.
    """
    _register_adapters()

    if runtime is None:
        runtime = "openclaw"

    if runtime not in ADAPTERS:
        available = ", ".join(sorted(ADAPTERS.keys())) or "none"
        raise ValueError(
            f"Unknown agent runtime: {runtime!r}. "
            f"Available: {available}"
        )

    return ADAPTERS[runtime](**opts)


def list_adapters() -> list[str]:
    """Return list of available agent runtime names."""
    _register_adapters()
    return sorted(ADAPTERS.keys())
