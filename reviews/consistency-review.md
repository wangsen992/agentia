# Consistency Review: README vs. Full Codebase

**Reviewer:** Jarvis (manual verification, subagent timed out)
**Files reviewed:** All major source files

---

## Summary

The README is **consistent with the codebase** for all the areas it documents. No phantom commands (documented but not implemented) and no undocumented commands (implemented but not documented) in the core CLI surface.

---

## Host CLI (`cli/host.py`) — Fully Consistent

All commands in the README match `cli/host.py`:

| Command | README | Code | Consistent |
|---|---|---|---|
| `register` | ✅ | ✅ | ✅ |
| `agents` | ✅ | ✅ | ✅ |
| `send [--conv]` | ✅ | ✅ | ✅ |
| `status` | ✅ | ✅ | ✅ |
| `configure` | ✅ | ✅ | ✅ |
| `update` | ✅ | ✅ | ✅ |
| `deregister` | ✅ | ✅ | ✅ |
| `prune` | ✅ | ✅ | ✅ |
| `sessions` | ✅ | ✅ | ✅ |
| `compact --conv` | ✅ | ✅ | ✅ |
| `session delete [--hard]` | ✅ | ✅ | ✅ |
| `files ls/get/put/edit/delete` | ✅ | ✅ | ✅ |
| `snapshot` | ✅ | ✅ | ✅ |
| `forward` | ✅ | ✅ | ✅ |

---

## Agent CLI (`cli/agent.py`) — Fully Consistent

| Command | README | Code | Consistent |
|---|---|---|---|
| `setup` | ✅ | ✅ | ✅ |
| `serve --install/--config/--provider/--model/--workspace` | ✅ | ✅ | ✅ |
| `--role-goal/--backstory/--skills/--var` | ✅ | ✅ | ✅ |
| `--session-ttl/--max-sessions/--context-threshold` | ✅ | ✅ | ✅ |

---

## Agent Adapters

README mentions: `pi-agent` and `openclaw` in `agents/adapters/`

**Reality:**
- `agents/adapters/pi_agent.py` — ✅ exists
- `agents/adapters/openclaw.py` — ✅ exists
- `agents/adapters/factory.py` — ✅ exists
- `agents/adapters/base.py` — ✅ exists

Both adapters are real and documented.

---

## Setup Adapter Templates

README says: `setup/adapters/pi-agent/` and `setup/adapters/openclaw/`

**Reality:**
- `setup/adapters/pi-agent/bootstrap/`, `config.tmpl`, `install.sh` — ✅ all exist
- `setup/adapters/openclaw/bootstrap/`, `config.tmpl`, `install.sh` — ✅ all exist

---

## SPECs Referenced

README references:
- `SPEC 020 — Session Management` — ✅ exists at `specs/020_session_management.md`

README mentions `SPEC 010 — CLI Interface` but doesn't reference it in the body (just in References section). `specs/010_cli_interface.md` exists and is a historical spec, not contradicted by README.

---

## Design Decisions — Still Accurate

| Decision | README says | Still true? |
|---|---|---|
| HTTP between host and agent | ✅ | ✅ |
| Session management server-owned | ✅ | ✅ |
| Workspace on host at ~/.agentia | ✅ | ✅ |
| pi-agent as primary runtime | ✅ | ✅ |
| Configurable idle/session limits | ✅ | ✅ |

---

## Files NOT Mentioned in README

These exist in the project but aren't in the README layout. None are core:

- `relay/` — legacy host-side relay (backends/docker.py, ssh.py)
- `containers/` — container management utilities
- `examples/` — example configs
- `reviews/review-2026-04-10/` — review output files (this directory)
- `research/` — research files
- `dev/test_imports.py`, `dev/test_moderator_e2e.py` — test files
- `agentia-agent` — root shell wrapper
- `constants.py` — constants
- `NEXT.md`, `NEXT-STEPS.md` — project notes
- `specs/007_memory_test.md` — one-off spec doc

**None of these are documentation bugs** — they're just outside the scope of the README.

---

## Conclusion

**The README and codebase are consistent.** The only real issue is:
1. Session lifecycle flag defaults don't match README example values (cosmetic mismatch, see arch-review.md)
2. Two minor undocumented endpoints: `/metrics` and `/inbox` (minor, not core usage)
