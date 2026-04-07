# Agentia — Federated Multi-Agent Organization System

**Mission:** Build a living, evolving organization of AI agents that communicate asynchronously, maintain hierarchical structure, and can self-manage through dynamic spawn and prune operations.

---

## Quick Start

```bash
# Build the image
cd ~/openclaw_space/projects/agentia
docker buildx build --load . -t agentia

# Create an agent (default: subprocess poller harness)
./agentia create analyst my-analyst

# Send a message
./agentia exec my-analyst "What is 2+2?"

# Or start with gateway harness (persistent gateway mode)
./agentia create analyst my-analyst --harness gateway

# List running agents
./agentia ps

# View logs
./agentia logs my-analyst

# Destroy
./agentia destroy my-analyst
```

## Current Status

**Phase 0 — Core Infrastructure: DONE**
- SPEC 004: Observability layer (logging, trace, session tracking)
- SPEC 005: Relay/Inbox architecture (async message passing via JSON Lines)
- SPEC 006: Orchestration patterns (decision: Moderator first, autonomous deferred)

**What's Working (2026-04-06)**
- Agent container create/start/stop/destroy lifecycle ✅
- `agent` harness: subprocess poller via inbox relay ✅
- `gateway` harness: persistent OpenClaw gateway (--auth none --bind loopback) ✅
- `agentia exec` — message roundtrip through inbox ✅
- Host config isolation (no ~/.openclaw/ mount) ✅
- Per-container OpenClaw config baked into image at build time ✅
- Registry auto-cleanup on stale containers ✅

**Next: SPEC 007 — End-to-End Integration Test**
Two agent containers + Moderator + InboxRelay working together.

---

## Architecture Layers

```
Layer 1: Container Infrastructure
├── Dockerfile                  ← unified image, all harness modes
├── harnesses/entrypoint.sh     ← single/multi/interactive/gateway/poller
└── agents/                    ← per-agent config and adapters

Layer 2: Async Relay & Communication
├── relay/base.py              ← BaseRelay ABC
├── relay/inbox.py             ← JSON Lines inbox store
├── relay/inbox_relay.py       ← InboxRelay (send_async, broadcast)
├── relay/exec_relay.py        ← docker exec relay
└── relay/moderator.py         ← debate-style orchestration

Layer 3: Observability (first-class from day 1)
├── observability/logger.py     ← structured JSON Lines logging
├── observability/session.py    ← session context manager
└── observability/session_trace.py ← trace parsing + extraction

Layer 4: Harnesses (control plane)
├── harnesses/single_harness.py
├── harnesses/multi_turn_harness.py
├── harnesses/interactive_harness.py
├── harnesses/gateway_harness.py
└── harnesses/inbox_poller.py  ← long-running inbox processor
```

---

## Design Decisions (Locked)

### Orchestration: Moderator First
- Start with structured moderator pattern (NOT autonomous/emergent)
- Autonomous is the end state, not the starting point
- Controlled case needed before emergent behavior is meaningful to study

### Output: Transcript
- Moderator output is a `ConversationResult` with `list[TurnRecord]`
- Each TurnRecord: turn number, agent_id, role, prompt, response, duration_ms
- Decisions/consensus are future layers on top of transcript

### Goal: Lives in Moderator
- Moderator holds topic, turn count, stopping condition
- Agents receive goal via first system prompt
- Simplest and most auditable for research

### Stopping: Deterministic
- Turn limit OR explicit STOP signal
- No convergence detection yet (deferred until pain point emerges)

---

## SPECs

| Spec | Status | Description |
|------|--------|-------------|
| 001 | done | Repository structure |
| 002 | done | OpenClaw agent adapter |
| 003 | done | Adapter Dockerfiles |
| 004 | done | Observability layer |
| 005 | done | Relay/Inbox architecture |
| 006 | done | Orchestration patterns decision |
| 007 | next | **End-to-end integration test** |

---

## SPEC 007: End-to-End Integration Test

**Goal:** Two agent containers + Moderator + InboxRelay, all talking to each other.

```
Host                  Container A              Container B
  │                        │                       │
  │─ Moderator.run() ──────│                       │
  │                        │                       │
  │─ InboxRelay.send_async("analyst", prompt) ──────│  [copied to A's inbox]
  │─ InboxRelay.send_async("critic", prompt)  ──────│  [copied to B's inbox]
  │                        │                       │
  │              [poller reads inbox]              │
  │              [calls openclaw agent]            │
  │              [writes response.jsonl]          │
  │                        │                       │
  │←─ Moderator collects responses ───────────────│
  │                        │                       │
  │─ Next turn...          │                       │
  │                        │                       │
  │←─ ConversationResult(transcript, turns, ended_at)
```

**What to verify:**
1. Both agents receive messages via inbox
2. Poller processes messages and returns responses
3. Moderator builds history correctly across turns
4. Transcript complete after N turns
5. Stop condition respected

---

## Security Model

**Host config isolation is strictly enforced.** The agent container never mounts the host's `~/.openclaw/` directory.

### Why this matters
OpenClaw writes to `~/.openclaw/` at runtime:
- Device identity (tokens, credentials)
- Session history
- Model configurations
- Canvas/artifacts

If a container's `/root/.openclaw/` were bind-mounted from the host, container processes would corrupt the host's OpenClaw state.

### How agentia handles it
1. **At build time:** OpenClaw config is COPY'd into the Docker image (`Dockerfile`)
2. **At container create:** Image config is extracted and copied to `~/.agentia/containers/{agent_id}/openclaw/`
3. **At container run:** That **per-container copy** is mounted as a volume into the container

```
Host                              Container
~/.agentia/containers/{id}/openclaw/  →  /root/.openclaw/
         ↑ copied from image at create time

Host ~/.openclaw/  ← NEVER touched
```

### Volume mounts (all safe)
| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `~/.agentia/inbox/` | `/workspace/inbox` | Relay messages (JSONL) |
| `~/.agentia/containers/{id}/workspace/` | `/workspace-src` | Per-agent workspace files |
| `~/.agentia/containers/{id}/openclaw/` | `/root/.openclaw/` | Per-agent OpenClaw config (image copy) |

### What the container cannot do
- Access host's `~/.openclaw/` — no path to it exists inside the container
- Modify host files outside `~/.agentia/`
- Affect other containers' OpenClaw state

---

## Key Questions (Answered / Deferred)

| Question | Status |
|----------|--------|
| Moderator vs autonomous? | **Answered: Moderator first** |
| What is output? | **Answered: Transcript** |
| Where does goal live? | **Answered: In Moderator** |
| What triggers spawn? | Deferred (Phase 2) |
| What triggers prune? | Deferred (Phase 2) |
| What survives prune? | Deferred (Phase 2) |
| Who evaluates org manager? | Deferred (Phase 2) |

---

## Relationship to agent-exp

```
agentia (this repo)
├── Owns: container provisioning, relay, observability, harnesses
└── Mission: federated org system + async communication

agent-exp (downstream)
├── Policy research: delegation triggers, AGENTS.md variants
├── Experiment fixtures: corpus, eval logic
└── Uses: agentia's containers and relay infrastructure
```

---

## References

- Downstream: [agent-exp](https://github.com/wangsen992/agent-exp)
- A2A Protocol studied but not adopted (enterprise middleware, not core infra)
- Inspired by: multi-agent LLMs (Anthropic 2025), AutoGen Core, Agentic workflows

## License

Private — internal research
