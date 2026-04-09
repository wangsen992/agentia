# Agentia Code Review — Task Manifest

Spawn 5 subagents, one per focus area. Each should:
1. Read all relevant files
2. Write a structured review to their output file
3. Return the output path

## Focus Areas

| Subagent | Area | Files |
|---------|------|-------|
| 1 | Core Server + Harness + Config | `agent_side/server.py`, `agent_side/harness.py`, `agent_side/config.py` |
| 2 | Agent Adapters | `agents/adapters/base.py`, `agents/adapters/factory.py`, `agents/adapters/pi_agent.py`, `agents/adapters/openclaw.py` |
| 3 | Delivery Patterns | `agent_side/patterns/inbox.py`, `agent_side/patterns/sync.py`, `agent_side/patterns/` |
| 4 | CLI + Container Orchestration | `agentia` (full file), `containers/start_agents.py`, `relay/` |
| 5 | Setup + Bootstrap System | `setup/adapters/pi-agent/`, `setup/README.md`, `Dockerfile` |

## Output Files

- `agentia/review/subagent-01-core.md`
- `agentia/review/subagent-02-adapters.md`
- `agentia/review/subagent-03-delivery.md`
- `agentia/review/subagent-04-cli.md`
- `agentia/review/subagent-05-setup.md`

## Review Criteria (each subagent should assess)

For each area, assess:
1. **Correctness** — does it work as intended? Any bugs or edge cases?
2. **Design** — is the architecture sound? Any design flaws?
3. **Completeness** — what's missing that should be there?
4. **Integration** — does it connect properly with other parts?
5. **Actionable findings** — specific bugs or improvements with file:line references

## Synthesis

After all 5 complete, I will synthesize into `agentia/review/FINAL-REVIEW.md`.
