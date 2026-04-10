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

## Current Status

The current host/session/files surface is implemented and now has a lightweight regression suite for the **current** product shape.

Run the current tests with:

```bash
python3 -m unittest -v \
  tests/test_current_surface.py \
  tests/test_host_cli_e2e.py \
  tests/test_more_cli_and_api.py \
  tests/test_agentserver_endpoints.py
```

What this covers today:
- host conversation command semantics
- smart-router session bookkeeping
- session deletion by resolved title
- file PUT created-vs-updated semantics
- host CLI end-to-end flows against a lightweight fake AgentServer
  - `register`, `agents`, `status`, `configure`, `sessions`, `send`, `compact`, `session delete`, `files`
- additional host CLI coverage for:
  - `snapshot`, `clean`, `prune`
- direct API-level check for file path traversal protection in `AgentServerHandler._handle_files`
- in-process AgentServer handler tests for:
  - `/status`, `/config`, `/sessions`, session messaging, deletion, and file PUT/GET flows

What this does **not** fully cover yet:
- live end-to-end runs against a real pi-backed AgentServer
- full REPL interaction testing
- broader API coverage for async/inbox-oriented paths

The older root-level relay/moderator tests are not sufficient validation for the current host/server/session architecture.

## Prerequisites

For local development and basic CLI usage:
- Python 3.11+ recommended
- Docker (for the container quick start)
- `MINIMAX_API_KEY` set if using the MiniMax examples

Optional but currently useful:
- `prompt_toolkit` for `python3 cli/host.py chat ...`
- `jinja2` for `python3 cli/agent.py setup ...`

## Quick Start

### Fastest happy path

If you just want to sanity-check the current stack quickly:

```bash
cd agentia
python3 -m unittest -v \
  tests/test_current_surface.py \
  tests/test_host_cli_e2e.py \
  tests/test_more_cli_and_api.py \
  tests/test_agentserver_endpoints.py

docker build -t agentia .
mkdir -p ~/.agentia/agents/my-agent

docker run -d --name my-agent -p 18080:8080 \
  -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
  -v ~/.agentia/agents/my-agent:/workspace \
  agentia-agent serve \
    --install pi-agent \
    --config /workspace/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace

python3 cli/host.py register http://localhost:18080 --name my-agent
python3 cli/host.py status my-agent
python3 cli/host.py send my-agent "What can you do?"
```

If those commands work, the current host/server/session path is basically alive.

### 1. Build the image

```bash
cd agentia
docker build -t agentia .
```

### 2. Start an agent container

First create a clean local home for the agent:

```bash
mkdir -p ~/.agentia/agents/my-agent
```

Then start the container:

```bash
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    -v ~/.agentia/agents/my-agent:/workspace \
    agentia-agent serve \
      --install pi-agent \
      --config /workspace/agent.json \
      --provider minimax \
      --model MiniMax-M2.7 \
      --workspace /workspace
```

> The image entrypoint is `agentia-agent`, so the command above is the direct container command.
>
> All agent state — config, bootstrap files, sessions, and workspace files — lives under `~/.agentia/agents/<name>/` on the host via the `/workspace` bind mount. The container is intended to be stateless.
>
> If port `18080` is already in use, pick another one like `18082` and use that same port in the `register` command below.
>
> Provider/model compatibility is **not universal**. In this repository's current state, a container may start successfully and still fail on the first `send` if the selected model is unsupported by your account or by pi-agent's current request defaults. Treat the first successful `send` as the real readiness check.
>
> If you hit an error on first `send`, inspect the stored pi session JSONL under `~/.agentia/agents/<name>/.pi/sessions/` for the upstream provider error, then switch to a known-good model for your account.

### 3. Send a message

```bash
# Register the agent (first time only)
python3 cli/host.py register http://localhost:18080 --name my-agent

# Verify the server is healthy
python3 cli/host.py status my-agent

# Send a message (this is the real model/provider validation step)
python3 cli/host.py send my-agent "What can you do?"

# List agents
python3 cli/host.py agents
```

---

## Deploying on a Remote VM (Bare Metal)

No Docker required on the remote — just Python 3 and curl. The setup script handles everything.

### On the remote machine (one-time setup)

This path is for a machine where you want to run AgentServer directly without Docker.

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

### On your Mac

```bash
# Register the remote agent
python3 cli/host.py register http://<vm-ip>:8080 --name research-agent

# Use it like any other agent
python3 cli/host.py send research-agent "What can you do?"
```

### If the VM has no public IP (SSH tunnel fallback)

```bash
# SSH tunnel: remote port 8080 → local 18080
ssh -L 18080:localhost:8080 user@vm

# On your Mac, AgentServer is now at localhost:18080
python3 cli/host.py register http://localhost:18080 --name research-agent
```

---

## Managing Agents

### Cleaning local state during development

If you've been iterating and want to clean up obvious host-side residue:

```bash
python3 cli/host.py clean --audit
python3 cli/host.py clean --apply --safe
```

This only removes tier-1 safe artifacts such as empty container directories and zero-byte inbox files. It does **not** reset Docker images/containers or wipe `~/.agentia` entirely.

Current implementation status:
- implemented: `clean --audit`, `clean --apply --safe`
- not implemented yet: category filtering, aggressive deletion, trash mode, JSON output

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
python3 cli/host.py conv list --agent my-agent

# Show conversation details
python3 cli/host.py conv show hawaii

# Switch active conversation
python3 cli/host.py conv use crocus --agent my-agent

# Tag a conversation
python3 cli/host.py conv tag hawaii travel

# Delete a conversation
python3 cli/host.py conv delete hawaii

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

`chat` currently depends on `prompt_toolkit`. If it is not installed, the CLI will tell you and exit instead of silently degrading.

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
python3 cli/host.py files my-agent get AGENTS.md
python3 cli/host.py files my-agent put notes.md -c "Hello world"
python3 cli/host.py files my-agent edit AGENTS.md   # Opens in $EDITOR
python3 cli/host.py files my-agent delete notes.md
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

## Tests

Current product-surface tests live under `tests/`.

```text
tests/
  test_current_surface.py      # targeted tests for conversation/session/files semantics
  test_host_cli_e2e.py         # end-to-end host CLI tests against a fake AgentServer
  test_more_cli_and_api.py     # snapshot/clean/prune coverage + API-level safety checks
  test_agentserver_endpoints.py # in-process AgentServer handler endpoint tests
```

Run them with:

```bash
python3 -m unittest -v \
  tests/test_current_surface.py \
  tests/test_host_cli_e2e.py \
  tests/test_more_cli_and_api.py \
  tests/test_agentserver_endpoints.py
```

These are the tests you should trust first when working on the current host/server/session/files surface.

## Project Layout

```text
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
    005_relay_inbox.md              # Mesh architecture, discovery, response scenarios
    006_orchestration_patterns.md   # Moderator pattern, autonomous coordination
    009_agentserver_api.md          # Full HTTP API reference
    010_cli_interface.md            # CLI reference
    020_session_management.md       # Session lifecycle, LRU, idle TTL
    021_conversation_management.md  # Conversation registry, smart router, REPL
    022_host_cleanup.md             # Conservative host-folder cleanup

tests/
    test_current_surface.py         # targeted tests for current semantics
    test_host_cli_e2e.py            # fake-server end-to-end CLI tests
    test_more_cli_and_api.py        # snapshot/clean/prune + API-level safety checks
    test_agentserver_endpoints.py   # in-process AgentServer handler endpoint tests

relay/                              # Deprecated (legacy; not current validation target)
```

---

## Design Decisions

**Pure HTTP transport** — No SSH tunnels, no docker exec, no custom binary protocol. Any two machines with network reachability can communicate. Works identically for Docker, SSH, or bare metal.

**Symmetric nodes** — Every machine runs both `agent.py` (server) and `host.py` (client). The MacBook you work from is just one node in the mesh.

**Session state lives on the agent machine** — `~/.agentia/agents/<name>/` is the agent's home. The host has access via the Files API and snapshot. No shared filesystem required.

**pi-agent for runtime** — `pi --mode rpc` gives a JSONL stdin/stdout protocol, session files, built-in compaction, and tool execution.

**mesh.json for discovery** — Static config file in a shared location (git, NFS, HTTP). No auto-discovery, no central registry service. Simple and auditable.

---

## After code changes

If you modify the current host/server/session/files surface, do this before you call it done:

1. Run the current regression suite:
   ```bash
   python3 -m unittest -v \
     tests/test_current_surface.py \
     tests/test_host_cli_e2e.py \
     tests/test_more_cli_and_api.py \
     tests/test_agentserver_endpoints.py
   ```
2. Update `README.md` if the user-facing workflow, command surface, caveats, or validation story changed.
3. Update the relevant spec(s) if behavior changed intentionally:
   - `specs/010_cli_interface.md`
   - `specs/020_session_management.md`
   - `specs/021_conversation_management.md`
   - `specs/022_host_cleanup.md`
4. If possible, do one manual sanity run of the changed path.
5. If a new feature is only partial, say so in the README instead of implying it is fully done.

## Troubleshooting

### `send` fails right after the container starts

Treat the first successful `send` as the real readiness check.

Things to check:
- the container is actually running
- the port mapping matches the URL you registered
- the model/provider pair is valid for your account
- upstream provider errors are visible in the session JSONL under:
  - `~/.agentia/agents/<name>/.pi/sessions/`

### `python3 cli/host.py chat ...` says prompt_toolkit is missing

Install it in the Python environment you use for Agentia:

```bash
pip install prompt_toolkit
```

### `python3 cli/agent.py setup ...` says jinja2 is missing

Install it in the Python environment you use for Agentia:

```bash
pip install jinja2
```

### The README says something works, but the repo behaves differently

Trust the current tests first, then the current CLI help output, then the specs. If you find drift, update the README in the same change.

### File PUT/GET behaves strangely on macOS temp paths

A real bug existed here: comparing a resolved target path against an unresolved workspace path can falsely trigger path-traversal protection on macOS (`/var` vs `/private/var`). The current handler now resolves the workspace path before checking containment.

## References

- [SPEC 005 — Relay & Inbox Architecture](./specs/005_relay_inbox.md)
- [SPEC 010 — CLI Interface](./specs/010_cli_interface.md)
- [SPEC 020 — Session Management](./specs/020_session_management.md)
- [SPEC 021 — Conversation Management](./specs/021_conversation_management.md)
- [SPEC 022 — Host Folder Cleanup](./specs/022_host_cleanup.md)
- [pi-agent RPC protocol](https://github.com/badlogic/pi-mono/blob/main/docs/rpc.md)
