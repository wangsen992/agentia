# Agentia tests

Current product-surface tests live here.

## Run

Use the standard library test runner so the suite works even when `pytest` is not installed:

```bash
python3 -m unittest -v \
  tests/test_current_surface.py \
  tests/test_host_cli_e2e.py \
  tests/test_more_cli_and_api.py \
  tests/test_agentserver_endpoints.py
```

## Purpose

These tests target the current user-facing surface:
- host conversation command semantics
- smart-router active conversation bookkeeping
- session deletion by resolved title
- file PUT created-vs-updated semantics
- host CLI end-to-end flows against a lightweight fake AgentServer (`register`, `agents`, `status`, `configure`, `sessions`, `send`, `compact`, `session delete`, `files`)
- coverage for `snapshot`, `clean`, and `prune`
- direct API-level check for file path traversal protection in `AgentServerHandler._handle_files`
- in-process AgentServer handler tests for `/status`, `/config`, `/sessions`, session messaging, deletion, and file PUT/GET flows

Legacy relay/moderator tests at repo root are not sufficient coverage for the current host/server/session architecture.
