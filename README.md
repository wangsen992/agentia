# Agentia — Federated Multi-Agent Organization System

**Mission:** Deploy AI agents as containers, managed from a host relay. Agents communicate asynchronously, expose HTTP APIs, and can be spawned, queried, and pruned from the host.

---

## Architecture

```
Host (your machine)                     Agent (Docker container)
─────────────────                      ───────────────────────
cli/host.py (agentia)                  cli/agent.py (agentia-agent)
  └─ HTTP POST /message ──────────────► agent_side/server.py
                                              └─ Harness
                                                    └─ PiAgentAdapter
                                                          └─ pi-agent subprocess
```

**Agent side** and **host side** are fully separate CLIs. The host CLI manages agents over HTTP — it works the same whether the agent is in Docker, SSH, or bare metal.

---

## Quick Start

### 1. Build the base image

```bash
docker build -t agentia .
```

### 2. Start an agent container (one-shot: install + serve)

```bash
# Workspace lives at ~/.agentia/<name>/workspace on the host
# Mount it into the container at /workspace
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    -v ~/.agentia/my-research-agent:/workspace \
    agentia serve \
      --install pi-agent \
      --config ~/.agentia/my-research-agent/agent.json \
      --provider minimax \
      --model MiniMax-M2.7 \
      --workspace /workspace \
      --role-goal "You are a helpful research assistant"
```

> All agent state — config, bootstrap files, skills, sessions — lives in `~/.agentia/<name>/` on the host. Snapshot the directory to snapshot the agent.

### 3. Register and manage from host

```bash
# Install host CLI
export PYTHONPATH=$PWD

# Register the agent
python3 cli/host.py register http://localhost:18080 --name my-research-agent

# List registered agents
python3 cli/host.py agents

# Send a message
python3 cli/host.py send my-research-agent "What can you do?"

# Check status (shows adapter, provider, model)
python3 cli/host.py status my-research-agent

# Update agent config (live)
python3 cli/host.py configure my-research-agent delivery inbox

# Re-render bootstrap files and restart agent
python3 cli/host.py update my-research-agent --role-goal "You specialize in turbulence modeling."

# Deregister
python3 cli/host.py deregister my-research-agent
```

---

## Two CLIs

### `agentia-agent` (agent side — runs in the container)

```bash
agentia-agent setup <adapter> [opts]   # render bootstrap + install runtime
agentia-agent serve [opts]            # start AgentServer HTTP API
```

**`setup`** — renders AGENTS.md, SYSTEM.md, TOOLS.md and runs the adapter's install script (e.g., `npm install -g @mariozechner/pi-coding-agent`). Must be called once before first `serve`.

**`serve`** — starts the AgentServer HTTP API. With `--install <adapter>`, runs `setup` first in the same container start — no `docker commit` workaround needed.

### `agentia` (host side — runs on your machine)

```bash
agentia register <url> --name <name>     # connect to an agent
agentia agents                           # list registered agents
agentia send <name> <message>            # send message (blocks)
agentia status <name>                    # get agent status
agentia configure <name> <key> <value>  # live config update
agentia update <name> [opts]             # re-render bootstrap + restart
agentia files <name> ls [path]          # list workspace files
agentia files <name> get <path>         # read workspace file
agentia files <name> put <path> -c "..." # write workspace file
agentia files <name> delete <path>      # delete workspace file
agentia snapshot <name> [out.tar.gz]   # snapshot workspace to .tar.gz
agentia deregister <name>               # remove from registry
agentia forward <name> <method> <path>  # raw HTTP passthrough
```

---

## AgentServer HTTP API

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET | `/status` | Agent health, delivery mode, adapter, provider, model |
| GET | `/config` | Get current config |
| PATCH | `/config` | Update config (`_restart: true` restarts agent subprocess) |
| PUT | `/config` | Replace entire config |
| POST | `/message` | Send message; blocks until agent finishes |
| POST | `/message/async` | Queue message; return correlation ID |
| GET | `/response/{id}` | Poll for async response |
| POST | `/restart` | Restart agent subprocess |
| GET | `/files/<path>` | Read workspace file |
| PUT | `/files/<path>` | Write workspace file (creates parent dirs) |
| DELETE | `/files/<path>` | Delete workspace file or directory |
| GET | `/files/` | List workspace directory |

### Status Response

`GET /status` returns:

```json
{
  "agent_id": "agent-001",
  "delivery": "inbox",
  "adapter": "pi-agent",
  "provider": "minimax",
  "model": "MiniMax-M2.7",
  "uptime": 26.7,
  "running": true,
  "ready": true
}
```

---

## Registry

Host registry: `~/.agentia/agents.json`

```json
{
  "version": 1,
  "agents": {
    "my-research-agent": {
      "url": "http://localhost:18080",
      "name": "my-research-agent",
      "registered_at": "2026-04-08T...",
      "last_seen_at": "2026-04-08T...",
      "metadata": {}
    }
  }
}
```

---

## Core Concepts

### AgentServer

Every agent container runs `agentia-agent serve`. It exposes an HTTP API that the host CLI talks to. No Docker/container management from the host CLI — those are handled by `docker` CLI directly.

### Delivery Modes

- **`sync`** — Harness calls the subprocess directly, returns response immediately
- **`inbox`** — Harness polls a file queue; useful when the subprocess is busy or long-running

Configure with `agentia configure <name> delivery sync`.

### Agent Adapters

The agent subprocess is swappable. Today we use **pi-agent**:

```
pi --mode rpc        # stdin/stdout JSONL protocol
                     # Reads bootstrap files: AGENTS.md, SYSTEM.md, TOOLS.md
```

---

## Project Layout

```
cli/
    agent.py          # Agent-side CLI (agentia-agent)
    host.py           # Host-side CLI (agentia)

agent_side/           # Container-side server
    server.py         # AgentServer HTTP API
    harness.py        # Spawns and manages agent subprocess
    config.py         # AgentServerConfig + ConfigManager
    patterns/
        inbox.py      # Inbox delivery pattern
        sync.py       # Sync delivery pattern

agents/adapters/      # Agent runtime adapters
    pi_agent.py       # pi-agent adapter (primary)
    openclaw.py       # OpenClaw adapter (legacy)
    factory.py        # get_adapter()

setup/adapters/       # Per-adapter setup templates
    pi-agent/
        install.sh    # Runtime install (npm install)
        config.tmpl  # Jinja2 → /etc/agentia/agent.json
        bootstrap/   # Jinja2 → AGENTS.md, SYSTEM.md, TOOLS.md

relay/                # Host-side library (legacy)
    backends/docker.py
    backends/ssh.py
```

---

## Design Decisions

**Separate CLIs** — agent side (`agentia-agent`) and host side (`agentia`) are fully independent. Host CLI works the same whether the agent is in Docker, SSH, or bare metal.

**HTTP between host and agent** — AgentServer is a simple HTTP server inside the container. No custom binary protocol, no shared filesystem required. Works identically whether the container is local (Docker) or remote (SSH + curl).

**Registry as local convenience** — The host CLI maps friendly names to URLs. Operations like `send`, `status`, `configure` all work by name lookup. If you know the URL directly, you can use `forward` without registering.

**`configure` vs `update`** — `configure` sends a live `PATCH /config` (delivery mode, polling interval). `update` sends a bootstrap change + `_restart: true`, which re-renders files and restarts the subprocess via `Harness.restart_agent()`.

### Snapshot

```bash
# Snapshot an agent's workspace to a .tar.gz archive
python3 cli/host.py snapshot my-research-agent
# Output: my-research-agent-snapshot.tar.gz (~5 entries, ~4KB)

# Restore: tar xzf my-research-agent-snapshot.tar.gz -C ~/.agentia/<name>/
# Clone:   cp -r ~/.agentia/<name-A>/ ~/.agentia/<name-B>/
```

**The filesystem API and `snapshot` work over HTTP** — they work the same way whether the agent is a local Docker container or a remote SSH machine. No special access needed beyond the AgentServer HTTP endpoint.

---

## CLI Reference

### Agent Side (in container)

```bash
# One-shot: install runtime + render config + start AgentServer
# Config and workspace default to ~/.agentia/ (no root needed)
agentia-agent serve \
    --install pi-agent \
    --config ~/.agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace

# Or two-step: setup first, then serve
agentia-agent setup pi-agent --config ~/.agentia/agent.json ...
agentia-agent serve --config ~/.agentia/agent.json
```

### Host Side (on your machine)

```bash
export PYTHONPATH=$PWD  # to run without installing

python3 cli/host.py register <url> --name <name>     # Connect to agent
python3 cli/host.py agents                            # List registered agents
python3 cli/host.py send <name> <message>            # Send message
python3 cli/host.py status <name>                     # Show agent status
python3 cli/host.py configure <name> <key> <value>   # Live config update
python3 cli/host.py update <name> --role-goal "..."  # Update bootstrap + restart
python3 cli/host.py files <name> ls [path]           # List workspace files
python3 cli/host.py files <name> get <path>          # Read workspace file
python3 cli/host.py files <name> put <path> -c "..." # Write workspace file
python3 cli/host.py files <name> delete <path>       # Delete workspace file
python3 cli/host.py snapshot <name> [out.tar.gz]    # Snapshot workspace
python3 cli/host.py deregister <name>                # Remove from registry
python3 cli/host.py forward <name> GET /status        # Raw HTTP passthrough
```

---

## References

- [SPEC 010 — CLI Interface](./specs/010_cli_interface.md)
- [pi-agent RPC protocol](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md)
