# SPEC 005: Relay & Inbox Architecture — 2026-04-07

## Goal

Define how agents communicate asynchronously in a multi-agent system, with clear separation between:
- **Routing** (multi-agent coordination)
- **Transport** (how messages cross deployment boundaries)
- **Delivery patterns** (how messages are handled on the agent side)

## Why This Matters

The original `Relay` + `Moderator` pattern was **synchronous and moderator-driven**:
- Moderator asks Agent A → waits → gets response → asks Agent B → ...
- Agents are always responding, never initiating
- No concept of "I have mail"

Real multi-agent systems need **async message passing**:
- Agent A spawns Agent B → doesn't wait → continues working
- Agent B finishes → sends result to Agent A's inbox
- Agent A picks it up when ready

---

## Architecture

```
Host side:
┌─────────────────────────────────────────────────────────────┐
│ BaseRelay                                                     │
│ - Multi-agent routing, broadcast, connection management       │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ HostContainerBackend                                          │
│ - Adapts to employment environment                            │
│ - HTTP client / SSH tunnel / cloud API / docker exec         │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓ (deployment-specific network)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent side (inside container / remote host):
                      ↑
                      │
┌─────────────────────────────────────────────────────────────┐
│ AgentServer                                                   │
│ - Universal HTTP/WebSocket interface                         │
│ - Configurable delivery pattern (inbox, sync, streaming)      │
│ - Owns AgentAdapter lifecycle                                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ AgentAdapter                                                  │
│ - Per-message contract: send(str) → AgentResponse            │
│ - Lifecycle: setup/start/send/stop/teardown                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓
              Agent process
```

### Layers

| Layer | Responsibility | Examples |
|-------|----------------|----------|
| **BaseRelay** | Multi-agent routing, broadcast, connection management | Moderator talks to this |
| **HostContainerBackend** | Adapts to deployment environment | Docker exec, SSH tunnel, HTTP, cloud API |
| **AgentServer** | Delivery patterns, universal interface, owns AgentAdapter | Listens on HTTP/WebSocket |
| **AgentAdapter** | Per-message send/receive contract | OpenClawAdapter |

---

## Core Concepts

### RelayMessage

Unified message type across all relay implementations:

```python
@dataclass
class RelayMessage:
    content: str                      # message text
    from_agent: Optional[str] = None  # sender ID
    to_agent: Optional[str] = None    # single recipient
    to_agents: Optional[list[str]] = None  # broadcast recipients
    correlation_id: Optional[str] = None  # request/response matching
    metadata: Optional[dict] = None   # additional data
    id: Optional[str] = None          # UUID, auto-generated
    timestamp: Optional[float] = None # auto-generated
```

### Message Patterns

| Pattern | Description | Use case |
|---------|-------------|----------|
| **Fire-and-forget** | `send_async()` without waiting | Notifications, spawning subagents |
| **Request/response** | `send()` with correlation_id | Task delegation with result |
| **Broadcast** | `broadcast()` to multiple agents | Topic announcement |

### Delivery Patterns (AgentServer-side)

AgentServer supports configurable delivery behavior:

**Inbox Pattern** (current):
```
- Messages queued in inbox
- Agent polls inbox on schedule
- Response written to correlation file
- Good for: background agents, monitoring agents
```

**Sync Pattern** (future):
```
- Message delivered directly to agent
- Response returned immediately
- Good for: interactive agents
```

**Streaming Pattern** (future):
```
- Message delivered via WebSocket stream
- Partial responses streamed back
- Good for: long-running tasks with progress
```

---

## AgentServer Interface

AgentServer exposes HTTP/WebSocket endpoints:

```python
class AgentServer:
    # Lifecycle
    def setup(self) -> None       # provision gateway, identity
    def start(self) -> None       # start listening
    def stop(self) -> None        # stop listening
    def teardown(self) -> None     # cleanup

    # Message handling
    def send(self, message: RelayMessage) -> str
        # POST /message → blocks until response

    def send_async(self, message: RelayMessage) -> bool
        # POST /message/async → queues and returns immediately

    def poll_inbox(self, agent_id: str, max: int = 10) -> list[RelayMessage]
        # GET /inbox → returns queued messages

    def write_response(self, correlation_id: str, content: str) -> bool
        # POST /response → writes response for correlation

    # Configuration
    def set_delivery_pattern(self, pattern: str) -> None
        # "inbox" | "sync" | "stream"
```

---

## HostContainerBackend Implementations

| Backend | Transport | Use Case |
|---------|-----------|----------|
| **DockerBackend** | docker exec → HTTP to AgentServer | Local Docker containers |
| **SSHBackend** | SSH tunnel → HTTP to AgentServer | Remote host access |
| **CloudBackend** | Cloud API → HTTP to AgentServer | Cloud-hosted agents |
| **WebSocketBackend** | WebSocket to AgentServer | Persistent connections |

---

## File Layout

```
relay/
├── __init__.py
├── base.py              ← BaseRelay abstract class + RelayMessage
├── moderator.py          ← Conversation orchestration
├── backends/
│   ├── __init__.py
│   ├── base.py          ← HostContainerBackend interface
│   ├── docker.py        ← Docker exec → HTTP to AgentServer
│   ├── ssh.py           ← SSH tunnel → HTTP to AgentServer
│   └── websocket.py     ← WebSocket to AgentServer

agent_side/
├── server.py            ← AgentServer implementation
├── adapters/
│   ├── base.py          ← AgentAdapter interface
│   └── openclaw.py      ← OpenClawAdapter
└── patterns/
    ├── inbox.py         ← Inbox delivery pattern
    ├── sync.py          ← Sync delivery pattern
    └── stream.py        ← Streaming delivery pattern
```

---

## Inbox File Format (legacy, now internal to AgentServer)

```
AgentServer inbox directory (internal):
/workspace/inbox/
├── <agent_id>.jsonl     ← One JSON Lines file per agent
│   {"id":"...","from":"A","content":"...","timestamp":...}
```

Note: Inbox files are now an internal detail of AgentServer's inbox pattern implementation, not exposed to BaseRelay.

---

## Open Questions

1. ~~**Polling interval**~~ — resolved: AgentServer exposes `poll_inbox`, polling strategy is AgentServer configuration
2. ~~**Message ordering**~~ — resolved: FIFO is fine
3. ~~**TTL expiration**~~ — resolved: AgentServer handles expiration internally
4. ~~**Persistence**~~ — resolved: Inbox files survive container restart if on shared volume
5. **Streaming pattern** — deferred, when real pain point emerges
6. **AgentServer discovery** — how does HostContainerBackend find AgentServer? Static config? Service discovery?

---

## Implementation Phases

### Phase 1: Define interfaces
- [ ] `HostContainerBackend` abstract interface
- [ ] `AgentServer` interface definition

### Phase 2: Implement AgentServer
- [ ] HTTP server with inbox pattern
- [ ] `poll_inbox` and `write_response` endpoints
- [ ] AgentAdapter lifecycle management

### Phase 3: Implement HostContainerBackend
- [ ] `DockerBackend` → HTTP client to AgentServer
- [ ] `WebSocketBackend` → WebSocket client to AgentServer

### Phase 4: Update BaseRelay
- [ ] Refactor to use HostContainerBackend
- [ ] Remove embedded behavioral patterns

### Phase 5: Deprecate gateway_harness
- [ ] Absorb into AgentServer

---

## Relationship to Existing Code

- `relay/base.py` — BaseRelay + RelayMessage (still relevant, interface unchanged)
- `relay/exec_relay.py` → becomes `relay/backends/docker.py`
- `relay/inbox_relay.py` → AgentServer inbox pattern + DockerBackend
- `relay/websocket_relay.py` → becomes `relay/backends/websocket.py`
- `gateway_harness` → absorbed into AgentServer setup
- `agents/adapters/openclaw.py` — AgentAdapter implementation (unchanged)

---

## References

- Issue #12: AgentServer meta-issue
- SPEC 006: Orchestration patterns (moderator still uses BaseRelay)
- SPEC 008: Agent self-configuration (AgentServer enables restart endpoint)
