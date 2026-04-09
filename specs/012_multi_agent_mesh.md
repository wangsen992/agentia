# SPEC 012: Multi-Agent Mesh — Peer-to-Peer Agent Communication

**Status:** Draft
**Date:** 2026-04-09

---

## What Changed

Today's session established a clearer understanding of the architecture through practical implementation:

- **agent.py** = the server side (AgentServer, receives messages)
- **host.py** = the client side (can send messages to any AgentServer)

Previously, `host.py` was conceived as a host-side tool (used only by the human on their Mac). The multi-agent mesh concept extends this: **host.py is also available to agents running on remote machines**, giving them the ability to proactively reach other agents.

This is NOT a new layer — it's a clarification of WHO can use host.py and WHEN.

---

## Architecture: Symmetric Nodes

Each machine runs a **symmetric node** — both a server and a client:

```
Machine A (your Mac)
  ├── AgentServer (agent.py)  ← receives messages
  └── host.py                 ← can send to any registered agent

Machine B (cloud VM)
  ├── AgentServer (agent.py)  ← receives messages
  └── host.py                 ← can send to any registered agent
```

- **AgentServer** — always listening, passive receiver, owns session lifecycle
- **host.py** — available as a tool to the running agent, initiates outbound communication

Any agent can reach any other agent by URL. No hub, no central broker. The host machine you work from is just one node in the mesh.

---

## Relation to Existing Specs

### SPEC 005 (Relay & Inbox Architecture)

**What SPEC 005 describes:**
- `BaseRelay` on the host side
- `HostContainerBackend` → `AgentServer` → `AgentAdapter`
- Moderator uses BaseRelay to coordinate agents

**What the mesh concept adds:**
- `host.py` (the BaseRelay/HostContainerBackend client) can also run ON an agent machine, not just on the host
- The agent itself decides when to reach out to other agents — not just the human orchestrator
- The moderator pattern still works, but agents can also self-coordinate

**Tension to resolve:**
SPEC 005's architecture diagram shows `BaseRelay` as host-side only. The mesh concept implies BaseRelay (or host.py equivalent) can run anywhere. This is an architectural clarification, not a new layer.

### SPEC 006 (Orchestration Patterns)

**What SPEC 006 describes:**
- Moderator holds the goal, orchestrates agents via BaseRelay
- Autonomous patterns deferred until pain points emerge

**What the mesh concept adds:**
- Agents can act as moderators for their own sub-tasks without human intervention
- An agent can spawn a sub-agent, give it work, and collect results via host.py
- This enables recursive delegation: Agent A delegates to Agent B, Agent B delegates to Agent C

**No spec changes needed** — SPEC 006's deferred "autonomous" patterns now have a concrete mechanism (host.py as a tool).

### SPEC 009 (AgentServer API)

**What SPEC 009 describes:**
- HTTP API contract between host and agent
- Control plane + Host Messaging plane
- Inbox/sync delivery patterns

**No changes needed** — the API is transport-agnostic. Whether a request comes from a human's host.py or from another agent's host.py is irrelevant to AgentServer.

### SPEC 010 (CLI Interface)

**What SPEC 010 describes:**
- `agentia-agent` (agent.py) for server side
- `agentia` (host.py) for host side
- Registry at `~/.agentia/agents.json`

**What needs updating:**
- `host.py` is not just a host-side tool — it's also available to agents as a first-class outbound communication tool
- The registry (`agents.json`) on each machine knows about other agents by URL
- Agents need their own registry of "known peers" — this could be a separate file (e.g., `~/.agentia/peers.json`) or the existing `agents.json`

---

## Discovery: How Does an Agent Find Other Agents?

**Current state:** Agents are registered manually via `agentia register <url> --name <name>`. The URL must be known upfront.

**Mesh model:** Each machine needs a registry of known peer agents by URL. Options:

### Option A: Static Config (simplest)
Each machine has a `peers.json` file listing known agents by name and URL:
```json
{
  "peers": {
    "research-agent": "http://vm-research.example.com:8080",
    "coding-agent": "http://192.168.1.50:8080"
  }
}
```
- Agent is told (via system prompt or config) which peer to contact for which task
- No auto-discovery needed
- Human maintains the registry

### Option B: Registry Sync
Each machine maintains `~/.agentia/agents.json` for all known agents. When an agent registers with the human's host, that registration is automatically available to all agents on the same host machine. But for agents on different machines, they need their own registry.

**Recommended: Option A initially.** Static config is explicit, auditable, and simple. Auto-discovery can be added later (mDNS, DNS-SD, or a central registry service) when there's a pain point.

---

## Trust and Capability Model

### Per-Agent Capability Grants

Each agent has a **capability grant** defining what it can do with host.py. The grants are enforced by the human through the agent's system prompt or config:

```
research-agent can:
  - send messages to: coding-agent
  - receive messages from: any
  - NOT access: filesystem of other agents

coding-agent can:
  - send messages to: research-agent, review-agent
  - receive messages from: any
  - NOT access: filesystem of other agents
```

This is enforced through:
1. **System prompt** — tells the agent who it can reach
2. **URL whitelist** — `host.py` could validate target URLs against a config
3. **Logging** — all outbound calls are logged to the host's audit trail

### Minimal V1 Capability Model

For V1, keep it simple:
- Each agent has a `peers.json` listing known peers by name + URL
- The agent's system prompt tells it which peer to use for which task type
- No technical enforcement — trust the system prompt
- All inter-agent messages are logged via the existing HTTP request logging

---

## Revised File Layout

```
~/.agentia/
├── agents.json          # human's registry (host-side)
├── conversations/       # conversation state (host-side)
└── peers.json          # peer agents registry (agent-side, synced from host)

# On each remote machine:
~/.agentia/
├── agents.json          # local registry (same format as host)
└── peers.json          # mirrors the host's peers for this machine
```

**Note:** `agents.json` on the remote machine may differ from the host's — the remote machine doesn't need to know about every agent the human has registered. It only needs to know agents reachable from that machine.

---

## What This Is NOT

- **NOT a new layer** — host.py already exists; we're just clarifying it runs on agent machines too
- **NOT a hub-and-spoke** — no central broker; all nodes are symmetric
- **NOT a shared filesystem** — agents communicate via messages, not shared files
- **NOT automatic discovery** — peers are registered explicitly, not discovered

---

## Open Questions

1. **Registry sync** — should `peers.json` on remote machines auto-sync from the host's `agents.json`, or is it maintained independently?
2. **Capability enforcement** — should host.py technically enforce URL whitelisting, or rely on system prompts?
3. **Response routing** — if agent A sends to agent B, does the response go back directly to A (peer-to-peer), or through A's host machine?
4. **Async vs sync** — for complex tasks, agents may want to send-and-forget (async). Does this use the existing `/message/async` API?
5. **Moderator role** — can an agent act as a moderator for sub-agents it spawns? Does this require a SupervisorAdapter pattern?

---

## Next Steps

1. **Update SPEC 005** — clarify that BaseRelay/host.py can run on any machine, not just the host
2. **Update SPEC 010** — add `peers.json` to the file layout, clarify host.py as a tool available to agents
3. **Add discovery spec** — define how agents learn about each other's URLs (Option A: static config initially)
4. **Implement V1 peers registry** — `~/.agentia/peers.json` on each machine, seeded from host's `agents.json`
