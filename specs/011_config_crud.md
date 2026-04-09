# Agentia Configuration CRUD — Interface Design

**Status:** Draft
**Date:** 2026-04-08
**Related:** SPEC 010 — CLI Interface

---

## Config Layers Recap

| Layer | Fields | Scope |
|-------|--------|-------|
| **Server config** | delivery, poll_interval, inbox_dir, agent_timeout, log_level | AgentServer operation |
| **Bootstrap** | role_goal, role_backstory | Agent identity + instructions |
| **Skills** | skills[] → .pi/skills/ files | Agent capabilities |
| **LLM model** | provider, model, thinking_level | Model + reasoning config |
| **Comm setup** | session_persist, session_dir | Conversation context persistence |

Each layer has different CRUD characteristics — what makes sense to Create/Read/Update/Delete and through which interface.

---

## Read Operations (All Layers)

### Agentic — `GET /status` + `GET /config`

```bash
# Human-readable summary (GET /status)
curl http://localhost:18080/status
→ {agent_id, delivery, adapter, provider, model, thinking_level?, uptime, running}

# Full config dump (GET /config)
curl http://localhost:18080/config
→ {all fields including role_goal, role_backstory, skills, session_persist, ...}
```

`GET /status` is a lightweight dashboard view. `GET /config` is the full record for programmatic use.

### Human — `status` + `configure` commands

```bash
# Lightweight status — agent name, URL, delivery, model, thinking level
agentia status my-agent
→ name:      my-agent
  url:       http://localhost:18080
  uptime:    2h 14m
  delivery:   inbox
  adapter:   pi-agent
  provider:  minimax
  model:     MiniMax-M2.7
  thinking:  medium

# Full config — all fields as key-value
agentia configure my-agent --show
→ delivery: inbox
  poll_interval: 2.0
  inbox_dir: ~/.agentia/workspace/inbox
  agent_timeout: 120
  role_goal: You specialize in turbulence modeling.
  role_backstory: Former NASA CFD researcher.
  skills: [brave-search, coder]
  thinking_level: medium
  session_persist: true
  session_dir: ~/.agentia/workspace/.pi/sessions
```

---

## Update Operations (Per Layer)

### Layer 1 — Server Config (live, no restart needed)

```bash
# Change delivery mode or polling
agentia configure my-agent delivery sync
agentia configure my-agent poll_interval 5.0
```

**Interface:** `PATCH /config` with field → AgentServer picks up immediately.
**Agentic:** `POST /config` with JSON body.
**Human:** `agentia configure <name> <key> <value>`.

---

### Layer 2 — Bootstrap (requires re-render + restart)

```bash
# Update identity via bootstrap re-render
agentia update my-agent \
    --role-goal "You specialize in fog density staircases." \
    --backstory "Expert in marine atmospheric boundary layer research."
```

**What happens:**
1. `PATCH /config` with `{role_goal, role_backstory, _restart: true}`
2. AgentServer re-renders AGENTS.md + SYSTEM.md from templates
3. Agent subprocess restarted — picks up new bootstrap on next message

**Agentic:** `POST /message` with a meta-instruction to update bootstrap, or direct `PATCH /config`.
**Human:** `agentia update <name> --role-goal "..." --backstory "..."`.

---

### Layer 3 — Skills (add/remove skill files)

```bash
# Add a skill
agentia skill add my-agent brave-search \
    --description "Web search via Brave API" \
    --definition "Skill for searching the web..."

# Remove a skill
agentia skill remove my-agent brave-search

# List available skills (from agent's loaded skills)
agentia skill ls my-agent
```

**What happens:**
- `add` — writes `.pi/skills/brave-search/SKILL.md` from a definition, triggers agent restart to load
- `remove` — deletes the skill directory, triggers restart
- `ls` — calls `GET /skills` on AgentServer → proxies to `pi get_commands`

**Agentic:** `POST /skills` + `DELETE /skills/<name>` endpoints.
**Human:** `agentia skill add/remove/ls`.

Skills have more structure than key-value — they need a name, description, and definition. This is the first config layer where a simple `<key> <value>` interface isn't enough.

---

### Layer 4 — LLM Model (partially live)

```bash
# Change thinking level — live, no restart
agentia configure my-agent thinking_level high

# Change model — requires restart
agentia configure my-agent model claude-sonnet-4-20250514 --restart
```

**Thinking level** — `set_thinking_level` RPC command, live without restart.
**Model/provider** — changes spawn flags, requires restart.

**Agentic:** `PATCH /config` with `{thinking_level: "high"}` is live. `{model: "...", _restart: true}` restarts.

---

### Layer 5 — Comm Setup (live where possible)

```bash
# Toggle session persistence
agentia configure my-agent session_persist false
# → next message starts fresh session (--no-session flag)

agentia configure my-agent session_persist true
# → next message uses persistent session

# Update session dir (needs restart)
agentia configure my-agent session_dir /data/agent-sessions --restart
```

**session_persist** — changes pi-agent spawn flag (`--no-session` vs `--session-dir`), live on next message.
**session_dir** — mount path change needs container restart (host volume remount).

---

## Create + Delete Operations

### Agent Creation (full config at setup time)

```bash
# Via container startup (agent side)
agentia-agent serve \
    --install pi-agent \
    --config /etc/agentia/agent.json \
    --provider minimax \
    --model MiniMax-M2.7 \
    --workspace /workspace \
    --role-goal "You are a CFD researcher" \
    --backstory "Expert in turbulence modeling." \
    --skills brave-search coder \
    --thinking medium \
    --session-persist
```

All bootstrap + model + comm fields set at creation time. Most are fixed after.

### Agent Deletion (host side)

```bash
# Deregister (remove from registry only)
agentia deregister my-agent

# Destroy container (separate concern — docker rm)
docker rm -f my-agent
```

Deregistering is purely local registry cleanup. The agent itself keeps running.

### Skills Deletion

```bash
agentia skill remove my-agent <skill-name>
```

Removes the skill file + restarts agent. No separate deregistration needed.

---

## Interface Summary

| Layer | Read | Update (live) | Update (restart) | Create | Delete |
|-------|------|---------------|------------------|--------|--------|
| Server config | GET /status, GET /config | PATCH /config | N/A | at serve | N/A |
| Bootstrap | GET /config | — | PATCH + _restart | at serve | re-serve |
| Skills | GET /skills | — | POST/DELETE /skills + _restart | POST /skills | DELETE /skills |
| LLM model (thinking) | GET /status | PATCH thinking_level | PATCH model + _restart | at serve | N/A |
| LLM model (provider/model) | GET /status | — | PATCH + _restart | at serve | N/A |
| Comm setup (session_persist) | GET /config | PATCH | — | at serve | N/A |
| Comm setup (session_dir) | GET /config | — | PATCH + _restart | at serve | N/A |

---

## Human vs Agentic Interface Map

### Human — CLI commands

```
agentia status <name>                    # GET /status
agentia configure <name> <key> <value>  # PATCH /config
agentia update <name> [opts]            # PATCH /config + _restart
agentia configure <name> --show          # GET /config
agentia skill add <name> <skill> [opts]  # POST /skills
agentia skill remove <name> <skill>       # DELETE /skills/<name>
agentia skill ls <name>                   # GET /skills

# Filesystem access
agentia files <name> ls [path]           # LIST /files/<path>
agentia files <name> get <path>          # GET /files/<path>
agentia files <name> put <path> -c "..."  # PUT /files/<path>
agentia files <name> delete <path>       # DELETE /files/<path>
agentia snapshot <name> [out.tar.gz]    # Snapshot workspace as tar.gz
```

### Human — Web UI (future)

Single-page control panel per agent:
- Status card at top (uptime, model, delivery, thinking level)
- Editable fields per layer with save/restart buttons
- Skills list with add/remove
- "Restart agent" button
- "View full config" toggle

### Agentic — HTTP API

```
GET  /status              → lightweight summary
GET  /config             → full config dump
GET  /skills             → loaded skills list
PATCH /config            → partial update (some fields live, some need restart)
POST /config             → full replace
POST /skills             → add skill
DELETE /skills/<name>   → remove skill
POST /restart            → restart subprocess
POST /message           → send message
```

Agents interact with this API directly. No CLI needed.

---

## Open Questions

1. **Skills definition format** — `agentia skill add` needs a `--definition` flag or reads from a file. Should skills be defined inline (`--definition "..."`) or from a local file (`--from path`)?

2. **`configure` vs `update` vs `skill` separation** — Currently `configure` handles all PATCH. Should skills have their own top-level command (`agentia skill ...`) or is it `agentia configure <name> skills.add <skill>`? CLI hierarchy question.

3. **Validation on update** — Should AgentServer validate fields before applying? e.g., `thinking_level` must be one of ["off", "minimal", "low", "medium", "high", "xhigh"]. Fail fast vs silently ignore.

4. **Partial restart** — Currently `_restart: true` restarts the whole subprocess. For thinking_level changes that are live, is restart even needed? Could track which fields need restart vs which are live.

5. **Agentic bootstrap update** — When an agent wants to update another agent's bootstrap (e.g., a moderator agent reassigning a worker), should it use `update` directly or send a message that triggers an intent confirmation?
