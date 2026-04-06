# Agentia — Federated Multi-Agent Organization System

**Mission:** Build a living, evolving organization of AI agents that communicate asynchronously, maintain hierarchical structure, and can self-manage through dynamic spawn and prune operations.

## Architecture Layers

```
Layer 1: Container Infrastructure
├── containers/
│   ├── Dockerfile              ← unified image, all harness modes
│   ├── config/                 ← openclaw.json, auth-profiles.json (build-time)
│   ├── startup/                ← gateway-startup.py, entrypoint.sh
│   └── start_agents.py          ← multi-container orchestration

Layer 2: Async Relay & Communication
├── relay/
│   ├── relay_core.py            ← base WebSocket relay
│   ├── exec_relay.py            ← docker exec path (reference impl)
│   └── moderator.py             ← debate-style multi-agent relay
└── (future: inbox.py, router.py, registry.py, state.py)

Layer 3: Observability (first-class from day 1)
├── observability/
│   ├── logger.py               ← structured logging
│   ├── trace.py                 ← message traces
│   └── metrics.py               ← agent performance metrics

Layer 4: Harnesses (control plane)
├── harnesses/
│   ├── gateway_harness.py
│   ├── interactive_harness.py
│   ├── multi_turn_harness.py
│   ├── single_harness.py
│   ├── ipc_harness.py
│   └── examples/
│       └── debate_example.py

Layer 5: Organization & Evolution (Phase 2+)
├── org/                        ← org manager, fitness, evolution
```

## Design Principles

1. **Relay is pure infrastructure** — message routing + state tracking, nothing else
2. **Harnesses are thin** — data-driven control plane, not hardcoded scripts
3. **Observability first** — logging and tracing ship from day 1
4. **Structure emerges** — directories added when data exists to fill them, not before

## Directory Structure

```
agentia/
├── containers/        ← Docker image + startup
├── relay/            ← async relay (core infra)
├── harnesses/        ← control plane (fresh design)
├── observability/    ← instrumentation
├── org/              ← org manager + evolution (Phase 2+)
├── specs/            ← design decisions with rationale
├── logs/             ← runtime logs (gitignored)
└── src/              ← core library
```

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

## Current Status

Phase 0 — Infrastructure. Observability first, relay next.

## Key Questions (Open)

1. What triggers agent spawn? (backlog? explicit request? quality threshold?)
2. What triggers prune? (missed SLAs? quality? minimum population?)
3. What survives a prune? (config only? partial context? nothing?)
4. Who evaluates the org manager? (external signal required)
5. What does "fitness" actually measure for an org?

## References

- Downstream: [agent-exp](https://github.com/wangsen992/agent-exp)
- A2A Protocol studied but not adopted (enterprise middleware, not core infra)
- Inspired by: multi-agent LLMs (Anthropic 2025), AutoGen Core, Agentic workflows

## License

Private — internal research
