# SPEC 005: Relay & Inbox Architecture — 2026-04-07
**Updated:** 2026-04-09 (mesh model merged from SPEC 012)

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

The second insight: `host.py` is not just a host-side tool for the human. It is also a **first-class tool available to agents** running on remote machines. An agent can decide on its own to reach out to another agent — not just when the human tells it to.

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
mesh.json                # central mesh config: all agents and their URLs (shared, git, or HTTP)
~/.agentia/
├── agents.json          # host-side registry: name → URL mapping
├── conversations/       # host-side conversation state
└── peers.json          # local copy of mesh.json, updated on boot and periodically

# On each remote machine:
~/.agentia/
├── agents.json          # local registry
└── peers.json          # local copy of mesh.json
```

---

## Discovery: mesh.json

Each agent pulls from `mesh.json` to discover peers. The file lives in a shared, writable location accessible to all agents.

```json
{
  "mesh": {
    "agents": {
      "research-agent": "http://vm-research.example.com:8080",
      "coding-agent": "http://vm-coding.example.com:8080",
      "review-agent": "http://192.168.1.50:8080"
    }
  }
}
```

- **Where it lives:** git repo, shared NFS volume, simple HTTP server, or a dedicated registry machine
- **How agents use it:** on boot and periodically, agents pull `mesh.json` and update their local `peers.json`
- **How changes propagate:** you edit `mesh.json` from any machine (no special admin machine required), push/sync, and all agents pick it up on their next pull
- **No central server required:** `mesh.json` is just a file. Any machine with access to that location can update it

### Why this works without a central server

`mesh.json` doesn't need to be served by a special process. It can be:
- A file in a git repository that all machines pull from
- A file on a shared network drive (NFS, SMB)
- A simple static file served by any HTTP server
- A file on a dedicated "admin" machine that you SSH into

The admin machine isn't architecturally special — it's just whichever machine you happen to be on when you update `mesh.json`.

---

## Capability Model

Each agent has a **capability grant** defining what it can do when using `host.py` to reach other agents. Grants are enforced through the agent's system prompt and `peers.json`:

```json
{
  "mesh": {
    "agents": {
      "research-agent": "http://vm-research.example.com:8080",
      "coding-agent": "http://vm-coding.example.com:8080"
    }
  }
}
```

**V1 (minimal):** Each agent has a `peers.json` listing known peers. The system prompt tells it which peer to use for which task. No technical enforcement — trust the system prompt and explicit configuration.

**Future:** `host.py` could validate target URLs against a `peers.json` whitelist before sending.

---

## What This Is NOT

- **NOT a new layer** — `host.py` already existed; we're clarifying it runs on agent machines too
- **NOT a hub-and-spoke** — no central broker; all nodes are symmetric
- **NOT a shared filesystem** — agents communicate via messages, not shared files
- **NOT automatic discovery** — peers are registered explicitly in `mesh.json`

---

## Relation to Other Specs

- **SPEC 006 (Orchestration Patterns):** The moderator pattern still works. The mesh enables autonomous patterns — an agent can act as moderator for sub-agents using the same `host.py` mechanism. No spec changes needed.
- **SPEC 009 (AgentServer API):** Transport-agnostic. Whether a request comes from a human's Mac or another agent's machine is irrelevant to AgentServer.
- **SPEC 010 (CLI Interface):** `peers.json` is the local copy of `mesh.json`, separate from `agents.json` (host-side registry). The agent doesn't need to know about every agent the human has registered — only its own peers.
- **SPEC 020/021:** Session and conversation layers are unaffected by the mesh topology.

---

## Next Steps

1. **Implement `peers.json` pull:** On boot and periodically, `agent.py` pulls `mesh.json` and updates `peers.json`
2. **Expose `host.py` to agents:** Ensure the agent's prompt/skill instructions tell it how to use `host.py send` to reach peers
3. **V1 capability grants:** Seed each remote machine's `peers.json` from the host's `agents.json`
4. **SSH tunnel fallback:** Document the `-L` tunnel approach for VMs with no public IP

---

## Open Questions

1. ~~**HostContainerBackend**~~ — resolved: removed, HTTP-to-HTTP is the only transport
2. ~~**Discovery**~~ — resolved: `mesh.json` + local `peers.json` with periodic pull
3. **Scenario 1 vs 2** — V1 uses Scenario 1 (polling). Scenario 2 (proactive delivery) deferred until a machine needs a publicly reachable HTTP endpoint
4. **Moderator role** — can an agent act as moderator for sub-agents? Uses same mesh communication; no spec changes needed
5. **Capability enforcement** — V1 trusts system prompt. Future: URL whitelist in `host.py`?
