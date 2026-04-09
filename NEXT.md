# Code Review & Testing — 2026-04-09

## Goal
Evaluate entire agentia codebase for problems, redundancies, duplications, and run integration tests.

## Sub-agents

### Agent 1: Code Quality Review
Scope: All Python files in agentia/
- Redundant imports, dead code, unused functions
- Inconsistent naming conventions
- Duplicated logic across files
- API inconsistency between host.py and agent_side/server.py
- Unnecessary complexity in session management
Output: agentia/reviews/code-quality-review.md

### Agent 2: Integration Testing
Scope: All CLI interfaces
- agentia agents / status / prune
- agentia send --conv / --new / implicit routing
- agentia conv list / show / rename / tag / delete
- agentia chat (REPL commands)
- agentia files ls / get / put
- Session management: create/resume/compact/delete
- Smart router: --conv, --new, fallback behavior
Output: agentia/reviews/integration-test-report.md

### Agent 3: Architecture Review
Scope: Design patterns and layering
- Layer A/B/C/D separation in SPEC 021
- Config flow: template → config.json → AgentServerConfig dataclass
- Session dir layout: .pi/sessions vs .agentia/sessions
- Adapter pattern: pi_agent.py vs other future adapters
- Config template alignment issues
Output: agentia/reviews/arch-review-findings.md

## Constraints
- Use runtime=acp with agentId=codex
- Report each finding with file:line reference
- Test commands against live container at localhost:18080
- Commit outputs to agentia/reviews/
