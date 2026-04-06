# SPEC: Observability Layer — 2026-04-05

## Goal

Instrument agentia to produce structured, queryable logs of everything happening in the system — without changing agent behavior.

## Design Decision: Single-File Per Session

All events for a session (including subagent traces) are written to one file: `logs/session_<SESSION_ID>.jsonl`.

**Why single-file:**
- Complete session story in one place — no joining required
- Simpler implementation, no file lifecycle coordination
- Subagent traces are fetched on-demand from the running agent, not written independently

**Limitation:** Subagent `session_id` is not always recoverable from the session trace. OpenClaw assigns session IDs internally after `sessions_spawn` returns. The UUID may appear in the thinking text as `agent:main:subagent:<uuid>` but this is not guaranteed — thinking may be truncated or omit it. When not found, `session_id=None` and `session_id_known=False` are logged.

**Future consideration (not implemented):**
Per-subagent log files could be added later if:
- Subagent sessions run independently and long-lived
- You need to query individual subagent histories separately
- The file becomes too large to manage

The linking fields (`parent_session_id`, `subagent_session_id`) are already in the log events, so migration to separate files would be backward-compatible.

## What Gets Captured

**Per session, one file (`logs/session_<SESSION_ID>.jsonl`):**

| Event | Fields |
|-------|--------|
| `session_start` | session_id, adapter_type |
| `lifecycle_event` | event_name, phase (start/end), duration_ms |
| `gateway_start` | gateway_pid, port |
| `gateway_ready` | wait_seconds |
| `gateway_stop` | gateway_pid |
| `pairing_approved` | req_id |
| `pairing_none` | — |
| `send` | turn, prompt_preview, response_preview, stderr_preview, returncode, duration_ms, trace_entries, has_thinking, thinking_count, tool_call_count, has_subagents, subagent_count |
| `thinking_snapshot` | turn, thinking_blocks (list of {timestamp, thinking, signature}) |
| `subagents_spawned` | turn, subagents (list of {session_id, agent_id, message}) |
| `subagent_session_start` | parent_session_id, subagent_session_id, subagent_agent_id, subagent_message |
| `subagent_trace` | subagent_session_id, trace_entries, has_thinking, thinking_count, tool_call_count, thinking |
| `subagent_session_end` | subagent_session_id |
| `session_end` | session_id |

## Architecture

```
observability/
├── __init__.py
├── logger.py              ← StructuredLogger (thread-safe JSON Lines writer)
├── session.py             ← SessionLogger (context manager + helpers)
└── session_trace.py       ← Trace parsing utilities (extract_thinking, extract_subagent_ids, parse_trace)
```

**StructuredLogger** — thread-safe, writes JSON Lines to file:
```python
logger = StructuredLogger("session", key="abc123")
logger.log("send", duration_ms=1234, ...)
```

**SessionLogger** — context manager with lifecycle and trace helpers:
```python
with SessionLogger("openclaw", session_id="abc") as logger:
    adapter.send("What is 2+2?")  # sends with trace → logger auto-captures
```

**session_trace.py** — trace parsing utilities:
```python
thinking = extract_thinking(trace)
subagent_ids = extract_subagent_ids(trace)
parsed = parse_trace(trace)  # full structured parse
```

## Implementation Status

✅ logger.py — StructuredLogger with thread-safe JSON Lines
✅ session.py — SessionLogger with context manager, log_send, capture_subagent_traces
✅ session_trace.py — extract_thinking, extract_subagent_ids, parse_trace
✅ OpenClawAdapter — all lifecycle and send events logged
✅ All harnesses — `--log` flag (single/multi/ipc) or `LOG=1` env var (interactive/gateway)

## Output Format

Each line is a valid JSON object:
```json
{"timestamp": "2026-04-06T03:15:59.628+00:00", "event": "send", "stream": "session", "key": "abc123", "adapter_type": "openclaw", "turn": 1, "prompt_preview": "What is 2+2?", "response_preview": "4", "duration_ms": 9980.62, "has_thinking": true, "thinking_count": 1, "has_subagents": false}
```

Query examples:
```bash
# All send events with timing
cat logs/session_abc123.jsonl | jq 'select(.event == "send")'

# Sessions that spawned subagents
cat logs/session_abc123.jsonl | jq 'select(.has_subagents == true)'

# Thinking blocks
cat logs/session_abc123.jsonl | jq 'select(.event == "thinking_snapshot")'

# Subagent traces
cat logs/session_abc123.jsonl | jq 'select(.event == "subagent_trace")'
```

## Open Questions

1. **Per-agent log files** — decide later based on file size and query needs
2. **Relay log stream** — when inbox/relay is built, add `relay_*.jsonl` stream
3. **Trace verbosity** — currently logs all thinking. May want to truncate for storage.
