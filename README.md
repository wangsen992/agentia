# Agentia — Federated Multi-Agent Organization System

**Mission:** Deploy AI agents as containers, managed from a host relay. Agents communicate asynchronously, expose HTTP APIs, and can be spawned, queried, and pruned from the host.

---

## What Is This?

Agentia has two sides:

- **Host side** (`relay/`) — A Python process you run. Manages agent containers, sends messages, collects responses.
- **Agent side** (`agent_side/`) — A container that runs inside Docker. Boots a Python HTTP server and spawns an agent subprocess.

```
Host (your machine)                     Agent (Docker container)
─────────────────                      ───────────────────────
relay/backends/docker.py
  └─ HTTP POST /message ──────────────► agent_side/server.py
                                              └─ Harness
                                                    └─ PiAgentAdapter
                                                          └─ `pi` subprocess
```

---

## Quick Start

```bash
# 1. Build the generic agent image
docker build -t agentia .

# 2. One-time setup: install runtime, then commit the container as an image
CONTAINER_ID=$(docker run -d agentia \
    install pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace)

sleep 25  # wait for install (npm + file render) to finish
docker commit $CONTAINER_ID my-agent-image
docker rm $CONTAINER_ID

# 3. Start AgentServer
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    my-agent-image agentserver

# 4. Send a message
curl -s -X POST http://localhost:18080/message \
    -H "Content-Type: application/json" \
    -d '{"content": "What can you do?"}'
```

> **Note:** pi-agent requires an LLM API key. Set `MINIMAX_API_KEY` (or your provider's env var) on the `docker run` command above.

Or use the Python host-side library directly:

```python
from relay.backends import DockerBackend, AgentEndpoint
from relay.base import RelayMessage

backend = DockerBackend({
    "my-agent": AgentEndpoint("my-agent", "localhost", 18080),
})

msg = RelayMessage(content="What can you do?", to_agents=["my-agent"])
response = backend.send_message(msg, "my-agent")
print(response)
backend.close()
```

---

## Core Concepts

### AgentServer

Every agent container runs `agentia agentserver` on start. It exposes an HTTP API:

| Method | Endpoint | What it does |
|--------|----------|--------------|
| POST | `/message` | Send a message; blocks until agent finishes; returns response |
| POST | `/message/async` | Queue message immediately; returns a correlation ID |
| GET | `/response/{id}` | Poll for an async response |
| GET | `/status` | Health check |
| PATCH | `/config` | Update delivery mode (`sync` or `inbox`) |

### Agent Adapters

The agent subprocess is swappable. Today we use **pi-agent**:

```
pi --mode rpc        # stdin/stdout JSONL protocol
                     # Reads bootstrap files: AGENTS.md, SYSTEM.md, TOOLS.md
```

To add a new runtime (e.g. openclaw, AutoGen), implement `AgentAdapter` and register it in `agents/adapters/factory.py`.

### Delivery Modes

Inside the container, `Harness` delivers messages to the agent subprocess:

- **`sync`** — Harness calls the subprocess directly, returns response immediately
- **`inbox`** — Harness polls a file queue; useful when the subprocess is busy or long-running

---

## Project Layout

```
relay/                       # Host-side library
├── backends/docker.py       # HTTP client → AgentServer
├── backends/ssh.py          # SSH + curl → remote AgentServer
└── base.py                  # RelayMessage dataclass

agent_side/                  # Container-side server
├── server.py                # AgentServer HTTP API
├── harness.py               # Spawns and manages agent subprocess
├── config.py                # AgentServerConfig dataclass
└── patterns/
    ├── inbox.py             # Inbox delivery pattern
    └── sync.py              # Sync delivery pattern

agents/adapters/             # Agent runtime adapters
├── pi_agent.py              # pi-agent adapter (primary)
├── openclaw.py              # OpenClaw adapter (legacy)
└── factory.py               # get_adapter() — pi-agent is default

setup/adapters/              # Per-adapter setup templates
├── pi-agent/
│   ├── install.sh           # Runtime install (npm install)
│   ├── config.tmpl          # Jinja2 → /etc/agentia/agent.json
│   └── bootstrap/           # Jinja2 → AGENTS.md, SYSTEM.md, TOOLS.md
└── openclaw/                # Legacy adapter
```

---

## CLI Reference

```bash
# Install runtime + render config inside a running container
docker run --rm agentia install pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace

# Start AgentServer (blocks — runs inside container)
docker run -d --name my-agent agentia agentserver

# Container lifecycle (host side)
agentia create <image> <name>           # Create container from image
agentia start <name>                   # Start container
agentia stop <name>                    # Stop container
agentia destroy <name>                 # Remove container
agentia agents                        # List all containers
agentia send <name> <message>          # Send message via HTTP
agentia logs <name>                    # Container logs
```

---

## Design Decisions

**pi-agent over OpenClaw** — Transparent bootstrap via plain files. No hidden system prompt injection. Subprocess-per-agent is simple and debuggable.

**HTTP between host and agent** — AgentServer is a simple HTTP server inside the container. No custom binary protocol, no shared filesystem required. Works identically whether the container is local (Docker) or remote (SSH + curl).

**Generic base image** — The Docker image contains Python + Node.js. The agent runtime (pi-agent) is installed at container start via `agentia install`. This keeps the image simple and adapter-specific dependencies out of the base.

**Inbox delivery by default** — The harness polls for responses rather than blocking the subprocess. This means the subprocess can be mid-task when a new message arrives — the message waits in the inbox file queue.

---

## SPECs

| # | Status | Description |
|---|--------|-------------|
| 001 | done | Repository structure |
| 002 | done | Agent adapter abstraction |
| 003 | done | Adapter-specific container images |
| 005 | done | Relay/Inbox architecture |
| 006 | done | Orchestration patterns |
| 007 | done | Agent provision + workspace |
| 009 | done | AgentServer API |

Full specs at `specs/` and in each adapter's directory.

---

## References

- [Issue #17 — pi-agent as primary runtime](https://github.com/wangsen992/agentia/issues/17)
- [pi-agent RPC protocol](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md)
- [SPEC 009 — AgentServer API](./specs/009_agentserver_api.md)
- [SPEC 005 — Relay/Inbox Architecture](./specs/005_relay_inbox.md)
