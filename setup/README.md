# Agentia Setup System

Unified setup scripts for installing agent runtimes (pi-agent, OpenClaw, etc.) in any deployment environment (Docker, SSH, bare metal).

## Overview

Each adapter is a self-contained directory under `adapters/`:
```
adapters/
├── pi-agent/
│   ├── install.sh          # Runtime installation (shell script)
│   ├── config.tmpl         # Jinja2 config template
│   └── bootstrap/
│       ├── AGENTS.md.tmpl
│       ├── SYSTEM.md.tmpl
│       └── TOOLS.md.tmpl
└── openclaw/
    ├── install.sh
    ├── config.tmpl
    └── bootstrap/
        ├── AGENTS.md.tmpl
        └── SYSTEM.md.tmpl
```

## How It Works

1. **Config template** is rendered via Jinja2 with context from CLI args + env vars
2. **Bootstrap files** (AGENTS.md, SYSTEM.md, etc.) are rendered from the same context
3. **Runtime install** script handles binary/dependency installation

## Adding a New Adapter

1. Create `adapters/<name>/`
2. Add `install.sh` — shell script that installs the runtime (npm, pip, etc.)
3. Add `config.tmpl` — Jinja2 template for `/etc/agentia/agent.json`
4. Add `bootstrap/*.tmpl` — Jinja2 templates for agent bootstrap files
5. Update the `agentia-agent setup` CLI subcommand to recognize the new adapter

## Template Variables

All templates share the same rendering context:

| Variable | Source | Example |
|----------|--------|---------|
| `{{ agent_id }}` | CLI `--agent-id` | `"my-agent"` |
| `{{ adapter }}` | CLI `--adapter` | `"pi-agent"` |
| `{{ provider }}` | CLI `--provider` | `"minimax"` |
| `{{ model }}` | CLI `--model` | `"MiniMax-M2.7"` |
| `{{ workspace }}` | CLI `--workspace` | `"/workspace"` |
| `{{ role_goal }}` | CLI `--role-goal` | `"Write code"` |
| `{{ backstory }}` | CLI `--backstory` | `"I am a coder"` |
| `{{ skills }}` | CLI `--skills` | `["skill1", "skill2"]` |
| `{{ env.VAR_NAME }}` | Auto-injected env vars | `{{ env.AGENT_MODEL }}` |

## Config Template

The `config.tmpl` renders to `/etc/agentia/agent.json` (or path set by `AGENTIA_CONFIG` env var).

Example `config.tmpl`:
```jinja2
{
  "agent_id": "{{ agent_id }}",
  "adapter": "{{ adapter }}",
  "provider": "{{ provider }}",
  "model": "{{ model }}",
  "workspace": "{{ workspace }}",
  "role": {
    "persona": "You are {{ agent_id }}{% if role_goal %}. Goal: {{ role_goal }}{% endif %}",
    "goal": "{{ role_goal }}",
    "backstory": "{{ backstory }}"
  },
  "skills": [{% for s in skills %}"{{ s }}"{% if not loop.last %}, {% endif %}{% endfor %}]
}
```

## Bootstrap Templates

Rendered into the agent workspace:
- `AGENTS.md` — agent identity and role
- `SYSTEM.md` — system prompt
- `TOOLS.md` — tool definitions (optional)

## Runtime Install Script

`install.sh` receives two args:
1. `$1` — workspace path
2. `$2` — config file path

It should:
1. Create required directories under workspace
2. Install runtime binary if not already installed
3. Exit 0 on success, non-zero on failure
