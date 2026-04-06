# SPEC 005: Relay & Inbox Architecture — 2026-04-06

## Goal

Define how agents communicate asynchronously in a multi-agent system. Agents should be able to:
- Send messages to named recipients
- Receive messages into an inbox even when busy
- Process messages on their own schedule
- Support one-way notifications (no response required)

## Why This Matters

The current `Relay` + `Moderator` pattern is **synchronous and moderator-driven**:
- Moderator asks Agent A → waits → gets response → asks Agent B → ...
- Agents are always responding, never initiating
- No concept of "I have mail"

Real multi-agent systems need **async message passing**:
- Agent A spawns Agent B → doesn't wait → continues working
- Agent B finishes → sends result to Agent A's inbox
- Agent A picks it up when ready

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Inbox Relay                           │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│  │ Agent A  │    │ Agent B  │    │ Agent C  │           │
│  │ Inbox    │    │ Inbox    │    │ Inbox    │           │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘           │
│       │               │               │                  │
│       └───────────────┴───────────────┘                  │
│                   ▲                                      │
│                   │ push / pull                          │
│         ┌─────────┴──────────┐                           │
│         │   Inbox Relay     │                           │
│         │  (message router) │                           │
│         └─────────┬─────────┘                           │
│                   │                                      │
│         ┌─────────┴──────────┐                           │
│         │  ExecRelay        │                           │
│         │  (docker exec)     │                           │
│         └───────────────────┘                           │
└─────────────────────────────────────────────────────────┘
```

## Core Concepts

### Inbox

Each agent has an **inbox** — a queue of messages waiting to be processed.

```python
@dataclass
class Message:
    id: str              # UUID
    from_agent: str      # sender agent ID
    to_agent: str        # recipient agent ID
    content: str         # message text
    timestamp: float     # when received
    correlation_id: str  # for tracing request/response pairs
    reply_to: Optional[str]  # set if this is a reply to a specific message
    ttl: int = 3600      # messages expire after 1 hour
```

### Message Patterns

| Pattern | Description | Use case |
|---------|-------------|----------|
| **Fire-and-forget** | Send without waiting | Notifications, spawning subagents |
| **Request/response** | Send and wait for reply | Task delegation with result |
| **Broadcast** | One message to all agents | Topic announcement |

### Relay Interface

The relay is the transport layer. Two implementations:

**ExecRelay** (current) — uses `docker exec` to drive containers:
```
- Simpler, no auth needed
- Message sent via `docker exec openclaw agent --message`
- Response returned via stdout
- Good for: spawning, synchronous tasks
```

**InboxRelay** (new) — persistent inbox per agent:
```
- Agent polls its inbox on a schedule
- Messages stored in a shared volume (JSON Lines per agent)
- Allows async delivery: agent can be busy, messages queue up
- Good for: background agents, monitoring agents
```

## File Layout

```
relay/
├── __init__.py
├── base.py              ← BaseRelay abstract class
├── exec_relay.py        ← (existing) docker exec relay
├── inbox_relay.py       ← (new) async inbox-based relay
├── moderator.py         ← (existing) conversation orchestration
└── inbox.py             ← (new) Inbox data structure + persistence
```

## Inbox File Format

```
inbox/
├── <agent_id>.jsonl     ← One JSON Lines file per agent
│   {"id":"...","from":"A","content":"...","timestamp":...}
```

Messages are appended as they're received. Agent reads and marks them processed.

## Open Questions

1. **Polling interval** — how often does an agent check its inbox? Configurable, default 5s?
2. **Message ordering** — FIFO is fine for now, no priority needed yet
3. **TTL expiration** — who cleans up expired messages? Background task or on-read?
4. **Persistence** — do messages survive agent restart? Inbox files on shared volume yes, container restart no
5. **Moderator role** — does the moderator become just another agent, or does it stay as the orchestrator layer?
6. **Gateway integration** — does the InboxRelay replace ExecRelay, or do they coexist?

## Implementation Order

1. `relay/base.py` — define `BaseRelay` abstract interface
2. `relay/inbox.py` — `Message` dataclass, `Inbox` class with file persistence
3. `relay/inbox_relay.py` — `InboxRelay` implementation
4. `relay/moderator.py` — refactor to use `BaseRelay`
5. Test with two-agent scenario: Agent A spawns Agent B, B delivers result to A's inbox

## Relationship to Existing Code

- `relay.py` (WebSocket) — keep for future when we have persistent gateway connections
- `exec_relay.py` — keep, it's the reliable workhorse for now
- `moderator.py` — refactor to use `BaseRelay` so it works with either implementation
