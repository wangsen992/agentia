# Agent Provision Tool — SPEC 007.2

## Purpose

A CLI tool (`provision.py`) that provisions a new agent container end-to-end:
1. Generates or loads agent framework identity/config
2. Sets up workspace files from template (AGENTS.md, SOUL.md, etc.)
3. Starts the container with all mounts
4. Returns the container ready to receive messages via inbox

## Key Architectural Property: Framework-Agnostic

The provision tool is the **adapter layer** between agentia and any agent framework. The relay/inbox doesn't know or care what's inside the container — it just sends JSON Lines messages. The provision tool handles framework specifics.

```
agentia relay/inbox
        ↑ messages (JSON Lines)
        │
   ┌─────┴─────┐
   │  Container │
   │  ┌──────┐ │
   │  │ Inbox │ │  ← framework-agnostic interface
   │  │Poller │ │
   │  └──────┘ │
   │  ┌──────┐ │
   │  │ Agent │ │  ← OpenClaw, Claude, Llama, etc.
   │  │Framework│ │
   │  └──────┘ │
   └──────────┘
        ↑ provision.py handles framework specifics
```

**What changes per framework:**
- OpenClaw: generate `.openclaw/` identity files, run gateway
- Claude: set ANTHROPIC_API_KEY, configure via `~/.claude/`
- Llama: download model, set OLLAMA_HOST
- Generic: just mount workspace, framework is pre-baked in image

**What stays the same:** workspace layout, inbox interface, container startup, teardown.

## Mental Model

**Container = ephemeral unit. Identity + workspace = baked in at provision time.**

```
provision.py analyst "You are the Analyst"
  → generates ~/.openclaw/analyst/
  → creates /tmp/agentia/workspaces/analyst/ from template
  → starts container with all mounts
  → pairs agent to gateway
  → returns: container running, agent ready
```

On restart: re-run the same command, identity is reused.

On teardown: delete the container and optionally clean up identity/workspace.

## Command Interface

```bash
python3 provision.py create <agent-id> <role> [options]

Options:
  --role TEXT              Agent persona (analyst, critic, synthesizer, ...)
  --workspace-dir DIR      Host directory for workspace mount [default: /tmp/agentia/workspaces/<agent-id>]
  --openclaw-dir DIR       Host directory for .openclaw mount [default: /tmp/agentia/openclaw/<agent-id>]
  --inbox-dir DIR           Host shared inbox dir [default: /tmp/agentia/inbox]
  --image NAME              Docker image [default: agentia]
  --no-cleanup             Don't clean up partial failures
  --teardown               Tear down existing agent instead of creating

Examples:
  python3 provision.py create analyst "You are the Analyst"
  python3 provision.py create critic "You are the Critic" --workspace-dir /data/critic
  python3 provision.py teardown analyst
```

## Provisioning Workflow (create)

### Step 1: Prepare directories

```
/tmp/agentia/
├── inbox/
│   ├── analyst.jsonl
│   └── critic.jsonl
├── workspaces/
│   └── analyst/          ← created from template
│       ├── AGENTS.md
│       ├── SOUL.md
│       ├── IDENTITY.md
│       ├── USER.md
│       ├── TOOLS.md
│       ├── MEMORY.md
│       └── memory/
└── openclaw/
    └── analyst/          ← created by OpenClaw gateway
        ├── identity.json
        └── agents/
```

### Step 2: Generate or load OpenClaw identity

**If `--openclaw-dir` is empty or doesn't exist:**
1. Start a temporary gateway container in "setup mode":
   ```bash
   docker run --rm \
     -v $OPENCLAW_DIR:/root/.openclaw \
     -e OPENCLAW_SETUP_MODE=1 \
     -e OPENCLAW_AUTO_PAIR=1 \
     agentia gateway --no-token &
   ```
2. Wait for gateway to generate identity files
3. Read the gateway URL from stdout or `gateway.json`
4. Kill the temporary container

**If `--openclaw-dir` already exists:**
- Skip — identity is already provisioned, reuse it

### Step 3: Build workspace from template

```bash
mkdir -p $WORKSPACE_DIR
cp -r workspaces/template/* $WORKSPACE_DIR/
# Customize per agent:
#   - Fill in SOUL.md with role description
#   - Copy role-specific AGENTS.md from templates/
```

### Step 4: Start the agent container

```bash
docker run -d --name agent-$AGENT_ID \
  --restart unless-stopped \
  -v $INBOX_DIR:/workspace/inbox \
  -v $WORKSPACE_DIR:/workspace \
  -v $OPENCLAW_DIR:/root/.openclaw \
  $IMAGE poller --agent-id $AGENT_ID --mode agent
```

### Step 5: Verify agent is ready

- Check container is running: `docker ps | grep agent-$AGENT_ID`
- Check inbox file exists: `$INBOX_DIR/$AGENT_ID.jsonl`

## Teardown Workflow

```bash
python3 provision.py teardown analyst

# Removes:
#   - container: agent-analyst
#   - workspace dir: /tmp/agentia/workspaces/analyst  (optional, --keep-state)
#   - openclaw dir: /tmp/agentia/openclaw/analyst     (optional, --keep-state)
```

## Workspace Template

```
workspaces/template/
├── SOUL.md          ← generic base persona
├── IDENTITY.md
├── USER.md          ← generic base
├── TOOLS.md         ← generic base
├── AGENTS.md        ← generic base
├── MEMORY.md
├── HEARTBEAT.md
└── memory/
```

**Agent-specific customization** — passed via `--role`:
- `SOUL.md` → role description injected into template
- `AGENTS.md` → role-specific instructions (analyst has research rules, critic has rebuttal rules)

## Open Questions

1. **Gateway pairing** — does the temporary gateway setup need a token? Can we auto-pair non-interactively?
2. **Role templates** — where do role-specific SOUL.md/AGENTS.md templates live? In `workspaces/roles/analyst.md`?
3. **Cleanup policy** — keep state by default, or clean up on teardown? Research suggests keeping state.
4. **Provision vs start** — should `create` also start the poller, or should there be a separate `start` command?

## What to Build

1. `provision.py` — the main CLI tool
2. `workspaces/template/` — the base workspace template
3. `workspaces/roles/` — role-specific template overrides (analyst.md, critic.md, etc.)
4. `Dockerfile` — already exists, may need `OPENCLAW_SETUP_MODE` env var support

## Relationship to SPEC 007 (End-to-End Test)

SPEC 007's integration test needs two running containers:
```bash
python3 provision.py create analyst "You are the Analyst, research-focused"
python3 provision.py create critic "You are the Critic, skeptical reviewer"

# Then run the moderator test
python3 test_moderator_inbox.py --topic "Is AI helpful?"
```
