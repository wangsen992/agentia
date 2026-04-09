# Session Management — Option A

**Status:** Draft  
**Owner:** AgentServer (agent_side/)

---

## Overview

AgentServer owns all session state. The host CLI (`cli/host.py`) is a dumb client — it calls the API without knowing session details. This mirrors how OpenClaw manages Jarvis's sessions.

Each **conversation** maps to one **named pi subprocess** with its own session file. Conversations persist across subprocess restarts via `--continue`.

---

## Data Model

```
/workspace/.agentia/sessions/
  manifest.jsonl                        ← session registry (one JSON per line)
  2026-04-09T00-22-30_hawaii.jsonl   ← timestamp-prefixed, pi session file
  2026-04-09T00-22-45_trip-planning.jsonl
```

**Naming convention:**
- Filename: `{timestamp}_{slugified-title}.jsonl` (e.g., `2026-04-09T00-22-30_hawaii.jsonl`)
  - Timestamp ensures uniqueness across all sessions
  - Title slugified (lowercase, hyphens) for readability
- `manifest.jsonl` holds the full record with human-readable `title` field separate from filename

**manifest.jsonl entry:**
```json
{"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "pid": 42, "session_file": "2026-04-09T00-22-30_hawaii.jsonl", "started_at": "2026-04-09T00:22:30Z", "message_count": 12, "last_active": "2026-04-09T03:00:00Z", "context_pct": 23}
```

- `name`: globally unique, matches filename without `.jsonl`
- `title`: human-readable display name (user-assigned or agent-generated)
- `context_pct`: estimated context window usage % (0-100)

**Session statuses:**
- `running` — subprocess alive, accepts messages
- `stopped` — subprocess killed, session file preserved
- `archived` — moved to cold storage (future)

---

## API Endpoints

### `POST /sessions/new`

Create or resume a named conversation.

```json
// Request — user-supplied name
{"name": "hawaii"}

// Request — agent-generated name (no user name provided)
{"title": "CROCUS CFD run analysis"}  

// Response 200 (new session)
{"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "session_file": "2026-04-09T00-22-30_hawaii.jsonl", "resumed": false}

// Response 200 (session existed, resumed)
{"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "session_file": "2026-04-09T00-22-30_hawaii.jsonl", "resumed": true}
```

**Naming logic:**
- If `name` provided → use it (slugified for filename, original for `title`)
- If only `title` provided → agent-generated, use `title`
- Filename always prefixed with ISO timestamp for uniqueness
- If session already `running` → return immediately (no-op)
- If session was `stopped` → spawn new pi with `--continue` (reconnects to session file)
- If session doesn't exist → create, spawn pi fresh

---

### `POST /sessions/<name>/message`

Send a message to a conversation.

```json
// Request
{"content": "What's the status of the Hawaii trip?"}

// Response 200
{"response": "We need to book flights by April 15th...", "message_count": 13}

// Response 404
{"error": "session not found: hawaii"}

// Response 409 (session not running)
{"error": "session not running, POST /sessions/hawaii/new first"}
```

- If session not `running` → 409, client must call `/sessions/new` first
- pi subprocess stdin → wait for `agent_end` event → return text

---

### `GET /sessions`

List all conversations.

```json
// Response 200
[
  {"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "message_count": 12, "context_pct": 23, "last_active": "2026-04-09T03:00:00Z"},
  {"name": "2026-04-09T01-10-00_crocus", "title": "crocus", "status": "stopped", "message_count": 47, "context_pct": 71, "last_active": "2026-04-09T01:30:00Z"},
  {"name": "2026-03-20T22-00-00_taxes-2025", "title": "taxes-2025", "status": "stopped", "message_count": 8, "context_pct": 12, "last_active": "2026-03-20T22:00:00Z"}
]
```

---

### `POST /sessions/<name>/compact`

Trigger pi's context compaction on a running session.

```json
// Request (optional)
{"message": "Focus on action items and decisions"}  // custom compact instruction

// Response 200
{"status": "compacted", "message_count_before": 47, "message_count_after": 18}
```

- Sends `{"type": "compact", "message": "..."}` to pi stdin
- Updates `message_count` in manifest

---

### `DELETE /sessions/<name>`

Stop subprocess, preserve session file.

```json
// Response 200
{"name": "hawaii", "status": "stopped"}

// Query param ?hard=true → also delete session file
DELETE /sessions/2026-04-09T00-22-30_hawaii?hard=true
// Response 200
{"name": "2026-04-09T00-22-30_hawaii", "deleted": true}
```

---

### `GET /sessions/<name>`

Get details for one conversation.

```json
// Response 200
{"name": "2026-04-09T00-22-30_hawaii", "title": "hawaii", "status": "running", "pid": 42, "session_file": "2026-04-09T00-22-30_hawaii.jsonl", "message_count": 12, "context_pct": 23, "last_active": "2026-04-09T03:00:00Z"}
```

---

## Resource Management

### Idle Timeout

**Config:** `session_idle_ttl` (default: 30 minutes)

After the last message to a session, a background timer starts. If no new message arrives before the TTL expires:
1. Subprocess receives SIGTERM
2. Session status → `stopped`
3. Session file preserved, can be resumed

**Implementation:** Each `POST /message` resets the timer for that session. A background thread per running session tracks idle time.

**Why SIGTERM not SIGKILL:** Graceful shutdown lets pi save state to session file.

### Max Sessions

**Config:** `max_sessions` (default: 10)

If a new session is requested and `max_sessions` is already running:
1. Sort running sessions by `last_active` (oldest first)
2. Idle-timeout the oldest session (stop its subprocess)
3. Proceed with new session

This is LRU eviction for active sessions.

### Auto-Compaction (Context Window Threshold)

**Config:** `context_threshold_pct` (default: 75%)

After each `POST /message`, estimate context window usage. If `context_pct >= context_threshold_pct`:
1. Automatically trigger compaction: send `{"type": "compact", "message": ""}` to pi stdin
2. Wait for `agent_end` event (compaction is a pi-side operation)
3. Update `message_count` and `context_pct` in manifest

**How context_pct is estimated:**
- pi exposes no direct context API, so we approximate: count tokens from session file vs. known model context limits
- Model context window from `--model` name (e.g., `MiniMax-M2.7` → 32k context) via a lookup table
- Accurate enough for threshold triggering; manual compact always available

**Manual compaction** (always available):
```
POST /sessions/<name>/compact
{"message": "Focus on decisions and action items"}  // optional custom instruction
```

### Session History Limit

**Config:** `max_session_age` (default: 30 days for `stopped` sessions)

Sessions not resumed within `max_session_age` after being stopped are marked `archived` (or optionally auto-deleted). Archived sessions are not counted toward `max_sessions`.

---

## Default Config

```json
{
  "session_idle_ttl": 1800,
  "max_sessions": 10,
  "max_session_age": 2592000,
  "context_threshold_pct": 75,
  "session_dir": "/workspace/.agentia/sessions"
}
```

All configurable via `agentia-agent serve --session-ttl 3600 --max-sessions 5 --context-threshold 80 ...`

---

## Host CLI (cli/host.py) — Dumb Client

The CLI doesn't track sessions. It just:

```bash
# New/resume conversation
agentia send <agent> <message>
  → POST /sessions/new?name=<default_conv>
  → POST /sessions/<name>/message {"content": "<message>"}

# Explicit conversation
agentia send <agent> --conv hawaii <message>
  → POST /sessions/new?name=hawaii
  → POST /sessions/hawaii/message {"content": "<message>"}

# List conversations
agentia sessions <agent>
  → GET /sessions

# Compact
agentia compact <agent> [--conv <name>]
  → POST /sessions/<name>/compact

# Delete conversation
agentia sessions delete <agent> <conv-name> [--hard]
  → DELETE /sessions/<name>[?hard=true]
```

The CLI can maintain a local `~/.agentia/<agent>/conversations.json` for display convenience (human-readable names), but this is purely local and optional — AgentServer is the source of truth.

---

## Open Questions

~~1. **Hard limit vs. graceful degradation** — when `max_sessions` hit, auto-stop oldest OR reject new session creation?~~ → **Resolved: LRU eviction (auto-stop oldest)**

~~2. **Who names conversations?**~~ → **Resolved: User-first. If not provided, agent generates. Filename = timestamp slug, title stored separately in manifest.**

~~3. **Cross-agent sessions**~~ → **Resolved: No. Each agent adapter has its own session namespace.**

~~4. **Compaction triggers**~~ → **Resolved: Auto-compact at ~75% context window usage. Manual always available via `POST /sessions/<name>/compact`.**
