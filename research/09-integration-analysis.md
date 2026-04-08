# Integration Analysis — Schema + Participation + OpenClaw Constraints

**Date:** 2026-04-08
**Researcher:** Jarvis

---

## Cross-Reference: All Three Systems

### System 1: Config Schema (Approach B — Pydantic)

Key decisions from prototype:
- Role persona/backstory → written to SOUL.md at adapter.setup() (OpenClaw injects it)
- AccessLevel → maps to OpenClaw tools.allow/deny during adapter.setup()
- Session sub-config (fork/resume) → OpenClaw supports via --session-id and session forking
- Adapter.tool_schema() → not yet implemented; OpenClaw exposes tools via --tools flag potentially

### System 2: Participation Evaluator (Approach C — Hybrid)

Key decisions from prototype:
- Runs OUTSIDE OpenClaw harness
- Evaluates BEFORE routing
- Passes context via message.metadata
- Fast rule filter (~80-90% of messages), LLM for ambiguous cases (~10-20%)

### System 3: OpenClaw Hidden Harnesses (research/05)

Key constraints:
- System prompt prepended (~30-50KB) — evaluator can't control this
- Tool schemas always sent (30-40KB) — evaluator can't strip these
- Workspace bootstrap always injected — role persona must be written to workspace files
- Skills loaded on-demand via read() — skills system is parallel to evaluator
- Memory auto-indexed — short-term = context window, long-term = memory_search

---

## Where They Fit Together

```
Host/Moderator
    │
    ▼
BaseRelay ── broadcasts ──► AgentServer
    │                          │
    │                    ┌─────┴──────┐
    │                    │ ParticipationEvaluator │
    │                    │  (Hybrid: rule+LLM)  │
    │                    └──────┬──────┘
    │                           │ evaluate() → active|observer|skip
    │                           ▼
    │                    ┌─────────────┐
    │                    │ AgentServer │
    │                    │  HTTP API   │
    │                    └──────┬──────┘
    │                           │ send() / send_async()
    │                           ▼
    │                    ┌─────────────┐
    │                    │ OpenClaw    │
    │                    │ Adapter     │
    │                    │ (subprocess)│
    │                    └──────┬──────┘
    │                           │
    │                    ┌──────┴───────────┐
    │                    │ OpenClaw gateway │ ← hidden harnesses live here
    │                    │ + workspace files │
    │                    └──────────────────┘
```

---

## Compatibility Matrix

| Constraint | Schema (B) | Participation (C) | Notes |
|-----------|-----------|-------------------|-------|
| Role persona → SOUL.md | ✅ Handled | N/A | Written at adapter.setup() |
| AccessLevel → tools.allow | ✅ Handled | N/A | Mapped in adapter.setup() |
| Session fork/resume | ✅ Handled | N/A | Via OpenClaw session flags |
| Participation function | N/A | ✅ Designed | Runs before routing |
| System prompt prepended | ⚠️ Can't control | ⚠️ Can't control | External constraint |
| Tool schemas always sent | ⚠️ Can't strip | N/A | External constraint |
| Memory auto-indexed | ⚠️ Can't disable | N/A | But can configure what gets indexed |

---

## Key Integration Points

### 1. Config → Adapter

When `adapter.setup()` runs:
1. Read `role.persona` → write to `/workspace/SOUL.md`
2. Read `role.backstory` → append to SOUL.md or write to AGENTS.md
3. Read `access_level` → set `tools.allow/deny` in OpenClaw config
4. Read `adapter.session` → store for session management
5. Read `knowledge.sources` → configure memory search paths

### 2. Participation → AgentServer

AgentServer's message handler:
```python
def handle_message(msg: RelayMessage):
    context = build_agent_context(msg)  # includes role, skills, memory_state
    level = evaluator.evaluate(msg, context)
    
    if level == "skip":
        return  # don't deliver
    elif level == "observer":
        deliver to inbox, no response expected
    else:  # active
        deliver via configured delivery mode
```

### 3. Delivery Modes

The participation level interacts with delivery:
- `active + sync` → send immediately, wait for response
- `active + inbox` → queue to inbox, agent polls
- `active + stream` → queue to inbox, agent streams response
- `observer` → deliver to inbox but agent knows not to respond

---

## Open Questions Resolved

### 1. Who evaluates participation?
**Answer: AgentServer** — evaluates before routing. The evaluator runs inside AgentServer, not inside OpenClaw. This is correct because:
- The evaluator needs to see the raw message before it goes to OpenClaw
- It needs to see agent config (role, skills, memory state)
- It runs on the agent side of the transport

### 2. How does the evaluator see agent context?
**Answer: Via AgentServer config** — AgentServer holds the full agent config. The evaluator receives `AgentContext` which is built from:
- `agent_id` (AgentServer's own ID)
- `role` (from AgentServerConfig)
- `skills` (from AgentServerConfig)
- `memory_state` (from AgentServer's memory backend)
- `conversation_history` (from inbox tracking)

### 3. Can the evaluator see what OpenClaw injects?
**No.** The evaluator runs outside OpenClaw. It cannot see:
- The system prompt
- Tool schemas
- Session history inside OpenClaw

This means the evaluator must work with EXTERNAL signals only:
- Message content
- Conversation ID / message history tracked outside OpenClaw
- Agent config
- Skills list from AgentServerConfig

---

## Integration Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Role persona written to SOUL.md overwrites existing workspace content | Medium | Backup SOUL.md before writing; preserve if already correct |
| Access level doesn't match OpenClaw's tools.allow format | Low | Validate against actual OpenClaw config schema |
| Evaluator adds latency to message routing | Low | Hybrid approach keeps 80-90% fast (rule-only) |
| LLM evaluator calls accumulate cost | Medium | Hybrid limits LLM calls to ~10-20%; set budget/cap |

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Integration analysis cross-referencing schema (B), participation evaluator (C), and OpenClaw constraints. Key finding: both approaches work within OpenClaw's constraints; role persona written at adapter.setup(), evaluator runs outside OpenClaw harness. Integration diagram produced.
next_trigger: Unit 5 — final synthesis
```
