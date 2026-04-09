# Conversation Management — Full Architectural Design

**Spec:** 021  
**Status:** Fully implemented (Phase 1 + 2 + 3)  
**Supersedes:** SPEC 020 (session management internals remain unchanged)

---

## Overview

Four layers work together to provide seamless conversation management:

| Layer | Location | What it owns |
|-------|-----------|--------------|
| A — Conversation Registry | Host (`~/.agentia/conversations/`) | Cross-agent conversation metadata, title, agent mapping |
| B — Session Manager | AgentServer (in container) | Per-agent session subprocesses, idle timers, LRU, auto-compact |
| C — Smart Router | Host CLI (`cli/host.py`) | Route `send` to correct agent+session, implicit resume |
| D — Interactive REPL | Host CLI (`cli/host.py`) | Persistent chat UI, `/switch`, `/new`, `/quit` |

```
┌─────────────────────────────────────────────────────────────────────┐
│  Host machine (~/.agentia/)                                          │
│                                                                     │
│  Layer A: conversations/          Layer C: Smart Router               │
│    hawaii-trip.jsonl               send without --conv               │
│    crocus-cfd.jsonl                → looks up last conv for agent      │
│    tax-2025.jsonl                  → resumes existing or creates new   │
│                                                                     │
│  Layer D: REPL (agentia chat)                                        │
│    agentia chat <name>                                             │
│    prompt_toolkit TUI                                              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP API
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent container (AgentServer)                                      │
│                                                                     │
│  Layer B: SessionManager                                            │
│    sessions/manifest.jsonl                                           │
│    2026-04-09T00-22-30_hawaii/                                     │
│      - subprocess (pi)                                              │
│      - idle timer                                                  │
│      - context_pct tracker                                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layer A: Conversation Registry (Host)

### Purpose

Track all conversations **across all agents** from the host side. This is the user's mental model — "I have a hawaii-trip conversation with my-research-agent, a crocus-cfd conversation with the same agent, and a tax-2025 conversation with my-accountant-agent."

The registry is **host-local, agent-independent**. It works even when no agents are running.

### Data Model

```
~/.agentia/conversations/
  hawaii-trip.jsonl
  crocus-cfd.jsonl
  tax-2025.jsonl
```

**`hawaii-trip.jsonl`**:
```json
{
  "id": "hawaii-trip",
  "title": "Hawaii Trip Planning",
  "created_at": "2026-04-09T00:22:30Z",
  "last_active": "2026-04-09T13:00:00Z",
  "message_count": 12,
  "agent_name": "my-research-agent",
  "session_name": "2026-04-09T00-22-30_hawaii",
  "status": "running",
  "context_pct": 45,
  "tags": ["travel", "budget"]
}
```

### Schema fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique slugified conversation ID (used in --conv) |
| `title` | string | Human-readable title (can be auto-generated) |
| `created_at` | ISO8601 | When conversation was first created |
| `last_active` | ISO8601 | Last message timestamp |
| `message_count` | int | Total messages sent in this conversation |
| `agent_name` | string | Which agent this conversation is with |
| `session_name` | string | AgentServer session name (e.g. `2026-04-09T00-22-30_hawaii`) |
| `status` | string | `active` (recent message), `idle` (session stopped), `archived` |
| `context_pct` | int | Last known context usage |
| `tags` | string[] | Optional tags for filtering |

### Update Strategy

Layer A is **updated after every send** from the host CLI. The flow:

```
cli/host.py send → HTTP POST /sessions/<name>/message
                 → response received
                 → update ~/.agentia/conversations/<conv>.jsonl with new last_active, message_count, context_pct
```

If the conversation doesn't have a corresponding file yet → create it.

If `status` becomes `idle` (agent's SessionManager reports session stopped) → update status field.

### Host-side CLI additions

```bash
# List all conversations across all agents
python3 cli/host.py conv list

# List conversations for a specific agent
python3 cli/host.py conv list --agent my-research-agent

# Show conversation details
python3 cli/host.py conv show hawaii-trip

# Rename / retitle a conversation
python3 cli/host.py conv rename hawaii-trip --title "Hawaii May 2026"

# Tag a conversation
python3 cli/host.py conv tag hawaii-trip travel budget

# Delete a conversation (from registry only — agent session untouched)
python3 cli/host.py conv delete hawaii-trip

# Switch active conversation for an agent (updates routing for next send)
python3 cli/host.py conv use hawaii-trip --agent my-research-agent
```

### Auto-generated titles

When a conversation is created without a user-supplied title:
- First message is prepended with "Re: " and truncated to 60 chars as title
- Or: session creation returns a title derived from first agent response
- User can always override with `conv rename`

### Archival

Conversations with `status: idle` and no activity for > 30 days → `status: archived`. Archived conversations are kept in `~/.agentia/conversations/archive/`. They don't clutter the list but can still be resumed.

---

## Layer B: Session Manager (AgentServer, unchanged)

**This spec does NOT change Layer B.** SPEC 020 defines it completely:

- Sessions are identified by `session_name` (timestamp-based, globally unique)
- Each session maps 1:1 to a pi subprocess
- Idle timeout, LRU eviction, auto-compact all work as designed
- The session `title` field in the manifest corresponds to the Layer A conversation `id`

**Key invariant:** Layer A's `session_name` = Layer B's session `name`. This is how routing works.

```
Layer A: hawaii-trip.jsonl → session_name = "2026-04-09T00-22-30_hawaii"
Layer B: manifest entry     → name = "2026-04-09T00-22-30_hawaii"  ← SAME
```

---

## Layer C: Smart Router (Host CLI)

### Purpose

When you type `send my-research-agent "hello"` without `--conv`, the CLI should automatically route to the right conversation. No manual `--conv` required for repeat conversations.

### Routing Logic

**Rule: Host-side primary lookup with agent-side verification fallback.**

```
send <agent> <message>
  ├─ If --conv <name> is given:
  │    → Route directly to that conversation
  │    → Update last_active in Layer A and .active/<agent>.jsonl
  │
  └─ Else (no --conv):
       STEP 1 — Host-side lookup (primary):
       ├─ Read ~/.agentia/conversations/.active/<agent>.jsonl
       │    (contains: conv_id, session_name, last_active)
       │
       STEP 2 — Route with agent-side verification (fallback):
       ├─ Try: POST /sessions/<session_name>/message
       │    (may fail if session stopped due to idle timeout)
       │
       ├─ If agent returns "session not running" (409):
       │    → Agent-side: GET /sessions → find most recently active session
       │    → If found: POST /sessions/new {title: conv_id} to resume with same conv name
       │    → If not found: create fresh "default" conversation
       │
       └─ If .active/<agent>.jsonl does NOT exist:
            → Agent-side: GET /sessions → most recently active session
            → If found: route to it
            → If not found: create new "default" conversation
```

**Why this approach?**
- Layer A (host-side) is the fast path — no extra API round-trips
- Agent-side verification handles stale state: idle timeout fired, agent restarted, etc.
- If agent is entirely offline: Layer A is the only option; create new session as fallback
- `GET /sessions` on the agent is authoritative for "what sessions actually exist right now"

### Active Conversation Tracking


### Active Conversation Tracking

```
~/.agentia/conversations/.active/
  my-research-agent.jsonl    ← {conv_id, session_name, agent_name, last_active}
  my-accountant-agent.jsonl
```

This is a **thin index** — the source of truth is still `hawaii-trip.jsonl`. The `.active/` file just caches which conversation is "current" for each agent.

Why a separate file and not just use a field in each conversation JSON?
- One less parse step for the hot path (send)
- Agent-isolated: doesn't require scanning all conversations

### Updating after send

After every `send` completes:

1. Update Layer A file (`hawaii-trip.jsonl`):
   - `last_active` → now
   - `message_count` → +1
   - `context_pct` → from response
   - `status` → "active"
   - `session_name` → session used

2. Update `.active/<agent>.jsonl`:
   - `conv_id` → current conversation
   - `session_name` → current session
   - `last_active` → now

### Status propagation

Layer B doesn't push updates to Layer A — Layer A is updated on the client side after every send. However, Layer A is **eventually consistent** with Layer B:
- After routing, Layer A reflects what the agent confirmed was running
- If idle timeout fires on Layer B, Layer A won't know until the next send attempt fails → then it falls back to `GET /sessions`
- The `.active/<agent>.jsonl` file is the hot path cache; Layer A conversation files are the durable record

If multiple CLI clients talk to the same agent (different machines), Layer A files can diverge. That's acceptable — Layer A is local to each host. The agent's `GET /sessions` is always the authoritative session state.

Sync across machines is out of scope for this spec.

---

## Layer D: Interactive REPL

### Purpose

A persistent chat UI that stays in one conversation until explicitly switched. For heavy usage where typing `--conv` every time is annoying.

### Interface

```bash
# Start a chat with an agent (uses last-active conversation)
python3 cli/host.py chat my-research-agent

# Start a chat with a specific conversation
python3 cli/host.py chat my-research-agent --conv hawaii-trip

# REPL commands (prefixed with /)
Agent: my-research-agent | Conv: hawaii-trip
> plan my trip to maui
[agent thinking...]
> also look up flight prices
[agent thinking...]
> /switch crocus-cfd
Switching to crocus-cfd...
Agent: my-research-agent | Conv: crocus-cfd
> explain the CFD results
[agent thinking...]
> /new another-project
Starting new conversation...
Agent: my-research-agent | Conv: another-project
> /sessions
1. hawaii-trip     (active, 12 msgs, 45%)
2. crocus-cfd      (idle, 47 msgs, 71%)
3. another-project (new)
> /sessions 1
Switching to hawaii-trip...
> /quit
Goodbye.
```

### TUI Implementation

Use `prompt_toolkit` for a proper terminal UI:
- Colored prompt showing agent name + conversation title
- Scrollback history
- Ctrl+C to interrupt agent
- ANSI color support

### REPL Commands

| Command | Description |
|---------|-------------|
| `/switch <conv>` | Switch to named conversation |
| `/new [title]` | Start a new conversation |
| `/sessions` | List recent conversations for current agent |
| `/sessions N` | Switch to conversation by number |
| `/send <file>` | Attach a file to next message |
| `/compact` | Manually trigger compaction on current session |
| `/status` | Show agent + session status |
| `/quit` / `/exit` | Exit REPL |
| `/help` | Show help |

### Background mode

The REPL runs in the foreground (blocks terminal). For long-running tasks, the agent still streams responses. Ctrl+C sends abort signal to agent.

---

## API: Layer A ← → Layer B Mapping

The key join between layers is:

```
Layer A: conversations/<conv>.jsonl  →  .session_name  →  "2026-04-09T00-22-30_hawaii"
Layer B: GET /sessions               →  name field    →  "2026-04-09T00-22-30_hawaii"  ← SAME
```

When the CLI routes a message:
1. Layer A lookup → get `session_name` for conv
2. Check if session is running: `GET /sessions/<session_name>` → `status: running`
3. If running → `POST /sessions/<session_name>/message`
4. If stopped → `POST /sessions/new {title: conv_id}` → Layer B creates new session, returns new `session_name`
5. Update Layer A with new `session_name`

---

## Directory Structure Summary

```
~/.agentia/
  conversations/                    ← Layer A
    .active/                       ←   active conversation per agent
      my-research-agent.jsonl
      my-accountant-agent.jsonl
    hawaii-trip.jsonl
    crocus-cfd.jsonl
    tax-2025.jsonl
    archive/                        ←   archived conversations
      2026-03-01_shopping.jsonl
  my-research-agent/                ← agent workspace
    .agentia/sessions/             ← Layer B (inside container workspace)
      manifest.jsonl
      2026-04-09T00-22-30_hawaii/
      2026-04-09T01-10-00_crocus/
    AGENTS.md
    SYSTEM.md
  my-accountant-agent/
    .agentia/sessions/
      ...
```

---

## Implementation Order

### ✅ Phase 1: Layer C (Smart Router) — IMPLEMENTED
- `.active/<agent>.jsonl` tracking
- `send` without `--conv` reads `.active/` → routes to last conversation
- After send: updates both `.active/` and Layer A conversation file
- `--new` flag: creates new session named from first message

### ✅ Phase 2: Layer A (Conversation Registry) — IMPLEMENTED
- `conv list [--agent]`, `conv show`, `conv rename`, `conv tag`, `conv delete`, `conv use`
- `conversations/<id>.jsonl` created/updated after every send
- Background archival: NOT YET (can be added later)

### ✅ Phase 3: Layer D (Interactive REPL) — IMPLEMENTED
- `chat <name> [--conv <conv>] [--new]` — prompt_toolkit TUI
- `/switch`, `/new`, `/sessions`, `/compact`, `/status`, `/conv`, `/clear`, `/help`, `/quit`
- History: `~/.agentia/history/<name>.hist`

---

## Open Questions

1. **Layer A persistence** — If the same conversation is used with two different agents (e.g., a research agent and an accountant agent both working on "taxes-2026"), should Layer A track this as one conversation with multiple `agent_name` entries, or two separate conversations? **This spec: two separate conversations.** (Same topic, but different agent context.)

2. **Conversation ID uniqueness** — Can two conversations have the same `id` if they're with different agents? No — Layer A IDs are globally unique across all agents (slugified, with agent name as prefix if needed: `hawaii-research` vs `hawaii-accountant`).

3. **Auto-title vs user title** — Who "owns" the title? User can rename at any time. Auto-generated titles are a best-effort starting point.

4. **Sync across machines** — If Sen uses multiple machines, Layer A files diverge. Out of scope for now, but note that the single source of truth per agent is Layer B (AgentServer). Layer A is a convenience cache.

5. **Layer D TUI vs CLI** — REPL could also be exposed as `agentia chat` (TUI mode) vs `agentia send` (CLI mode), toggled by a flag. Or keep them as separate commands.
