# SPEC: Observability Layer — 2026-04-05

## Goal

Instrument agentia to produce structured, queryable logs of everything happening in the system — without changing agent behavior.

## What to Capture

**Three log streams:**

```
logs/
├── session_<SESSION_ID>.jsonl   ← one file per session run
├── agent_<AGENT_ID>.jsonl       ← per-agent lifecycle events
└── relay_<TIMESTAMP>.jsonl      ← message routing events
```

**Event types:**

| Stream | Event | Fields |
|--------|-------|--------|
| `session_*.jsonl` | `send` | timestamp, adapter_type, session_id, message_preview, duration_ms, response_preview, returncode |
| `session_*.jsonl` | `lifecycle` | timestamp, event (setup/start/stop/teardown), duration_ms |
| `agent_*.jsonl` | `gateway_start` | timestamp, gateway_pid, port |
| `agent_*.jsonl` | `gateway_stop` | timestamp, gateway_pid, exit_code |
| `relay_*.jsonl` | `message_sent` | timestamp, from_agent, to_agent, correlation_id, message_preview |
| `relay_*.jsonl` | `message_delivered` | timestamp, to_agent, delivery_time_ms |

## Design

```
observability/
├── __init__.py
├── logger.py          ← StructuredLogger (JSON Lines writer, thread-safe)
├── session.py         ← SessionLogger (per-run, used by harness)
└── adapters/
    └── openclaw.py   ← OpenClawAdapter instrumentation
```

**StructuredLogger** — thread-safe, writes JSON Lines to file:
```python
logger = StructuredLogger("session", session_id="abc123")
logger.log("send", message_preview="What is 2+2?", duration_ms=1234, ...)
```

**SessionLogger** — context manager that manages log file lifecycle:
```python
with SessionLogger(session_id, adapter_type="openclaw") as logger:
    adapter.send("What is 2+2?")
    logger.log_response(result)
```

**Harnesses get logging for free** — pass `log=True` to harness:
```python
harness = MultiTurnHarness(workspace=args.workspace, log=True)
result = harness.run(args.prompt, ...)
# logs/ now has session_<id>.jsonl with everything captured
```

## What Gets Logged

From `OpenClawAdapter`:
- `setup_start` / `setup_done` (with duration)
- `gateway_start` (gateway PID, port)
- `gateway_ready` (with time-to-ready)
- `gateway_stop` (with exit code)
- `send_start` / `send_done` (per message, with duration)
- `teardown_done`

From harnesses:
- Turn number, prompt, response, duration
- Subagent detection (had_subagents result)

From relay (when built):
- Message routing events
- Correlation IDs
- Delivery confirmation

## Implementation Order

1. `observability/logger.py` — StructuredLogger base class
2. `observability/session.py` — SessionLogger context manager
3. `OpenClawAdapter` — add logging to all lifecycle and send events
4. `harnesses` — add `--log/--no-log` flag, pass logger to adapter

## Output Format

Each line is a valid JSON object:
```json
{"timestamp": "2026-04-06T02:57:00.123Z", "event": "send", "session_id": "abc123", "message_preview": "What is 2+2?", "duration_ms": 1234, "returncode": 0}
```

Can be queried with `jq`:
```bash
cat logs/session_abc123.jsonl | jq '.event == "send"'
cat logs/session_abc123.jsonl | jq '.duration_ms > 5000'
```
