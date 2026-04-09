#!/usr/bin/env python3
"""
agentia — Host-side CLI

Runs on the host machine. Discovers agents via HTTP, registers them locally,
and manages them through the AgentServer API.

Commands: register, agents, send, status, configure, update, deregister, forward
"""

import argparse
import json
import shutil
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
        return f'session-{time.strftime("%Y-%m-%dT%H-%M-%S")}'
    slug = re.sub(r'[^a-zA-Z0-9\s]', '', message.lower())
    slug = re.sub(r'\s+', '-', slug).strip('-')[:max_len]
    return slug or f'session-{time.strftime("%Y-%m-%dT%H-%M-%S")}'



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


def _conv_file(conv_id: str) -> Path:
    """Path to the conversation metadata file."""
    return _conv_base() / f"{conv_id}.jsonl"


def _load_conv(conv_id: str) -> dict:
    """Load a conversation record. Returns minimal default if missing."""
    path = _conv_file(conv_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "id": conv_id,
        "title": conv_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_active": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message_count": 0,
        "agent_name": "",
        "session_name": "",
        "status": "active",
        "context_pct": 0,
        "tags": [],
    }


def _save_conv(conv_id: str, data: dict):
    """Save a conversation record."""
    path = _conv_file(conv_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _upsert_conv_from_send(agent_name: str, conv_id: str, session_name: str,
                            message_count: int = 0, context_pct: int = 0,
                            status: str = "active"):
    """Create or update a Layer A conversation file after a send."""
    conv = _load_conv(conv_id)
    conv["id"] = conv_id
    conv["title"] = conv.get("title") or conv_id
    conv["last_active"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    conv["message_count"] = message_count
    conv["agent_name"] = agent_name
    conv["session_name"] = session_name
    conv["status"] = status
    conv["context_pct"] = context_pct
    _save_conv(conv_id, conv)


def _list_convs(agent_name: str | None = None) -> list[dict]:
    """List all conversations, optionally filtered by agent."""
    base = _conv_base()
    if not base.exists():
        return []
    convs = []
    for fp in base.glob("*.jsonl"):
        if fp.name.startswith("."):
            continue
        try:
            conv = json.loads(fp.read_text())
            if agent_name is None or conv.get("agent_name") == agent_name:
                convs.append(conv)
        except (json.JSONDecodeError, IOError):
            continue
    convs.sort(key=lambda c: c.get("last_active", ""), reverse=True)
    return convs


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
            _upsert_conv_from_send(
                agent_name, conv_to_use, session_name,
                message_count=response.get("message_count", 0),
                context_pct=response.get("context_pct", 0),
            )
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
                _upsert_conv_from_send(
                    agent_name, conv_to_use, session_name,
                    message_count=response.get("message_count", 0),
                    context_pct=response.get("context_pct", 0),
                )
                _set_active_conv(agent_name, conv_to_use, conv_to_use)
                return response

    # Step 4: Nothing available — create new "default" session
    conv_to_use = "default"
    response = _http_post(agent_name, "/sessions/new", {"name": conv_to_use}, timeout=10)
    if not response:
        print("[agentia] Session management unavailable, using legacy /message")
        return _http_post(agent_name, "/message", {"content": message}, timeout=120)

    actual_name = response.get("name", conv_to_use)
    response = _http_post(
        agent_name,
        f"/sessions/{actual_name}/message",
        {"content": message},
        timeout=120,
    )
    if response:
        _upsert_conv_from_send(
            agent_name, conv_to_use, actual_name,
            message_count=response.get("message_count", 0),
            context_pct=response.get("context_pct", 0),
        )
        _set_active_conv(agent_name, conv_to_use, actual_name)
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
            _upsert_conv_from_send(
                name, actual_name, actual_name,
                message_count=response.get("message_count", 0),
                context_pct=response.get("context_pct", 0),
            )
            _set_active_conv(name, actual_name, actual_name)
    elif conv:
        # Explicit conversation: create/resume then send
        session_info = _http_post(name, "/sessions/new", {"name": conv}, timeout=10)
        if not session_info:
            print(f"[agentia] Failed to create/resume session '{conv}'")
            return 1
        actual_name = session_info.get("name", conv)
        response = _http_post(name, f"/sessions/{actual_name}/message", {"content": message}, timeout=120)
        if not response:
            print(f"[agentia] Session '{conv}' was created but message delivery failed. "
                  f"The agent may be unavailable. Try --new to start fresh.")
            return 1
        _upsert_conv_from_send(
            name, conv, actual_name,
            message_count=response.get("message_count", 0),
            context_pct=response.get("context_pct", 0),
        )
        _set_active_conv(name, conv, actual_name)
    else:
        # Smart router: implicit conversation routing
        response = _smart_route(name, message, None)

    if not response:
        return 1
    content = response.get("response") or response.get("content") or response.get("stdout", "")
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
            # Check candidates in order; use shutil.which to avoid shell injection
            for candidate in ["code", "nano", "vim", "vi"]:
                if shutil.which(candidate):
                    # Add --wait flag only for VS Code
                    editor = f"{candidate} --wait" if candidate == "code" else candidate
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

        exe = editor.split()[0]
        print(f"[agentia] Opening in {exe}... (save & close to upload changes)")

        # Open in editor and wait — editor is already validated (shutil.which or $EDITOR)
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


# ─── Conv commands (Phase 2) ──────────────────────────────────────────────────

def cmd_conv_list(agent_name: str | None = None) -> int:
    """List all conversations, optionally filtered by agent."""
    convs = _list_convs(agent_name)
    if not convs:
        print("No conversations found." +
              (f" for agent '{agent_name}'" if agent_name else ""))
        return 0
    print(f"{'CONV ID':<40} {'AGENT':<25} {'STATUS':<8} {'MSGS':<5} {'%':<4} {'LAST ACTIVE':<20} TITLE")
    for c in convs:
        print(
            f"{c['id']:<40} "
            f"{c.get('agent_name', ''):<25} "
            f"{c.get('status', '?'):<8} "
            f"{c.get('message_count', 0):<5} "
            f"{c.get('context_pct', 0):<4} "
            f"{c.get('last_active', ''):<20} "
            f"{c.get('title', '')}"
        )
    return 0


def cmd_conv_show(conv_id: str) -> int:
    """Show full details of a conversation."""
    conv = _load_conv(conv_id)
    if conv.get("agent_name") == "":
        print(f"[agentia] Conversation '{conv_id}' not found.")
        return 0  # Not found is a valid query result, not an error
    print(f"ID:          {conv['id']}")
    print(f"Title:       {conv.get('title', '')}")
    print(f"Agent:       {conv.get('agent_name', '')}")
    print(f"Session:     {conv.get('session_name', '')}")
    print(f"Status:      {conv.get('status', '')}")
    print(f"Messages:    {conv.get('message_count', 0)}")
    print(f"Context:     {conv.get('context_pct', 0)}%")
    print(f"Tags:        {', '.join(conv.get('tags', []) or ['(none)'])}")
    print(f"Created:     {conv.get('created_at', '')}")
    print(f"Last active: {conv.get('last_active', '')}")
    return 0


def cmd_conv_rename(conv_id: str, title: str) -> int:
    """Rename a conversation."""
    conv = _load_conv(conv_id)
    if conv.get("agent_name") == "":
        print(f"[agentia] Conversation '{conv_id}' not found.")
        return 0  # Not found is a valid query result, not an error
    old_title = conv.get("title", "")
    conv["title"] = title
    _save_conv(conv_id, conv)
    print(f"Renamed '{conv_id}': '{old_title}' -> '{title}'")
    return 0


def cmd_conv_tag(conv_id: str, tags: list[str], clear: bool = False) -> int:
    """Tag a conversation (--clear to replace, otherwise append)."""
    conv = _load_conv(conv_id)
    if conv.get("agent_name") == "":
        print(f"[agentia] Conversation '{conv_id}' not found.")
        return 0  # Not found is a valid query result, not an error
    if clear:
        conv["tags"] = tags
    else:
        existing = set(conv.get("tags", []))
        for t in tags:
            existing.add(t)
        conv["tags"] = sorted(existing)
    _save_conv(conv_id, conv)
    print(f"Tags for '{conv_id}': {', '.join(conv['tags'])}")
    return 0


def cmd_conv_delete(conv_id: str) -> int:
    """Delete a conversation from the registry (does not touch agent session)."""
    path = _conv_file(conv_id)
    if not path.exists():
        print(f"[agentia] Conversation '{conv_id}' not found.")
        return 0  # Not found is a valid query result, not an error
    path.unlink()
    print(f"[agentia] Deleted conversation registry: {conv_id}")
    return 0


def cmd_conv_use(conv_id: str, agent_name: str) -> int:
    """Set active conversation for an agent (updates routing)."""
    conv = _load_conv(conv_id)
    if conv.get("agent_name") == "":
        print(f"[agentia] Conversation '{conv_id}' not found.")
        return 1
    session_name = conv.get("session_name", conv_id)
    _set_active_conv(agent_name, conv_id, session_name)
    print(f"[agentia] Active conversation for '{agent_name}' set to '{conv_id}'")
    return 0


# ─── Chat REPL (Phase 3) ───────────────────────────────────────────────────────

_from_ptk_imported = False


def cmd_chat(name: str, conv: str | None = None, new_conv: bool = False) -> int:
    """Interactive REPL for chatting with an agent.

    Uses prompt_toolkit for a proper TUI with:
    - Colored prompt showing agent + conversation
    - Up-arrow command history
    - Slash commands: /switch, /new, /sessions, /compact, /status, /conv, /help, /quit
    - Ctrl+C to interrupt
    """
    global _from_ptk_imported
    if not _from_ptk_imported:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.styles import Style
            from prompt_toolkit.shortcuts import clear
            _from_ptk_imported = True
        except ImportError:
            print("[agentia] prompt_toolkit not installed. Run: pip install prompt_toolkit")
            return 1
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.shortcuts import clear

    # ── State ──────────────────────────────────────────────────────────────
    current_agent_name = name
    current_conv_id: str | None = conv
    current_session_name: str | None = None

    # ── Verify agent ───────────────────────────────────────────────────────
    agent_info = _get_agent(name)
    if not agent_info:
        print(f"[agentia] Agent '{name}' not found.")
        return 1

    # ── Resolve initial conversation ──────────────────────────────────────
    if new_conv:
        current_conv_id = None
    elif conv:
        session_info = _http_post(name, "/sessions/new", {"name": conv}, timeout=10)
        if session_info:
            current_session_name = session_info.get("name", conv)
        else:
            print(f"[agentia] Failed to access conversation '{conv}'.")
            return 1
    else:
        active = _get_active_conv(name)
        if active:
            current_conv_id = active["conv_id"]
            current_session_name = active["session_name"]

    # ── History file ───────────────────────────────────────────────────────
    hist_dir = Path.home() / ".agentia" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_file = hist_dir / f"{name}.hist"

    # ── Style ──────────────────────────────────────────────────────────────
    style = Style.from_dict({
        "prompt": "ansigreen bold",
        "sep": "ansiblue",
        "error": "ansired bold",
        "info": "ansiblue",
    })

    HELP_LINES = [
        ("/switch <id>",  "Switch to a conversation"),
        ("/new <title>",  "Start a new conversation"),
        ("/sessions",     "List recent sessions for this agent"),
        ("/compact",     "Trigger compaction on current session"),
        ("/status",      "Show agent + session status"),
        ("/conv",        "Show current conversation info"),
        ("/clear",       "Clear the screen"),
        ("/help",        "Show this help"),
        ("/quit",        "Exit the REPL"),
    ]

    def make_prompt() -> str:
        c = current_conv_id or "(new)"
        return f"\n  Agent: {current_agent_name}  |  Conv: {c}\n  > "

    def send_message(message: str):
        """Send via smart router. Updates conversation state on success."""
        nonlocal current_conv_id, current_session_name
        response = _smart_route(name, message, None)
        if not response:
            print("[agentia] No response (agent may be unavailable).")
            return False
        resp_conv = response.get("conversation") or current_conv_id
        resp_count = response.get("message_count", 0)
        resp_ctx = response.get("context_pct", 0)
        if resp_conv and resp_conv != current_conv_id:
            current_conv_id = resp_conv
        if current_conv_id:
            _upsert_conv_from_send(
                name, current_conv_id,
                current_session_name or current_conv_id,
                message_count=resp_count,
                context_pct=resp_ctx,
            )
        content = response.get("response") or response.get("content") or ""
        if content:
            print(f"\n{content}\n")
        return True

    # ── Main loop ───────────────────────────────────────────────────────────
    print(f"[agentia] Chatting with '{name}'. Type /help for commands.\n")
    session = PromptSession(history=FileHistory(str(hist_file)))

    while True:
        try:
            user_input = session.prompt(make_prompt(), style=style).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[agentia] Exiting.")
            break

        if not user_input:
            continue

        # ── Slash commands ──────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=2)
            cmd = parts[0]
            arg1 = parts[1] if len(parts) > 1 else None

            if cmd in ("/quit", "/exit"):
                print("[agentia] Goodbye.")
                break

            if cmd == "/help":
                print("\nCommands:")
                for c, desc in HELP_LINES:
                    print(f"  {c:<16} {desc}")
                print()
                continue

            if cmd == "/clear":
                clear()
                continue

            if cmd == "/status":
                status = _http_get(name, "/status")
                if status:
                    print(f"  Agent:    {name}")
                    print(f"  Ready:   {'yes' if status.get('ready') else 'no'}")
                    print(f"  Model:   {status.get('model', '?')}")
                    uptime = status.get("uptime", 0)
                    print(f"  Uptime:  {uptime:.0f}s ({uptime/3600:.1f}h)")
                    print(f"  Conv:    {current_conv_id or '(new)'}")
                    print(f"  Session: {current_session_name or 'none'}")
                else:
                    print("[agentia] Could not reach agent.")
                continue

            if cmd == "/conv":
                if current_conv_id:
                    d = _load_conv(current_conv_id)
                    print(f"  ID:       {current_conv_id}")
                    print(f"  Title:    {d.get('title', '')}")
                    print(f"  Session:  {current_session_name or 'none'}")
                    print(f"  Messages: {d.get('message_count', 0)}")
                    print(f"  Context: {d.get('context_pct', 0)}%")
                    tags = d.get('tags', []) or []
                    print(f"  Tags:     {', '.join(tags) if tags else '(none)'}")
                else:
                    print("  No active conversation.")
                continue

            if cmd == "/sessions":
                sessions = _get_agent_sessions(name)
                if not sessions:
                    print("  No sessions.")
                else:
                    def _by_time(s): return s.get("last_active", "")
                    for s in sorted(sessions, key=_by_time, reverse=True)[:10]:
                        title = s.get("title") or s.get("name", "?")
                        sts = s.get("status", "?")
                        msgs = s.get("message_count", 0)
                        last = s.get("last_active", "?")[:19]
                        mark = " ←" if title == current_conv_id else ""
                        print(f"  {title:<35} [{sts}] {msgs:>3} msgs  {last}{mark}")
                continue

            if cmd == "/switch":
                if not arg1:
                    print("[agentia] Usage: /switch <conversation-id>")
                    continue
                d = _load_conv(arg1)
                if not d.get("agent_name"):
                    print(f"[agentia] Conversation '{arg1}' not found.")
                    continue
                new_sess = d.get("session_name", arg1)
                _set_active_conv(name, arg1, new_sess)
                current_conv_id = arg1
                current_session_name = new_sess
                print(f"[agentia] Switched to '{arg1}'.")
                continue

            if cmd == "/new":
                if not arg1:
                    print("[agentia] Usage: /new <title>")
                    continue
                slug = _slugify_message(arg1)
                si = _http_post(name, "/sessions/new", {"name": slug}, timeout=10)
                if not si:
                    print(f"[agentia] Failed to create conversation '{slug}'.")
                    continue
                actual = si.get("name", slug)
                # conv_id = slug (user-facing Layer A id), session_name = actual (Layer B session name)
                # Spec: .active/<agent>.jsonl stores {conv_id, session_name} per Layer A mapping
                _set_active_conv(name, slug, actual)
                _upsert_conv_from_send(name, slug, actual, message_count=0, context_pct=0)
                current_conv_id = slug
                current_session_name = actual
                print(f"[agentia] New conversation: '{slug}'.")
                continue

            if cmd == "/compact":
                if not current_session_name:
                    print("[agentia] No active session.")
                else:
                    r = _http_post(name, f"/sessions/{current_session_name}/compact",
                                   {"message": ""}, timeout=30)
                    if r:
                        print(f"[agentia] Compacted: "
                              f"{r.get('message_count_before','?')} msgs → "
                              f"{r.get('message_count_after','?')} msgs")
                    else:
                        print("[agentia] Compact failed.")
                continue

            print(f"[agentia] Unknown: {cmd}. Type /help.")
            continue

        # Regular message
        send_message(user_input)

    return 0


# ─── Prune ────────────────────────────────────────────────────────────────────

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

    # conv <subcommand> [<args>]
    p_conv = sub.add_parser("conv", help="Conversation management (Phase 2)")
    p_conv_sub = p_conv.add_subparsers(dest="conv_cmd", help="Conv subcommand")

    # conv list [--agent <name>]
    p_conv_list = p_conv_sub.add_parser("list", help="List conversations")
    p_conv_list.add_argument("--agent", default=None, help="Filter by agent name")

    # conv show <conv_id>
    p_conv_show = p_conv_sub.add_parser("show", help="Show conversation details")
    p_conv_show.add_argument("conv_id", help="Conversation ID")

    # conv rename <conv_id> --title <title>
    p_conv_rename = p_conv_sub.add_parser("rename", help="Rename a conversation")
    p_conv_rename.add_argument("conv_id", help="Conversation ID")
    p_conv_rename.add_argument("--title", required=True, help="New title")

    # conv tag <conv_id> [--clear] [tags...]
    p_conv_tag = p_conv_sub.add_parser("tag", help="Tag a conversation")
    p_conv_tag.add_argument("conv_id", help="Conversation ID")
    p_conv_tag.add_argument("--clear", action="store_true", help="Replace existing tags (default: merge with existing)")
    p_conv_tag.add_argument("tags", nargs="*", default=[], help="Tag(s) to add")

    # conv delete <conv_id>
    p_conv_del = p_conv_sub.add_parser("delete", help="Delete conversation from registry")
    p_conv_del.add_argument("conv_id", help="Conversation ID")

    # conv use <conv_id> --agent <name>
    p_conv_use = p_conv_sub.add_parser("use", help="Set active conversation for an agent")
    p_conv_use.add_argument("conv_id", help="Conversation ID")
    p_conv_use.add_argument("--agent", "-a", dest="agent_name", required=True, help="Agent name")

    # deregister <name>
    p_dereg = sub.add_parser("deregister", help="Remove agent from registry")
    p_dereg.add_argument("name", help="Agent name")

    # chat <name> [--conv <conv>] [--new] — interactive REPL
    p_chat = sub.add_parser("chat", help="Start an interactive REPL chat with an agent")
    p_chat.add_argument("name", help="Agent name")
    p_chat.add_argument("--conv", "-c", dest="conv", default=None,
                        help="Start in a specific conversation")
    p_chat.add_argument("--new", "-n", dest="new", action="store_true",
                        help="Start a new conversation")

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

    if args.command == "conv":
        sub = args.conv_cmd
        if sub == "list":
            return cmd_conv_list(getattr(args, "agent", None))
        if sub == "show":
            return cmd_conv_show(args.conv_id)
        if sub == "rename":
            return cmd_conv_rename(args.conv_id, args.title)
        if sub == "tag":
            return cmd_conv_tag(args.conv_id, args.tags, args.clear)
        if sub == "delete":
            return cmd_conv_delete(args.conv_id)
        if sub == "use":
            return cmd_conv_use(args.conv_id, args.agent_name)
        print("[agentia] Unknown conv subcommand. Run: agentia conv --help")
        return 1

    if args.command == "chat":
        return cmd_chat(args.name, conv=getattr(args, "conv", None),
                        new_conv=getattr(args, "new", False))

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
