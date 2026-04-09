# Code Review: Core Server + Harness + Config

**Reviewer:** subagent-01 (core files)
**Files:** `agent_side/server.py`, `agent_side/harness.py`, `agent_side/config.py`
**Context:** File-based inbox delivery pattern, HTTP control/messaging planes, ConfigManager persistence

---

## Summary

The three files implement a coherent architecture: `AgentServer` (HTTP/WebSocket server + request routing), `Harness` (agent lifecycle + delivery pattern orchestration), and `ConfigManager` (atomic disk-backed config with thread-safe updates). The design is reasonably sound for a single-process, single-threaded agent server, but there are several correctness bugs, race conditions, and missing guards that should be fixed before production use.

---

## Per-File Analysis

### `config.py`

#### Design: Sound overall
- Atomic save via write-to-tmp + atomic rename prevents corruption on crash
- `RLock` protects all read/write operations
- `AgentServerConfig.from_dict` filters unknown fields (forward-compat)

#### Bug 1: Silent config loading failures (line 86–89)
```python
except (json.JSONDecodeError, TypeError) as e:
    print(f"[ConfigManager] Failed to load config: {e}, using defaults")
```
If the config file is corrupted, the error is logged but the caller receives defaults silently. The server may silently run with wrong config (e.g., wrong port, wrong delivery mode) with no indication beyond a print statement.

#### Design Issue 1: No validation on numeric config fields (throughout)
`poll_interval`, `agent_timeout`, `port`, `host` are never validated:
- `poll_interval <= 0` → division by zero or busy loop
- `agent_timeout <= 0` → immediate timeout on every message
- `port` outside 1–65535 → `OSError` from `HTTPServer`
- `responses_dir` or `inbox_dir` on a read-only filesystem → silent failure on first write

#### Design Issue 2: `from_dict` silently drops unknown fields (line 61–62)
```python
@classmethod
def from_dict(cls, data: dict) -> "AgentServerConfig":
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```
A typo in the config file (e.g., `"poll_interal": 5.0`) is silently ignored. Should warn or raise on unknown keys.

---

### `harness.py`

#### Bug 1: `teardown` sets `_uptime = None`, risking `TypeError` in `get_status` (line 102, 108)
```python
def teardown(self):
    ...
    self._uptime = None  # line 102

def get_status(self) -> dict:
    ...
    "uptime": time.time() - self._uptime if self._uptime else 0,  # line 108
```
`_uptime` is set to `None` in `teardown()`, but the expression `time.time() - self._uptime if self._uptime else 0` is safe only because `None or 0 == 0`. The `or 0` hides a type error: `time.time() - None` would be a `TypeError` if `_uptime` were `0` (falsy). Fix: use `self._uptime if self._uptime is not None else 0`.

#### Bug 2: `InboxDelivery.run()` defined but never called (inbox.py + harness.py)

`InboxDelivery.run()` is defined at `inbox.py:122`:
```python
def run(self):
    """Poll loop (called in a background thread by AgentServer)."""
```
But `Harness` never calls it. Instead, `Harness._run_inbox_loop()` calls `self._delivery.poll_once()` directly:
```python
def _run_inbox_loop(self):
    while self._running:
        try:
            self._delivery.poll_once()  # NOT self._delivery.run()
```
The docstring in `run()` is wrong — it's not called by `AgentServer`. This is dead code. Either call `run()` instead of `poll_once()` in `_run_inbox_loop()`, or remove `run()`.

#### Bug 3: Race condition in `restart_agent()` — new delivery swapped while poller holds old reference (line 95–100)
```python
def restart_agent(self):
    print(f"[Harness] Restarting agent {self.agent_id}...")
    self._delivery.teardown()
    self._delivery = self._create_delivery()  # old _delivery still in use by poller thread
    self._uptime = time.time()
    ...
```
`_run_inbox_loop()` holds a reference to the old `self._delivery` (a Python local at call time). If `restart_agent()` is called between `poll_once()` returning and the next `poll_once()` call, the new `_delivery` is assigned but the poller keeps using the old one (since `self._delivery` lookup in the next iteration gets the new value... actually this may be fine since Python looks up `self._delivery` each time. Let me re-examine).

Actually, because `self._delivery` is looked up on `self` each iteration, assigning a new delivery object to `self._delivery` in `restart_agent()` WILL be picked up by the running poller thread in subsequent iterations. The `teardown()` call on the old delivery may still have the poller thread sleeping inside `poll_once()` → `_read_inbox()` → `read_inbox()`. The old adapter's `poll_once()` will complete its current iteration using the old adapter, then next iteration will pick up the new delivery. This is fine for most cases but there is a window where the old adapter is torn down while it may still be executing. More importantly: `restart_agent()` does NOT restart the `_running` flag or the poller thread — it just swaps the delivery. The poller thread keeps running. If the new delivery has different `poll_interval`, the old interval is still used until the next loop iteration.

#### Design Issue: `SyncDelivery` creates a new session per message (sync.py:55–59)
```python
def send(self, content: str, correlation_id: Optional[str] = None) -> dict:
    adapter = self._ensure_adapter()
    session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
    adapter.start(session_id=session_id)
```
Every call to `send()` starts a fresh session (new `session_id`). For `OpenClawAdapter`, this means `openclaw agent` subprocess is spawned per message. For `pi-agent`, the subprocess is reused but gets a new session ID. If the intent is conversational continuity within a session, this breaks it. If messages are independent, this is fine but wasteful. This should be documented or configurable.

#### Missing: No validation in `_create_delivery` for unknown delivery mode (line 34)
```python
else:
    raise ValueError(f"Unknown delivery pattern: {self.config.delivery}")
```
This raises at runtime when `Harness.__init__()` is called. If config is loaded from disk with an invalid `delivery` value, the agent fails to start with a `ValueError` rather than a helpful config error.

---

### `server.py`

#### Bug 1: `_poll_response` creates `responses_dir` on every loop iteration (line 213)
```python
def _poll_response(self, correlation_id: str, timeout: float) -> Optional[dict]:
    resp_dir = Path(self._harness.config.responses_dir)
    resp_dir.mkdir(parents=True, exist_ok=True)  # called on EVERY iteration
    start = time.time()
    poll_interval = self._harness.config.poll_interval
    while time.time() - start < timeout:
        resp = self._get_async_response(correlation_id)
        if resp:
            return resp
        time.sleep(poll_interval)
```
This is O(timeout / poll_interval) redundant `mkdir` syscalls. Move `mkdir` before the loop.

#### Bug 2: `_poll_response` timeout is unbounded if `poll_interval` is 0 (line 218)
```python
while time.time() - start < timeout:
```
If `poll_interval == 0` (which passes the config validation check in `config.py`), this becomes a tight busy loop. Also, if `timeout` is very small (e.g., 0.001), the loop may never execute `time.sleep(poll_interval)` and may exit before checking the response.

#### Bug 3: `do_PUT /config` — no `None` guard for `_harness._harness` (line 135)
```python
def do_PUT(self):
    if self.path == "/config":
        data = self._read_json()
        config = AgentServerConfig.from_dict(data)
        new_config = self._harness.config_manager.replace(config)
        self._harness.config = new_config
        self._harness._harness.config = new_config  # _harness._harness could be None
```
If `_harness._harness` is `None` (e.g., `start()` not called, or `stop()` was called), this raises `AttributeError`. The same pattern appears in `do_PATCH` but it has an explicit `if self._harness._harness is not None:` guard (line 150) — the PUT handler is missing this guard.

#### Bug 4: `restart` endpoint returns immediately before restart completes (line 183–187)
```python
if path == "/restart":
    if self._harness._harness is not None:
        self._harness._harness.restart_agent()
    self._send_json(200, {"status": "restarting"})  # returns BEFORE restart_agent() finishes
```
`restart_agent()` is synchronous and blocks until the old delivery is torn down and the new one is created. The response says "restarting" but the restart is already done by the time the response is sent. Either return `"status": "restarted"` after completion, or make it truly async.

#### Bug 5: No request body size limit in `_read_json` (line 84)
```python
def _read_json(self) -> dict:
    content_length = int(self.headers.get("Content-Length", 0))
    body = self.rfile.read(content_length)
    return json.loads(body) if body else {}
```
A malicious client can send `Content-Length: 2147483647` (2GB) and exhaust server memory. Should cap at a reasonable maximum (e.g., 1MB).

#### Bug 6: `write_response` truncates existing response file (inbox.py:79)
```python
with open(resp_path, "w") as f:
    json.dump(entry, f)
    f.write("\n")
```
Uses `"w"` mode — if somehow two responses are written for the same `correlation_id`, the second overwrites the first. With unique `correlation_id` per request (UUID), this is unlikely, but there's no protection against it.

#### Missing: No handler for `do_DELETE` (no endpoint to remove a message from inbox)

#### Missing: `/health` endpoint — only `/status` exists, which requires the harness to be initialized

---

## Cross-File Integration Issues

### Issue 1: File-based inbox race condition (critical)

`server.py:_handle_message()` calls `self._harness._harness._delivery.append_message(message)` from the HTTP handler thread. Meanwhile, `Harness._run_inbox_loop()` calls `self._delivery.poll_once()` → `read_inbox()` → `mark_processed()` from the poller thread.

**The race:**
1. Poller reads inbox file → gets `[msg1, msg2]`
2. HTTP handler appends `msg3` to inbox file
3. Poller processes `msg1`, `msg2`, calls `mark_processed([msg1_id, msg2_id])`
4. `mark_processed` rewrites inbox with only unprocessed IDs
5. `msg3` (which was appended after the read) is NOT in the rewritten file → **lost**

**Fix options:**
- Use file locking (`fcntl.flock`) around all read/write operations
- Use a separate inbox file per message (append-only, never rewrite)
- Use `inotify` / `FSEvents` to detect new messages rather than polling
- Use an in-memory queue with a writer lock, flush to disk periodically

### Issue 2: `Harness._harness` attribute chain is fragile

Throughout `server.py`, accesses are through `self._harness._harness._delivery...`. This double indirection (`AgentServer._harness` → `Harness` instance) is confusing and error-prone. If `_harness` is `None` at any point, accessing `._harness` (on `None`) raises `AttributeError`. While the server flow ensures `_harness` is set before `serve_forever()` and cleared after `stop()`, external callers or tests could easily trigger this.

### Issue 3: Config propagation is inconsistent between PUT and PATCH

- `do_PATCH` has `if self._harness._harness is not None:` guard
- `do_PUT` does NOT have this guard

If `Harness` is swapped out (e.g., via `restart_agent()`), the PUT handler could set config on a stale harness while a new one exists.

### Issue 4: `Harness` lifecycle mismatch with `AgentServer`

`Harness.__init__()` creates a delivery immediately via `_create_delivery()`. But `start()` must be called to start the polling thread. If `stop()` is called without `start()`, `teardown()` is called on an un-started delivery. The adapters' `setup()` is called lazily in `_ensure_adapter()`, so this mostly works, but the init-then-start lifecycle is not enforced.

---

## Top 3–5 Actionable Findings

### Finding 1: [Critical — Race Condition] File-based inbox loses messages under concurrent load
**Files:** `inbox.py` + `server.py` + `harness.py`
**Fix:** Add `fcntl.flock` around `read_inbox()`, `append_message()`, and `mark_processed()` file operations. Or redesign to append-only files (one per message) that are moved/renamed after processing.

### Finding 2: [Bug — Correctness] `do_PUT /config` crashes if `_harness._harness` is `None`
**File:** `server.py:135`
**Fix:** Add `if self._harness._harness is not None: self._harness._harness.config = new_config` (matching the PATCH handler's guard).

### Finding 3: [Bug — Correctness] `_uptime = None` in `teardown()` creates type-unsafe expression
**File:** `harness.py:102, 108`
**Fix:** Replace `self._uptime = None` with `self._uptime = 0` OR use `Optional[float]` type hint and change expression to `time.time() - self._uptime if self._uptime is not None else 0`.

### Finding 4: [Bug — Correctness] `_poll_response` mkdir inside polling loop
**File:** `server.py:213`
**Fix:** Move `resp_dir.mkdir(parents=True, exist_ok=True)` before the `while` loop.

### Finding 5: [Design — Robustness] No request body size limit
**File:** `server.py:84`
**Fix:** Add a `MAX_BODY_SIZE = 1024 * 1024` (1MB) constant and validate `content_length <= MAX_BODY_SIZE` before reading.

---

## Secondary Findings (Lower Priority)

- **inbox.py:79**: `write_response` uses `"w"` mode — use `"x"` or track count to detect duplicate writes
- **config.py:86**: `from_dict` silently drops unknown fields — warn via `logging.warning` for forward-compat sanity
- **config.py**: No bounds validation on `poll_interval`, `agent_timeout`, `port` — add `@validator` or manual checks
- **harness.py**: `SyncDelivery` creates new session per message — document this as intentional or add session reuse option
- **inbox.py:122**: `InboxDelivery.run()` is dead code — remove or fix `_run_inbox_loop` to call it
- **server.py:183**: `/restart` returns `"status": "restarting"` before restart completes — return `"status": "restarted"` after `restart_agent()` returns
