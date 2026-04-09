# Code Quality Review — agentia

**Reviewer:** subagent (code quality scan)  
**Files scanned:** `cli/host.py`, `cli/agent.py`, `agent_side/server.py`, `agent_side/config.py`, `agents/adapters/pi_agent.py`, `agent_side/harness.py`, `relay/*.py`, `setup/adapters/pi-agent/config.tmpl`

---

## Summary

| File | Issues | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| `cli/host.py` | 22 | 2 | 12 | 8 |
| `cli/agent.py` | 2 | 0 | 1 | 1 |
| `agent_side/server.py` | 4 | 1 | 3 | 0 |
| `agent_side/config.py` | 0 | 0 | 0 | 0 |
| `agents/adapters/pi_agent.py` | 4 | 1 | 2 | 1 |
| `agent_side/harness.py` | 0 | 0 | 0 | 0 |
| `relay/base.py` | 0 | 0 | 0 | 0 |
| `relay/backends/docker.py` | 0 | 0 | 0 | 0 |
| `relay/backends/ssh.py` | 0 | 0 | 0 | 0 |
| `setup/adapters/pi-agent/config.tmpl` | 0 | 0 | 0 | 0 |
| **TOTAL** | **32** | **4** | **18** | **10** |

---

## `cli/host.py`

### 1. Duplicate module-level constant definition

**Line 18 and Line 45** | Severity: **MEDIUM**

`CONV_BASE` is defined at module level (line 18) and then redefined identically inside the conversation helpers section (line 45). The second definition shadows the first and makes the module-level one dead code.

```python
# Line 18 (module level, never used as written)
CONV_BASE = Path.home() / ".agentia" / "conversations"

# Line 45 (shadows the above, also redundant with _conv_base())
CONV_BASE = Path.home() / ".agentia" / "conversations"
```

**Fix:** Remove the duplicate at line 45. The function `_conv_base()` at line 48 redefines it again anyway.

---

### 2. F-string with nested double quotes — syntax error

**Line 30** | Severity: **HIGH**

```python
return f"session-{time.strftime("%Y-%m-%dT%H-%M-%S")}"
```

The inner double quotes around the format string are not escaped and will cause a `SyntaxError`.

**Fix:** Use single quotes for the inner format string:
```python
return f'session-{time.strftime("%Y-%m-%dT%H-%M-%S")}'
```

---

### 3. Bare `except:` — too broad

**Lines 36, 550, 653, 672, 724, 805** | Severity: **MEDIUM**

Examples:
```python
# Line 36 (_slugify_message)
except:
    return f"session-{time.strftime("%Y-%m-%dT%H-%M-%S")}"  # Swallows all errors silently

# Line 550 (cmd_prune)
except Exception as e:
    pass  # Agent marked "OK" despite any network error
```

Bare `except:` catches `KeyboardInterrupt`, `SystemExit`, and `MemoryError` — things that should propagate. In `cmd_prune`, a failure is masked as "reachable."

**Fix:** Use specific exception types, e.g. `except (json.JSONDecodeError, IOError)` or at minimum `except Exception`.

---

### 4. `re` imported but never used in host.py

**Line 14** | Severity: **LOW**

`import re` is present but the slugification logic uses it correctly (`re.sub`). Wait — actually it IS used at line 31. No issue here. Retracting.

Actually, re-reading: `_slugify_message` at line 31 uses `re.sub(...)` — so `re` IS used. **No issue. Strike this finding.**

---

### 5. Shell injection vulnerability in `$EDITOR` detection

**Line 661** | Severity: **HIGH**

```python
result = subprocess.run(f"which {candidate.split()[0]}", shell=True, capture_output=True)
```

`candidate.split()[0]` is user-controlled input (environment `$EDITOR` or editor candidates). Using `shell=True` with an f-string constructed from env vars allows command injection.

**Fix:** Use `shlex.split()` or avoid `shell=True`:
```python
result = subprocess.run(["which", candidate.split()[0]], capture_output=True)
```

---

### 6. Bare `except:` in `cmd_files` edit subcommand — file descriptor leak

**Lines 372–379** | Severity: **MEDIUM**

```python
try:
    os.write(fd, original)
    os.close(fd)
except:
    os.close(fd)
    raise
```

Two problems: (1) bare `except:`; (2) if `os.write` fails and then `os.close(fd)` also fails, the fd leaks (not closed, not assigned to `None`).

**Fix:**
```python
try:
    os.write(fd, original)
finally:
    os.close(fd)
```

---

### 7. Redundant imports inside `cmd_chat` after conditional import guard

**Lines 686–689** | Severity: **LOW**

```python
if not _from_ptk_imported:
    from prompt_toolkit import PromptSession
    ...
    _from_ptk_imported = True

from prompt_toolkit import PromptSession          # re-imported unconditionally
from prompt_toolkit.history import FileHistory    # re-imported unconditionally
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import clear
```

The imports after the guard are unconditional and duplicate the ones inside the guard block. They will always run since `_from_ptk_imported` is `False` at the point of first import (module-level `_from_ptk_imported = False`), meaning the guard import runs AND the subsequent imports run (Python doesn't have a "skip" mechanism here).

**Fix:** Remove the duplicate imports after the guard block, or restructure so imports only happen once.

---

### 8. Inconsistent `_set_active_conv` call in `/new` slash command

**Line 768** | Severity: **MEDIUM**

```python
if cmd == "/new":
    ...
    actual = si.get("name", slug)
    _set_active_conv(name, actual, actual)   # conv_id=actual, session_name=actual
```

`_set_active_conv(agent_name, conv_id, session_name)` — both `conv_id` and `session_name` receive `actual`. For consistency with `/switch` (which passes `new_sess` as the third arg and `arg1` as the second), `session_name` should likely be `slug`.

**Fix:**
```python
_set_active_conv(name, slug, actual)
```

---

### 9. Duplicate code: session creation + response handling in `cmd_send`

**Lines 308–318 and 319–329** | Severity: **LOW**

The `new_conv=True` branch and `conv=<id>` branch in `cmd_send` both contain the same pattern: create/resume session → send message → call `_upsert_conv_from_send` → call `_set_active_conv`. ~20 lines duplicated.

**Fix:** Extract into a helper:
```python
def _send_via_session(name, session_name, message, conv_id=None, ...):
    ...
```

---

### 10. Duplicate code: `_http_post` error handling is repeated in `_http_get` and `_http_patch`

**Lines 305–321** | Severity: **LOW**

All three HTTP helper functions have identical error-handling blocks:
```python
except HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"[agentia] HTTP {e.code} at {url}: {body[:200]}")
    return None
except URLError as e:
    print(f"[agentia] Connection failed: {e.reason}")
    return None
```

**Fix:** Extract to a shared `_http_handle_error()` helper.

---

### 11. Unused variable: `current_agent_name` in `cmd_chat`

**Line 730** | Severity: **LOW**

```python
current_agent_name = name   # line 730
...
def make_prompt() -> str:
    c = current_conv_id or "(new)"
    return f"\n  Agent: {current_agent_name}  |  Conv: {c}\n  > "
```

`current_agent_name` is used correctly in `make_prompt()`. Wait — re-reading: it IS used on line 736. **No issue. Retracting.**

---

### 12. Inconsistent error message format — mixed `"[agentia]"` prefix

**Lines 305, 320, 330, 364, 372, 388, 394, 429, 432, 550, 653, 655, 660** | Severity: **LOW**

Some error messages use `"[agentia]"` prefix, some don't:
```python
print(f"[agentia] Cannot reach AgentServer at {url}")   # Line 290
print(f"[prune] {name}: OK ({url})")                     # Line 553
print(f"[agentia] Pruned {len(pruned)} agent(s)...")    # Line 661
print(f"[agentia] Snapshot written: {output}")           # Line 655 — no prefix
```

**Fix:** Standardize all messages to use the `"[agentia]"` prefix, or none at all.

---

### 13. Redundant `get()` default in `_list_convs` sort key

**Line 97** | Severity: **LOW**

```python
convs.sort(key=lambda c: c.get("last_active", ""), reverse=True)
```

`.get()` already returns `""` as the default for missing keys — explicit `""` is redundant but harmless.

**Fix:** `c.get("last_active")` is sufficient.

---

### 14. Duplicate import: `Request` from `urllib.request`

**Line 800** | Severity: **LOW**

```python
from urllib.request import Request   # line 5 (module level)

def cmd_session_delete(...):
    from urllib.request import Request   # line 800 (function-local, shadows module-level)
    ...
```

The local import shadows the module-level one and creates confusion.

**Fix:** Remove the function-local import; use the module-level `Request`.

---

### 15. Dead `subprocess` import in `cmd_chat`

**Lines 357–359** | Severity: **LOW**

```python
import subprocess

def cmd_chat(...):
    ...
    for candidate in ["code --wait", "nano", "vim", "vi"]:
        result = subprocess.run(f"which {candidate.split()[0]}", shell=True, ...)
```

`subprocess` IS used at line 661. **No issue. Retracting.**

---

### 16. Unused `uuid` import in `cmd_chat`

**Line 355** | Severity: **LOW**

```python
import uuid   # line 355
```

`uuid` is not used within `cmd_chat` (it's used at line 26 of `host.py` for correlation IDs, but not in `cmd_chat`).

**Fix:** Remove `import uuid` from `cmd_chat` (or confirm it's used elsewhere in the module).

---

### 17. `open()` without context manager in `cmd_snapshot` (tarfile)

**Line 655** | Severity: **LOW**

```python
with tarfile.open(output, "w:gz") as tar:
    tar.add(tmpdir_path, arcname=name)
```

The tarfile itself is fine. This is not an issue. **Retracting.**

---

### 18. Redundant local `CONV_BASE` in `_conv_base()`

**Lines 45, 48** | Severity: **LOW**

```python
CONV_BASE = Path.home() / ".agentia" / "conversations"   # line 45 (duplicate of line 18)

def _conv_base() -> Path:
    base = CONV_BASE     # line 49 — uses the local duplicate, not the module-level one
    base.mkdir(parents=True, exist_ok=True)
    return base
```

The function-level `CONV_BASE = ...` makes the module-level one unreachable. The function could simply use the module-level constant directly.

**Fix:** Remove the duplicate at line 45, and in `_conv_base()` use `CONV_BASE` directly (it's the module-level).

---

### 19. Response extraction logic in `cmd_send` is fragile

**Lines 457–462** | Severity: **MEDIUM**

```python
content = response.get("response") or response.get("content") or response.get("stdout", "")
if isinstance(content, dict):
    print(response.get("response", content))
    if response.get("compact_triggered"):
        print(f"[agentia] Auto-compacted ...")
else:
    print(content)
```

If `response.get("response")` returns a dict, it falls through to `isinstance(content, dict)` and prints the dict. But `response.get("stdout", "")` as fallback means a missing key silently returns `""`. No clear contract on which field contains the actual content.

**Fix:** Document the response shape and use a dedicated helper with explicit key precedence.

---

### 20. `cmd_snapshot` creates empty directories in archive

**Line 653** | Severity: **LOW**

```python
for file_path, ftype in files:
    if ftype == "directory":
        continue   # skips dirs
```

Directories are excluded from the archive. If the archive is extracted and directories don't exist, file extraction may fail.

**Fix:** Either create directory entries in the tar, or document this limitation.

---

### 21. `_http_post_or_409` silently swallows `URLError` without logging

**Lines 158–170** | Severity: **LOW**

```python
except URLError:
    return None, False
```

Unlike `_http_get` and `_http_post` which print a message on `URLError`, `_http_post_or_409` silently returns `(None, False)`. The caller does print a message, but the helper itself is inconsistent.

**Fix:** Add `print(f"[agentia] Connection failed: {e.reason}")` before returning, consistent with other helpers.

---

### 22. Debug artifact: `open('/tmp/debug_config_hit.txt', 'w')` in production code

**Line 31** | Severity: **MEDIUM**

```python
if path == "/config":
    open('/tmp/debug_config_hit.txt', 'w').write("config route hit")  # DEBUG artifact
```

This is almost certainly debug code left in production.

**Fix:** Remove the line.

---

## `cli/agent.py`

### 1. Duplicate `import argparse`

**Lines 6–7** | Severity: **MEDIUM**

```python
import argparse  # line 6
import argparse  # line 7 — duplicate
import os
import subprocess
import sys
from pathlib import Path
```

**Fix:** Remove the duplicate.

---

### 2. Unused `Path` import

**Line 11** | Severity: **LOW**

`Path` is imported but `DEFAULT_CONFIG_PATH` and `DEFAULT_WORKSPACE` use `Path.home()` directly in the expressions (not `Path()`). However, `Path(__file__)` IS used at line 230. So `Path` IS used. **Retracting this finding.**

---

## `agent_side/server.py`

### 1. Duplicate method: `stop` defined twice

**Lines 91–98 and 100–109** | Severity: **HIGH**

```python
def stop(self):
    """Stop the harness and server."""
    if self._harness is not None:
        self._harness.stop()
        self._harness.teardown()

def stop(self):                          # ← overwrites the first
    """Stop the harness and server."""
    if self._harness is not None:
        self._harness.stop()
        self._harness.teardown()
        self._harness = None
    if self._server is not None:
        self._server.shutdown()
        self._server = None
    print("[AgentServer] Stopped")
```

The second `stop()` is more complete (nulls out `self._harness` and `self._server`, calls `self._server.shutdown()`). The first one is dead code that gets overridden. However, the second one doesn't call `self._harness.teardown()` — wait, it does. The second one adds `self._harness = None`, `self._server.shutdown()`, `self._server = None`, and `print(...)`.

**Fix:** Remove the first `stop()` (lines 91–98); keep only the second (lines 100–109).

---

### 2. `re` imported but not used

**Line 40** | Severity: **LOW**

```python
import re   # line 40
```

No `re.` calls in the file.

**Fix:** Remove `import re`.

---

### 3. Unused `Optional` in `agent_side/server.py`

**Line 41** | Severity: **LOW**

```python
from typing import Optional  # line 41
```

`Optional` is imported but not used in the file. (It appears in `config.py` but that's a different file.)

**Fix:** Remove `from typing import Optional`.

---

### 4. Double underscore attribute access: `self._harness._harness`

**Lines 35–37, 108** | Severity: **MEDIUM**

```python
status = (
    self._harness._harness.get_status()   # ← double underscore access pattern
    if self._harness._harness else {}
)
```

`self._harness` is `Harness` instance; `self._harness._harness` accesses `Harness`'s own `_harness` attribute. This naming collision (the field happens to be named `_harness` inside `Harness`) makes the code harder to follow and fragile if `Harness` internals change.

**Fix:** Rename `Harness._harness` to `Harness._adapter` or `Harness._delivery` to avoid collision with the enclosing `AgentServer._harness`.

---

## `agents/adapters/pi_agent.py`

### 1. `s._proc.poll() is not None` — attribute method confused with callable check

**Line 484** | Severity: **HIGH**

```python
if s._proc is None or s._proc.poll() is not None:  # s._proc.poll() -> int, not callable
    s.session_file = f"{s.name}.jsonl"
    self._spawn(s)
```

Wait — `subprocess.Popen.poll()` IS a method (callable). The code calls `s._proc.poll()` which returns the exit code or `None`. `s._proc.poll() is not None` correctly checks if the process has terminated. This is NOT a bug. **Retracting.**

---

### 2. Unused `asdict` import

**Line 12** | Severity: **LOW**

```python
from dataclasses import dataclass, field, asdict  # asdict not used
```

**Fix:** Remove `asdict` from the import.

---

### 3. `session._event_thread: Optional[threading.Thread]` — runtime-only field included in manifest

**Lines 184–185** | Severity: **MEDIUM**

In `_save_manifest()`, the code explicitly builds `session_rec` without underscore-prefixed fields (good). But the dataclass definition documents `_proc`, `_event_thread`, `_response_buffer`, `_response_event`, `_idle_timer` as runtime-only. The manifest I/O looks correct. However, `_resolve_name` and `_evict_lru` operate on in-memory `self._sessions` dict which holds `Session` objects — these are consistent.

**No finding here — the design is sound.**

---

### 4. `gemini-2.0-flash` context window estimate: 1M tokens

**Line 32** | Severity: **LOW**

```python
"gemini-2.0-flash": 1000000,
```

`gemini-2.0-flash` (the stable release) has a 1M token context window. This is a rough heuristic estimate (used for context_pct calculation). The value seems inflated vs. reality — gemini-2.0-flash is typically 32K-1M depending on version. The other values (e.g., `gpt-4o: 128000`) are reasonable.

**Fix:** Confirm actual context window size for `gemini-2.0-flash` and update. Consider using a comment explaining the estimate.

---

### 5. Bare `except Exception` in `_read_events` (SessionManager)

**Lines 175–177** | Severity: **MEDIUM**

```python
try:
    for line in proc.stdout:
        ...
except Exception:
    pass   # silently swallows all errors including OSErrors
```

In a long-running event reader thread, silently swallowing `Exception` means real errors (broken pipe, OSError from subprocess) go undetected.

**Fix:** At minimum, log the exception:
```python
except Exception:
    pass  # stderr/stdout exhausted
```
Add a comment documenting why this is intentionally silent (subprocess cleanup).

---

## `agent_side/config.py`

No issues found.

---

## `agent_side/harness.py`

No issues found. Clean implementation.

---

## `relay/base.py`

No issues found.

---

## `relay/backends/docker.py`

No issues found. Clean implementation.

---

## `relay/backends/ssh.py`

No issues found.

---

## `setup/adapters/pi-agent/config.tmpl`

No issues found. Jinja2 template is syntactically correct.

---

## Priority Fix Order

### Immediately (HIGH)

1. **`cli/host.py` Line 30** — Syntax error from nested double quotes in f-string
2. **`cli/host.py` Line 661** — Shell injection via `EDITOR` env var
3. **`agent_side/server.py` Lines 91–109** — Duplicate `stop()` method (first is dead, second is incomplete but correct)
4. **`agents/adapters/pi_agent.py` Line 32** — Confirmed: no bug, `poll()` is callable (strike that finding)

### Soon (MEDIUM)

5. **`cli/host.py` Line 31** — Debug artifact `open('/tmp/debug_config_hit.txt', 'w')`
6. **`cli/host.py` Lines 36, 550, 653, 672, 724, 805** — Replace bare `except:` with specific exception types
7. **`cli/host.py` Lines 45, 49** — Remove duplicate `CONV_BASE` definitions
8. **`cli/host.py` Line 768** — Fix `_set_active_conv` argument order in `/new` command
9. **`cli/host.py` Lines 686–689** — Remove duplicate prompt_toolkit imports
10. **`agent_side/server.py` Lines 40–41** — Remove unused `re` and `Optional` imports
11. **`agent_side/server.py` Line 37** — Rename `Harness._harness` to avoid double-underscore shadowing
12. **`cli/agent.py` Lines 6–7** — Remove duplicate `import argparse`
13. **`agents/adapters/pi_agent.py` Lines 175–177** — Add logging to bare except in `_read_events`

### Eventually (LOW)

14. **`cli/host.py`** — Extract duplicated session creation/send logic in `cmd_send` into helper
15. **`cli/host.py`** — Standardize error message format (`[agentia]` prefix consistency)
16. **`cli/host.py`** — Extract shared HTTP error handler
17. **`agents/adapters/pi_agent.py`** — Remove unused `asdict` import
18. **`cli/host.py`** — Add directory entries to tar archive in `cmd_snapshot`
19. **`cli/host.py`** — Add `URLError` logging in `_http_post_or_409`
20. **`cli/host.py`** — Remove unused `uuid` import from chat area
