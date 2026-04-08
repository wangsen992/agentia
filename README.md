# Agentia — Federated Multi-Agent Organization System

**Mission:** Build a living, evolving organization of AI agents that communicate asynchronously, maintain hierarchical structure, and can self-manage through dynamic spawn and prune operations.

---

## Quick Start

### 1. Build the Container

```bash
git clone https://github.com/wangsen992/agentia.git
cd agentia
docker build -t agentia .
```

### 2. Setup Agent Runtime (pi-agent)

pi-agent is Agentia's primary agent runtime. Install it at container start:

```bash
agentia install pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace
```

### 3. Start AgentServer

```bash
agentia agentserver
```

### 4. Create and Manage Agents

```bash
# Build an image
agentia image build my-agent --from /path/to/workspace

# Create and start agent
agentia create my-image my-agent \
    --adapter pi-agent \
    --provider minimax \
    --model MiniMax-M2.7

# List agents
agentia agents

# Send a message
agentia send my-agent "Hello, what can you do?"
```

---

## Architecture

```
Host side:
┌──────────────────────────────────────────────────────────────┐
│  DockerBackend / SSHBackend (HostContainerBackend)             │
│    ↓                                                          │
│  Network (HTTP to AgentServer)                                │
└──────────────────────────────────────────────────────────────┘

Agent side (inside container):
┌──────────────────────────────────────────────────────────────┐
│  AgentServer                                                 │
│    ├── Control: GET/PUT/PATCH /config, GET /status           │
│    ├── Messaging: POST /message, POST /message/async         │
│    └── Harness → PiAgentAdapter → pi --mode rpc subprocess   │
└──────────────────────────────────────────────────────────────┘

pi-agent subprocess:
  stdin/stdout JSONL
  Bootstrap files: AGENTS.md, SYSTEM.md (written by agentia install)
```

### Runtime Installation

The `agentia install` command renders Jinja2 templates and installs the agent runtime:

```bash
agentia install <adapter> --config <path> [options]
```

Templates are in `setup/adapters/<adapter>/`:
- `config.tmpl` → `/etc/agentia/agent.json`
- `bootstrap/*.tmpl` → `AGENTS.md`, `SYSTEM.md` in workspace
- `install.sh` → runtime-specific installation

---

## pi-agent Adapter

pi-agent runs as a subprocess with JSONL stdin/stdout protocol. It is Agentia's **primary** agent runtime.

### Key features:
- **Transparent bootstrap** — AGENTS.md/SYSTEM.md are plain files written by `agentia install`
- **Clean RPC protocol** — stdin/stdout JSONL, no gateway, no hidden state
- **Subprocess-per-agent** — dead simple isolation
- **Session branching** — tree-structured sessions

### Adding a new adapter

1. Create `setup/adapters/<name>/install.sh` — runtime install
2. Create `setup/adapters/<name>/config.tmpl` — Jinja2 config template
3. Create `setup/adapters/<name>/bootstrap/*.tmpl` — bootstrap templates
4. `agentia install <name>` works automatically

See `setup/README.md` for details.

---

## Transport Backends

### DockerBackend (HTTP to AgentServer)

```python
from relay.backends import DockerBackend, AgentEndpoint

backend = DockerBackend({
    "agent-a": AgentEndpoint("agent-a", "localhost", 18080),
    "agent-b": AgentEndpoint("agent-b", "localhost", 18081),
})

# Sync send — blocks until response
response = backend.send_message(msg, "agent-a")

# Async send — fire and forget
backend.send_message_async(msg, "agent-a")

# Broadcast to multiple agents
backend.broadcast(RelayMessage(to_agents=["agent-a", "agent-b"], content="Hello"))

backend.close()
```

### SSHBackend (SSH + curl to remote AgentServer)

```python
from relay.backends import SSHBackend, AgentEndpoint

backend = SSHBackend(
    endpoints={
        "agent-remote": AgentEndpoint("agent-remote", "user@ssh.example.com", 8080),
    },
    ssh_user="root",
)

response = backend.send_message(msg, "agent-remote")
backend.close()
```

---

## AgentServer API

AgentServer runs inside each agent container and exposes these endpoints:

### Control Plane

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | Read current config |
| PUT | `/config` | Replace entire config |
| PATCH | `/config` | Partial update (e.g. `{"delivery": "sync"}`) |
| GET | `/status` | Health + readiness |
| POST | `/restart` | Restart agent subprocess |
| GET | `/metrics` | Telemetry |

### Host Messaging Plane

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/message` | Sync — blocks until agent finishes, returns response |
| POST | `/message/async` | Async — queues immediately, returns `{queued: true, correlation_id}` |
| GET | `/response/{correlation_id}` | Poll for async response |

### Example

```bash
# Check status
curl http://localhost:18080/status

# Send sync message
curl -X POST http://localhost:18080/message \
  -H "Content-Type: application/json" \
  -d '{"content":"What is 2+2?"}'

# Switch delivery mode
curl -X PATCH http://localhost:18080/config \
  -H "Content-Type: application/json" \
  -d '{"delivery":"inbox"}'
```

---

## File Structure

```
relay/
├── __init__.py          ← DockerBackend, SSHBackend, HostContainerBackend, AgentEndpoint
├── base.py              ← RelayMessage dataclass
└── backends/
    ├── __init__.py
    ├── base.py          ← HostContainerBackend interface
    ├── docker.py        ← HTTP client to AgentServer
    └── ssh.py           ← SSH + curl client to AgentServer

agent_side/
├── server.py            ← AgentServer HTTP server
├── config.py            ← Config management (adapter fields added)
├── harness.py          ← Internal harness
└── patterns/
    ├── inbox.py         ← File-based inbox delivery
    └── sync.py          ← Direct subprocess delivery

agents/adapters/
├── __init__.py          ← AgentAdapter, get_adapter()
├── base.py              ← AgentAdapter ABC
├── factory.py           ← Adapter factory (pi-agent default)
├── pi_agent.py          ← pi-agent implementation (primary)
└── openclaw.py          ← OpenClaw implementation (legacy)

setup/
├── README.md             ← How to add new adapter
└── adapters/
    ├── pi-agent/
    │   ├── install.sh
    │   ├── config.tmpl
    │   └── bootstrap/
    │       ├── AGENTS.md.tmpl
    │       ├── SYSTEM.md.tmpl
    │       └── TOOLS.md.tmpl
    └── openclaw/
        ├── install.sh
        ├── config.tmpl
        └── bootstrap/

examples/
└── moderator.py         ← Multi-agent orchestration example
```

---

## Design Decisions

### Primary Runtime: pi-agent
- **pi-agent** replaces OpenClaw as the primary agent runtime
- Transparent bootstrap via plain files (AGENTS.md, SYSTEM.md)
- No hidden system prompt injection
- Clean subprocess-per-agent isolation

### Transport: HTTP to AgentServer
- AgentServer runs inside each agent container/VM
- HostContainerBackend (DockerBackend, SSHBackend) makes HTTP calls to AgentServer
- Deployment-agnostic — works with Docker, SSH, cloud hosts alike

### Delivery Patterns (AgentServer-side)
- **Sync**: Message delivered directly; harness calls subprocess; response returned immediately
- **Inbox**: Messages queued in file; harness polls; response written to correlation file

### Orchestration: Moderator First
- Start with structured moderator pattern (NOT autonomous/emergent)
- Autonomous is the end state, not the starting point

---

## SPECs

| Spec | Status | Description |
|------|--------|-------------|
| 001 | done | Repository structure |
| 002 | done | Agent adapter abstraction (PiAgentAdapter + factory) |
| 003 | done | Adapter-specific container images (generic base + runtime install) |
| 005 | done | Relay/Inbox architecture (AgentServer refactor) |
| 006 | done | Orchestration patterns decision |
| 007 | done | Agent provision + workspace |
| 009 | done | AgentServer API specification |

---

## References

- Issue #12: [AgentServer meta-issue](https://github.com/wangsen992/agentia/issues/12)
- Issue #17: [pi-agent as Primary Agent Runtime](https://github.com/wangsen992/agentia/issues/17)
- Issue #15: [Observability](https://github.com/wangsen992/agentia/issues/15)
- pi-agent RPC docs: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md
- SPEC 002: [Agent Adapter Abstraction](./specs/002_agent_adapter.md)
- SPEC 003: [Adapter Dockerfiles](./specs/003_adapter_dockerfiles.md)
- SPEC 005: [Relay & Inbox Architecture](./specs/005_relay_inbox.md)
- SPEC 009: [AgentServer API](./specs/009_agentserver_api.md)
- Inspired by: multi-agent LLMs (Anthropic 2025), AutoGen Core, Agentic workflows

## License

Private — internal research
