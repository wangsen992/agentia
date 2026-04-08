# OpenClaw Hidden Harnesses — Context Injection and System Prompt Analysis

**Date:** 2026-04-07
**Researcher:** Jarvis
**Subject:** What OpenClaw injects into every agent run that could affect the single agent composition dimensions

---

## Executive Summary

OpenClaw has significant hidden infrastructure that automatically injects into every agent run — system prompts, workspace files, memory, skills, and hook systems — that an AgentAdapter wrapping OpenClaw would inherit without being able to control. These are **not visible to the adapter** unless the adapter explicitly inspects them. This document maps every hidden injection point and how it affects our composition dimensions.

---

## 1. System Prompt Injection

OpenClaw builds a custom system prompt for every agent run. The adapter sends a prompt; OpenClaw **prepends its own system prompt** before the model sees it.

### What's Injected (per-run)

| Section | What | Affects Dimension |
|---------|------|-----------------|
| **Tooling** | Current tool list + short descriptions | Skills |
| **Safety** | Guardrail reminder (advisory only) | Access Level |
| **Skills** | Compact `<available_skills>` list (name + desc + location) | Skills |
| **OpenClaw Self-Update** | How to run `config.apply` and `update.run` | Adapter |
| **Workspace** | Working directory path | Access Level |
| **Documentation** | Local docs path + clawhub URL | (none) |
| **Sandbox** | Sandbox mode, paths, elevated exec availability | Access Level |
| **Current Date & Time** | User timezone + time format | (none) |
| **Reply Tags** | Optional reply tag syntax per provider | (none) |
| **Heartbeats** | Heartbeat prompt + ack behavior | Participation |
| **Runtime** | Host, OS, node, model, repo root, thinking level | (none) |
| **Reasoning** | Visibility level + /reasoning toggle | (none) |

### Prompt Modes

The system prompt has 3 modes controlled by `promptMode`:

| Mode | Used for | Sections included |
|------|----------|-----------------|
| `full` | Default (main session) | All sections above |
| `minimal` | Sub-agents | Tooling, Safety, Workspace, Sandbox, Date, Runtime ONLY. Skills, Memory Recall, Self-Update, Model Aliases, User Identity, Reply Tags, Messaging, Silent Replies, Heartbeats OMITTED |
| `none` | Bare | Only base identity line |

### Critical Implication

**The adapter cannot see or control what OpenClaw injects.** If the adapter sends a prompt to OpenClaw, OpenClaw adds its own ~30-50KB of system prompt on top (tool schemas alone can be 30KB+). This means:

1. The adapter's "prompt in → response out" contract is not truly clean
2. Token costs are higher than the adapter can account for
3. OpenClaw's tool definitions are baked in — the adapter can't swap them out

---

## 2. Workspace File Bootstrap Injection

These files are **automatically injected into the context window** on every turn under "Project Context":

```
AGENTS.md       — Operating instructions, memory rules
SOUL.md         — Persona, tone, boundaries
TOOLS.md        — Local tool conventions (NOT tool availability)
IDENTITY.md     — Agent's name, vibe, emoji
USER.md         — Who the user is
HEARTBEAT.md    — Optional heartbeat checklist
BOOTSTRAP.md    — Only on first-run
MEMORY.md       — Long-term curated memory (when present)
```

### Key Properties

- **Injected every turn** — not just on session start. Every message sees the full bootstrap.
- **Not skill-loaded** — these are injected as text, not loaded via `read` tool
- **Auto-truncated** — `bootstrapMaxChars` (default 20K per file), `bootstrapTotalMaxChars` (default 150K total)
- **`memory/*.md` daily files** — NOT injected automatically; only accessed via `memory_search` tool when model explicitly calls it
- **Sub-agents** — only `AGENTS.md` and `TOOLS.md` are injected (bootstrap files filtered)

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Role** | SOUL.md, IDENTITY.md, AGENTS.md define persona — adapter can't control this unless it replaces these files |
| **Adapter** | OpenClaw owns these files; adapter is a wrapper around OpenClaw, so these are always present |
| **Skills** | Skills listed in `<available_skills>` in system prompt; loaded via `read` tool from SKILL.md when needed |
| **Memory** | MEMORY.md injected automatically; `memory_search` tool provides on-demand recall |
| **Participation** | HEARTBEAT.md contains participation logic — checked every ~30 min heartbeat |

### The `agent:bootstrap` Hook

OpenClaw has an internal `agent:bootstrap` hook that **runs while building bootstrap files before the system prompt is finalized**. This can:
- Mutate bootstrap files
- Replace SOUL.md with an alternate persona
- Add/remove bootstrap context

**The adapter cannot intercept this.** It's an internal OpenClaw mechanism.

---

## 3. Skills System — On-Demand Loading

### How It Works

1. System prompt includes `<available_skills>` — a compact list of name + description + file path
2. The model decides when to use a skill and calls `read` on the SKILL.md
3. SKILL.md is read and its instructions are followed

### Skill Types (in order of precedence)

1. **Workspace skills** — `skills/` folder in workspace (highest priority)
2. **Managed skills** — `~/.openclaw/skills/` (bundled by OpenClaw)
3. **Bundled skills** — installed via ClawHub

### Skill Discovery

The system prompt tells the model to use `read` to load SKILL.md at the listed location. If no skills are eligible, the Skills section is omitted entirely.

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Skills** | OpenClaw's skill system is baked in. The adapter's "skills" dimension needs to account for OpenClaw's built-in skill loading mechanism. If the adapter wants to expose its own skill registry, it needs to either: (a) disable OpenClaw's skill loading, or (b) coexist with it |

---

## 4. Tool Schema Injection

### The Two Costs

Tools affect context in two ways:

1. **Tool list text** — in system prompt (what you see as "Tooling"): ~1-2KB
2. **Tool schemas (JSON)** — sent to model so it can call tools: **30-40KB for typical setup** (counts toward context even though not visible as text)

### Biggest Offenders (from `/context detail`)

- `browser` tool: ~9.8KB schema
- `exec` tool: ~6.2KB schema
- Other tools add up

### Critical Implication for Adapter

**The adapter cannot strip or modify tool schemas.** OpenClaw's tool definitions are sent to the model. If the adapter wants to present a different tool surface to the agent (e.g., only expose a subset of tools), this is not possible at the adapter level — it would require modifying OpenClaw's tool registration.

This directly affects the **Skills** dimension: OpenClaw's skills system and tool system are intertwined. A clean "skill interface" abstraction at the adapter layer would sit on top of OpenClaw's tool definitions, not replace them.

---

## 5. Memory System

### What's Auto-Indexed

OpenClaw's builtin memory engine automatically indexes:
- `MEMORY.md` — long-term curated memory
- `memory/*.md` — daily memory logs

Into chunks (~400 tokens with 80-token overlap), stored in SQLite at `~/.openclaw/memory/<agentId>.sqlite`.

### Memory Types

| Type | Mechanism | Injected? |
|------|-----------|-----------|
| **Context window** | Current session messages | Every turn |
| **Compacted history** | Older messages summarized | After compaction |
| **Memory search** | Via `memory_search` tool | On demand |
| **Pruned tool results** | Old tool results removed from memory | Automatic policy |

### The `memory_search` Tool

The model calls `memory_search` to recall past events. This is **not automatic** — the model must explicitly invoke it. Results are fetched and injected into context.

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Memory** | OpenClaw's memory is built-in. Our "short-term/episodic/semantic" memory model maps to: context window = short-term, memory_search = episodic/semantic. But OpenClaw's memory is tightly coupled to its session system |
| **Knowledge** | If "knowledge" means RAG from external documents, OpenClaw's memory is NOT this — it's personal memory (MEMORY.md, daily logs). External knowledge bases would be an additional layer |

---

## 6. Multi-Agent Routing — Per-Agent Isolation

### Per-Agent Boundaries

Each OpenClaw agent has:
- **Own workspace** (files, AGENTS.md, SOUL.md, USER.md)
- **Own state directory** (`agentDir`) for auth profiles
- **Own session store** (`~/.openclaw/agents/<agentId>/sessions`)
- **Own memory index** (`~/.openclaw/memory/<agentId>.sqlite`)

### Routing

Messages route to agents via **bindings** — deterministic, most-specific-wins matching on `(channel, accountId, peer, guildId)`.

### Cross-Agent Memory

If one agent should search another's QMD sessions, configure `agents.list[].memorySearch.qmd.extraCollections`. This is the **only** sanctioned cross-agent memory path.

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Adapter** | Each agent is a separate OpenClaw instance with its own workspace. For Agentia's "federated agents" model, each OpenClaw agent = one AgentServer. But OpenClaw's multi-agent is NOT federated — it's co-hosted on the same gateway |
| **Memory** | Memory indices are per-agent. No shared memory unless explicitly configured via `extraCollections` |

---

## 7. Sandbox and Tool Policy

### Per-Agent Sandboxing

```json
{
  "agents": {
    "list": [{
      "id": "family",
      "workspace": "~/.openclaw/workspace-family",
      "sandbox": { "mode": "all", "scope": "agent" },
      "tools": {
        "allow": ["read", "exec", "sessions_list"],
        "deny": ["write", "edit", "browser"]
      }
    }]
  }
}
```

### Tool Allow/Deny vs Skills

**Important:** `tools.allow` and `tools.deny` are **tools**, not skills. If a skill needs to run a binary, ensure `exec` is allowed.

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Access Level** | OpenClaw has per-agent tool policies that map directly to access level. `deny: ["exec", "write", "edit"]` = sandboxed. This is the closest OpenClaw gets to our access level dimension |
| **Skills** | Skills can be blocked if their required tools aren't allowed |

---

## 8. Plugin Hooks — `before_prompt_build`

This is the most relevant hook for the adapter:

```
before_prompt_build: runs after session load (with messages) to inject
  prependContext      — per-turn dynamic text
  systemPrompt        — stable guidance (sits in system prompt space)
  prependSystemContext — prepends to system context
  appendSystemContext  — appends to system context
```

### What This Means

The adapter could, in theory, use a plugin that implements `before_prompt_build` to inject custom context into the system prompt. But this requires:
1. A plugin registered in OpenClaw
2. The plugin has access to the adapter's context
3. OpenClaw must be configured to use the plugin

**The adapter doesn't control the prompt assembly** — but it could influence it via a plugin.

---

## 9. Session, Compaction, and Pruning

### What Persists

| Mechanism | What | How Long |
|-----------|------|----------|
| **Normal history** | Full transcript | Until compacted/pruned |
| **Compaction** | Summary + recent messages | Permanent |
| **Pruning** | Old tool results removed from in-memory prompt | Session only (transcript untouched) |

### Compaction Trigger

Auto-compaction runs when the context window fills up. It summarizes older messages into a compact entry.

### Affect on Composition Dimensions

| Dimension | Effect |
|-----------|--------|
| **Memory** | Compaction is OpenClaw's automatic memory consolidation. The adapter can't control when it fires |
| **Session** | Session = transcript + routing state. The adapter's "session" sub-dimension (fork/resume) maps to OpenClaw's session system |

---

## 10. Hidden Costs Summary

| Hidden System | Token Cost | Adapter Visible? |
|--------------|-----------|-----------------|
| System prompt (full) | ~30-50KB | No |
| Tool schemas (JSON) | ~30-40KB | No |
| Bootstrap files | Up to 150KB total | Partially (files exist in workspace) |
| Skills list | ~2KB | Yes (in system prompt) |
| Session history | Variable | Partially (via `/context`) |
| Memory search results | Variable | Only when invoked |

---

## Key Findings for AgentAdapter Design

### What the Adapter Can Control

1. **What it sends as the prompt** — but OpenClaw prepends its own system prompt
2. **What it receives as the response** — clean
3. **The adapter's own config** — Role, Access Level, etc. stored in AgentServer config
4. **Plugin hooks** — if it registers a plugin, it can influence prompt assembly

### What the Adapter Cannot Control

1. **OpenClaw's system prompt** — injected automatically (~30-50KB)
2. **Tool schemas** — OpenClaw's tool definitions are always present
3. **Bootstrap files** — SOUL.md, IDENTITY.md, USER.md, AGENTS.md always injected
4. **Memory indexing** — OpenClaw auto-indexes MEMORY.md and daily logs
5. **Session management** — compaction and pruning are automatic
6. **Skills loading** — OpenClaw's skill system is baked in

### Design Implications

**Option A: Accept OpenClaw's harnesses as the base layer**
- The adapter wraps OpenClaw as-is
- OpenClaw's workspace files, system prompt, and tool schemas are always present
- The adapter adds a **control plane** (AgentServer config, restart, metrics) on top
- Skills layer sits above OpenClaw's built-in tools
- This is the pragmatic approach — work with OpenClaw, not around it

**Option B: Suppress OpenClaw's harnesses via plugin**
- Use `before_prompt_build` to strip or replace OpenClaw's injected content
- Use `agent:bootstrap` to replace workspace files
- Very complex; essentially building a parallel harness on top of OpenClaw
- Not recommended unless OpenClaw's defaults are genuinely incompatible

**Recommendation:** Option A. The adapter is a **control plane wrapper** around OpenClaw, not a replacement harness. OpenClaw's injected content is the base reality; the adapter adds organizational capabilities (federation, config management, multi-agent routing) on top.

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Comprehensive analysis of OpenClaw's hidden harnesses: system prompt injection (50KB+), workspace file bootstrap (SOUL.md, IDENTITY.md, etc.), tool schemas (30KB+), skills on-demand loading, memory system, multi-agent isolation, sandbox policies, and plugin hooks. Key finding: the adapter cannot control OpenClaw's injected content; the adapter is a control plane wrapper, not a replacement harness.
next_trigger: Report to Sen
```
