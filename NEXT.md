# Session Management Implementation — NEXT

## Spec
`specs/020_session_management.md`

## Phases

### Phase 1: SessionManager class (pi_agent.py)
- Add `SessionManager` class — manages multiple named sessions
- Per-session `session_dir = <base>/sessions/<name>/`
- Spawn: `pi --session-dir <dir> --continue`
- Route message to correct subprocess by name
- Manifest I/O: read/write `manifest.jsonl`
- Status tracking: running, stopped
- Fields per session: name, title, status, pid, session_file, started_at, message_count, context_pct, last_active

### Phase 2: AgentServer API (server.py)
- `POST /sessions/new` — create/resume named session
- `POST /sessions/<name>/message` — send to running session
- `GET /sessions` — list all
- `GET /sessions/<name>` — get one
- `POST /sessions/<name>/compact` — trigger compaction
- `DELETE /sessions/<name>[?hard=true]` — stop or delete

### Phase 3: Resource Management
- Idle TTL: per-session background timer, SIGTERM on expiry
- Max sessions: LRU eviction when limit hit
- Auto-compact: context_pct estimation post-message

### Phase 4: Host CLI (host.py)
- `agentia sessions <name>` — list sessions
- `agentia send <name> --conv <conv> <msg>` — send to specific conv
- `agentia compact <name> [--conv <conv>]` — manual compact
- `agentia session delete <name> <conv> [--hard]` — delete

### Phase 5: Test
- Rebuild image
- Start container
- Create multiple sessions, switch between them
- Verify session persistence
- Verify idle timeout
- Verify LRU eviction at max_sessions

## Constraints
- AgentServer must stay backward-compatible with existing `/message` (single-session mode)
- Existing `cli/host.py send` command must keep working without --conv flag
