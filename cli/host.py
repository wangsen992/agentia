#!/usr/bin/env python3
"""
agentia — Host-side CLI

Runs on the host machine. Discovers agents via HTTP, registers them locally,
and manages them through the AgentServer API.

Commands: register, agents, send, status, configure, update, deregister, forward
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REGISTRY = Path.home() / ".agentia" / "agents.json"
CONV_BASE = Path.home() / ".agentia" / "conversations"

def _slugify_message(message: str, max_len: int = 50) -> str:
    """Derive a slugified session name from a message.
    
    If message is short (< 10 chars), returns a timestamp-based fallback.
    Otherwise returns first `max_len` chars, slugified.
    """
    if len(message.strip()) < 10:
        return f"session-{time.strftime("%Y-%m-%dT%H-%M-%S")}"
    slug = re.sub(r'[^a-zA-Z0-9\s]', '', message.lower())
    slug = re.sub(r'\s+', '-', slug).strip('-')[:max_len]
    return slug or f"session-{time.strftime("%Y-%m-%dT%H-%M-%S")}"



# ─── Registry ────────────────────────────────────────────────────────────────

def _load_registry(path: Path = DEFAULT_REGISTRY) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 1, "agents": {}}


def _save_registry(data: dict, path: Path = DEFAULT_REGISTRY):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ─── Conversation helpers (Layer A) ───────────────────────────────────────────

CONV_BASE = Path.home() / ".agentia" / "conversations"


def _conv_base() -> Path:
    """Base directory for conversation registry."""
    base = CONV_BASE
    base.mkdir(parents=True, exist_ok=True)
    return base


def _active_file(agent_name: str) -> Path:
    """Path to the active-conversation index file for an agent."""
    return _conv_base() / ".active" / f"{agent_name}.jsonl"


def _get_active_conv(agent_name: str) -> dict | None:
    """Read the active conversation for an agent. Returns {conv_id, session_name} or None."""
    path = _active_file(agent_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, IOError):
        return None


def _set_active_conv(agent_name: str, conv_id: str, session_name: str):
    """Update the active conversation index for an agent."""
    path = _active_file(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "conv_id": conv_id,
        "session_name": session_name,
        "last_active": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2))


def _get_agent_sessions(agent_name: str) -> list[dict]:
    """Get the list of sessions from an agent via GET /sessions. Returns [] on failure."""
    sessions = _http_get(agent_name, "/sessions")
    if sessions is None:
        return []
    if isinstance(sessions, list):
        return sessions
    return []


def _http_post_or_409(name: str, path: str, data: dict, timeout: float = 120) -> tuple[dict | None, bool]:
    """Like _http_post but returns (response, is_409) instead of printing on HTTPError.

    Returns (response_dict, False) on success.
    Returns (None, True) on 409 Conflict.
    Returns (None, False) on other errors.
    """
    url = _agent_url(name, path)
    if not url:
        return None, False
    body = json.dumps(data).encode()
    try:
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), False
    except HTTPError as e:
        if e.code == 409:
            return None, True
        return None, False
    except URLError:
        return None, False


def _smart_route(agent_name: str, message: str, explicit_conv: str | None) -> dict | None:
    """Route a message using the smart router.

    Returns the agent response dict, or None on failure.
    Prints its own error messages.

    Routing logic (SPEC 021 Layer C):
      1. If explicit_conv given -> use that
      2. Read .active/<agent>.jsonl (host-side primary lookup)
      3. Try sending to that session
      4. On 409 (not running) -> GET /sessions -> most recent -> create new
      5. If no .active/ -> GET /sessions -> most recent -> create new
      6. If nothing -> create "default" session
    """
    # Step 1: Determine conversation to use
    if explicit_conv:
        conv_to_use = explicit_conv
        session_name = explicit_conv
    else:
        active = _get_active_conv(agent_name)
        if active:
            conv_to_use = active["conv_id"]
            session_name = active["session_name"]
        else:
            conv_to_use = None
            session_name = None

    # Step 2: Try to send to the session
    if session_name:
        response, is_409 = _http_post_or_409(
            agent_name,
            f"/sessions/{session_name}/message",
            {"content": message},
            timeout=120,
        )
        if response is not None:
            _set_active_conv(agent_name, conv_to_use, conv_to_use)
            return response
        if not is_409:
            print("[agentia] Failed to send message")
            return None
        # 409 — session not running, fall through to GET /sessions

    # Step 3: Fall back to agent-side GET /sessions for authoritative lookup
    sessions = _get_agent_sessions(agent_name)

    def _sort_key(s):
        return s.get("last_active", "")

    sessions_sorted = sorted(sessions, key=_sort_key, reverse=True)

    if sessions_sorted:
        most_recent = sessions_sorted[0]
        conv_to_use = most_recent.get("title") or most_recent.get("name", "default")
        session_name = most_recent.get("name")

        if session_name:
            response, _ = _http_post_or_409(
                agent_name,
                f"/sessions/{session_name}/message",
                {"content": message},
                timeout=120,
            )
            if response is not None:
                _set_active_conv(agent_name, conv_to_use, conv_to_use)
                return response

    # Step 4: Nothing available — create new "default" session
    conv_to_use = "default"
    response = _http_post(agent_name, "/sessions/new", {"name": conv_to_use}, timeout=10)
    if not response:
        print("[agentia] Session management unavailable, using legacy /message")
        return _http_post(agent_name, "/message", {"content": message}, timeout=120)

    response = _http_post(
        agent_name,
        f"/sessions/{conv_to_use}/message",
        {"content": message},
        timeout=120,
    )
    if response:
        _set_active_conv(agent_name, conv_to_use, conv_to_use)
    return response


# ─── Registry ────────────────────────────────────────────────────────────────

def _get_agent(name: str) -> dict | None:
    registry = _load_registry()
    return registry["agents"].get(name)


# ─── HTTP helpers ────────────────────────────────────────────────────────────

def _agent_url(name: str, path: str = "") -> str | None:
    agent = _get_agent(name)
    if not agent:
        print(f"[agentia] Agent '{name}' not found in registry. Run: agentia register <url> --name {name}")
        return None
    base = agent["url"].rstrip("/")
    return f"{base}{path}" if path else base


def _http_get(name: str, path: str) -> dict | None:
    url = _agent_url(name, path)
    if not url:
        return None
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        print(f"[agentia] HTTP {e.code} at {url}: {e.reason}")
        return None
    except URLError as e:
        print(f"[agentia] Connection failed: {e.reason}")
        return None


def _http_post(name: str, path: str, data: dict, timeout: float = 120) -> dict | None:
    url = _agent_url(name, path)
    if not url:
        return None
    body = json.dumps(data).encode()
    try:
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[agentia] HTTP {e.code} at {url}: {body[:200]}")
        return None
    except URLError as e:
        print(f"[agentia] Connection failed: {e.reason}")
        return None


def _http_patch(name: str, path: str, data: dict) -> bool:
    url = _agent_url(name, path)
    if not url:
        return False
    body = json.dumps(data).encode()
    try:
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="PATCH")
        with urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[agentia] HTTP {e.code} at {url}: {body[:200]}")
        return False
    except URLError as e:
        print(f"[agentia] Connection failed: {e.reason}")
        return False


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_register(url: str, name: str, metadata: dict | None) -> int:
    """Register an agent by its AgentServer endpoint."""
    # Verify the agent is reachable
    print(f"[agentia] Connecting to {url}...")
    status = _http_get_raw(url)
    if not status:
        print(f"[agentia] Cannot reach AgentServer at {url}")
        return 1

    registry = _load_registry()
    agent_data = {
        "url": url.rstrip("/"),
        "name": name,
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metadata": metadata or {},
    }
    registry["agents"][name] = agent_data
    _save_registry(registry)
    print(f"[agentia] Registered '{name}' → {url}")
    return 0


def _http_get_raw(url: str) -> dict | None:
    try:
        req = Request(url.rstrip("/") + "/status")
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def cmd_agents() -> int:
    """List all registered agents."""
    registry = _load_registry()
    agents = registry.get("agents", {})
    if not agents:
        print("No agents registered. Run: agentia register <url> --name <name>")
        return 0

    print(f"{'NAME':<25} {'URL':<40} {'METADATA'}")
    print("-" * 80)
    for name, info in agents.items():
        meta = json.dumps(info.get("metadata", {})) if info.get("metadata") else ""
        print(f"{name:<25} {info['url']:<40} {meta}")
    return 0


def cmd_send(name: str, message: str, conv: str | None = None, new_conv: bool = False) -> int:
    """Send a message to an agent. Blocks until response.

    If --new is set, starts a fresh conversation named from the message content
    (first ~50 chars, slugified). If message is < 10 chars, uses timestamp fallback.

    If conv is specified, routes to that named conversation.

    If neither is set, uses the smart router (Layer C):
      - Reads .active/<agent>.jsonl for last-used conversation
      - Falls back to GET /sessions for most recent agent-side session
      - Creates "default" conversation if nothing exists
    """
    print(f"[agentia] Sending to '{name}'..." +
          (f" (--new)" if new_conv else f" (conv={conv})" if conv else ""))

    if new_conv:
        # Start a new conversation named from the message
        conv_name = _slugify_message(message)
        session_info = _http_post(name, "/sessions/new", {"name": conv_name}, timeout=10)
        if not session_info:
            print(f"[agentia] Failed to create new session '{conv_name}'")
            return 1
        actual_name = session_info.get("name", conv_name)
        response = _http_post(name, f"/sessions/{actual_name}/message", {"content": message}, timeout=120)
        if response:
            _set_active_conv(name, actual_name, actual_name)
    elif conv:
        # Explicit conversation: create/resume then send
        session_info = _http_post(name, "/sessions/new", {"name": conv}, timeout=10)
        if not session_info:
            print(f"[agentia] Failed to create/resume session '{conv}'")
            return 1
        actual_name = session_info.get("name", conv)
        response = _http_post(name, f"/sessions/{actual_name}/message", {"content": message}, timeout=120)
        if response:
            _set_active_conv(name, actual_name, actual_name)
    else:
        # Smart router: implicit conversation routing
        response = _smart_route(name, message, None)

    if not response:
        return 1
    content = response.get("content", response.get("stdout", ""))
    if isinstance(content, dict):
        # Session API returns structured response
        print(response.get("response", content))
        if response.get("compact_triggered"):
            print(f"[agentia] Auto-compacted (context threshold reached)")
    else:
        print(content)
    return 0


def cmd_status(name: str) -> int:
    """Get agent status."""
    status = _http_get(name, "/status")
    if not status:
        return 1

    # Update last_seen
    registry = _load_registry()
    if name in registry["agents"]:
        registry["agents"][name]["last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save_registry(registry)

    uptime = status.get("uptime", 0)
    if uptime:
        mins = int(uptime) // 60
        hrs = mins // 60
        mins = mins % 60
        uptime_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
    else:
        uptime_str = "unknown"

    delivery = status.get("delivery", "?")
    adapter = status.get("adapter", "?")
    model = status.get("model", "?")

    print(f"name:      {name}")
    print(f"url:       {_get_agent(name)['url']}")
    print(f"uptime:    {uptime_str}")
    print(f"delivery:  {delivery}")
    print(f"adapter:   {adapter}")
    print(f"model:     {model}")
    return 0


def cmd_configure(name: str, key: str, value: str) -> int:
    """
    Update agent config via PATCH /config.
    Supports dot notation for nested keys: role.goal, role.backstory, etc.
    """
    keys = key.split(".")
    if len(keys) == 1:
        patch_data = {key: _parse_value(value)}
    else:
        # Build nested dict from dot notation
        patch_data = _nested_set({}, keys, _parse_value(value))

    ok = _http_patch(name, "/config", patch_data)
    if ok:
        print(f"[agentia] Updated {name}.{key} = {value!r}")
    return 0 if ok else 1


def cmd_update(name: str, role_goal: str, backstory: str, skills: list[str]) -> int:
    """
    Push updated bootstrap config to agent. AgentServer re-renders bootstrap files
    and restarts the agent subprocess.
    """
    patch_data = {}
    if role_goal:
        patch_data["role_goal"] = role_goal
    if backstory:
        patch_data["backstory"] = backstory
    if skills:
        patch_data["skills"] = skills

    # Also mark that a restart is needed
    patch_data["_restart"] = True

    ok = _http_patch(name, "/config", patch_data)
    if ok:
        print(f"[agentia] Updated bootstrap config for '{name}' and triggered restart")
    return 0 if ok else 1


def cmd_files(name: str, subcmd: str, path: str, content: str | None) -> int:
    """
    Access agent filesystem via AgentServer /files API.

    subcmd: get | put | delete | ls
    path: relative to workspace (e.g. AGENTS.md, .pi/skills/)
    content: file content for 'put'
    """
    agent = _get_agent(name)
    if not agent:
        return 1
    base = agent["url"].rstrip("/")
    file_path = path.lstrip("/")

    if subcmd == "ls":
        url = f"{base}/files/{file_path}" if file_path else f"{base}/files/"
        try:
            req = Request(url)
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            entries = data.get("entries", [])
            if not entries:
                print(f"(empty directory)")
            for e in entries:
                tag = "/" if e["type"] == "directory" else ""
                print(f"  {e['name']}{tag}")
            return 0
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

    url = f"{base}/files/{file_path}"

    if subcmd == "get":
        try:
            req = Request(url)
            with urlopen(req, timeout=10) as resp:
                print(resp.read().decode())
            return 0
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

    if subcmd == "put":
        if not content:
            print(f"[agentia] put requires --content or --from")
            return 1
        body = content.encode()
        try:
            req = Request(url, data=body, headers={"Content-Type": "application/octet-stream"}, method="PUT")
            with urlopen(req, timeout=10) as resp:
                print(f"[agentia] Written: {file_path} ({resp.status})")
            return 0
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

    if subcmd == "delete":
        try:
            req = Request(url, method="DELETE")
            with urlopen(req, timeout=10) as resp:
                print(f"[agentia] Deleted: {file_path}")
            return 0
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

    if subcmd == "edit":
        import tempfile
        import os
        import subprocess

        # Determine editor
        editor = os.environ.get("EDITOR")
        if not editor:
            for candidate in ["code --wait", "nano", "vim", "vi"]:
                result = subprocess.run(f"which {candidate.split()[0]}", shell=True, capture_output=True)
                if result.returncode == 0:
                    editor = candidate
                    break
        if not editor:
            print("[agentia] No editor found. Set $EDITOR or install nano/vim")
            return 1

        # GET file
        try:
            req = Request(url)
            with urlopen(req, timeout=10) as resp:
                original = resp.read()
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

        # Write to temp file
        suffix = os.path.splitext(file_path)[1]
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.write(fd, original)
            os.close(fd)
        except:
            os.close(fd)
            raise

        print(f"[agentia] Opening in {editor.split()[0]}... (save & close to upload changes)")

        # Open in editor and wait
        result = subprocess.run(editor.split() + [tmp_path])
        if result.returncode != 0:
            print(f"[agentia] Editor exited with code {result.returncode}")
            os.unlink(tmp_path)
            return 1

        # Read edited content
        edited = open(tmp_path, "rb").read()
        os.unlink(tmp_path)

        if edited == original:
            print("[agentia] No changes, skipping upload")
            return 0

        # PUT back
        try:
            req = Request(url, data=edited, headers={"Content-Type": "application/octet-stream"}, method="PUT")
            with urlopen(req, timeout=10) as resp:
                print(f"[agentia] Updated: {file_path}")
            return 0
        except HTTPError as e:
            print(f"[agentia] HTTP {e.code}: {e.reason}")
            return 1

    print(f"[agentia] Unknown subcommand: {subcmd}")
    return 1


def cmd_snapshot(name: str, output_path: str | None) -> int:
    """
    Snapshot an agent's workspace to a .tar.gz archive.

    Downloads all files via AgentServer /files API and tars them.
    Falls back to direct host-side copy if agent is on localhost.
    """
    import tarfile
    import tempfile

    agent = _get_agent(name)
    if not agent:
        return 1

    base = agent["url"].rstrip("/")
    output = output_path or f"{name}-snapshot.tar.gz"

    def list_files_recursive(prefix: str) -> list[tuple[str, str]]:
        """Returns list of (full_path, type)."""
        url = f"{base}/files/{prefix}" if prefix else f"{base}/files/"
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for entry in data.get("entries", []):
            entry_path = f"{prefix}{entry['name']}" if prefix else entry["name"]
            results.append((entry_path, entry["type"]))
            if entry["type"] == "directory":
                results.extend(list_files_recursive(f"{entry_path}/"))
        return results

    print(f"[agentia] Snapshotting '{name}' → {output}")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        files = list_files_recursive("")
        print(f"[agentia] Found {len(files)} entries, archiving...")
        for file_path, ftype in files:
            if ftype == "directory":
                continue
            src_url = f"{base}/files/{file_path}"
            req = Request(src_url)
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
            dst = tmpdir_path / file_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        with tarfile.open(output, "w:gz") as tar:
            tar.add(tmpdir_path, arcname=name)
    print(f"[agentia] Snapshot written: {output}")
    return 0


def cmd_deregister(name: str) -> int:
    """Remove an agent from the local registry."""
    registry = _load_registry()
    if name not in registry["agents"]:
        print(f"[agentia] Agent '{name}' not in registry")
        return 1

    del registry["agents"][name]
    _save_registry(registry)
    print(f"[agentia] Deregistered '{name}'")
    return 0


def cmd_prune() -> int:
    """Remove unreachable agents from the registry."""
    registry = _load_registry()
    agents = registry.get("agents", {})
    if not agents:
        print("No agents registered.")
        return 0

    pruned = []
    for name in list(agents.keys()):
        url = agents[name]["url"]
        try:
            req = Request(f"{url}/status")
            with urlopen(req, timeout=5) as resp:
                if resp.status >= 200 and resp.status < 300:
                    print(f"[prune] {name}: OK ({url})")
                    continue
        except Exception as e:
            pass

        print(f"[prune] {name}: unreachable — removing ({url})")
        del registry["agents"][name]
        pruned.append(name)

    if pruned:
        _save_registry(registry)
        print(f"[agentia] Pruned {len(pruned)} agent(s): {', '.join(pruned)}")
    else:
        print("[agentia] All agents reachable, nothing to prune.")
    return 0


def cmd_sessions_list(name: str) -> int:
    """List all sessions for an agent."""
    sessions = _http_get(name, "/sessions")
    if sessions is None:
        print("[agentia] Failed to list sessions — agent may not support session management")
        return 1
    if not sessions:
        print("No sessions.")
        return 0
    print(f"{'NAME':<45} {'TITLE':<20} {'STATUS':<10} {'MSGS':>5} {'CTX%':>5} {'LAST ACTIVE'}")
    print("-" * 100)
    for s in sessions:
        name_s = s.get("name", "")[:44]
        title = s.get("title", "")[:19]
        status = s.get("status", "?")[:9]
        msgs = s.get("message_count", 0)
        ctx = s.get("context_pct", 0)
        last = s.get("last_active", "-")
        print(f"{name_s:<45} {title:<20} {status:<10} {msgs:>5} {ctx:>5}% {last}")
    return 0


def cmd_compact(name: str, conv: str) -> int:
    """Manually trigger compaction on a session."""
    print(f"[agentia] Compacting session '{conv}' on '{name}'...")
    result = _http_post(name, f"/sessions/{conv}/compact", {"message": ""}, timeout=30)
    if result is None:
        print("[agentia] Failed — session may not exist or not running")
        return 1
    if "error" in result:
        print(f"[agentia] Error: {result['error']}")
        return 1
    print(f"[agentia] Compacted: before={result.get('message_count_before','?')} msgs, "
          f"after={result.get('message_count_after','?')} msgs, "
          f"ctx={result.get('context_pct','?')}%")
    return 0


def cmd_session_delete(name: str, conv: str, hard: bool = False) -> int:
    """Delete a session (stop subprocess, optionally delete session file)."""
    path = f"/sessions/{conv}" + ("?hard=true" if hard else "")
    # Use _http_post with DELETE method via cmd_forward
    print(f"[agentia] Deleting session '{conv}' on '{name}'" + (" (hard)" if hard else ""))
    from urllib.request import Request
    agent = _get_agent(name)
    if not agent:
        print(f"[agentia] Agent '{name}' not found")
        return 1
    url = f"{agent['url'].rstrip('/')}{path}"
    try:
        req = Request(url, method="DELETE")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"[agentia] Deleted: {data}")
            return 0
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[agentia] HTTP {e.code}: {body[:300]}")
        return 1
    except Exception as e:
        print(f"[agentia] Error: {e}")
        return 1


def cmd_forward(name: str, method: str, path: str, data: str | None) -> int:
    """Forward a raw HTTP request to the agent."""
    url = _agent_url(name, path)
    if not url:
        return 1

    body = data.encode() if data else None
    headers = {"Content-Type": "application/json"} if body else {}
    try:
        req = Request(url, data=body, headers=headers, method=method)
        with urlopen(req, timeout=30) as resp:
            print(f"Status: {resp.status}")
            body = resp.read()
            if body:
                print(body.decode("utf-8", errors="replace"))
            return 0
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body[:500]}")
        return 1
    except URLError as e:
        print(f"[agentia] Connection failed: {e.reason}")
        return 1


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_value(value: str) -> str | int | float | bool:
    """Parse a string value into the most appropriate type."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _nested_set(d: dict, keys: list[str], value) -> dict:
    """Build a nested dict from a list of keys."""
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
    return d


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agentia",
        description="agentia — Host-side agent management CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # register <url> --name <name>
    p_reg = sub.add_parser("register", help="Register an agent")
    p_reg.add_argument("url", help="AgentServer base URL (e.g. http://localhost:18080)")
    p_reg.add_argument("--name", "-n", required=True, help="Friendly agent name")
    p_reg.add_argument("--metadata", "-m", default=None,
                        help="JSON metadata blob")

    # agents
    sub.add_parser("agents", help="List registered agents")

    # send <name> <message>
    p_send = sub.add_parser("send", help="Send a message to an agent")
    p_send.add_argument("name", help="Agent name")
    p_send.add_argument("message", nargs="...", help="Message to send")
    p_send.add_argument("--conv", "-c", dest="conv", default=None,
                        help="Conversation/session name (enables session management)")
    p_send.add_argument("--new", "-n", dest="new", action="store_true",
                        help="Start a new conversation with a name derived from the first message")

    # status <name>
    p_status = sub.add_parser("status", help="Get agent status")
    p_status.add_argument("name", help="Agent name")

    # configure <name> <key> <value>
    p_conf = sub.add_parser("configure", help="Update agent config")
    p_conf.add_argument("name", help="Agent name")
    p_conf.add_argument("key", help="Config key (supports dot notation, e.g. role.goal)")
    p_conf.add_argument("value", help="New value")

    # update <name>
    p_upd = sub.add_parser("update", help="Update agent bootstrap files + restart")
    p_upd.add_argument("name", help="Agent name")
    p_upd.add_argument("--role-goal", default="", help="New role goal")
    p_upd.add_argument("--backstory", default="", help="New backstory")
    p_upd.add_argument("--skills", action="append", default=[], help="Skill name")

    # deregister <name>
    p_dereg = sub.add_parser("deregister", help="Remove agent from registry")
    p_dereg.add_argument("name", help="Agent name")

    # prune
    sub.add_parser("prune", help="Remove unreachable agents from registry")

    # sessions <name> — list sessions
    p_sess = sub.add_parser("sessions", help="List agent sessions")
    p_sess.add_argument("name", help="Agent name")

    # compact <name> [--conv <conv>] — trigger compaction
    p_comp = sub.add_parser("compact", help="Trigger session compaction")
    p_comp.add_argument("name", help="Agent name")
    p_comp.add_argument("--conv", "-c", dest="conv", required=True,
                        help="Conversation name to compact")

    # session delete <name> <conv> [--hard]
    p_sdel = sub.add_parser("session", help="Delete a session")
    p_sdel_sub = p_sdel.add_subparsers(dest="session_cmd")
    p_sdel_del = p_sdel_sub.add_parser("delete", help="Delete a session")
    p_sdel_del.add_argument("name", help="Agent name")
    p_sdel_del.add_argument("conv", help="Conversation name")
    p_sdel_del.add_argument("--hard", action="store_true",
                            help="Also delete session file (not just stop subprocess)")

    # forward <name> <method> <path>
    p_fwd = sub.add_parser("forward", help="Forward raw HTTP to agent")
    p_fwd.add_argument("name", help="Agent name")
    p_fwd.add_argument("method", help="HTTP method (GET/POST/PATCH/DELETE)")
    p_fwd.add_argument("path", help="AgentServer path (e.g. /status)")
    p_fwd.add_argument("--data", "-d", default=None, help="Request body")

    # files <name> <subcmd> <path>
    p_files = sub.add_parser("files", help="Access agent workspace files")
    p_files.add_argument("name", help="Agent name")
    p_files.add_argument("subcmd", choices=["get", "put", "delete", "ls", "edit"], help="Subcommand")
    p_files.add_argument("path", help="Path relative to workspace (e.g. AGENTS.md, .pi/skills/)")
    p_files.add_argument("--content", "-c", default=None, help="File content for 'put'")
    p_files.add_argument("--from", dest="from_file", default=None, help="Read content from file")

    # snapshot <name> [output]
    p_snap = sub.add_parser("snapshot", help="Snapshot agent workspace to .tar.gz")
    p_snap.add_argument("name", help="Agent name")
    p_snap.add_argument("output", nargs="?", help="Output path (default: <name>-snapshot.tar.gz)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "register":
        metadata = None
        if args.metadata:
            try:
                metadata = json.loads(args.metadata)
            except json.JSONDecodeError:
                print(f"[agentia] --metadata must be valid JSON")
                return 1
        return cmd_register(args.url, args.name, metadata)

    if args.command == "agents":
        return cmd_agents()

    if args.command == "send":
        message = " ".join(args.message) if args.message else ""
        return cmd_send(args.name, message, conv=getattr(args, "conv", None),
                         new_conv=getattr(args, "new", False))

    if args.command == "sessions":
        return cmd_sessions_list(args.name)

    if args.command == "compact":
        return cmd_compact(args.name, args.conv)

    if args.command == "session":
        if args.session_cmd == "delete":
            return cmd_session_delete(args.name, args.conv, args.hard)
        parser.print_help()
        return 1

    if args.command == "status":
        return cmd_status(args.name)

    if args.command == "configure":
        return cmd_configure(args.name, args.key, args.value)

    if args.command == "update":
        return cmd_update(args.name, args.role_goal, args.backstory, args.skills or [])

    if args.command == "deregister":
        return cmd_deregister(args.name)

    if args.command == "prune":
        return cmd_prune()

    if args.command == "forward":
        return cmd_forward(args.name, args.method.upper(), args.path, args.data)


    if args.command == "files":
        content = None
        if args.from_file:
            content = Path(args.from_file).read_text()
        elif args.content:
            content = args.content
        return cmd_files(args.name, args.subcmd, args.path, content)

    if args.command == "snapshot":
        return cmd_snapshot(args.name, args.output)



if __name__ == "__main__":
    sys.exit(main())
