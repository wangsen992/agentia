# Agentia Codebase Audit — Current Agent State

**Date:** 2026-04-08
**Researcher:** Jarvis

---

## Current Agent Config

### AgentServerConfig (agent_side/config.py)

The current config is **infrastructure-only** — no composition dimensions:

```python
@dataclass
class AgentServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    delivery: str = "inbox"          # inbox | sync | stream
    poll_interval: float = 2.0
    inbox_dir: str = "/workspace/inbox"
    responses_dir: str = "/workspace/inbox/responses"
    agent_timeout: int = 120
    log_level: str = "info"
```

**Missing from our model:**
- No Role (persona/goal/backstory)
- No Adapter type/config
- No Access Level
- No Memory
- No Knowledge
- No Skills
- No Participation
- No Session (sub-dimension of Adapter)
- No Lifecycle

The current `delivery` field maps to our Participation dimension.

### ConfigManager

- Loads from `~/.agentia/agent.json`
- Supports partial update via `PATCH /config`
- Atomic write-then-reload
- Simple and well-designed

---

## Current AgentAdapter Base

### Interface (agents/adapters/base.py)

```python
class AgentAdapter(ABC):
    session_id: Optional[str] = None
    
    def setup(self) -> None       # lifecycle: once before first use
    def teardown(self) -> None    # lifecycle: once when done
    def start(self, session_id=None, **opts) -> str
    def send(self, message: str) -> AgentResponse
    def stop(self) -> None
    def is_running(self) -> bool  # default: False
    def get_session_id() -> Optional[str]
    def get_session_trace(session_id=None) -> list  # raises NotImplementedError
```

### What's Missing from Our Adapter Contract

| Our Contract | Current? |
|-------------|----------|
| `send(prompt) → str` | ✅ `send(message)` exists |
| `send_stream(prompt) → Iterator[str]` | ❌ No streaming |
| `healthcheck() → bool` | ❌ No healthcheck |
| `tool_schema() → dict` | ❌ No tool schema |

### AdapterFactory (agents/adapters/factory.py)

- Lazy registration from `agents/adapters/<name>.py`
- `get_adapter(runtime: str, **opts) → AgentAdapter`
- Currently only OpenClaw registered
- Clean pattern — easy to add new adapters

---

## Current OpenClawAdapter (agents/adapters/openclaw.py)

The adapter wraps `openclaw agent` CLI subprocess. Key characteristics:

**Lifecycle:**
- `setup()` → patches config for loopback bind + no auth → starts gateway → waits for ready → approves pairings
- `teardown()` → kills gateway
- `start(session_id)` → sets session ID (non-blocking init)
- `send(message)` → `openclaw agent --session-id <id> --message <msg>` → blocks for full response
- `stop()` → no-op (process exits after each send)

**Session Management:**
- Session ID generated as `agent-{uuid8}`
- Session trace read from `~/.openclaw/agents/main/sessions/{sid}*.jsonl`

**Tool Schema:**
- No tool schema exposed
- All OpenClaw tools available (via system prompt injection)
- Adapter has no control over tool list

---

## Key Structural Observations

### What Works Well
1. **Adapter factory pattern** — easy to add new runtimes
2. **ConfigManager** — atomic updates, disk persistence, clean partial update API
3. **AgentAdapter lifecycle** — setup/teardown/start/send/stop is a clean minimal interface
4. **Delivery mode** — already has `delivery: inbox | sync | stream` in config

### What Needs Extension
1. **Config is flat** — no concept of nested dimensions (Role, Memory, Knowledge as objects)
2. **Adapter interface is minimal** — no streaming, no healthcheck, no tool schema
3. **No participation evaluator** — delivery mode is a static config, not a function
4. **No skills system** — adapters expose all their tools, no capability filtering
5. **No session sub-dimensions** — session fork/resume not configurable

### OpenClaw Hidden Harnesses (from research/05)

These are realities the adapter must work around:
- Workspace bootstrap files always injected (SOUL.md, IDENTITY.md, USER.md, AGENTS.md)
- Tool schemas always sent (30-40KB, non-configurable)
- System prompt always prepended (~30-50KB)
- Skills loaded on-demand via `read` on SKILL.md
- Memory auto-indexed for MEMORY.md and memory/*.md

---

## Mapping Current → Target Model

| Current | Becomes |
|---------|---------|
| `AgentServerConfig.delivery` | `Participation.delivery` (static default) |
| `AgentServerConfig.host/port` | Infrastructure (unchanged) |
| `AgentServerConfig.inbox_dir` | Infrastructure (unchanged) |
| `AgentAdapter` | Extended with `healthcheck()`, `tool_schema()`, `send_stream()` |
| `AgentServerConfig` | Extended with Role, Adapter, Access Level, Memory, Knowledge, Skills, Participation.function, Session, Lifecycle |

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Audit of Agentia's current agent state. Config is infrastructure-only (no composition dimensions). AgentAdapter is minimal (no streaming, healthcheck, or tool_schema). Factory pattern is clean. Delivery mode exists but is static config, not a function.
next_trigger: Units 2 and 3 — schema options and participation evaluator prototypes
```
