# SPEC: Agent Adapter Abstraction — 2026-04-05

## Problem

The relay and harness scripts call `openclaw agent` directly. If we need to switch agent runtimes (e.g., pi-agent, AutoGen, custom), we have to rewrite the relay, harnesses, and everything that spawns agents.

## Solution: Adapter Pattern

Define a minimal **Agent interface** that any agent runtime must implement. The relay talks to the interface, not the implementation.

### Minimal Agent Interface

```python
class AgentAdapter(ABC):
    """Minimal interface all agent runtimes must implement."""

    @abstractmethod
    def start(self, session_id: str, **opts) -> None:
        """Start agent with given session ID. Non-blocking."""

    @abstractmethod
    def send(self, message: str) -> str:
        """Send message to running agent, return response."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the agent."""

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if agent is still running."""
```

### Implementations

```
agents/
├── __init__.py           ← exports AgentAdapter, get_agent()
├── openclaw_adapter.py   ← implements interface via openclaw agent
├── pi_adapter.py         ← (future) implements via pi-agent
├── autogen_adapter.py    ← (future) implements via AutoGen Core
└── factory.py            ← AgentAdapter factory: get_agent(runtime="openclaw")
```

### Factory Pattern

```python
def get_agent(runtime: str = "openclaw", **opts) -> AgentAdapter:
    """Return agent adapter for specified runtime."""
    adapters = {
        "openclaw": OpenClawAdapter,
        "pi": PiAgentAdapter,
        "autogen": AutoGenAdapter,
    }
    return adapters[runtime](**opts)
```

## Why This Matters Now

1. **Future-proofing** — adding pi-agent or any other runtime is just a new adapter class, no relay changes
2. **Testing** — can swap in a mock adapter for testing without spinning up containers
3. **Benchmarking** — can test same relay behavior with different agent runtimes
4. **Clarity** — the interface forces us to define what "an agent" actually is from relay's perspective

## Backward Compatibility

Existing code calling `openclaw agent` directly can be migrated incrementally:
1. Wrap existing code in `OpenClawAdapter`
2. Update relay to accept adapter instance
3. Add new adapters as needed

No rewrite required at any step.

## Decision Deferred

Which agent runtime to use is a separate question from whether to build the abstraction. We can build the adapter now with OpenClaw, evaluate pi-agent later, and switch with one file change.
