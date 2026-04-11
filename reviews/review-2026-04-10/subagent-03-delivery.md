# Subagent Review: Delivery Patterns

**Reviewer:** subagent-03  
**Date:** 2026-04-08  
**Files Reviewed:**
- `agent_side/patterns/inbox.py`
- `agent_side/patterns/sync.py`
- `agent_side/patterns/__init__.py`
- `agent_side/participation/types.py`
- `agents/adapters/base.py`
- `agents/adapters/openclaw.py`
- `agents/adapters/pi_agent.py`

---

## Summary

Both `SyncDelivery` and `InboxDelivery` have a **critical bug: `adapter.start()` is called per-message**, which for `PiAgentAdapter` spawns a new subprocess per message (and never cleans up the previous one). For `OpenClawAdapter`, each message gets a fresh session ID with no session continuity. Additionally, `InboxDelivery.mark_processed()` has a **file-based race condition** that can silently lose messages when the poller runs concurrently with message producers.

---

## Per-File Analysis

### `agent_side/patterns/sync.py`

**Lines 70–73 — `start()` called per-message (BUG):**
```python
adapter = self._ensure_adapter()
session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
adapter.start(session_id=session_id)
```

`SyncDelivery.send()` is the entry point for every incoming message. `_ensure_adapter()` correctly reuses the adapter instance (lazy singleton pattern, lines 43–53). However, `adapter.start()` is called on **every send**, generating a new session ID each time.

**Impact by adapter:**
- **`PiAgentAdapter.start()` (pi_agent.py:66–95):** Spawns a brand-new `pi --mode rpc` subprocess each call. If you send 10 messages, you get 10 zombie subprocesses that are never `stop()`ed or `teardown()`ed. The `_read_events` thread from the previous session keeps running, causing resource leaks and potential stdout race conditions.
- **`OpenClawAdapter.start()` (openclaw.py:115–122):** Just sets `self.session_id`. No process is spawned here — the actual subprocess spawns in `send()` via `subprocess.run()`. So the bug for OpenClaw is less severe (no zombie processes), but session continuity is still broken: every message gets a brand-new session with no conversation context.

**No `stop()` called after `send()`:** `SyncDelivery.send()` never calls `adapter.stop()`. For `PiAgentAdapter`, this means the subprocess stays alive after each send, but subsequent `send()` calls won't reuse it properly because a **new subprocess is spawned on every `start()`**. The alive subprocess from the previous `start()` call is orphaned.

**Line 70 — shadowing `self._adapter` with local variable:**
```python
adapter = self._ensure_adapter()
```
The local `adapter` variable shadows `self._adapter` but is fine. Not a bug, just worth noting.

---

### `agent_side/patterns/inbox.py`

**`process_message()` lines 106–121 — same per-message `start()` bug:**
```python
def process_message(self, message: dict) -> Optional[str]:
    session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
    adapter = self._ensure_adapter()   # ✓ adapter instance is reused
    adapter.start(session_id=session_id)  # ✗ new session per message
    ...
```

Same issue as `SyncDelivery`. For `PiAgentAdapter`, each message in the inbox spawns a new subprocess and orphans the previous one.

**`mark_processed()` lines 77–96 — RACE CONDITION (BUG):**

```python
def mark_processed(self, message_ids: list[str]) -> int:
    remaining = []
    try:
        with open(self._inbox_path, "r") as f:      # ← READ
            for line in f:
                ...
                remaining.append(line)

        with open(self._inbox_path, "w") as f:      # ← WRITE (truncates!)
            f.write("\n".join(remaining) + ...)
```

The **read-modify-write is not atomic**. A producer calling `append_message()` during the window between the read and the write will have its message silently dropped from the file. No file locking, no rename-to-replace, no advisory lock.

**Scenario:** Poller reads 10 messages (lines 1–10), processes them. Before `mark_processed()` rewrites, an external producer appends 3 more messages (lines 11–13). The rewrite writes only messages 1–10 back, and lines 11–13 are gone forever.

**`append_message()` line 68 — also no locking on write:**
```python
with open(self._inbox_path, "a") as f:
    f.write(json.dumps(message) + "\n")
```
The `append_message()` itself is safe (append is atomic for a single `write()` call smaller than PIPE_BUF), but combined with the unprotected `mark_processed()` rewrite, concurrent use will cause data loss.

**`write_response()` line 102 — mode `"w"` not `"a"` (potential bug, low severity):**
```python
with open(resp_path, "w") as f:
```
This is a fresh **write/truncate** per correlation ID. If two responses are written for the same correlation ID, the second overwrites the first. If this is intentional (only one response per correlation), it's fine. If multiple responses are expected, it should be `"a"`.

**`poll_once()` lines 140–157 — no locking around the read-process-write cycle:**
```python
messages = self.read_inbox()          # no lock
for msg in messages:
    response = self.process_message(msg)
    ...
if processed_ids:
    self.mark_processed(processed_ids)  # race window here
```
Entire read→process→write cycle is unprotected.

---

### `agent_side/participation/types.py`

No issues. Clean dataclass definitions. `RelayMessage`, `RoleConfig`, `AgentContext`, and `ParticipationLevel` are all straightforward data containers. `ParticipationLevel` correctly uses string enum values `"active"`, `"observer"`, `"skip"`.

---

### `agents/adapters/base.py`

**Line 21 — `AgentAdapter.session_id: Optional[str] = None` as class attribute (potential confusion):**
```python
class AgentAdapter(ABC):
    session_id: Optional[str] = None   # class-level annotation
```
This is annotated at class level but is actually intended to be an instance attribute. `OpenClawAdapter.start()` does `self.session_id = session_id` which correctly sets an instance attribute, shadowing the class annotation. `PiAgentAdapter` uses `self._session_id` (private). This is a minor design inconsistency but not a bug.

**`__enter__`/`__exit__` (lines 156–163):** The context manager calls `setup()` then `start()` but never calls `stop()` or `teardown()` in `__exit__`. This is a bug in the base class — it only calls `teardown()` implicitly via `__exit__`. Actually looking again: `__exit__` calls `self.stop()` then `self.teardown()`. Wait, it only passes `*args` to `teardown`. Let me re-read:

```python
def __exit__(self, *args):
    self.stop()
    self.teardown()
```
Yes, it calls `stop()` then `teardown()`. So the base context manager is correct. However, the delivery patterns never use the context manager protocol — they call `setup()`, `start()`, `send()` repeatedly, `teardown()` directly.

---

### `agents/adapters/openclaw.py`

**`send()` lines 137–163 — subprocess per send (by design, not a bug):**
`OpenClawAdapter` is stateless per `send()` — each call runs `openclaw agent --session-id <id> --message <msg>` as a one-shot subprocess. `start()` only sets `self.session_id`. The adapter is designed for one-shot message delivery, so the delivery pattern calling `start()` before each `send()` is redundant but harmless for this adapter.

---

### `agents/adapters/pi_agent.py`

**`start()` lines 66–95 — subprocess spawn per call (confirms the sync/inbox bug):**

```python
def start(self, session_id: Optional[str] = None, **opts) -> str:
    self._session_id = session_id
    self._proc = subprocess.Popen(   # ← NEW subprocess every call
        ["pi", "--mode", "rpc", ...]
    )
    ...
```

This confirms the bug in the delivery patterns: calling `adapter.start()` per message creates a new `pi-agent` subprocess every time, and the previous subprocess is **orphaned** (never stopped/killed). The `_read_events` thread from the orphaned subprocess keeps consuming stdout from the zombie process.

**`send()` lines 97–137 — auto-restart if dead (partial mitigation):**
```python
if self._proc is None or self._proc.poll() is not None:
    self.start()
```
`PiAgentAdapter.send()` auto-restarts the subprocess if it's dead. But because the delivery pattern calls `start()` before `send()`, the pattern's orphaned subprocess is still alive. So `send()` sees `_proc.poll() is not None` as False (the orphaned proc is still technically alive), and tries to write to a stale stdin. This causes interleaved stdout from two `_read_events` threads.

---

## Top 5 Actionable Findings

### 1. **[BUG — Critical] `PiAgentAdapter.start()` called per-message spawns zombie subprocesses**
- **Files:** `sync.py:70`, `inbox.py:111`
- **Behavior:** Each message triggers `adapter.start(session_id=<new>)`, which calls `subprocess.Popen(["pi", "--mode", "rpc", ...])`. The previous subprocess is orphaned — never `stop()`ed or `teardown()`ed. `_read_events` threads accumulate.
- **Fix:** Call `adapter.start()` **once** when the delivery pattern is initialized, not per-message. The session ID can be set once; subsequent messages reuse the same session for conversation continuity. If per-message sessions are required, call `adapter.stop()` before the next `adapter.start()`.
- **Reference:** `sync.py:70–72`, `inbox.py:111–112`

### 2. **[BUG — High] `InboxDelivery.mark_processed()` race condition causes message loss**
- **File:** `inbox.py:77–96`
- **Behavior:** Read entire file → filter → truncate-write. If `append_message()` runs concurrently, its appended lines are read but then **not rewritten** (the truncate-write only writes back what was read). Silent data loss.
- **Fix:** Use an atomic write pattern: read, filter, write to a temp file, then `os.replace(tmp, inbox_path)` (atomic on POSIX). Alternatively, use `fcntl.flock()` around the read+write or mark messages with a processed flag instead of rewriting.
- **Reference:** `inbox.py:82–95`

### 3. **[BUG — High] No file locking in `poll_once()` read-process-write cycle**
- **File:** `inbox.py:124–157`
- **Behavior:** `read_inbox()` → `process_message()` (may be slow) → `mark_processed()` runs entirely unlocked. Any concurrent `append_message()` during this window can be silently lost on the `mark_processed()` rewrite.
- **Fix:** Use `fcntl.flock()` with `LOCK_EX` for the duration of the entire `poll_once()` operation, or switch to a queue-based IPC (POSIX queue, Redis) instead of a shared file.

### 4. **[BUG — Medium] `SyncDelivery.send()` never calls `adapter.stop()` between messages**
- **File:** `sync.py:54–92`
- **Behavior:** For `PiAgentAdapter`, even if `start()` were called only once, `send()` never calls `stop()` after each message. The subprocess accumulates state and event reader threads.
- **Fix:** If per-message session isolation is truly needed, call `adapter.stop()` at the end of each `send()`. Alternatively, move `start()` out of `send()` entirely and call it once in `__init__` or a separate `start()` method on the delivery pattern.

### 5. **[Design — Medium] `InboxDelivery.append_message()` is safe but `write_response()` uses `mode="w"`**
- **File:** `inbox.py:102`
- **Behavior:** `write_response()` opens with `mode="w"` (truncate). If the same `correlation_id` receives multiple responses (e.g., streaming chunks), only the last survives.
- **Fix:** Determine intended semantics. If multiple responses per correlation ID are valid, use `mode="a"`. If not, document this invariant and consider adding a deduplication check.

---

## Architecture Notes

**Positive:**
- Lazy adapter creation (`_ensure_adapter()`) is correct — avoids starting the agent before the first message.
- Adapter abstraction (`AgentAdapter`) is clean and works well for both `pi-agent` and `OpenClaw`.
- Response dataclass pattern in `SyncDelivery.send()` is consistent and well-structured.

**Concerns:**
- Both delivery patterns call `adapter.start()` as if it were a per-message operation. The base class docs say `start()` starts a session, but the semantics of "session" differ per adapter — stateless for OpenClaw, stateful for pi-agent. This API ambiguity enables the bugs.
- No `stop()` discipline: neither delivery pattern calls `adapter.stop()`. For a stateful adapter like `PiAgentAdapter`, this means sessions are never explicitly terminated.
- The `InboxDelivery` file-based inbox is fundamentally racy. A proper fix would move to a queue-based design (POSIX mqueue, SQLite with WAL, or Redis).

---

*Review generated by subagent-03 (Delivery Patterns Review)*
