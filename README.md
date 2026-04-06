# Agentia — Federated Multi-Agent Organization System

**Mission:** Build a living, evolving organization of AI agents that communicate asynchronously, maintain hierarchical structure, and can self-manage through dynamic spawn and prune operations.

## Core Concept

An `Agentia` is a federated multi-agent system where:
- Agents operate asynchronously via persistent inboxes
- Organizational hierarchy provides structure and purpose
- An org manager evaluates performance and decides population dynamics
- Genetic-style selection allows the organization to evolve over time

## Architecture Layers

```
Layer 1: Infrastructure (Foundation)
├── Containerized agents (OpenClaw in Docker)
├── Shared inbox storage (SQLite on host volume)
├── Relay with async routing (message → target inbox)
└── State tracking (idle/busy/timeout/dead)

Layer 2: Organization (Structure)
├── Registry (agent capabilities, locations, state)
├── Capability map (routing by function, not name)
├── Task queue with priority
└── Hierarchy: org manager → orchestrator → specialists

Layer 3: Evolution (Intelligence)
├── Performance metrics per agent type
├── Org manager: spawn/prune decisions based on metrics
├── Genetic inheritance (new agents inherit + vary from parents)
└── Fitness function (how does the org evaluate itself?)

Layer 4: Observability (Visibility)
├── Full message audit log
├── Agent behavior traces
├── Performance dashboards
└── Decision logs (why did the org manager spawn/prune?)
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

- Parent project: [openclaw-agent-experimentation](https://github.com/wangsen992/agent-exp) — policy research on delegation triggers
- Inspired by: Federated Agentic Workflows, A2A protocol research, multi-agent LLMs (2025-2026)

## License

Private — internal research