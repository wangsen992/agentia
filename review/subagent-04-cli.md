# Code Review: CLI + Container Orchestration + Relay
**Reviewer:** Subagent-04
**Files Reviewed:**
- `agentia` (main CLI)
- `containers/start_agents.py`
- `examples/moderator.py`
- `relay/base.py`
- `relay/backends/base.py`
- `relay/backends/docker.py`
- `relay/backends/ssh.py`

---

## Summary

The CLI and relay layer are broadly functional but have several correctness bugs, design gaps, and missing pieces that would cause failures in production or concurrent scenarios. The most serious issues are: a race condition in port allocation, a config mount mismatch in `start_container`, and a missing import in `moderator.py` that prevents transcript saving from working at all.

---

## Per-File Analysis

### 1. `agentia` (Main CLI)

#### `_allocate_agent_port()` — lines 56–79

**TOCTOU race condition.** The function runs `docker ps` to check if a port is in use, then saves the port to config and returns it — but another process can allocate the same port between the check and the save. Two concurrent calls could return the same port. There is no file locking or atomic compare-and-swap.

**Line 71:** `config["next_port"] = port + 1` is saved even when the port was found occupied (the loop does `port += 1` and continues). This means the counter always advances, but not necessarily past an unoccupied port — it only advances within the `while` loop until an unoccupied port is found. This is actually correct behavior for the loop, but the race condition above undermines it.

**Line 59–61:** The `docker ps --format "{{.Ports}}"` check only looks at Docker's port mappings. If a non-Docker process is using a host port, this returns a false negative (port appears free in Docker but is actually in use). Also, this approach does not account for ports allocated by `start_agents.py` which uses a different port (18789).

**No concurrency protection:** The registry is a JSON file. Multiple concurrent `agentia create` calls all read/write the same file with no locking.

---

#### `DockerAdapter.start_container()` — lines 240–286

**Critical: Config mount mismatch (line 280).** The container config file is written to `container_dir / "config" / "agent.json"` on the host. This directory is mounted as `-v {container_config_dir}:/etc/agentia` at line 280. Inside the container, the env `AGENTIA_CONFIG=/etc/agentia/agent.json` points to a *file* at `/etc/agentia/agent.json`, but the mount is a *directory* at `/etc/agentia`. Docker mounts a directory over a directory, not a file into a file — so the container sees the *content* of the host's `container_config_dir/` directory at `/etc/agentia/`, but the file `agent.json` may not exist there (it would be at `/etc/agentia/config/agent.json` from the container's perspective if the mount overlays correctly). This almost certainly means AgentServer starts without the config file.

**Line 276–278:** The inbox is mounted twice redundantly:
```python
-v {inbox_str}:/workspace/inbox
-v {inbox_str}/responses:/workspace/inbox/responses
```
The second line is a strict subset of the first. The nested `responses/` directory is already covered by the first mount. This is harmless but misleading.

**Line 273:** `--network bridge` uses Docker's default bridge network. Containers on the default bridge cannot resolve each other by hostname — only via `--link` (deprecated) or IP. If two agent containers need to communicate (e.g., relay between them), they cannot via DNS. Should use a user-defined bridge network.

**Line 268:** `inbox_file.touch(exist_ok=True)` creates the inbox file but it is never mounted directly — only the directory containing it is mounted. This is fine, but the file must be created before the container starts or the mount will shadow it with an empty directory entry.

**Port not re-persisted on restart:** `start_existing_container()` (line 305) does not re-allocate or verify the port. If the container was destroyed externally and the port is stale, no error is raised.

---

#### `cmd_agentserver()` — lines 167–175

**Line 173:** `os.execvp("python3", ["python3", "/workspace/agent_side/server.py"])` — the path `/workspace/agent_side/server.py` is hardcoded inside the container's filesystem. This function is intended to run *inside* a container (it's called `agentserver` subcommand), so this path only works because `/workspace` is the container's working dir. However, the `AGENTIA_CONFIG` env var is read but not passed anywhere — the `os.execvp` call ignores all environment. If AgentServer respects `AGENTIA_CONFIG`, it should be injected via `-e` in the Dockerfile or entrypoint.

**Line 174:** `cmd_agentserver()` returns nothing (implicitly `None`). The `main()` function treats this as `1` (error) because `return None` is falsy. This is fine behavior but non-obvious.

---

#### `cmd_create()` — lines 415–462

**Line 440:** Template rendering failure is caught and printed, but then `start_container()` is called anyway with whatever config was there before (or an empty `container.json`). The container will start with the agent defaults rather than the rendered config. This is a silent failure — the user is not told the agent won't have their custom config.

**Line 451:** `adapter_cli.start_container()` is called *after* `create_container()` — the container status is set to "running" inside `start_container()`. But if `start_container()` throws (e.g., Docker fails to start), the registry still has status "created" from `create_container()`. There is no try/except rollback.

**Missing `--template` for `cmd_create`:** The `--template` arg is defined in the argparser (line 499) but never passed to `create_container()` or used in `cmd_create()`. The `workspace_template` field in `create_container()` is always `None`.

---

#### `cmd_install()` — lines 141–163

**Line 149:** `install_sh` runs with `workspace` as `$1` and `config_path` as `$2`. But `workspace` here is the CLI `--workspace` argument (default `/workspace`), not the actual container workspace path. If the adapter's `install.sh` script expects the host path, this works. If it expects the in-container path, it's wrong.

---

### 2. `containers/start_agents.py`

#### `start_agent()` — lines 36–63

**Line 55:** Port mapping is `f"{port}:18789"` but the gateway inside the container is expected on port 18789 (the internal port). This is correct as stated — host port to container internal port. However, `wait_for_gateway()` (line 66–80) checks `http://localhost:{port}/` expecting an HTTP 200. This assumes the gateway serves HTTP on that port inside the container. If the gateway inside the container listens on a different port, this will fail silently.

**Line 47–49:** `docker kill` then `docker rm -f` is run sequentially. If `kill` fails (container already stopped), `rm -f` still runs. This is fine, but there's a brief window where the name is unregistered, then re-registered. If two processes call this simultaneously for the same index, they could conflict.

**No network creation:** All containers are started without a shared Docker network. If agents need to communicate with each other via hostnames, they can't. Should create a shared network (e.g., `agentia-net`) and attach all containers to it.

**Line 55:** Uses `image` parameter but the entrypoint is `"gateway"` — there's no verification that the Docker image has a `gateway` entrypoint or command. If the image's CMD is different, this silently does nothing useful.

---

### 3. `examples/moderator.py`

#### `save_transcript()` — lines 157–175

**Missing `Path` import (line 157).** `Path(path)` is called but `Path` is not imported. This will raise `NameError: name 'Path' is not defined` at runtime. The `print()` call and file writing will fail. This is a simple fix but it means the example's `save_transcript()` method is completely broken.

**Fix:** Add `from pathlib import Path` at the top, or change line 157 to use `pathlib.Path(path)` explicitly.

---

#### `Moderator._send_to_agent()` — lines 122–125

**No timeout handling.** `backend.send_message()` can return `None` on timeout (see `DockerBackend.send_message()`), but `_send_to_agent()` returns `""` for both "success with empty response" and "complete failure". Callers cannot distinguish them. In `run()` loop, an empty string is recorded as a valid response and the conversation continues silently.

---

#### `Moderator` overall

**`to_agents` field not used.** The `Moderator` class always sends to a single agent at a time via `send_message(msg, agent_id)`. It never uses `RelayMessage.to_agents` for fan-out. The `broadcast()` method on the backend is implemented but never called from the Moderator.

**`context_policy="sequential"` not implemented.** The config supports `topology: sequential` but the `_next_agent()` method simply rotates through agents in order — it doesn't support round-robin, priority, or dependency-based ordering.

---

### 4. `relay/base.py`

#### `RelayMessage` — lines 16–38

**`to_agents` is defined but AgentServer may not handle it.** `to_agents: Optional[list[str]]` is in the dataclass but the backends use `message.to_agents or []` which means it's passed as an empty list if `None`. AgentServer's inbox processor would need to understand this field for fan-out to work. There is no documentation or server-side definition visible in this review scope.

**`metadata` field is `Optional[dict]` but never validated.** The backends do not forward `metadata` in the HTTP payload — `DockerBackend.send_message()` builds its payload as:
```python
payload = {
    "content": message.content,
    "from_agent": message.from_agent or "moderator",
    "correlation_id": correlation_id,
}
```
`message.metadata` is dropped entirely. Any semantic information (e.g., `{"type": "system"}`) set by `Moderator.setup()` (line 72 of moderator.py) is lost before it reaches AgentServer.

**No schema validation.** `RelayMessage.to_json()` serializes arbitrary dicts in `metadata`. If `metadata` contains non-JSON-serializable values, this will fail at the relay layer with no clear error.

---

### 5. `relay/backends/base.py`

#### `HostContainerBackend` interface — lines 29–84

**`poll_response()` return type is `Optional[dict]` but backends return `dict` or `None`.** The docstring says "Response dict with content, from_agent, timestamp", but there's no enforcement that these fields are present. A backend could return `{"foo": "bar"}` and the caller would not know.

**`discover()` returns `list[str]` of agent_ids, but there's no way to discover agents dynamically.** The backends only return the statically configured endpoints. No mechanism for AgentServer to advertise itself to the host.

---

### 6. `relay/backends/docker.py`

#### `DockerBackend.send_message()` — lines 56–83

**The comment says "block until agent finishes" but the implementation is fire-and-forget.** The code makes a single `POST /message` call and waits for the HTTP response. This is only a true blocking wait if AgentServer itself blocks the HTTP request until the agent has finished processing. If AgentServer queues the message and returns immediately (similar to `send_message_async`), the `send_message` caller will get a quick "queued" response, not the actual agent output. The semantic difference between `send_message` and `send_message_async` is not enforced at the relay level — it depends entirely on AgentServer's behavior, which is not defined in this codebase.

**No session reuse.** Each `requests.post()` call creates a new TCP connection. For high-frequency messaging (e.g., Moderator running 6 turns with multiple agents), this adds unnecessary overhead. A `requests.Session()` would enable connection pooling.

**`correlation_id` is not returned to the caller of `send_message()`.** The `message.correlation_id` is set on the object, but the caller of `send_message()` has no way to retrieve it to correlate with a later `poll_response()` call. The `correlation_id` on the `RelayMessage` object is mutated in-place but the method returns only the content string.

---

#### `DockerBackend.poll_response()` — lines 99–127

**Polling logic has a bug at line 113.** After a non-404 error (e.g., 500), `last_error` is set and the loop continues — but it keeps polling with the same `last_error` message forever. A 500 error means the endpoint exists but is broken. Polling it repeatedly until timeout is not useful. The loop should distinguish 404 (still processing) from 5xx (error) and break early on unrecoverable errors.

---

#### `DockerBackend.broadcast()` — lines 130–151

**Uses `POST /message` not `POST /message/async`.** Each agent's response is waited for serially, blocking the entire broadcast. If one agent is slow, the whole broadcast hangs. For a true fan-out broadcast, this should use `send_message_async` for each agent and collect results via `poll_response()` — or at minimum use `async` endpoints. As written, broadcast is O(n) blocking time, not O(1).

---

### 7. `relay/backends/ssh.py`

#### `SSHBackend._ssh_url()` — lines 56–60

**URL parsing bug with `ssh://` prefix.** If `endpoint.host` is already `ssh://user@host`, calling `self._ssh_url(endpoint)` returns it unchanged (line 58: `if "://" in host: return host`). Then in `_run_ssh()` (line 64), the ssh host is extracted as:
```python
ssh_host = host.replace("ssh://", "").replace("http://", "").replace("https://", "")
```
This strips the protocol but leaves `user@host` intact, which is correct for SSH. However, if `endpoint.host` is `ssh://user@host` and `ssh_user` is also set (e.g., "root"), the resulting command would be `ssh user@host` with the default user overridden by the URL — which is fine. But the real issue is the inconsistency: sometimes `endpoint.host` contains the user (`ssh://user@host`), sometimes it doesn't and `_ssh_user` is prepended. This is fragile.

**More critically: `_ssh_url()` with `ssh://user@host` format returns `ssh://user@host`, then `_run_ssh()` strips `ssh://` to get `user@host`. The SSH command becomes `ssh user@host ...`. This works only if the SSH key/agent is set up for that user on that host. But if the endpoint was created with `AgentEndpoint("agent-a", "ssh://user@host", 8080)` and `_ssh_user = "root"`, there's no way to use the URL-embedded user — the `_ssh_user` field is ignored when a URL is present.**

**Line 62:** `full_cmd = ["ssh", ssh_host] + curl_cmd` — the SSH command has no `-o StrictHostKeyChecking=no` or `-o UserKnownHostsFile=/dev/null`. First connection to a new host will hang waiting for host key confirmation, with no interactive TTY available in this context.

**Line 62:** No `-o ConnectTimeout` is set. If the SSH connection hangs, `_run_ssh()` will block for the full `timeout` (which could be 60 seconds for `send_message`). This is a poor user experience.

---

## Top 5 Actionable Findings

### Finding 1: **[BUG — `start_container()`]** Config mount is broken (line 280)

**File:** `agentia`, line 280  
**Problem:** `container_config_dir` (a host path) is mounted to `/etc/agentia` (a directory mount). The config file is written to `{container_config_dir}/agent.json` on the host, but `AGENTIA_CONFIG=/etc/agentia/agent.json` in the container expects the file at `/etc/agentia/agent.json`. Docker overlay-mounts the *directory*, so the file is at `/etc/agentia/config/agent.json` inside the container — not where AgentServer looks.

**Fix:** Mount the config file directly: `-v {container_config_file}:/etc/agentia/agent.json:ro`. Or set the env var to `/etc/agentia/config/agent.json` and mount the parent dir.

---

### Finding 2: **[BUG — `_allocate_agent_port()`]** Race condition / non-Docker port false negatives

**File:** `agentia`, lines 56–79  
**Problem:** `docker ps` only checks Docker port mappings, not host-level port usage. A non-Docker process on the host port will not be detected. Additionally, two concurrent calls can both see the same port as free and allocate it.

**Fix:** Use `ss -tlnp` or `netstat` to check actual host-level port binding, not just Docker's view. Add a file lock around the read-check-write cycle using `fcntl.flock()` on the registry file, or switch to an atomic allocate-and-claim approach (allocate, immediately try to bind, rollback if fail).

---

### Finding 3: **[BUG — `moderator.py`)]** `Path` not imported, `save_transcript()` always fails

**File:** `examples/moderator.py`, line 157  
**Problem:** `Path(path)` is called but `Path` is not in scope. Any call to `save_transcript()` raises `NameError`.

**Fix:** Add `from pathlib import Path` at the top of the file.

---

### Finding 4: **[BUG — `DockerBackend`)]** `poll_response()` keeps polling on HTTP 500 errors

**File:** `relay/backends/docker.py`, lines 110–116  
**Problem:** After a 500 response, `last_error` is set and polling continues for the full timeout. A 500 is a server error, not "still processing" — polling will not help.

**Fix:** Break out of the loop on non-404, non-200 responses. Only 404 means "not ready yet, keep polling." Anything else is an error condition and should be returned/failed immediately.

---

### Finding 5: **[BUG — `DockerBackend`)]** `metadata` field in `RelayMessage` is silently dropped

**File:** `relay/backends/docker.py`, line 70–74  
**Problem:** `message.metadata` (e.g., `{"type": "system"}` set by `Moderator.setup()`) is never forwarded to AgentServer. The payload only contains `content`, `from_agent`, and `correlation_id`. AgentServer cannot distinguish system messages from user messages based on this relay.

**Fix:** Include `metadata` in the payload dict, e.g.:
```python
payload = {
    "content": message.content,
    "from_agent": message.from_agent or "moderator",
    "correlation_id": correlation_id,
    "metadata": message.metadata or {},
}
```

---

## Additional Findings (Lower Priority)

| # | Location | Issue |
|---|----------|-------|
| 6 | `agentia:261` | `--network bridge` should be a user-defined network for inter-container DNS |
| 7 | `agentia:440` | Template rendering failure is silent — agent starts with no custom config |
| 8 | `agentia:173` | `os.execvp` ignores the `AGENTIA_CONFIG` env var that was read above it |
| 9 | `relay/backends/ssh.py:62` | SSH command lacks `-o StrictHostKeyChecking=no` — first-connect will hang |
| 10 | `moderator.py:122` | `_send_to_agent()` conflates timeout failure with empty response |
| 11 | `relay/backends/docker.py:145` | `broadcast()` does serial blocking `POST /message` instead of async fan-out |
| 12 | `agentia:451` | `start_container()` can throw after status is set to "created", no rollback |
| 13 | `relay/backends/docker.py:62` | No `requests.Session()` reuse — TCP connection overhead per call |
| 14 | `start_agents.py:55` | `"gateway"` entrypoint not validated against the image before running |
