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

### 2. Start AgentServer (Agent Side)

Each agent runs `AgentServer` which exposes an HTTP interface for messaging:

```bash
# Start AgentServer in a container (sync delivery — direct request/response)
docker run -d --name my-agent \
  -e AGENT_ID=my-agent \
  -p 18080:8080 \
  --entrypoint python3 \
  agentia \
  /workspace/agent_side/server.py \
    --agent-id=my-agent --host=0.0.0.0 --port=8080 --delivery=sync
```

Or with inbox delivery (async, background processing):

```bash
docker run -d --name my-agent \
  -e AGENT_ID=my-agent \
  -p 18080:8080 \
  --entrypoint python3 \
  agentia \
  /workspace/agent_side/server.py \
    --agent-id=my-agent --host=0.0.0.0 --port=8080 --delivery=inbox
```

### 3. Send a Message (Host Side)

From the host, use `DockerBackend` to communicate with AgentServer:

```python
from relay.backends import DockerBackend, AgentEndpoint
from relay.base import RelayMessage

backend = DockerBackend({
    "my-agent": AgentEndpoint("my-agent", "localhost", 18080),
})

# Sync message — blocks until agent responds
msg = RelayMessage(to_agent="my-agent", content="What is 2+2?", from_agent="user")
response = backend.send_message(msg, "my-agent")
print(response)  # "2+2 equals 4"

# Async message — fire and forget
backend.send_message_async(msg, "my-agent")
```

### 4. Multi-Agent with Moderator

```python
from relay.moderator import Moderator, ModeratorConfig, AgentConfig
from relay.exec_relay import ExecRelay

config = ModeratorConfig(
    agents=[
        AgentConfig(
            id="analyst",
            name="Analyst",
            role="Research analyst",
            system_prompt="You are a research analyst.",
            ws_url="docker://analyst",
            agent_host="localhost",
            agent_port=18081,
        ),
        AgentConfig(
            id="critic",
            name="Critic",
            role="Critical reviewer",
            system_prompt="You are a critical reviewer.",
            ws_url="docker://critic",
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
print(mod.summarize())
```

---

## Architecture

```
Host side:
┌──────────────────────────────────────────────────────────────┐
│ BaseRelay (multi-agent routing, broadcast)                     │
│   ↓                                                           │
│ HostContainerBackend (Docker / SSH — pure transport)            │
│   ↓                                                           │
│ Network (HTTP to AgentServer)                                  │
└──────────────────────────────────────────────────────────────┘

Agent side (inside container):
┌──────────────────────────────────────────────────────────────┐
│ AgentServer (HTTP/WebSocket — control plane + messaging plane)  │
│   ├── Control: GET/PUT/PATCH /config, GET /status, POST /restart │
│   ├── Messaging: POST /message, POST /message/async, GET /response/{id} │
│   └── Harness (reads inbox, calls agent subprocess, writes response) │
│   ↓                                                           │
│ AgentAdapter → Agent process (OpenClaw)                        │
└──────────────────────────────────────────────────────────────┘
```

### Layers

| Layer | Responsibility | Files |
|-------|----------------|-------|
| **BaseRelay** | Multi-agent routing, broadcast, connection management | `relay/base.py` |
| **HostContainerBackend** | Adapts to deployment environment | `relay/backends/` |
| **AgentServer** | Delivery patterns, HTTP interface, owns AgentAdapter lifecycle | `agent_side/` |
| **AgentAdapter** | Per-message send/receive contract | `agents/adapters/` |

---

## AgentServer API

AgentServer runs on the agent side and exposes these endpoints:

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

# Switch to sync delivery
curl -X PATCH http://localhost:18080/config \
  -H "Content-Type: application/json" \
  -d '{"delivery":"sync"}'
```

See [SPEC 009](./specs/009_agentserver_api.md) for full API documentation.

---

## Current Status

**Phase 1-5 — AgentServer Architecture: DONE**
- `HostContainerBackend` interface + `DockerBackend` + `SSHBackend` ✅
- `AgentServer` with inbox + sync delivery patterns ✅
- `ExecRelay` / `InboxRelay` refactored to use `DockerBackend` ✅
- `Moderator` cleaned up (no more `isinstance` checks) ✅
- `gateway_harness` deprecated in favor of `AgentServer` ✅

**What's Working (2026-04-07)**
- AgentServer HTTP endpoints (`/message`, `/message/async`, `/response/{id}`, `/config`, `/status`, `/restart`) ✅
- DockerBackend → AgentServer communication ✅
- Inbox delivery pattern (file-based, background polling) ✅
- Sync delivery pattern (direct subprocess call) ✅
- AgentServer config persistence (`~/.agentia/agent.json`) ✅

**Next**
- WebSocketBackend for persistent connections (SPEC 005)
- Multi-agent end-to-end test with Moderator + 2x AgentServer

---

## File Structure

```
relay/
├── base.py              ← BaseRelay ABC + RelayMessage
├── moderator.py          ← Conversation orchestration
├── backends/
│   ├── base.py          ← HostContainerBackend interface
│   ├── docker.py        ← HTTP client to AgentServer
│   └── ssh.py           ← SSH tunnel + curl to AgentServer
└── patterns/            ← (legacy, now in agent_side/)

agent_side/
├── server.py            ← AgentServer HTTP/WebSocket server
├── config.py            ← Config management
├── harness.py           ← Internal harness (delivery pattern runner)
└── patterns/
    ├── inbox.py         ← Inbox delivery pattern
    └── sync.py          ← Sync delivery pattern

harnesses/
├── gateway_harness.py   ← DEPRECATED — use AgentServer instead
└── ...
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
- **Inbox**: Messages queued in file; harness polls; response written to correlation file
- **Sync**: Message delivered directly; harness calls subprocess; response returned immediately
- **Stream**: Deferred (SSE-based streaming)

---

## SPECs

| Spec | Status | Description |
|------|--------|-------------|
| 001 | done | Repository structure |
| 002 | done | OpenClaw agent adapter |
| 003 | done | Adapter Dockerfiles |
| 004 | done | Observability layer |
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
