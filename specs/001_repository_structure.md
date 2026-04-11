# SPEC: Repository Structure — 2026-04-07 (Updated)

## Why Restructure?

The previous structure was inherited from `openclaw-agent-experimentation`. The refactor (issue #12) cleaned up deprecated code and aligned the architecture around **AgentServer** — a HTTP-based agent-side server that handles message delivery and agent lifecycle.

## Current Structure

```
agentia/
├── agentia               ← CLI tool for agent container management
├── Dockerfile            ← Container image definition
├── constants.py          ← Shared constants
│
├── relay/               ← Host-side transport layer
│   ├── __init__.py      ← Exports: DockerBackend, SSHBackend, HostContainerBackend, AgentEndpoint
│   ├── base.py          ← RelayMessage dataclass
│   └── backends/
│       ├── __init__.py
│       ├── base.py      ← HostContainerBackend abstract interface
│       ├── docker.py    ← HTTP client to AgentServer (Docker)
│       └── ssh.py       ← SSH+curl client to AgentServer (remote hosts)
│
├── agent_side/          ← Agent-side AgentServer
│   ├── server.py        ← AgentServer HTTP server
│   ├── config.py        ← ConfigManager for per-agent config
│   ├── harness.py      ← Internal harness (manages delivery patterns)
│   └── patterns/
│       ├── inbox.py     ← File-based async delivery
│       └── sync.py      ← Direct subprocess delivery
│
├── agents/              ← Agent runtime adapters
│   └── adapters/
│       ├── __init__.py  ← Exports: AgentAdapter, AgentResponse, get_adapter()
│       ├── base.py      ← AgentAdapter ABC
│       ├── factory.py   ← Adapter factory
│       └── openclaw.py  ← OpenClaw implementation
│
├── examples/
│   └── moderator.py     ← Multi-agent orchestration example
│
├── containers/
│   └── config-sanitized/  ← Isolated OpenClaw config (no API keys)
│
├── specs/               ← Design decisions with rationale
├── tests/               ← Automated regression tests
├── dev/                 ← Manual/dev validation scripts
└── logs/                ← Runtime logs (gitignored)
```

## Design Principles

1. **HostContainerBackend is the transport interface** — DockerBackend and SSHBackend implement this interface, providing HTTP access to AgentServer instances.

2. **AgentServer owns agent lifecycle** — Each agent container runs an AgentServer that manages the agent subprocess (via AgentAdapter) and exposes HTTP endpoints for messaging.

3. **Moderator is an example** — Multi-agent orchestration is demonstrated via `examples/moderator.py`, not built into the core relay layer.

4. **No legacy harnesses** — The old `harnesses/` directory (gateway_harness, interactive_harness, multi_turn_harness, single_harness) was removed. AgentServer replaces all of these.

5. **Automated tests vs manual scripts are separated** — proper regression tests live under `tests/`; one-off developer scripts live under `dev/`.

## Removed Components

The following were removed in the cleanup:
- `relay/exec_relay.py` — Functionality merged into DockerBackend
- `relay/inbox_relay.py` — Superseded by agent_side/patterns/inbox.py
- `relay/websocket_relay.py` — Separate WebSocket hierarchy, not aligned
- `relay/inbox.py` — Legacy file-based inbox, superseded by agent_side/patterns/inbox.py
- `harnesses/` (entire directory) — Deprecated; AgentServer is the replacement
- `observability/` (entire directory) — Agent-side specific; will be re-added via AgentServer in future
- `workspaces/` (entire directory) — Template mechanism not aligned with AgentServer
- `adapters/` (root level) — ProvisionAdapter ABC was never used

## Future Components

- **Observability** — Will be integrated into AgentServer in a future phase
- **WebSocketBackend** — For persistent connections to AgentServer
