# SPEC 005: Relay & Inbox Architecture — 2026-04-07
**Updated:** 2026-04-09

## Goal

Define how agents communicate asynchronously in a multi-agent mesh, with clear separation between:
- **Routing** (which agent to contact)
- **Transport** (how messages cross machine boundaries — HTTP API)
- **Delivery patterns** (how messages are handled on the receiving agent side)

## Why This Matters

The original `Relay` + `Moderator` pattern was **synchronous and moderator-driven**:
- Moderator asks Agent A → waits → gets response → asks Agent B → ...
- Agents are always responding, never initiating
- No concept of "I have mail"

Real multi-agent systems need **async message passing**:
- Agent A sends to Agent B → doesn't wait → continues working
- Agent B finishes → sends result back to Agent A
- Agent A picks it up when ready

---

## Architecture: Peer-to-Peer Mesh

There is no central hub. Each machine runs a **symmetric node** — both a server (receives messages) and a client (sends messages to other agents).

```
Machine A (your Mac)
  ├── AgentServer (agent.py)     ← receives messages
  └── host.py                    ← sends messages to any peer

Machine B (cloud VM)
  ├── AgentServer (agent.py)     ← receives messages
  └── host.py                    ← sends messages to any peer
```

Communication is always machine-to-machine HTTP. No relay, no backend adapter.

```
Agent A (Machine A)                     Agent B (Machine B)
       │                                      ↑
       │  HTTP POST /sessions/.../message      │
       │ ──────────────────────────────────► │
       │                                      │ processes, generates response
       │  response (Scenario 1: A polls)     │
       │ ◄────────────────────────────────── │
       │  OR                                 │
       │  response (Scenario 2: B calls A)  │
       │ ──────────────────────────────────► │
```

**Every machine in the mesh runs both:**
- `agent.py` — AgentServer HTTP API (receiving end)
- `host.py` — HTTP client (sending end, available to the agent as a tool)

---

## Transport: Pure HTTP API

Messages cross machine boundaries via HTTP POST to the target machine's AgentServer. No SSH tunnels, no docker exec, no cloud-specific backends. Any machine with an HTTP server and network reachability can participate in the mesh.

This replaces the HostContainerBackend concept from the original spec — that layer is no longer relevant since all communication is HTTP-to-HTTP.

---

## Two Response Scenarios

### Scenario 1: Initiator polls for response

Agent A sends message to Agent B, then polls B's API for the response.

- A sends via HTTP POST to B's AgentServer
- B stores conversation on B's machine, processes, stores response
- A polls: `GET /responses?from_agent=B`
- B returns stored response
- A receives it as a conversation

**Tradeoff:** Simple, no machine needs a publicly reachable HTTP server. But requires A to poll periodically.

### Scenario 2: Responder proactively delivers response

Agent B sends the response back to Agent A by calling A's HTTP API.

- A sends via HTTP POST to B's AgentServer
- B processes, generates response
- B uses its own `host.py` to call A's AgentServer: `POST /message` with the response
- A receives it as a conversation on A's machine

**Tradeoff:** Immediate delivery, but requires A's machine to have a reachable HTTP endpoint.

**For V1, Scenario 1 (polling) is recommended** because it works without any machine needing a publicly reachable HTTP server.

---

## Layer Responsibilities

| Layer | Responsibility | Location |
|-------|----------------|----------|
| **host.py** | Sends messages to any peer agent by URL | Any machine (host or agent) |
| **AgentServer** | Receives messages, manages sessions, delivers responses | Any machine |
| **SessionManager** | Manages pi subprocess lifecycle, session files | Inside AgentServer |
| **AgentAdapter** | Per-message contract: send(str) → response | Inside AgentServer |

---

## File Layout

```
~/.agentia/
├── agents.json          # host-side registry: name → URL mapping
├── conversations/       # host-side conversation state
└── peers.json          # peer agents known from this machine (name → URL)

# On each remote machine:
~/.agentia/
├── agents.json          # local registry (may differ from host's)
└── peers.json          # mirrors known peers for this machine
```

---

## Current File Structure

```
relay/
├── __init__.py          ← (deprecated, HostContainerBackend removed 2026-04-09)
├── base.py              ← (deprecated, no longer needed)
└── backends/
    ├── base.py          ← (deprecated)
    ├── docker.py        ← (deprecated)
    └── ssh.py           ← (deprecated)

agent_side/
├── server.py            ← AgentServer HTTP server
├── config.py            ← ConfigManager
├── harness.py           ← Internal harness
└── patterns/
    ├── inbox.py         ← File-based inbox delivery
    └── sync.py          ← Direct subprocess delivery

agents/adapters/         ← AgentAdapter implementations
├── __init__.py
├── base.py
├── factory.py
└── pi_agent.py         ← pi-agent adapter

cli/
├── agent.py             ← agent-side CLI (runs AgentServer)
└── host.py              ← host-side CLI + available to agents as tool
```

> **Note:** The `relay/` directory and its backends are deprecated as of 2026-04-09. All transport is now pure HTTP API. The directory remains for reference until cleaned up.

---

## Open Questions

1. ~~**HostContainerBackend**~~ — resolved: removed, HTTP-to-HTTP is the only transport
2. **Discovery** — how do agents learn peer URLs? V1: static `peers.json` config
3. **Scenario 1 vs 2** — V1 uses Scenario 1 (polling). Scenario 2 (proactive delivery) deferred until a machine needs a publicly reachable HTTP endpoint
4. **Moderator role** — can an agent act as moderator for sub-agents? Uses same mesh communication; no spec changes needed
