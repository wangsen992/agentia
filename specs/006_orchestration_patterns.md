# Orchestration Patterns — Design Decision

## Decision: Start with Moderator Only

**Do not build a spectrum yet.** Emergent/autonomous behavior is the end state, but it's not the starting point.

> "You need the controlled case before the emergent one is meaningful. You need the controlled case before the emergent one is meaningful."

## Why Moderator First

- **Observable** — you can establish a baseline of what "correct" orchestration looks like
- **Auditable** — goal lives in one place, traceable
- **Stop condition** — deterministic (turn limit), easy to measure
- **Transcript** — guaranteed complete output
- **Debuggable** — when it breaks you know where

The autonomous mode will reveal itself through pain points once the moderator is running.

---

## The Two Load-Bearing Questions (Answered)

### 1. What is the output?
**Answer: Transcript** (not decision, not consensus, not vote)

A transcript is the minimal useful output. It lets you:
- Measure response quality
- Replay or resume conversations
- Build evaluation datasets

Decisions/consensus require post-processing on top of a transcript. Build the foundation first.

### 2. Where does the goal live?
**Answer: In the Moderator**

The moderator holds the topic/goal. Agents receive it as part of their system prompt or first message. This is simplest and most auditable for research.

Agents agreeing on a goal is a future layer (interesting but adds negotiation overhead before studying core behavior).

---

## Clean Moderator Spec (Control Condition)

```
Moderator
├── Holds: topic, turn count, stopping condition
├── Sends: role assignment (first), then alternating prompts with history
├── Receives: responses from each agent
├── Output: full transcript (list of TurnRecord)
└── Stopping: turn limit reached OR explicit STOP signal
```

### TurnRecord shape:
```python
@dataclass
class TurnRecord:
    turn: int
    agent_id: str
    role: str
    prompt: str       # what was sent
    response: str    # what came back
    duration_ms: float
```

### Moderator output:
```python
@dataclass
class ConversationResult:
    topic: str
    turns: list[TurnRecord]
    num_turns: int
    ended_at: datetime
    stop_reason: str  # "turn_limit" | "stop_signal" | "error"
```

---

## What to Build Next (SPEC 007)

**Moderator + InboxRelay integration test — end to end**

Two agent containers + moderator + inbox relay, all talking to each other:
1. Moderator uses InboxRelay to send prompts to each agent
2. Each agent runs as inbox_poller (agent mode)
3. Poller receives message, calls OpenClaw, returns response via correlation ID
4. Moderator collects responses, builds history, sends next prompt
5. After N turns: Moderator returns ConversationResult

This is the control condition. Once it runs reliably on real tasks, the pain points will tell us which autonomous features to add.

---

## Future (Autonomous Pattern) — Deferred

Do NOT design ahead of these. Wait for real pain:
- Shared board / message board pattern
- Agents managing own conversation state
- Convergence detection (when does an agent stop?)
- Hybrid: moderator sets up → board takes over

> "Once you have that running on real tasks, the places where it feels wrong will tell you exactly which autonomous features are actually worth adding."

---

## Architecture Context

Moderator uses **BaseRelay** for multi-agent coordination. The underlying transport has been refactored (see SPEC 005):

```
Moderator
    ↓
BaseRelay (unchanged interface to moderator)
    ↓
HostContainerBackend (transport to agent side)
    ↓
AgentServer (HTTP/WebSocket, owns inbox pattern)
    ↓
AgentAdapter → Agent process
```

The moderator itself is unaffected by this refactor — it still calls `relay.send()` and `relay.broadcast()` with `RelayMessage` objects.

## Related Specs

- [SPEC-005_relay_inbox.md](./005_relay_inbox.md) — AgentServer architecture
- [SPEC-008_agent_self_configuration.md](./008_agent_self_configuration.md) — Agent self-configuration with verify loop
