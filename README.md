# Agentia — Federated Multi-Agent Organization System

**Mission:** Deploy AI agents as containers, managed from a host relay. Agents communicate asynchronously, expose HTTP APIs, and can be spawned, queried, and pruned from the host.

---

## Architecture

```
Host (your machine)                     Agent (Docker container)
─────────────────                      ───────────────────────
python3 cli/host.py                      agentia-agent serve
  └─ HTTP API ─────────────────────────►  agent_side/server.py
                                             └─ SessionManager (multi-session)
                                                   └─ Harness
                                                         └─ PiAgentAdapter
                                                               └─ pi-agent subprocess
```

**Two CLIs:** `cli/host.py` (host side, on your machine) and `cli/agent.py` (agent side, runs in the container). They communicate over HTTP — the host CLI works identically whether the agent is in Docker, SSH, or bare metal.

---

## Quick Start

### 1. Build the image

```bash
docker build -t agentia .
```

### 2. Start an agent container

```bash
# pi-agent natural design: mount host workspace to ~/.pi/agent/ inside container
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    -e PI_DIR=/root/.pi/agent \
    -v ~/.agentia/agents/my-research-agent:/root/.pi/agent \
    agentia serve \
      --install pi-agent \
      --config /root/.pi/agent/agent.json \
      --provider minimax \
      --model MiniMax-M2.7 \
      --workspace /root/.pi/agent
```

> All agent state — config, bootstrap files, skills, sessions — lives in `~/.agentia/agents/<name>/` on the host. pi-agent uses its natural layout (`~/.pi/agent/`) inside the container. Snapshot: `cp -r ~/.agentia/agents/my-research-agent/`.

### 3. Manage from host

```bash
export PYTHONPATH=$PWD

# Register the agent
python3 cli/host.py register http://localhost:18080 --name my-agent

# Send a message
python3 cli/host.py send my-agent "What can you do?"

# List agents
python3 cli/host.py agents
```

---

## Session Management

Each conversation with an agent is a **named session** — a persistent pi subprocess with its own session file. Sessions survive agent restarts.

```bash
# Send to a named conversation (creates or resumes)
python3 cli/host.py send my-agent "Plan my Hawaii trip" --conv hawaii

# Send to a second conversation
python3 cli/host.py send my-agent "Tell me about CFD" --conv crocus

# List all sessions for an agent
python3 cli/host.py sessions my-agent

# Manually compact a session
python3 cli/host.py compact my-agent --conv hawaii

# Delete a session (stops subprocess, keeps session file)
python3 cli/host.py session delete my-agent hawaii

# Delete a session + session file
python3 cli/host.py session delete my-agent hawaii --hard
```

### Session behavior

- **Auto-resume**: sending to an existing session name reconnects to its session file
- **Idle timeout**: subprocesses auto-stop after `session_idle_ttl` seconds (default: 30 min). Session file is preserved.
- **LRU eviction**: when `max_sessions` limit is hit, oldest running session is stopped to make room
- **Auto-compact**: when context window reaches `context_threshold_pct` (default: 75%), pi auto-compacts before the next response

### Session lifecycle flags

| Flag | Default | What it controls |
|------|---------|------------------|
| `--session-ttl` | `1800` (30 min) | Idle timeout before subprocess auto-stops |
| `--max-sessions` | `10` | Max concurrent running subprocesses |
| `--context-threshold` | `75` | Context % to trigger auto-compact |

```bash
docker run ... agentia serve \
    --session-ttl 300 \          # Override: stop after 5 min idle
    --max-sessions 5 \           # Override: max 5 concurrent sessions
    --context-threshold 80        # Override: compact at 80% context
```

---

## Files API

Manage files in the agent's workspace over HTTP:

```bash
python3 cli/host.py files my-agent ls
python3 cli/host.py files my-agent get memory/2026-04-08.md
python3 cli/host.py files my-agent put memory/2026-04-08.md --from /tmp/mem.md
python3 cli/host.py files my-agent put notes.md -c "Hello world"
python3 cli/host.py files my-agent edit memory/2026-04-08.md   # Opens in $EDITOR, uploads on save
python3 cli/host.py files my-agent delete tmp/cache.txt
```

---

## Snapshot

```bash
# Snapshot an agent's workspace to a .tar.gz archive
python3 cli/host.py snapshot my-agent
# Output: my-agent-snapshot.tar.gz

# Restore: tar xzf my-agent-snapshot.tar.gz -C ~/.agentia/<name>/
# Clone:   cp -r ~/.agentia/<name-A>/ ~/.agentia/<name-B>/
```

Snapshot and Files API work over HTTP — no special access needed beyond the AgentServer endpoint.

---

## AgentServer HTTP API

### Core

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET | `/status` | Agent health, adapter, provider, model, uptime |
| GET | `/metrics` | Prometheus-compatible metrics (uptime, request counts, errors) |
| GET | `/config` | Get current config |
| PATCH | `/config` | Update config (`_restart: true` restarts subprocess) |
| PUT | `/config` | Replace entire config |
| POST | `/message` | Send message (legacy single-session, blocks for response) |
| POST | `/message/async` | Queue message; return correlation ID |
| GET | `/response/{id}` | Poll for async response |
| POST | `/restart` | Restart agent subprocess |
| GET | `/inbox` | List queued inbox messages |
| GET | `/inbox/{id}` | Get specific inbox message |

### Files

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET | `/files/` | List workspace directory |
| GET | `/files/<path>` | Read workspace file |
| PUT | `/files/<path>` | Write workspace file |
| DELETE | `/files/<path>` | Delete file or directory |

### Sessions

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET | `/sessions` | List all sessions |
| GET | `/sessions/<name>` | Get session details |
| POST | `/sessions/new` | Create or resume a named session |
| POST | `/sessions/<name>/message` | Send message to a session |
| POST | `/sessions/<name>/compact` | Trigger manual compaction |
| DELETE | `/sessions/<name>` | Stop subprocess (session file kept) |
| DELETE | `/sessions/<name>?hard=true` | Stop and delete session file |

### `GET /status` response

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

### `GET /sessions` response

```json
[
  {"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "message_count": 12, "context_pct": 23, "last_active": "2026-04-09T03:00:00Z"},
  {"name": "2026-04-09T01-10-00_crocus", "title": "crocus", "status": "stopped", "message_count": 47, "context_pct": 71, "last_active": "2026-04-09T01:30:00Z"}
]
```

---

## Two CLIs

### `cli/agent.py` — agent-side (runs in container)

```bash
# One-shot: install runtime + start AgentServer
agentia-agent serve \
    --install pi-agent \
    --config /root/.pi/agent/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /root/.pi/agent \
    --session-ttl 300 \
    --max-sessions 5 \
    --context-threshold 80

# Or two-step
agentia-agent setup pi-agent --config /root/.pi/agent/agent.json ...
agentia-agent serve --config /root/.pi/agent/agent.json
```

### `cli/host.py` — host-side (runs on your machine)

```bash
# Register and manage
python3 cli/host.py register <url> --name <name>
python3 cli/host.py agents
python3 cli/host.py status <name>
python3 cli/host.py configure <name> delivery sync
python3 cli/host.py update <name> --role-goal "You specialize in turbulence."
python3 cli/host.py deregister <name>
python3 cli/host.py prune              # Remove unreachable agents from registry

# Messaging
python3 cli/host.py send <name> <message> [--conv <session-name>]

# Sessions
python3 cli/host.py sessions <name>                    # List sessions
python3 cli/host.py compact <name> --conv <session>  # Trigger compaction
python3 cli/host.py session delete <name> <session> [--hard]

# Files
python3 cli/host.py files <name> ls [path]
python3 cli/host.py files <name> get <path>
python3 cli/host.py files <name> put <path> -c "..." | --from <file>
python3 cli/host.py files <name> edit <path>
python3 cli/host.py files <name> delete <path>

# Workspace snapshot
python3 cli/host.py snapshot <name> [out.tar.gz]

# Raw HTTP passthrough
python3 cli/host.py forward <name> GET /status
```

---

## Registry

Host registry: `~/.agentia/agents.json`

```json
{
  "version": 1,
  "agents": {
    "my-agent": {
      "url": "http://localhost:18080",
      "name": "my-agent",
      "registered_at": "2026-04-09T...",
      "last_seen_at": "2026-04-09T...",
      "metadata": {}
    }
  }
}
```

The registry maps friendly names to URLs. Operations like `send`, `status`, `sessions` all work by name lookup. Use `forward` for direct URL access without registration.

---

## Project Layout

```
cli/
    agent.py          # Agent-side CLI (agentia-agent, runs in container)
    host.py           # Host-side CLI (python3 cli/host.py, runs on host)

agent_side/
    server.py         # AgentServer HTTP API (multi-session)
    harness.py        # Spawns and manages agent subprocess
    config.py         # AgentServerConfig + ConfigManager
    patterns/
        inbox.py      # Inbox delivery pattern
        sync.py       # Sync delivery pattern

agents/adapters/
    pi_agent.py       # pi-agent adapter + SessionManager
    openclaw.py       # OpenClaw adapter (legacy)
    factory.py        # get_adapter()

setup/adapters/       # Per-adapter setup templates
    pi-agent/
        install.sh
        config.tmpl
        bootstrap/

specs/
    010_cli_interface.md
    020_session_management.md

README.md
```

---

## Design Decisions

**HTTP between host and agent** — AgentServer is a simple HTTP server inside the container. No custom binary protocol, no shared filesystem required. Works identically for Docker, SSH, or bare metal.

**Session management is server-owned (Option A)** — AgentServer owns session state: the manifest, subprocesses, idle timers, LRU eviction. The host CLI is a dumb client that calls the API. This mirrors how OpenClaw manages Jarvis's sessions.

**Workspace lives on the host** — `~/.agentia/agents/<name>/` is bind-mounted into the container at `~/.pi/agent/` (pi-agent's natural home). The host has full access to all agent state. Snapshot: `cp -r ~/.agentia/agents/<name>/`.

**pi-agent for agent runtime** — `pi --mode rpc` gives us a robust JSONL stdin/stdout protocol, session files, built-in compaction, and tool execution. The `AGENTS.md` system prompt is injected via `--append-system-prompt`.

**Configurable idle/session limits** — `session_idle_ttl`, `max_sessions`, and `context_threshold_pct` let you tune resource usage per deployment.

---

## References

- [SPEC 020 — Session Management](./specs/020_session_management.md)
- [pi-agent RPC protocol](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md)
