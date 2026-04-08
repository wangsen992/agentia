# Agentia — Next Steps

**Last Updated:** 2026-04-08

## Completed: pi-agent as Primary Adapter

pi-agent is now Agentia's primary agent runtime. OpenClaw is legacy.

### What was built

| Component | Status |
|-----------|--------|
| `agents/adapters/pi_agent.py` | ✅ PiAgentAdapter (RPC subprocess, event reader, block-on-agent_end) |
| `agents/adapters/factory.py` | ✅ pi-agent registered, default = "pi-agent" |
| `setup/adapters/pi-agent/` | ✅ install.sh, config.tmpl, bootstrap/*.tmpl |
| `setup/adapters/openclaw/` | ✅ install.sh, config.tmpl, bootstrap/*.tmpl |
| `agentia install <adapter>` | ✅ Jinja2 template rendering + runtime install |
| `agentia agentserver` | ✅ Starts AgentServer |
| `agentia create --adapter --provider --model` | ✅ Full adapter config |
| `agent_side/config.py` | ✅ adapter_type, provider, model, workspace, role, skills fields |
| `agent_side/patterns/` | ✅ Pass adapter kwargs to get_adapter() |
| `Dockerfile` | ✅ Generic base, ENTRYPOINT=agentia |
| `setup/README.md` | ✅ How to add new adapter |

### Architecture

```
agentia install pi-agent --config /etc/agentia/agent.json
  → Render config.tmpl (Jinja2) → /etc/agentia/agent.json
  → Render bootstrap/*.tmpl → /workspace/AGENTS.md, SYSTEM.md
  → Run setup/adapters/pi-agent/install.sh (npm install)

agentia agentserver
  → Start AgentServer (reads /etc/agentia/agent.json)

AgentServer
  → Harness → InboxDelivery/SyncDelivery
  → get_adapter(provider, model, workspace) → PiAgentAdapter
  → pi --mode rpc subprocess → JSONL stdin/stdout
```

---

## What's Left

### HIGH PRIORITY

#### 1. AgentServer reads adapter config from /etc/agentia/agent.json ✅ DONE
AgentServer reads `AGENTIA_CONFIG` env var (default `/etc/agentia/agent.json`) and uses adapter fields (adapter_type, adapter_provider, adapter_model, adapter_workspace) at startup. Verified working:
```
[AgentServer] Config: default | adapter=pi-agent provider=minimax model=MiniMax-M2.7
[Harness] Started with inbox delivery for agent-001
```

#### 2. Participation Evaluator wiring
HybridEvaluator exists in `agent_side/participation/` but is not wired into AgentServer message handler. Route: `server.py _handle_message()` → evaluator.evaluate() → skip/observer/active decision.

#### 3. SSH deployment
`agentia install` should work on SSH targets:
```bash
agentia install pi-agent --host user@server --config /etc/agentia/agent.json
```
- Copy setup scripts to remote
- Run install.sh via SSH
- AgentServer runs natively (no Docker)

### MEDIUM PRIORITY

#### 4. Multi-Agent Coordination
Agent-to-agent messaging via AgentServer relay. Session sharing / delegation protocol.

#### 5. Channel Integration (borrowed from OpenClaw)
Discord, Telegram, etc. via channel-to-agent routing.

#### 6. Skills System
pi-agent skills follow Agent Skills standard. Define Agentia's skill interface and per-agent skill loading.

### DEFERRED / FUTURE

- **Auth** — token auth for AgentServer API
- **Federation across machines** — session abstraction needed
- **Pydantic config migration** — Phase 2, after schema validated
- **Observability** — see issue #15

---

## Key Reference

### pi-agent RPC Protocol
- stdin/stdout JSONL
- Key commands: `prompt`, `steer`, `follow_up`, `abort`, `new_session`, `get_state`, `get_messages`, `compact`, `bash`
- Sessions: JSONL in `~/.pi/agent/sessions/`
- Bootstrap: `AGENTS.md` + `SYSTEM.md` per workspace (we write, pi-agent reads at startup)

### agentia CLI
```bash
agentia install pi-agent --config /etc/agentia/agent.json --provider minimax --model MiniMax-M2.7
agentia agentserver
agentia create my-image my-agent --adapter pi-agent --provider minimax --model MiniMax-M2.7
agentia send my-agent "Hello"
```

### Adding New Adapter
1. Create `setup/adapters/<name>/install.sh`
2. Create `setup/adapters/<name>/config.tmpl`
3. Create `setup/adapters/<name>/bootstrap/*.tmpl`
4. `agentia install <name>` works automatically
