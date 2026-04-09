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


# ─── Registry ────────────────────────────────────────────────────────────────

def _load_registry(path: Path = DEFAULT_REGISTRY) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 1, "agents": {}}


def _save_registry(data: dict, path: Path = DEFAULT_REGISTRY):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


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


def cmd_send(name: str, message: str) -> int:
    """Send a message to an agent. Blocks until response."""
    print(f"[agentia] Sending to '{name}'...")
    response = _http_post(name, "/message", {"content": message}, timeout=120)
    if not response:
        return 1
    content = response.get("content", response.get("stdout", ""))
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
        return cmd_send(args.name, message)

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
