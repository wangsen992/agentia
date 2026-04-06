# Agent Workspace Configuration — SPEC 007.1 (Revised)

## The Hard Constraint

**Never mount over host `~/.openclaw/`** — never bind-mount the host's OpenClaw config into a container.

This means we cannot do:
```bash
# BAD — overwrites host ~/.openclaw with container content on exit
docker run -v ~/.openclaw:/root/.openclaw ...
```

## What Must Be Provisioned Per Container

```
/root/.openclaw/           ← OpenClaw config (identity, gateway URL, tokens)
/workspace/                ← Workspace files (AGENTS.md, SOUL.md, memory, etc.)
```

## Strategy: Isolated Per-Agent Directories on Host

Store each agent's OpenClaw config in an **isolated host directory**, not in `~/.openclaw/`:

```
Host filesystem:
/tmp/agentia/
├── inbox/                    ← shared inbox (as before)
├── workspaces/
│   └── analyst/            ← analyst's workspace mount
│       ├── AGENTS.md
│       ├── SOUL.md
│       └── memory/
└── openclaw/
    └── analyst/             ← analyst's OpenClaw config (isolated)
        ├── identity.json
        └── agents/
            └── main/
                └── agent/
                    └── gateway.json   ← paired gateway URL

Container filesystem:
/root/.openclaw/   ← mounted from /tmp/agentia/openclaw/analyst/
/workspace/        ← mounted from /tmp/agentia/workspaces/analyst/
```

## Key Properties

- **No conflict with host `~/.openclaw/`** — we use a separate directory
- **Identity persists across container restarts** — gateway.json and identity.json survive
- **No shared state** — each agent has its own identity and paired gateway
- **Clean teardown** — just delete `/tmp/agentia/` if you want to reset

## Container Startup

```bash
AGENT_ID=analyst
WORKSPACE_DIR=/tmp/agentia/workspaces/analyst
OPENCLAW_DIR=/tmp/agentia/openclaw/analyst

docker run -d --name agent-$AGENT_ID \
  -v /tmp/agentia/inbox:/workspace/inbox \
  -v $WORKSPACE_DIR:/workspace \
  -v $OPENCLAW_DIR:/root/.openclaw \
  agentia poller --agent-id $AGENT_ID --mode agent
```

## First Run: Provisioning

On first run, the container needs to:
1. Generate a new identity (`openclaw gateway` does this)
2. Start the gateway and get the gateway URL
3. Save gateway.json to `/root/.openclaw/agents/main/agent/gateway.json`
4. All subsequent runs reuse this identity and gateway URL

**Option A — Provision once, reuse:** Run the container once in a "setup" mode that provisions and then the identity is persisted in the mount.

**Option B — Fresh each time:** Accept that each container starts with a fresh identity. Fine for some use cases, bad for research memory continuity.

**Recommendation: Option A** — run once with a setup harness that provisions identity, then use the persisted mount for all subsequent runs.

## Open Question

What is the "setup" harness that provisions the OpenClaw identity? This could be:
1. A new `setup` harness mode that runs `openclaw gateway`, saves the config, then exits
2. Or the `gateway` harness itself provisions on first run and the gateway stays running

For the container model where each agent runs its own gateway, Option 2 is cleaner — each container runs its own gateway and pairs to it.

## What's Still Unresolved

1. **Third-party tool configs** — e.g., Zotero credentials, YNAB tokens. These are currently on the host in `~/.config/` or similar. Mounting those into containers is also risky (different OS paths, could conflict).
   - Options: environment variables at container run, or per-container config files on host

2. **Who provisions the workspace** — should be a script `workspaces/setup.py` that creates from template and customizes per-agent. Not manual.

3. **The `setup` harness** — needs to be built so the first-run provisioning is automatic.

## Summary of Mounts Per Container

```bash
-v /tmp/agentia/inbox:/workspace/inbox       # shared, all agents
-v /tmp/agentia/workspaces/$AGENT:/workspace # per-agent workspace
-v /tmp/agentia/openclaw/$AGENT:/root/.openclaw  # per-agent OpenClaw config
```

Three separate mounts, all under `/tmp/agentia/` — nothing conflicts with host config.
