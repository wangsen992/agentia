# NEXT — Conversation Management Implementation

**Spec:** SPEC 021  
**Start date:** 2026-04-09

---

## Overview

Implement 4 layers in priority order. Layer C first (biggest UX win), then Layer A (conversation registry), then Layer D (REPL).

---

## Phase 1: Layer C — Smart Router

**Goal:** `send my-agent "hello"` (no --conv) auto-routes to last-used conversation.

### Changes

**`cli/host.py`** — add conversation tracking to `cmd_send`:

```
~/.agentia/
  conversations/
    .active/
      <agent>.jsonl     ← {conv_id, session_name, last_active}
```

- `cmd_send()`: if no `--conv`, read `conversations/.active/<name>.jsonl`
  - If found and session running → route to that session
  - If 409 (not running) → GET /sessions → find most recent → create new
  - If not found → GET /sessions → most recent or create "default"
- After every send (success or error): write `conversations/.active/<name>.jsonl`
- Add `--conv` override still works as before

### Files changed
- `cli/host.py`: add `_get_active_conv()`, `_set_active_conv()`, update `cmd_send()`

### Verification
```
# Send without --conv → should use last conversation
python3 cli/host.py send my-research-agent "hello" --conv hawaii
python3 cli/host.py send my-research-agent "continue"  # no --conv → resumes hawaii

# 409 fallback → session stopped
# 1. Session times out (agent idle)
# 2. send without --conv → 409 → GET /sessions → resumes or creates new
```

---

## Phase 2: Layer A — Conversation Registry

**Goal:** Full conversation metadata, CLI commands for management.

### Data model

```
~/.agentia/conversations/
  .active/
    <agent>.jsonl
  hawaii-trip.jsonl
  crocus-cfd.jsonl
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
  "status": "active",
  "context_pct": 45,
  "tags": ["travel"]
}
```

### Files changed
- `cli/host.py`: add `cmd_conv_list()`, `cmd_conv_show()`, `cmd_conv_rename()`, `cmd_conv_tag()`, `cmd_conv_delete()`
- New subparser: `conv <subcommand>` with list/show/rename/tag/delete

### Verification
```
# List all conversations
python3 cli/host.py conv list
# List per agent
python3 cli/host.py conv list --agent my-research-agent

# Show details
python3 cli/host.py conv show hawaii-trip

# Rename
python3 cli/host.py conv rename hawaii-trip --title "Hawaii May 2026"

# Tag
python3 cli/host.py conv tag hawaii-trip travel budget

# Delete (from registry only)
python3 cli/host.py conv delete hawaii-trip
```

### Update strategy (after every send)
After `POST /sessions/<name>/message` response:
1. Read current `conversations/<conv>.jsonl` (or create new)
2. Update: `last_active`, `message_count`, `context_pct`, `status`, `session_name`
3. Write back to `conversations/<conv>.jsonl`
4. Update `.active/<agent>.jsonl`

---

## Phase 3: Layer D — Interactive REPL

**Goal:** `agentia chat <name> [--conv <conv>]` with TUI.

### Files changed
- `cli/host.py`: add `cmd_chat()`, new subparser `chat`
- Dependency: `prompt_toolkit` (add to Dockerfile)

### REPL commands
| Command | Description |
|---------|-------------|
| `/switch <conv>` | Switch conversation |
| `/new [title]` | New conversation |
| `/sessions` | List sessions |
| `/sessions N` | Switch by number |
| `/send <file>` | Attach file |
| `/compact` | Trigger compaction |
| `/status` | Agent + session status |
| `/quit`, `/exit` | Exit |
| `/help` | Help |

### Verification
```
python3 cli/host.py chat my-research-agent
> hello
[streams response]
> /switch crocus-cfd
[switches]
> /quit
```

---

## Constraints

- Layer A (Phase 2) requires Phase 1 to work (conversation files created after sends)
- Layer D (Phase 3) requires Phase 2 to work (conv list/show)
- All phases must work backward-compatibly: existing `send --conv` still works exactly as before

## Done Criteria

- [ ] Phase 1: `send` without `--conv` routes to last-used conversation
- [ ] Phase 1: 409 fallback correctly resumes or creates new session
- [ ] Phase 1: `.active/<agent>.jsonl` correctly updated after every send
- [ ] Phase 2: `conv list` shows all conversations with metadata
- [ ] Phase 2: conversation files created and updated on every send
- [ ] Phase 2: `conv rename`, `conv tag`, `conv delete` work
- [ ] Phase 3: REPL streams responses, /switch works, /quit exits cleanly
