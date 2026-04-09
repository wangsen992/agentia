# Architecture Review: README vs. Actual Implementation

**Reviewer:** Jarvis (manual verification, subagents timed out)
**Files reviewed:** `README.md`, `agent_side/server.py`, `agents/adapters/pi_agent.py`, `agent_side/harness.py`, `agent_side/config.py`

---

## AgentServer HTTP API

### ✅ All documented endpoints are implemented

| README endpoint | Status | Code location |
|---|---|---|
| GET /status | ✅ | server.py:125 |
| GET /config | ✅ | server.py:120 |
| PATCH /config | ✅ | server.py:261 |
| PUT /config | ✅ | server.py:222 |
| POST /message | ✅ | server.py:289 |
| POST /message/async | ✅ | server.py:293 |
| GET /response/{id} | ✅ | server.py:149 |
| POST /restart | ✅ | server.py:283 |
| GET /files/ | ✅ | server.py (do_GET, startswith) |
| GET /files/<path> | ✅ | server.py (do_GET, startswith) |
| PUT /files/<path> | ✅ | server.py (do_PUT) |
| DELETE /files/<path> | ✅ | server.py (do_DELETE) |
| GET /sessions | ✅ | server.py:178 |
| GET /sessions/<name> | ✅ | server.py (startswith /sessions/) |
| POST /sessions/new | ✅ | server.py:299 |
| POST /sessions/<name>/message | ✅ | server.py (startswith) |
| POST /sessions/<name>/compact | ✅ | server.py (startswith) |
| DELETE /sessions/<name> | ✅ | server.py (do_DELETE) |

### ⚠️ Undocumented endpoints in server.py

These exist in server.py but NOT in the README API table:

- **GET /metrics** — `server.py:139` — Prometheus-compatible metrics endpoint
- **GET /inbox** — `server.py:158` — Returns inbox messages for the agent

These are relatively niche. Not blocking, but should be noted.

---

## Session Behavior

### ✅ All session behaviors documented correctly

| Behavior | README says | Code does | Verdict |
|---|---|---|---|
| Idle timeout | SIGTERM after `session_idle_ttl` | `_reset_idle_timer` + `_terminate(graceful=True)` | ✅ |
| LRU eviction | Oldest running evicted when max hit | `_evict_lru()` — sorts by `last_active` | ✅ |
| Auto-compact | Fires at `context_threshold_pct` | `if s.context_pct >= self._context_threshold_pct: self._compact_session(s)` | ✅ |
| Hard delete | `?hard=true` deletes session file | `if hard: shutil.rmtree(self._session_dir / s.name)` | ✅ |
| Manifest | `manifest.jsonl` with status/pid/msg_count | `_save_manifest`, `_upsert_manifest` | ✅ |
| Session dir | `_session_dir / s.name` | `session_dir = self._session_dir / session.name` | ✅ |

All session management descriptions match the code.

---

## Architecture Diagram

### ✅ Matches reality

README diagram:
```
cli/host.py (agentia) ──HTTP──► agent_side/server.py
                                        └─ SessionManager
                                              └─ Harness
                                                    └─ PiAgentAdapter
                                                          └─ pi-agent subprocess
```

Code structure: `server.py` creates `SessionManager` in `start()`, routes to `Harness` for non-session requests. ✅

---

## Project Layout Discrepancies

### ⚠️ README layout is incomplete (not wrong, just partial)

README lists:
```
cli/agent.py, cli/host.py, agent_side/, agents/adapters/, setup/adapters/, specs/, README.md
```

**Correct.** But the actual project has additional dirs/files NOT mentioned:
- `relay/` — host-side relay library (backends/docker.py, backends/ssh.py) — legacy
- `containers/` — container management scripts
- `research/` — research files
- `review/` — review outputs
- `examples/` — example configs
- `SPEC-007-memory-test.md`, `NEXT.md`, `NEXT-STEPS.md` — project notes
- `constants.py`, `test_imports.py`, `test_moderator_e2e.py`
- `agentia-agent` — root shell wrapper script

**Verdict:** The README accurately describes the **core** project layout. The extra dirs are workspace artifacts not part of the core system. Not a documentation bug — just incomplete.

---

## Session Lifecycle Flags

This was flagged in the CLI review and confirmed here:

| Flag | README example | Code default |
|---|---|---|
| `--session-ttl` | 300 | **1800** |
| `--max-sessions` | 5 | **10** |
| `--context-threshold` | 80 | **75** |

The README's Session Lifecycle Flags section uses example values that differ from argparse defaults. This is misleading — a user who omits these flags gets **1800s / 10 sessions / 75%**, not the values the section implies are "the" values.

---

## Summary

**Overall: README is accurate and complete for the documented scope.**

1. ✅ All documented API endpoints exist and are implemented
2. ✅ All session behaviors are correctly described
3. ✅ Architecture diagram matches actual code
4. ✅ Project layout is correct for core files
5. ⚠️ Two undocumented endpoints: `/metrics`, `/inbox`
6. ⚠️ Session lifecycle flag defaults don't match README examples
