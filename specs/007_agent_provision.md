# Agentia Agent Registry and Provision Tool — SPEC 007.2 (Revised)

## Overview

agentia provisions and manages agent **instances** (containers) from agent **templates** (images), organized like Docker:

| Docker concept | agentia concept |
|---------------|-----------------|
| Image | Agent template — workspace config + role definition + framework config |
| Container | Running/stopped agent instance — image + identity + state |
| Registry | `~/.agentia/` directory |
| Daemon | `provision.py` CLI — the agent runtime |

## Registry Structure

```
~/.agentia/
├── config.toml              # agentia global config
├── registry.json            # index: known images, containers
├── images/
│   ├── analyst/
│   │   ├── VERSION          # "latest" or "v1.0"
│   │   ├── role.md          # SOUL.md override
│   │   ├── workspace/       # files that go into /workspace/
│   │   │   ├── AGENTS.md
│   │   │   ├── TOOLS.md
│   │   │   └── ...
│   │   └── framework.json   # { "type": "openclaw", "setup": "..." }
│   ├── critic/
│   └── synthesizer/
└── containers/
    ├── analyst-001/
    │   ├── container.json   # { "container_id": "analyst-001", "image": "analyst", "status": "running" }
    │   ├── workspace/       # the actual workspace (may be modified from image)
    │   ├── openclaw/       # generated identity (for openclaw type)
    │   └── state/          # runtime state (logs, memory snapshots, etc.)
    └── critic-001/
```

## The Agentia Interface (Uniform)

Every agent instance implements this interface, regardless of transport:

```python
class AgentInstance:
    def create(image_name: str, agent_id: str) -> AgentInstance
        """Instantiate a new container from an image."""

    def start() -> None
        """Start the agent (provisions identity, starts gateway/poller)."""

    def stop() -> None
        """Stop the agent gracefully."""

    def destroy() -> None
        """Stop and delete all state (workspace, identity, state/)."""

    def send(message: str) -> str
        """Send a message, return the response."""

    def status() -> AgentStatus
        """Returns: running | stopped | error | unknown"""
```

The `AgentInstance` interface is implemented by **adapters** — one per transport:

```python
# adapters/docker.py      — local Docker container (current implementation)
# adapters/ssh.py         — SSH to remote cloud VM (future)
# adapters/local.py       — local subprocess (future)
# adapters/anthropic.py   — Anthropic Claude API (future)
```

## Adapter Interface

```python
class AgentAdapter(ABC):
    """Translates AgentInstance calls to the actual transport."""

    @abstractmethod
    def create(self, image: ImageDef, agent_id: str, target: str) -> None:
        """
        Create (but do not start) an agent instance.
        Args:
            image: image definition
            agent_id: unique instance name
            target: transport-specific target (e.g. "analyst-001" for docker)
        """

    @abstractmethod
    def start(self, agent_id: str) -> None:
        """Start the agent — provisions identity, starts listening."""

    @abstractmethod
    def stop(self, agent_id: str) -> None:
        """Stop the agent gracefully."""

    @abstractmethod
    def destroy(self, agent_id: str) -> None:
        """Delete all instance state."""

    @abstractmethod
    def send_message(self, agent_id: str, message: str) -> str:
        """Send a message, return the response."""

    @abstractmethod
    def status(self, agent_id: str) -> AgentStatus:
        """Check if the agent is running."""
```

## Image Management

```bash
# List available images
agentia image list

# Pull an image from a registry (future)
agentia image pull analyst

# Build a new image from a workspace template
agentia image build analyst --from workspaces/roles/analyst

# Inspect an image
agentia image inspect analyst
```

## Container Lifecycle

```bash
# Create + start a new agent from an image
agentia create analyst analyst-001
# Equivalent to: docker run -d --name agent-analyst-001 ...

# List running agents
agentia ps

# List all agents (including stopped)
agentia ps -a

# Stop an agent
agentia stop analyst-001

# Start a stopped agent
agentia start analyst-001

# Destroy an agent (irreversible)
agentia destroy analyst-001

# Send a message to an agent (CLI)
agentia exec analyst-001 "What is the status of the project?"
```

## Image Definition

An image is defined by:

```
images/<name>/
├── VERSION          — version string (latest, v1, etc.)
├── role.md         — SOUL.md content to inject
├── workspace/      — files copied into /workspace/
│   ├── AGENTS.md
│   ├── TOOLS.md
│   └── ...
└── framework.json   — framework-specific config
    {
        "type": "openclaw",
        "setup": {
            "identity_required": true,
            "gateway_required": true
        }
    }
```

## Container Definition

A container is defined by:

```
containers/<agent-id>/
├── container.json   — metadata (image ref, status, created_at)
├── workspace/       — the agent's workspace (from image, may be modified)
├── openclaw/       — identity directory (openclaw type only)
└── state/          — runtime artifacts
    ├── logs/
    ├── memory/
    └── sessions/
```

## Framework-Specific Notes

### OpenClaw

- Identity provisioned by running a temporary gateway container
- Identity stored in `containers/<id>/openclaw/`
- Adapter: `adapters/docker.py` (current implementation in `adapters/openclaw.py`)

### SSH (future)

- Target: `user@host:port` instead of container name
- Adapter: `adapters/ssh.py`
- Workspace synced via rsync or SFTP

### Anthropic Claude API (future)

- No container needed — direct API calls
- Adapter: `adapters/anthropic.py`
- Identity = API key

## CLI Interface (Revised)

```bash
# Image management
agentia image list
agentia image build <name> [--from <workspace-template>] [--role <role-name>]
agentia image inspect <name>
agentia image rm <name>

# Container management
agentia create <image> <agent-id>   # create + start
agentia ps [-a]                      # list containers
agentia start <agent-id>
agentia stop <agent-id>
agentia restart <agent-id>
agentia destroy <agent-id>
agentia inspect <agent-id>

# Interact
agentia exec <agent-id> <message>    # send message, print response
agentia logs <agent-id>               # tail container logs
agentia attach <agent-id>            # interactive REPL

# Registry
agentia registry info                # show ~/.agentia/ structure
```

## Why This Design

1. **Transport-agnostic** — the agentia interface doesn't care if an agent is a local Docker container, an SSH'd cloud VM, or an API. The adapter handles the translation.

2. **Images are templates** — you create N containers from the same image, each with its own identity and workspace modifications.

3. **Registry is explicit** — everything is on disk in `~/.agentia/`, no hidden state.

4. **Composable with inbox patterns** — the Moderator uses `InboxRelay` to send messages. The InboxRelay uses `agentia exec` under the hood, which goes through the adapter. So the moderator never knows or cares how the agent is actually running.

5. **Cloud-ready** — adding SSH support means agents can run on any machine you can SSH into, not just locally.

## What's Built (b72f19d)

The current `provision.py` is a partial implementation:
- `create` / `teardown` / `list` / `status` commands work
- `adapters/openclaw.py` handles Docker-based provisioning
- Workspace templates exist at `workspaces/template/` and `workspaces/roles/`

## What's Next

1. Refactor `provision.py` → `agentia` CLI with image + container subcommands
2. Add `container.json` metadata to each container
3. Add `agentia exec` command for sending messages
4. Add `framework.json` to images
5. Add SSH adapter stub (`adapters/ssh.py`) to show the pattern
