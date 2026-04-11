# Agentia Hardening / Structure Refactor — 2026-04-11

## Goal
Cleanly remove legacy `relay/`, unify awkward runtime package layout (`agent_side/` + `agents/adapters/`), and keep the current validated host/server/session/files surface green.

## Scope for this slice
1. Remove temporary local junk first
   - revert smoke-test change in `setup/adapters/pi-agent/bootstrap/AGENTS.md.tmpl`
   - remove generated `build/`
2. Unify runtime package structure
   - move `agent_side/*` and `agents/adapters/*` under one coherent package
   - update imports across code/tests
3. Remove `relay/`
   - update/remove examples/dev scripts that depend on it
   - stop copying it in Dockerfile and packaging metadata
4. Update docs/spec references to reflect the new layout and deprecations
5. Run full regression suite and fix fallout
6. Commit only after the repo is clean and tests pass

## Constraints
- No backward-compatibility gymnastics needed; repo is effectively single-user.
- Preserve current validated behavior first; structure cleanup should not silently break host/server/session/files flows.
- Treat docs as part of the refactor, not optional cleanup.
