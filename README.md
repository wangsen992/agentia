# Agentia — Federated Multi-Agent Organization System

**Mission:** Build a living, evolving organization of AI agents that communicate asynchronously, maintain hierarchical structure, and can self-manage through dynamic spawn and prune operations.

> Agentia serves as the **foundational infrastructure layer** for multi-agent experimentation. It owns the container provisioning, relay communication, and organizational management. Downstream projects (like `agent-exp`) use agentia as their agent runtime.

## Relationship to Other Projects

```
agentia (this repo)
├── Infrastructure: container provisioning, relay, observability
└── Owns: containers/, relay/, observability/, org/

agent-exp (downstream)
├── Policy research: delegation triggers, AGENTS.md variants
├── Experiment fixtures: corpus, eval logic, launch scripts
└── Uses: agentia's containers and relay infrastructure
```

## Architecture Layers

```
Layer 1: Container Infrastructure
├── Dockerfile (unified, all-in-one image)
├── start_agents.py (orchestrates multi-container deployment)
├── gateway-startup.py (gateway config + auto-pairing)
└── entrypoint.sh (harness modes: interactive/multi/single/gateway)

Layer 2: Async Relay & Communication
├── Inbox per agent (SQLite, persistent, sequential)
├── Message routing (sender → target inbox)
├── Correlation IDs (trace multi-agent conversations)
├── State tracking (idle/busy/timeout/dead per agent)
└── Relay API (programmatic control for external harnesses)

Layer 3: Observability
├── Message audit log (timestamp, from, to, content preview, correlation_id)
├── Agent state log (state transitions with timestamps)
├── Turn trace log (prompt/response per turn, linkable via correlation_id)
└── Decision log (org manager spawn/prune decisions with rationale)

Layer 4: Organization & Hierarchy
├── Registry (agent capabilities, locations, state)
├── Capability map (routing by function, not name)
├── Task queue with priority
└── Hierarchy: org manager → orchestrator → specialists

Layer 5: Evolution (Intelligence)
├── Performance metrics per agent type
├── Org manager: spawn/prune decisions based on metrics
├── Genetic inheritance (new agents inherit + vary from parents)
└── Fitness function (how does the org evaluate itself?)
```

## Directory Structure

```
agentia/
├── containers/           ← Docker image definition + startup scripts
│   ├── Dockerfile
│   ├── openclaw.json    (copied at build time)
│   ├── auth-profiles.json
│   └── runners/
│       ├── entrypoint.sh
│       ├── gateway-startup.py
│       └── start_agents.py
├── relay/               ← async relay implementation
│   ├── relay.py         (WebSocket relay, thread-safe)
│   ├── exec_relay.py    (docker exec path, reference impl)
│   └── inbox_relay.py   (async inbox-based relay, under development)
├── observability/        ← logging and instrumentation
├── org/                 ← org manager and hierarchy
├── specs/               ← design decisions with rationale
├── logs/                ← runtime logs (gitignored)
└── src/                 ← core library
```

## Current Status

Phase 0 — Infrastructure setup. Observability first, async inbox next.

## Key Questions (Open)

1. What triggers agent spawn? (backlog? explicit request? quality threshold?)
2. What triggers prune? (missed SLAs? quality? minimum population?)
3. What survives a prune? (config only? partial context? nothing?)
4. Who evaluates the org manager? (external signal required)
5. What does "fitness" actually measure for an org?

## References

- Downstream: [agent-exp](https://github.com/wangsen992/agent-exp) — policy research using agentia's infrastructure
- Inspired by: Federated Agentic Workflows, A2A protocol research, multi-agent LLMs (2025-2026)

## License

Private — internal research