# Agentia — Federated Multi-Agent System

**Mission:** Deploy AI agents on any machine, manage them from anywhere. Agents communicate over HTTP — no shared filesystem, no custom protocol, no central hub.

---

## What Is This?

Agentia is a lightweight framework for running multiple AI agents across different machines, with each agent running as an independent HTTP server. You communicate with agents using a simple CLI — from your Mac, from another agent, from a script.

**The key idea:** every machine runs the same two things:
- **`agent.py`** — the server, exposing an HTTP API
- **`host.py`** — the client, available as a CLI tool and to other agents

Any agent can talk to any other agent by HTTP. No hub, no central server.

---

## Architecture

```
Machine A (your Mac)                    Machine B (cloud VM)
────────────────────                  ─────────────────────
python3 cli/host.py                    python3 cli/agent.py
  └─ send, status, files...             └─ AgentServer :8080
         │                                      │
         └────── HTTP POST /sessions/... ◄──────┘
                    message + response
```

```
Machine A (Agent A)                    Machine B (Agent B)
────────────────────                  ─────────────────────
python3 cli/agent.py                     python3 cli/agent.py
  └─ AgentServer :8080                   └─ AgentServer :8080

Agent A's host.py ──── HTTP ──── Agent B's AgentServer
```

**Two CLIs:**
- **`python cli/agent.py`** — runs on each agent machine, starts the HTTP server
- **`python cli/host.py`** — runs anywhere, sends messages to any agent by URL

---

## Quick Start

### 1. Build the image

```bash
cd agentia
docker build -t agentia .
```

### 2. Start an agent container

```bash
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    -e PI_DIR=/root/.pi/agent \
    -v ~/.agentia/agents/my-agent:/root/.pi/agent \
    python cli/agent.py serve \
      --install pi-agent \
      --config /root/.pi/agent/agent.json \
      --provider minimax \
      --model MiniMax-M2.7 \
      --workspace /root/.pi/agent
```

> All agent state — config, sessions, workspace — lives in `~/.agentia/agents/<name>/` on the host. The container is stateless.

### 3. Send a message

```bash
export PYTHONPATH=$PWD

# Register the agent (first time only)
python3 cli/host.py register http://localhost:18080 --name my-agent

# Send a message
python3 cli/host.py send my-agent "What can you do?"

# List agents
python3 cli/host.py agents
```

---

## Deploying on a Remote VM (Bare Metal)

No Docker required on the remote — just Python 3 and curl. The setup script handles everything.

### On the remote machine (one-time setup):

```bash
# Download and run the setup script
git clone https://github.com/your/agentia.git
cd agentia
chmod +x setup/setup-remote.sh

# Run setup — answer the prompts
export MINIMAX_API_KEY=your_key
./setup/setup-remote.sh \
    --name research-agent \
    --provider minimax \
    --model MiniMax-M2.7 \
    --role-goal "You are a research assistant specializing in fluid dynamics."

# Start AgentServer
cd agentia
export MINIMAX_API_KEY=your_key
python3 cli/agent.py serve --config ~/.pi/agent/agent.json \
    --provider minimax --model MiniMax-M2.7 --workspace ~/.pi/agent
```

The setup script:
1. Checks prerequisites (Python 3.8+, curl)
2. Installs pi-agent (binary + companion files)
3. Creates the agent config at `~/.pi/agent/agent.json`
4. Prints the AgentServer URL and registration command

### On your Mac:

```bash
# Register the remote agent
python3 cli/host.py register http://<vm-ip>:8080 --name research-agent

# Use it like any other agent
python3 cli/host.py send research-agent "What can you do?"
```

### If the VM has no public IP (SSH tunnel fallback):

```bash
# SSH tunnel: remote port 8080 → local 18080
ssh -L 18080:localhost:8080 user@vm

# On your Mac, AgentServer is now at localhost:18080
python3 cli/host.py register http://localhost:18080 --name research-agent
```

---

## Managing Agents

```bash
# Register an agent by URL
python3 cli/host.py register http://vm.example.com:8080 --name research-agent

# List all registered agents
python3 cli/host.py agents

# Check agent health
python3 cli/host.py status my-agent

# Update agent configuration (live)
python3 cli/host.py configure my-agent delivery sync
python3 cli/host.py configure my-agent role.goal "You specialize in turbulence modeling."

# Remove from registry
python3 cli/host.py deregister my-agent

# Prune unreachable agents (cleans up stale registry entries)
python3 cli/host.py prune
```

---

## Conversations and Sessions

Each conversation maps to a **named session** — a persistent subprocess with its own session file.

```bash
# Send to a named conversation (creates or resumes)
python3 cli/host.py send my-agent "Plan my Hawaii trip" --conv hawaii

# Send without --conv: uses last active conversation (smart routing)
python3 cli/host.py send my-agent "Update the research notes"

# Start a new conversation (name derived from first message)
python3 cli/host.py send my-agent "Let's start something new" --new

# List all conversations
python3 cli/host.py conv list my-agent

# Show conversation details
python3 cli/host.py conv show my-agent hawaii

# Switch active conversation
python3 cli/host.py conv use my-agent crocus

# Tag a conversation
python3 cli/host.py conv tag my-agent hawaii --tag travel

# Delete a conversation
python3 cli/host.py conv delete my-agent hawaii

# List agent sessions
python3 cli/host.py sessions my-agent

# Manually compact a session (reduces context window)
python3 cli/host.py compact my-agent --conv hawaii

# Delete a session
python3 cli/host.py session delete my-agent hawaii
python3 cli/host.py session delete my-agent hawaii --hard  # also deletes session file
```

### Session behavior

| Feature | Behavior |
|---|---|
| **Auto-resume** | Sending to an existing session name reconnects to the same subprocess |
| **Idle timeout** | Subprocess auto-stops after idle TTL (default: 30 min). Session file preserved. |
| **LRU eviction** | At `max_sessions` limit, oldest running session is stopped to make room |
| **Auto-compact** | When context reaches `context_threshold_pct` (default: 75%), pi compacts before responding |

### Session lifecycle flags

```bash
python cli/agent.py serve \
    --session-ttl 300 \          # Idle timeout: 5 min (default: 1800 = 30 min)
    --max-sessions 5 \           # Max concurrent sessions (default: 10)
    --context-threshold 80        # Compact at 80% context (default: 75)
```

---

## Interactive REPL

```bash
# Chat with an agent interactively
python3 cli/host.py chat my-agent

# Start in a specific conversation
python3 cli/host.py chat my-agent --conv hawaii

# Start a new conversation
python3 cli/host.py chat my-agent --new
```

Inside the REPL:
- Type messages to send to the agent
- `/new` — start a new conversation
- `/conv <name>` — switch to an existing conversation
- `/sessions` — list sessions
- `/quit` — exit

---

## Files API

Manage files in an agent's workspace over HTTP:

```bash
python3 cli/host.py files my-agent ls
python3 cli/host.py files my-agent get memory/2026-04-08.md
python3 cli/host.py files my-agent put notes.md -c "Hello world"
python3 cli/host.py files my-agent edit memory/2026-04-08.md   # Opens in $EDITOR
python3 cli/host.py files my-agent delete tmp/cache.txt
```

---

## Workspace Snapshot

```bash
# Snapshot an agent's workspace to a .tar.gz archive
python3 cli/host.py snapshot my-agent
# Output: my-agent-snapshot.tar.gz

# Restore: tar xzf my-agent-snapshot.tar.gz -C ~/.agentia/<name>/
# Clone:   cp -r ~/.agentia/<name-A>/ ~/.agentia/<name-B>/
```

---

## AgentServer HTTP API

### Core endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Health, adapter, provider, model, uptime |
| GET | `/config` | Current config |
| PATCH | `/config` | Update config |
| PUT | `/config` | Replace entire config |
| POST | `/restart` | Restart agent subprocess |

### Sessions endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sessions` | List all sessions |
| GET | `/sessions/<name>` | Get session details |
| POST | `/sessions/new` | Create or resume a named session |
| POST | `/sessions/<name>/message` | Send message, get response |
| POST | `/sessions/<name>/compact` | Trigger compaction |
| DELETE | `/sessions/<name>` | Stop subprocess, keep session file |
| DELETE | `/sessions/<name>?hard=true` | Stop and delete session file |

### Files endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/files/` | List workspace directory |
| GET | `/files/<path>` | Read file |
| PUT | `/files/<path>` | Write file |
| DELETE | `/files/<path>` | Delete file or directory |

### Example responses

**GET /status:**
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

**GET /sessions:**
```json
[
  {"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "message_count": 12, "context_pct": 23, "last_active": "2026-04-09T03:00:00Z"},
  {"name": "2026-04-09T01-10-00_crocus", "title": "crocus", "status": "stopped", "message_count": 47, "context_pct": 71, "last_active": "2026-04-09T01:30:00Z"}
]
```

---

## Multi-Agent Mesh

Each machine is a **symmetric node** — both a server (receives messages) and a client (sends messages to other agents). Any agent can reach any other agent directly by HTTP.

```
Machine A                              Machine B
────────────                          ────────────
python cli/agent.py :8080              python cli/agent.py :8080
python cli/host.py (client)            python cli/host.py (client)

Agent A ────── host.py send ──────► Agent B
             HTTP POST
```

**How agents find each other:** `mesh.json` — a shared config file listing all agents and their URLs. Each agent pulls `mesh.json` on boot and periodically to update its local `peers.json`.

```json
{
  "mesh": {
    "agents": {
      "research-agent": "http://vm-research.example.com:8080",
      "coding-agent": "http://192.168.1.50:8080"
    }
  }
}
```

- `mesh.json` can live in git, on a shared NFS volume, or any HTTP server
- No central server required — it's just a file
- Any machine with access can update it
- Agents update their local `peers.json` from `mesh.json` on boot and periodically

---

## Project Layout

```
cli/
    agent.py         # Agent-side CLI: setup + serve (runs in container/on agent machine)
    host.py          # Host-side CLI: send, manage, files, chat (runs anywhere)

agent_side/
    server.py        # AgentServer HTTP API
    harness.py       # Spawns and manages agent subprocess
    config.py        # AgentServerConfig + ConfigManager
    patterns/
        inbox.py     # Inbox delivery pattern
        sync.py      # Sync delivery pattern

agents/adapters/
    pi_agent.py      # pi-agent adapter + SessionManager
    openclaw.py      # OpenClaw adapter (legacy)
    factory.py       # Adapter factory

setup/
    setup-remote.sh  # Bare-metal deployment script (no Docker)
    adapters/
        pi-agent/    # pi-agent install script, config template, bootstrap

specs/
    005_relay_inbox.md        # Mesh architecture, discovery, response scenarios
    006_orchestration_patterns.md      # Moderator pattern, autonomous coordination
    009_agentserver_api.md    # Full HTTP API reference
    010_cli_interface.md      # CLI reference
    012_multi_agent_mesh.md   # Peer-to-peer mesh design
    020_session_management.md  # Session lifecycle, LRU, idle TTL
    021_conversation_mgmt.md  # Layer A: conversation registry

relay/                   # Deprecated (HostContainerBackend removed 2026-04-09)
```

---

## Design Decisions

**Pure HTTP transport** — No SSH tunnels, no docker exec, no custom binary protocol. Any two machines with network reachability can communicate. Works identically for Docker, SSH, or bare metal.

**Symmetric nodes** — Every machine runs both `agent.py` (server) and `host.py` (client). The MacBook you work from is just one node in the mesh.

**Session state lives on the agent machine** — `~/.agentia/agents/<name>/` is the agent's home. The host has access via the Files API and snapshot. No shared filesystem required.

**pi-agent for runtime** — `pi --mode rpc` gives a JSONL stdin/stdout protocol, session files, built-in compaction, and tool execution.

**mesh.json for discovery** — Static config file in a shared location (git, NFS, HTTP). No auto-discovery, no central registry service. Simple and auditable.

---

## References

- [SPEC 005 — Relay & Inbox Architecture](./specs/005_relay_inbox.md)
- [SPEC 012 — Multi-Agent Mesh](./specs/012_multi_agent_mesh.md)
- [SPEC 020 — Session Management](./specs/020_session_management.md)
- [SPEC 021 — Conversation Management](./specs/021_conversation_management.md)
- [pi-agent RPC protocol](https://github.com/badlogic/pi-mono/blob/main/docs/rpc.md)
