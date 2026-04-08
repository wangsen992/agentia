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

### 2. Create and Start an Agent

Use the `agentia` CLI to create and manage agent containers:

```bash
# Build an agent image (requires --from flag pointing to workspace)
agentia image build analyst --from /path/to/workspace

# Create and start an agent
agentia create analyst my-analyst

# List all agents
agentia agents
```

### 3. Send a Message

```python
from relay.backends import DockerBackend, AgentEndpoint
from relay.base import RelayMessage

backend = DockerBackend({
    "my-analyst": AgentEndpoint("my-analyst", "localhost", 18080),
})

msg = RelayMessage(to_agent="my-analyst", content="What is 2+2?", from_agent="user")
response = backend.send_message(msg, "my-analyst")
print(response)

backend.close()
```

### 4. Multi-Agent with Moderator

See `examples/moderator.py` for a complete example:

```python
from examples.moderator import Moderator, ModeratorConfig, AgentConfig

config = ModeratorConfig(
    agents=[
        AgentConfig(
            id="analyst",
            name="Analyst",
            role="Research analyst",
            system_prompt="You are a research analyst.",
            agent_host="localhost",
            agent_port=18081,
        ),
        AgentConfig(
            id="critic",
            name="Critic",
            role="Critical reviewer",
            system_prompt="You are a critical reviewer.",
            agent_host="localhost",
            agent_port=18082,
        ),
    ],
    topic="Should we use AI for research?",
    max_turns=4,
)

mod = Moderator(config)
mod.setup()
mod.run()
mod.print_transcript()
```

---

## Architecture

```
Host side:
┌──────────────────────────────────────────────────────────────┐
│  DockerBackend / SSHBackend (HostContainerBackend)            │
│    ↓                                                         │
│  Network (HTTP to AgentServer)                               │
└──────────────────────────────────────────────────────────────┘

Agent side (inside container):
┌──────────────────────────────────────────────────────────────┐
│  AgentServer                                                 │
│    ├── Control: GET/PUT/PATCH /config, GET /status, POST /restart │
│    ├── Messaging: POST /message, POST /message/async, GET /response/{id} │
│    └── Harness → AgentAdapter → OpenClaw subprocess          │
└──────────────────────────────────────────────────────────────┘
```

### Layers

| Layer | Responsibility | Files |
|-------|----------------|-------|
| **HostContainerBackend** | HTTP transport to AgentServer (Docker/SSH) | `relay/backends/` |
| **AgentServer** | Delivery patterns, HTTP interface, owns AgentAdapter lifecycle | `agent_side/` |
| **AgentAdapter** | Per-message send/receive contract | `agents/adapters/` |

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

# Check status
status = backend.get_status("agent-a")
print(status)  # {"status": "ready", "ready": True, "uptime": 123}

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

See [SPEC 009](./specs/009_agentserver_api.md) for full API documentation.

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
├── config.py            ← Config management
├── harness.py           ← Internal harness
└── patterns/
    ├── inbox.py         ← File-based inbox delivery
    └── sync.py          ← Direct subprocess delivery

agents/
└── adapters/
    ├── __init__.py      ← AgentAdapter, get_adapter()
    ├── base.py          ← AgentAdapter ABC
    ├── factory.py       ← Adapter factory
    └── openclaw.py      ← OpenClaw implementation

examples/
└── moderator.py         ← Multi-agent orchestration example

containers/
└── config-sanitized/   ← Isolated OpenClaw config (no API keys)
```

---

## Design Decisions

### Orchestration: Moderator First
- Start with structured moderator pattern (NOT autonomous/emergent)
- Autonomous is the end state, not the starting point
- Controlled case needed before emergent behavior is meaningful to study

### Transport: HTTP to AgentServer
- AgentServer runs inside each agent container/VM
- HostContainerBackend (DockerBackend, SSHBackend) makes HTTP calls to AgentServer
- Deployment-agnostic — works with Docker, SSH, cloud hosts alike

### Delivery Patterns (AgentServer-side)
- **Sync**: Message delivered directly; harness calls subprocess; response returned immediately
- **Inbox**: Messages queued in file; harness polls; response written to correlation file

---

## SPECs

| Spec | Status | Description |
|------|--------|-------------|
| 001 | done | Repository structure |
| 002 | done | OpenClaw agent adapter |
| 003 | done | Adapter Dockerfiles |
| 005 | done | Relay/Inbox architecture (AgentServer refactor) |
| 006 | done | Orchestration patterns decision |
| 007 | done | Agent provision + workspace |
| 008 | done | Agent self-configuration (verify loop) |
| 009 | done | AgentServer API specification |

---

## Security Model

**Host config isolation is strictly enforced.** The agent container never mounts the host's `~/.openclaw/` directory.

### How agentia handles it
1. **At build time:** OpenClaw config is COPY'd into the Docker image
2. **At container create:** Image config is extracted to `~/.agentia/containers/{id}/`
3. **At container run:** That per-container copy is mounted as a volume

```
Host ~/.agentia/containers/{id}/openclaw/  →  Container /root/.openclaw/
Host ~/.openclaw/  ← NEVER touched
```

---

## References

- Issue #12: [AgentServer meta-issue](https://github.com/wangsen992/agentia/issues/12)
- SPEC 005: [Relay & Inbox Architecture](./specs/005_relay_inbox.md)
- SPEC 009: [AgentServer API](./specs/009_agentserver_api.md)
- Inspired by: multi-agent LLMs (Anthropic 2025), AutoGen Core, Agentic workflows

## License

Private — internal research
