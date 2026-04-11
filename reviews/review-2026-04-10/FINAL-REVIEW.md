# Agentia Codebase Review — Final Synthesis

**Date:** 2026-04-08  
**Reviewers:** 5 parallel subagents covering Core, Adapters, Delivery, CLI/Relay, Setup  
**Files Reviewed:** ~25 across the full codebase  
**Output:** `reviews/review-2026-04-10/subagent-0X-<area>.md` (individual reports) + this synthesis

---

## Severity Key

| Tag | Meaning |
|-----|---------|
| 🔴 Critical | Data loss, security issue, or fundamental design break |
| 🟡 Medium | Correctness bug or significant design gap |
| 🟢 Low | Minor issue, code smell, or missing documentation |

---

## Cross-cutting Issues (appear in multiple areas)

These are the highest-leverage fixes — they affect multiple layers simultaneously.

### 🔴 Issue A: `adapter.start()` called per-message

**Appears in:** `sync.py:70`, `inbox.py:111`, `pi_agent.py:66`  
**Impact:** Critical — spawns a new pi-agent subprocess per message, orphaning the previous one. Zombie processes accumulate.

Both `SyncDelivery.send()` and `InboxDelivery.process_message()` call `adapter.start(session_id=<new>)` on every message. For `PiAgentAdapter`, each `start()` spawns a brand-new `pi --mode rpc` subprocess. The previous subprocess is orphaned — never stopped or waited on. `_read_events` threads pile up.

**Fix:** Call `adapter.start()` once when the delivery pattern is initialized. Reuse the same subprocess for all messages in a session. If per-message session isolation is truly needed, call `adapter.stop()` before the next `start()`.

---

### 🔴 Issue B: File-based inbox race condition (message loss)

**Appears in:** `server.py:_handle_message()`, `harness.py:_run_inbox_loop()`, `inbox.py:mark_processed()`  
**Impact:** Critical — concurrent writes and rewrites silently lose messages.

`append_message()` appends to the inbox file from the HTTP handler thread. `mark_processed()` reads the entire file, filters, then **truncates and rewrites** it. If `append_message()` runs during the window between read and write, those messages are permanently lost.

**Fix:** Use `fcntl.flock()` around all read/write operations. Or switch to append-only files (one JSONL entry per file, named by message ID) that are moved after processing — no rewrite needed.

---

### 🔴 Issue C: `role_persona` silently ignored in all Jinja2 templates

**Appears in:** `config.tmpl` (both adapters), `_build_context()` in `agentia` CLI  
**Impact:** High — persona always falls back to "You are {agent_id}."

`config.tmpl` references `{{ role_persona }}` in the persona template, but `_build_context()` never passes `role_persona` — only `role_goal`, `backstory`, and `skills`. The persona line silently falls back to the default every time.

**Fix:** Either pass `role_persona` in the context, or replace the persona template with the `backstory` variable which is the actually-documented and passed field.

---

## Per-Area Findings

---

### Area 1: Core Server + Harness + Config

**Review:** `subagent-01-core.md`

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 Critical | `server.py`, `inbox.py` | Inbox file race condition (see Issue B above) |
| 2 | 🟡 | `server.py:135` | `do_PUT /config` crashes if `_harness._harness` is `None` — missing guard that `do_PATCH` has |
| 3 | 🟡 | `server.py:213` | `_poll_response` calls `mkdir()` inside the polling loop — move outside |
| 4 | 🟡 | `harness.py:102,108` | `_uptime = None` in `teardown()` with `if self._uptime else 0` is a type-safety issue; should use `is not None` |
| 5 | 🟡 | `server.py:84` | No request body size limit — a client can exhaust memory with a multi-GB `Content-Length` |

**Cross-file observation:** `Harness` creates a delivery in `__init__` but `start()` must be called separately. If `stop()` is called without `start()`, `teardown()` is called on an un-started delivery. The init-then-start lifecycle is not enforced.

---

### Area 2: Agent Adapters

**Review:** `subagent-02-adapters.md`

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 | `pi_agent.py:165–169,178–179` | Race condition: `_response_buffer` and `_response_event` cleared in `send()` while old event reader thread may still be writing. Needs `threading.Lock`. |
| 2 | 🔴 | `openclaw.py:166–173` | `start()` is a no-op — each `send()` forks a new subprocess. Violates AgentAdapter ABC contract. |
| 3 | 🟡 | `pi_agent.py:195–202` | After timeout, `abort` is sent but `_terminate()` is never called — subprocess leaks. |
| 4 | 🟡 | `openclaw.py:158–163` | `_approve_pairings()` is fully implemented but never called from `setup()` — dead code. |
| 5 | 🟡 | `openclaw.py:133–134` | `_wait_gateway_ready()` returns `False` on failure but `setup()` ignores it and continues. |

**Shared observation:** Both `PiAgentAdapter` and `OpenClawAdapter` have nearly identical `get_session_trace()` implementations (~28 lines duplicated). Could be a shared utility.

---

### Area 3: Delivery Patterns

**Review:** `subagent-03-delivery.md`

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 | `sync.py:70`, `inbox.py:111` | Per-message `adapter.start()` spawns zombie subprocesses (see Issue A above) |
| 2 | 🔴 | `inbox.py:77–96` | `mark_processed()` read-filter-rewrite race condition (see Issue B above) |
| 3 | 🟡 | `inbox.py:124–157` | Entire `poll_once()` read-process-write cycle has no locking |
| 4 | 🟡 | `sync.py`, `inbox.py` | `adapter.stop()` is never called after each send — sessions never terminated |
| 5 | 🟢 | `inbox.py:102` | `write_response()` uses `mode="w"` — if same correlation_id gets multiple writes, earlier ones are silently overwritten |

**Additional note:** `InboxDelivery.run()` is defined but never called — `Harness._run_inbox_loop()` calls `poll_once()` directly instead. Dead code.

---

### Area 4: CLI + Container Orchestration + Relay

**Review:** `subagent-04-cli.md`

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 | `agentia:280` | Config mount is broken: `-v {config_dir}:/etc/agentia` mounts a directory but `AGENTIA_CONFIG` points to `/etc/agentia/agent.json` (a file). Docker mounts dir over dir, not file into file. AgentServer starts without config. |
| 2 | 🔴 | `agentia:56–79` | Port allocation race condition: `docker ps` check then save is not atomic. Non-Docker host processes on a port are invisible to the check. |
| 3 | 🟡 | `examples/moderator.py:157` | `Path` not imported — `save_transcript()` always raises `NameError`. |
| 4 | 🟡 | `relay/backends/docker.py:110–116` | `poll_response()` retries through HTTP 500 errors — only 404 should mean "keep polling" |
| 5 | 🟢 | `relay/backends/docker.py:70–74` | `RelayMessage.metadata` is silently dropped, never forwarded to AgentServer |
| 6 | 🟢 | `agentia:173` | `os.execvp()` ignores the `AGENTIA_CONFIG` env var read earlier |

**Additional issues:**
- `--network bridge` (line 261) prevents inter-container DNS resolution. Should use a user-defined network.
- Template rendering failure in `cmd_create()` is silent — agent starts with defaults.
- `start_container()` can throw after registry status is set to "created" with no rollback.

---

### Area 5: Setup + Bootstrap System

**Review:** `subagent-05-setup.md`

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🟡 | `config.tmpl` (both) | `role_persona` used but never passed — silently falls back (see Issue C above) |
| 2 | 🟡 | `config.tmpl` (both) | Empty `env` block — if `env` is `None` (undefined), `env.items()` raises Jinja2 error |
| 3 | 🟡 | `bootstrap/SYSTEM.md.tmpl:5`, `TOOLS.md.tmpl` | `{{ tools }}` variable never passed to templates — `{% if tools %}` always falsy |
| 4 | 🟡 | `Dockerfile` | Runtime not baked in — causes the `docker commit` two-step boot workaround in README |
| 5 | 🟢 | `AGENTS.md.tmpl` (both) | `# System` heading embedded in AGENTS.md — duplicates the content of SYSTEM.md |

**Additional issues:**
- No version pinning in npm installs (`@latest` only).
- No Docker `HEALTHCHECK` instruction.
- No workspace writability check in `install.sh`.

---

## Priority Stack — What to Fix First

### Tier 1 (must fix before any meaningful testing)

1. **`adapter.start()` per-message bug** — Without this fix, every message spawns a new pi-agent process. Everything else is unusable.
2. **Config mount in `start_container()`** — AgentServer starts with empty config, no adapter settings.
3. **`Path` import in moderator.py** — Example code is completely broken.

### Tier 2 (correctness bugs)

4. **File-based inbox race condition** — Silent message loss under concurrent load.
5. **Port allocation race condition** — Same port can be double-allocated.
6. **`role_persona` silently ignored** — Persona always falls back to default.
7. **`poll_response()` retries through 500s** — Wastes full timeout waiting on a broken endpoint.

### Tier 3 (design improvements)

8. **Bake pi-agent into Dockerfile** — Eliminate `docker commit` workaround.
9. **`do_PUT /config` missing guard** — Crash when harness not started.
10. **`InboxDelivery.run()` dead code** — Or wire it into `Harness`.
11. **`metadata` dropped in relay** — AgentServer can't distinguish system messages.
12. **`_terminate()` not called after timeout** — Subprocess leaks.

---

## Files with the Most Bugs

| File | Bug Count |
|------|-----------|
| `agentia` (main CLI) | 4 |
| `agent_side/patterns/inbox.py` | 3 |
| `agent_side/patterns/sync.py` | 2 |
| `agents/adapters/pi_agent.py` | 2 |
| `agents/adapters/openclaw.py` | 3 |
| `relay/backends/docker.py` | 2 |
| `setup/adapters/pi-agent/config.tmpl` | 2 |
| `setup/adapters/pi-agent/bootstrap/*.tmpl` | 2 |

---

## Positive Findings

- **`ConfigManager` atomic saves** — write-to-tmp + rename is the right pattern.
- **`AgentAdapter` ABC** — clean minimal interface, easy to implement.
- **Lazy adapter creation** (`_ensure_adapter()`) — correct, avoids premature subprocess spawn.
- **Jinja2 template system** — sound architecture, self-contained per adapter.
- **Factory lazy registration** — avoids circular imports successfully.
- **`PiAgentAdapter` event reader thread** — correctly streams JSONL events.
- **Adapter-agnostic design** — relay and harness are decoupled from the runtime.

---

## Recommendations

**Before running any test:** Fix issues 1–3 (start-per-message, config mount, Path import). Without these, the system produces zombie processes and starts without config.

**Before production use:** Fix issues 4–6 (inbox race, port race, persona fallback) and the Jinja2 `tools`/`role_persona` variable gaps.

**Before multi-agent deployment:** Fix the inbox race condition and port allocation race. These will cause silent data loss under concurrent load.

**Architecture to consider for V2:** Replace the file-based inbox with a queue-based design (POSIX mqueue, SQLite WAL, or Redis). The current JSONL append-then-rewrite approach is fundamentally racy no matter what locking is applied.
