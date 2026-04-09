# Agentia CLI — Interface Specification

**Status:** Draft  
**Date:** 2026-04-08

---

## Design Principle

**Agent side** and **host side** are fully separate CLIs that know nothing about each other.

The only connection: both communicate with AgentServer's HTTP API.

---

## Agent Side CLI

Runs on the machine where the agent is deployed. Manages the local agent environment. CLI name: **`agentia-agent`**.

### `agentia-agent setup <adapter> [options]`
Render bootstrap files + install runtime. Must be run before first `serve`.

```
agentia-agent setup pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace \
    --role-goal "You are a helpful research assistant" \
    --backstory "You specialize in fluid dynamics and CFD."
```

- `--adapter` — `pi-agent` or `openclaw` (required)
- `--config` — output path for agent.json (default: `/etc/agentia/agent.json`)
- `--provider`, `--model`, `--workspace` — standard config fields
- `--role-goal`, `--backstory`, `--skills` — bootstrap content
- `--var KEY=VALUE` — additional template variables

**Does NOT start AgentServer.** Run `agentia-agent serve` separately after setup.

### `agentia-agent serve [options]`
Start AgentServer HTTP API. Can optionally run `setup` first with `--install <adapter>` — the single-shot pattern that avoids a `docker commit` workaround.

```
# Two-step: setup first, then serve
agentia-agent setup pi-agent --config /etc/agentia/agent.json ...
agentia-agent serve --config /etc/agentia/agent.json

# Or one-shot: setup + serve in the same container start
agentia-agent serve \
    --install pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace \
    --role-goal "You are a helpful research assistant"
```

---

## Host Side CLI

Runs on the host machine. Discovers agents via HTTP, registers them locally, and manages them through the AgentServer API. Does not manage Docker or deployment — those are handled by external tools.

### `agentia register <url> [options]`
Register an agent by its AgentServer HTTP endpoint. Saves to local registry.

```
agentia register http://localhost:18080 \
    --name my-research-agent \
    --metadata '{"role": "research", "domain": "fluid-dynamics"}'
```

- `<url>` — AgentServer base URL (required)
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
      "metadata": {...}
    }
  }
}
```

### `agentia agents`
List all registered agents.

```
$ agentia agents
my-research-agent  http://localhost:18080  [research]
claude-coder      http://localhost:18081  [coding]
```

### `agentia send <name> <message>`
Send a message to a registered agent. Blocks until response.

```
agentia send my-research-agent "What can you do?"
```

- `<name>` — agent name from registry (required)
- `<message>` — message string (remaining args joined)

### `agentia status <name>`
Get agent status via `GET /status`.

```
$ agentia status my-research-agent
name:      my-research-agent
url:       http://localhost:18080
uptime:    3h 14m
delivery:  inbox
adapter:   pi-agent
provider:  minimax
model:     MiniMax-M2.7
```

### `agentia configure <name> <key> <value>`
Update agent configuration via `PATCH /config`. Supports live config updates.

```
# Change delivery mode
agentia configure my-research-agent delivery inbox

# Update role goal
agentia configure my-research-agent role.goal "You specialize in turbulence modeling."

# Update persona via dot notation
agentia configure <name> role.backstory "Former NASA CFD researcher."
```

Config changes are sent to AgentServer's `PATCH /config` endpoint. AgentServer applies them to the running harness.

### `agentia update <name> [options]`
Push updated bootstrap files to a running agent. Re-renders AGENTS.md + SYSTEM.md and signals the agent to reload.

```
agentia update my-research-agent \
    --role-goal "You specialize in turbulence modeling." \
    --backstory "Expert in boundary layer instability."
```

- Sends new config via `PATCH /config` with updated role fields
- AgentServer re-renders bootstrap files and signals the running agent
- The agent subprocess receives the updated context on next message

### `agentia deregister <name>`
Remove an agent from the local registry. Does NOT stop the remote agent.

```
agentia deregister my-research-agent
```

### `agentia forward <name> <subcommand>`
Forward any command directly to the agent's AgentServer HTTP API. For debugging and advanced usage.

```
agentia forward my-research-agent GET /status
agentia forward my-research-agent POST /message/async --data '{"content": "hello"}'
```

---

## Registry

`~/.agentia/agents.json` — single source of truth for host-side agent registry.

```json
{
  "version": 1,
  "agents": {
    "<name>": {
      "url": "https://agent.example.com:8080",
      "name": "<display name>",
      "registered_at": "<ISO timestamp>",
      "last_seen_at": "<ISO timestamp>",
      "metadata": {}
    }
  }
}
```

---

## HTTP API (AgentServer side)

For reference — what the host-side CLI talks to.

| GET | `/status` | Agent health, delivery mode, adapter type, provider, model |
| PATCH | `/config` | Update config (delivery mode, role fields, etc.) |
| POST | `/restart` | Restart agent subprocess |
| POST | `/message` | Send message, wait for response |
| POST | `/message/async` | Queue message, return correlation ID |
| GET | `/response/{id}` | Poll for async response |
| GET | `/config` | Get current config |
| PUT | `/config` | Replace entire config |

---

## Design Decisions

### Why separate CLIs?
- Agent side may run in Docker, SSH, bare metal, any environment
- Host side should work the same way regardless of where the agent is deployed
- Docker/container management is already handled by `docker` CLI — no need to duplicate

### Why register first?
The registry is a local convenience — it maps friendly names to URLs. Operations like `send`, `status`, `configure` all work by name lookup. If you know the URL directly, you can use `forward` without registering.

### Why `configure` and `update` separately?
- `configure` — live config changes via PATCH /config (delivery mode, polling interval, etc.)
- `update` — re-render bootstrap files and signal agent context reload (role, backstory, skills)

Both flow through the same `PATCH /config` endpoint but carry different semantic intent.

### Why not manage containers from host CLI?
- Docker is already manageable via `docker` CLI
- SSH/bare-metal environments require manual setup anyway — the CLI can't automate that
- Keeping container lifecycle separate means the host CLI stays thin and focused on agent operations

---

## Open Questions

1. **Auto-discovery** — option for future. Manual `register` first. Design for pluggable discovery (e.g., `--discovery mdns` flag).

2. **Auth** — defer. No auth between host and agent for now.

3. **`update` signal** — confirmed: `Harness.restart_agent()` called after re-rendering bootstrap files.


4. **Registry path** — `~/.agentia/agents.json` — confirmed.
