# SPEC: Repository Structure — 2026-04-05

## Why Restructure?

The previous structure was inherited from `openclaw-agent-experimentation`, which had a different mission (policy research on delegation triggers). The copied-in files didn't reflect how agentia should work as a **federated multi-agent org system**.

Key problems with the old structure:
- `containers/runners/` mixed harness scripts and relay code together
- No separation between "relay infrastructure" and "experiment harnesses"
- No place for observability or org management
- `agents/` was speculative — no data to put in it yet

## New Structure

```
agentia/
├── containers/            ← container image definition + startup scripts
│   ├── Dockerfile
│   ├── config/           ← openclaw.json, auth-profiles.json (build-time)
│   ├── startup/          ← gateway-startup.py, entrypoint.sh
│   └── start_agents.py   ← multi-container orchestration
│
├── relay/               ← async message routing (core infrastructure)
│   ├── relay_core.py     ← base WebSocket relay
│   ├── exec_relay.py     ← docker exec path (reference implementation)
│   └── moderator.py      ← debate-style multi-agent relay
│
├── harnesses/           ← control plane, built on top of relay
│   ├── base.py           ← (future: harness abstract base class)
│   ├── gateway_harness.py
│   ├── interactive_harness.py
│   ├── multi_turn_harness.py
│   ├── single_harness.py
│   ├── ipc_harness.py
│   └── examples/
│       └── debate_example.py
│
├── observability/       ← instrumentation (first-class from day 1)
│   ├── logger.py         ← structured logging
│   ├── trace.py          ← message traces
│   └── metrics.py        ← agent performance metrics
│
├── org/                 ← org manager + evolution (Phase 2+)
│
├── specs/               ← design decisions with rationale
│
├── logs/               ← runtime logs (gitignored)
└── src/                ← core library (utilities)
```

## Design Principles

1. **Relay is pure infrastructure** — knows nothing about agent roles or harness logic. It routes messages and tracks state.

2. **Harnesses are thin control plane** — they use the relay API. When we build a new harness type, it goes here without touching relay.

3. **Observability is first-class** — not bolted on later. Logger and trace ship from day 1, used everywhere.

4. **`agents/` was removed** — speculative structure with no data to back it. If we need agent configs, that will emerge from the relay + harness layers.

5. **`org/` is reserved for Phase 2** — org manager, fitness, evolution. Not built yet, directory is ready.

## Why Not Just Keep `containers/runners/`?

The runner scripts were tightly coupled to a specific relay pattern. They hardcoded:
- Specific agent names (critic, defender)
- Specific turn sequences
- Specific docker exec paths

A scalable harness layer needs to be data-driven, not script-driven. The new `harnesses/` directory starts fresh with a base class pattern, so new harnesses can be composed without rewriting relay code.

## Staged Build

- **Phase 0 (now):** Container infrastructure + relay + observability
- **Phase 1:** Fresh harness implementations using relay API
- **Phase 2:** Org manager + evolution layer
