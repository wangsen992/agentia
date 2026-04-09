# Agentia CLI — Interface Specification

**Status:** Updated
**Date:** 2026-04-08
**Last updated:** 2026-04-09

---

## Design Principle

**Agent side** and **host side** are fully separate CLIs that communicate only through HTTP.

The only connection: both communicate with AgentServer's HTTP API.

Each machine in the mesh runs both CLIs — every node is symmetric.

---

## Agent Side CLI

Runs on the machine where the agent is deployed. Starts and manages the local AgentServer. CLI name: **`python cli/agent.py`** (the `agentia-agent` wrapper script is deprecated).

### `python cli/agent.py setup <adapter> [options]`
Render bootstrap files + install runtime. Must be run before first `serve`.

```
python cli/agent.py setup pi-agent \
    --config /root/.pi/agent/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /root/.pi/agent \
    --role-goal "You are a helpful research assistant." \
    --backstory "You specialize in fluid dynamics and CFD."
```

- `--adapter` — `pi-agent` (required)
- `--config` — output path for agent.json (required)
- `--provider`, `--model`, `--workspace` — standard config fields
- `--role-goal`, `--backstory`, `--skills` — bootstrap content

**Does NOT start AgentServer.** Run `serve` separately after setup.

### `python cli/agent.py serve [options]`
Start AgentServer HTTP API. Can optionally run setup first with `--install <adapter>`.

```
# Two-step: setup first, then serve
python cli/agent.py setup pi-agent --config /root/.pi/agent/agent.json ...
python cli/agent.py serve --config /root/.pi/agent/agent.json

# One-shot: setup + serve
python cli/agent.py serve \
    --install pi-agent \
    --config /root/.pi/agent/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /root/.pi/agent \
    --role-goal "You are a helpful research assistant."
```

---

## Host Side CLI

Runs on any machine (host or agent). Sends messages to registered agents via their AgentServer HTTP API, and manages the local registry.

CLI name: **`python cli/host.py`**

**Critical clarification:** `host.py` is not just a host-side tool. It is available to the running agent as a first-class outbound communication tool. When an agent needs to reach another agent, it calls `host.py send <peer> <message>` just like the human does from the command line.

### `python cli/host.py register <url> [options]`
Register an agent by its AgentServer HTTP endpoint. Saves to local registry.

```
python cli/host.py register http://localhost:18080 \
    --name my-research-agent \
    --metadata '{"role": "research", "domain": "fluid-dynamics"}'
```

- `<url>` — AgentServer base URL (required). Can be any reachable URL — localhost, cloud VM, remote server.
- `--name` — friendly name for this agent (required)
- `--metadata` — arbitrary JSON blob stored locally with the agent

The registry is `~/.agentia/agents.json`:
```json
{
  "agents": {
    "my-research-agent": {
      "url": "http://localhost:18080",
      "name": "my-research-agent",
      "registered_at": "2026-04-08T...",
      "metadata": {}
    }
  }
}
```

### `python cli/host.py agents`
List all registered agents.

```
$ python cli/host.py agents
my-research-agent  http://localhost:18080  [research]
claude-coder      http://vm.example.com:8080  [coding]
```

### `python cli/host.py send <name> <message> [--new]`
Send a message to a registered agent. Blocks until response.

```
python cli/host.py send my-research-agent "What can you do?"
```

- `<name>` — agent name from registry (required)
- `<message>` — message string (remaining args joined)
- `--new` — create a new conversation/session for this message

### `python cli/host.py sessions <name>`
List all sessions for an agent.

### `python cli/host.py conv <subcommand>`
Manage conversations. Subcommands: `list`, `show`, `rename`, `tag`, `delete`, `use`.

### `python cli/host.py status <name>`
Get agent status via `GET /status`.

### `python cli/host.py configure <name> <key> <value>`
Update agent configuration via `PATCH /config`.

### `python cli/host.py deregister <name>`
Remove an agent from the local registry. Does NOT stop the remote agent.

---

## File Layout

```
~/.agentia/
├── agents.json          # registry: name → URL mapping for known agents
├── conversations/       # conversation state (Layer A)
│   └── .active/        # active conversation per agent
└── peers.json          # peer agents known from this machine (name → URL)

# On remote machines, peers.json is seeded from the host's agents.json
# so the agent knows which peers it can reach
```

---

## Discovery: How Does an Agent Find Peers?

Each machine maintains `peers.json` listing known peer agents by name and URL:

```json
{
  "peers": {
    "research-agent": "http://vm-research.example.com:8080",
    "coding-agent": "http://192.168.1.50:8080"
  }
}
```

The agent is told (via system prompt or config) which peer to contact for which task. No auto-discovery — peers are registered explicitly.

**V1:** Static config. Future: DNS-SD/mDNS or a central registry.

---

## HTTP API (AgentServer side)

For reference — what `host.py` talks to. See SPEC 009 for full API documentation.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Agent health, delivery mode, adapter type |
| PATCH | `/config` | Update config |
| POST | `/restart` | Restart agent subprocess |
| POST | `/sessions/new` | Create new session |
| POST | `/sessions/<name>/message` | Send message, wait for response |
| GET | `/sessions` | List all sessions |
| DELETE | `/sessions/<name>` | Stop/delete session |
| POST | `/sessions/<name>/compact` | Trigger compaction |

---

## Design Decisions

### Why separate CLIs?
- Agent side runs on the machine where the agent lives
- Host side can run anywhere — host machine or agent machine
- `host.py` is a first-class tool available to agents for inter-agent communication

### Why register first?
The registry maps friendly names to URLs. Operations like `send`, `status`, `configure` all work by name lookup. If you know the URL directly, you can use `forward` without registering.

### Why symmetric nodes?
Every machine runs both `agent.py` (server) and `host.py` (client):
- Server (`agent.py`) — receives messages, manages sessions
- Client (`host.py`) — sends messages to any peer, available as a tool to the agent

This enables the peer-to-peer mesh: any agent can reach any other agent by URL, with no central hub.

### Why `peers.json` separate from `agents.json`?
- `agents.json` — agents registered from this machine's perspective (host-side view)
- `peers.json` — agents this machine's agent can reach (agent-side view, may be a subset)

The agent doesn't need to know about every agent the human has registered. It only needs to know peers it can use for specific tasks.

### Why not manage containers from host CLI?
- Docker is already manageable via `docker` CLI
- SSH/bare-metal environments require manual setup anyway
- Keeping container lifecycle separate means the CLI stays thin and focused on agent operations

---

## Open Questions

1. **Registry sync** — should `peers.json` on remote machines auto-sync from the host's `agents.json`?
2. **Capability enforcement** — should `host.py` validate target URLs against a whitelist, or trust the system prompt?
3. **Async communication** — for long-running tasks, should agents use `/message/async` + polling instead of blocking sends?
