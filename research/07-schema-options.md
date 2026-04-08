# Schema Formalization Options for Single Agent Composition

**Date:** 2026-04-08
**Researcher:** Jarvis (subagent)
**Task:** Design 3 concrete schema approaches for extending `AgentServerConfig` to support the full 9-dimension agent composition model.

---

## Context: The 9-Dimension Model

The current `AgentServerConfig` is a flat dataclass with infrastructure fields only (host, port, delivery, poll_interval, etc.). We need to extend it to cover:

```
Required:
  role           { persona, goal, backstory }
  adapter        { type, config, session: { id_prefix, fork_enabled, resume_enabled } }
  access_level   none | read_only | standard | privileged | explicit_confirm
  memory         { short_term: { type, max_tokens }, long_term: { episodic, semantic } }
  knowledge      { sources, retrieval: { top_k, threshold }, update_policy }

Optional:
  skills         [{ name, version, interface, adapter_impl }]
  participation  { evaluator, default }

Missing (add):
  lifecycle      { state, last_active }
```

**OpenClaw Constraints** (from `research/05-openclaw-hidden-harnesses.md`):

- OpenClaw **prepends its own system prompt** (~30-50KB) — the adapter cannot see or control this
- Bootstrap files (`SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `USER.md`) are **injected every turn** from per-agent workspace directories
- Tool schemas (~30KB) are **always present** — the adapter cannot strip or modify them
- Skills are **on-demand loaded** from `SKILL.md` paths listed in the system prompt
- Memory: context window = short-term, `memory_search` = episodic/semantic long-term
- Per-agent **tool allow/deny** maps directly to our `access_level` dimension
- Multi-agent isolation: each OpenClaw agent has its own workspace, memory index, session store
- The adapter is a **control plane wrapper** around OpenClaw, not a replacement harness

---

## Files Generated

```
agent_side/config_schemas/
  __init__.py                  — Public exports for all three approaches
  approach_a_flat.py           — Prototype: Flat JSON with dotted-key conventions
  approach_b_pydantic.py        — Prototype: Nested Pydantic models
  approach_c_layered.py         — Prototype: Layered base + env override
```

---

## Approach A: Flat JSON with Conventions

### Description

Extends the existing flat `AgentServerConfig` dataclass pattern. Nested objects are stored as **dotted keys** (e.g., `role.persona`, `adapter.session.id_prefix`) or JSON strings for complex values. Conventions govern structure — no schema enforcement, just agreed-upon naming. The existing `ConfigManager` is extended to handle both flat and partially-nested input.

This is the **lowest-friction evolution** of the current codebase.

### 9-Dimension Mapping

| Dimension | Field(s) | Storage |
|-----------|----------|---------|
| role.persona | `role_persona` | string |
| role.goal | `role_goal` | string |
| role.backstory | `role_backstory` | string |
| adapter.type | `adapter_type` | string enum |
| adapter.config | `adapter_config` | JSON string |
| adapter.session.id_prefix | `session_id_prefix` | string |
| adapter.session.fork_enabled | `session_fork_enabled` | bool |
| adapter.session.resume_enabled | `session_resume_enabled` | bool |
| access_level | `access_level` | string enum |
| memory.short_term.type | `memory_short_term_type` | string |
| memory.short_term.max_tokens | `memory_short_term_max_tokens` | int |
| memory.long_term.episodic | `memory_long_term_episodic` | bool |
| memory.long_term.semantic | `memory_long_term_semantic` | bool |
| knowledge.sources | `knowledge_sources` | JSON list string |
| knowledge.retrieval.top_k | `knowledge_retrieval_top_k` | int |
| knowledge.retrieval.threshold | `knowledge_retrieval_threshold` | float |
| knowledge.update_policy | `knowledge_update_policy` | string |
| skills | `skills` | JSON list string |
| participation.evaluator | `participation_evaluator` | bool |
| participation.default | `participation_default` | string |
| lifecycle.state | `lifecycle_state` | string |
| lifecycle.last_active | `lifecycle_last_active` | ISO8601 string |

### How AgentServer Reads/Writes Config

- **Load:** `ConfigManagerFlat.load()` reads JSON → `AgentServerConfigFlat.from_dict()` maps flat keys to dataclass fields. Accepts both flat and partially-nested input (normalizes via `_flatten()`).
- **Save:** `to_dict()` serializes to flat JSON; `_save()` writes atomically.
- **Update:** `update(patch)` accepts nested or flat dict, normalizes to flat, merges, validates field names exist on dataclass.
- **Nested access:** `role()`, `adapter_session()`, `memory_short_term()`, etc. return clean nested dicts for API responses.

### Compatibility with OpenClaw Hidden Harnesses

- ✅ **Role:** `role_persona/goal/backstory` fields can be used to **write SOUL.md** before agent startup in `adapter.setup()`. OpenClaw injects bootstrap files from the agent's workspace — if each agent has a unique workspace dir, each gets its own SOUL.md.
- ✅ **Adapter:** `adapter_type` + `adapter_config` map directly to what `OpenClawAdapter` needs. `session_*` fields control session behavior.
- ✅ **Access Level:** `access_level` string maps to OpenClaw's `tools.allow/deny` in `openclaw.json` — can be applied during adapter setup.
- ✅ **Memory:** `memory_short_term_type` = "context_window" maps to OpenClaw's built-in context. `memory_long_term_*` maps to `memory_search` tool.
- ✅ **Knowledge:** Sources list + retrieval params define an external RAG layer above OpenClaw's built-in memory.
- ✅ **Skills:** `skills` JSON list defines skill names/versions; `OpenClawAdapter` can inject these into the system prompt's `<available_skills>` or validate them against the actual skill registry.
- ✅ **Lifecycle:** `lifecycle_state` is writable by the harness — enables state tracking (stopped/running/error).
- ⚠️ **Bootstrap file injection:** OpenClaw injects SOUL.md/IDENTITY.md/AGENTS.md every turn. The flat config approach sets the workspace path (via `OPENCLAW_WORKSPACE` env var), so per-agent workspace dirs get per-agent bootstrap files. This is the correct pattern.
- ⚠️ **Tool schemas:** OpenClaw's tool schemas (~30KB) are injected automatically and cannot be controlled by the config. This is an external constraint all approaches share.

### Tradeoffs

| Criterion | Approach A | Approach B | Approach C |
|-----------|-----------|-----------|-----------|
| Schema enforcement | ❌ None | ✅ Full runtime validation | ⚠️ Conventions only |
| Nested ergonomics | ❌ Awkward (`role_goal`) | ✅ `config.role.persona` | ⚠️ Flat dict, dot-access |
| Type safety | ❌ None | ✅ Pydantic validators | ❌ None |
| Backward compat | ✅ Drop-in replacement | ⚠️ New serialization format | ⚠️ Base/env file structure |
| Dependency | ✅ Zero new deps | ❌ Requires pydantic | ✅ Zero new deps |
| Multi-agent templates | ❌ Manual merge | ❌ Manual merge | ✅ Native layering |
| Org-wide defaults | ❌ Copy-paste | ❌ Copy-paste | ✅ Base + env override |
| Skill conflict resolution | ❌ Manual | ❌ Manual | ✅ Named override |
| Complexity | Low | Medium | Medium-High |
| Debugging | Harder (nested lookups by convention) | Easier (typed errors) | Medium (layer tracing) |

---

## Approach B: Typed Python Dataclasses with Pydantic

### Description

Full nested dataclass hierarchy using **Pydantic v2** models with validators, `model_validate`, and `model_dump`. Each dimension is a typed sub-model. Enums for constrained fields (AccessLevel, AdapterType, MemoryType, etc.). Runtime validation with clear error messages. Self-documenting schema — the model class IS the documentation.

This is the **most robust and maintainable** approach for a Python-first codebase.

### 9-Dimension Mapping

| Dimension | Pydantic Model | Field |
|-----------|--------------|-------|
| role | `RoleConfig` | `persona`, `goal`, `backstory` |
| adapter | `AdapterConfig` | `type_` (AdapterType), `config` (dict), `session` (SessionConfig) |
| adapter.session | `SessionConfig` | `id_prefix`, `fork_enabled`, `resume_enabled` |
| access_level | `AccessLevel` (enum on root) | Literal[NONE/READ_ONLY/STANDARD/PRIVILEGED/EXPLICIT_CONFIRM] |
| memory.short_term | `ShortTermMemory` | `type` (MemoryType), `max_tokens` |
| memory.long_term | `LongTermMemory` | `episodic`, `semantic` |
| knowledge | `KnowledgeConfig` | `sources`, `retrieval` (RetrievalConfig), `update_policy` (UpdatePolicy) |
| knowledge.retrieval | `RetrievalConfig` | `top_k`, `threshold` |
| skills | `list[SkillEntry]` | Each: `name`, `version`, `interface`, `adapter_impl` |
| participation | `ParticipationConfig` | `evaluator`, `default` (ParticipationDefault) |
| lifecycle | `LifecycleConfig` | `state` (LifecycleState), `last_active` (datetime) |

### How AgentServer Reads/Writes Config

- **Load:** `ConfigManagerPydantic.load()` reads JSON → `AgentServerConfigPydantic.from_dict()` (Pydantic validates and deserializes in one step). `ValidationError` on bad data.
- **Save:** `config.to_dict()` → JSON via `model_dump(mode="json")`. Handles Enum serialization to strings, datetime to ISO8601.
- **Update:** `update(patch)` merges patch dict into current config, then re-validates via `model_validate`. Full validation on every update.
- **Flat export:** `to_flat_dict()` converts nested → dotted keys for backward compatibility with tools expecting flat JSON.
- **Lifecycle helper:** `update_lifecycle(state)` updates state + `last_active` timestamp atomically.

### Compatibility with OpenClaw Hidden Harnesses

- ✅ **Role:** `RoleConfig` persona/backstory can be used to **write SOUL.md** in the agent's workspace during `adapter.setup()`. The workspace path is per-agent, so each gets its own bootstrap files.
- ✅ **Adapter:** `AdapterConfig.type_` (AdapterType enum) maps to `OpenClawAdapter` instantiation. `config` dict passes adapter-specific options. `session.id_prefix` controls session naming.
- ✅ **Access Level:** `AccessLevel` enum maps to OpenClaw's `tools.allow/deny` — applied during adapter setup by reading the enum and mapping to the corresponding tool list.
- ✅ **Memory:** `ShortTermMemory.type` (MemoryType enum) maps to OpenClaw's memory types. `long_term.episodic/semantic` maps to `memory_search` behavior.
- ✅ **Knowledge:** Pydantic model defines the full knowledge config; the adapter/harness is responsible for implementing the RAG retrieval.
- ✅ **Skills:** `list[SkillEntry]` is a typed skill registry. `adapter.setup()` can validate that listed skills exist in OpenClaw's skill registry and inject appropriate paths.
- ✅ **Lifecycle:** `LifecycleConfig` with `LifecycleState` enum enables harness state machine (stopped → starting → running → error → stopped).
- ✅ **Validators:** `RoleConfig` has a model validator ensuring `persona` OR `goal` is set — prevents misconfigured agents.
- ⚠️ Same OpenClaw harness constraints as Approach A (bootstrap file injection, tool schemas).

### Tradeoffs

| Criterion | Approach B | Approach A | Approach C |
|-----------|-----------|-----------|-----------|
| Schema enforcement | ✅ Full | ❌ None | ⚠️ Conventions |
| Type safety | ✅ Pydantic validators | ❌ None | ❌ None |
| Nested ergonomics | ✅ `config.role.persona` | ❌ `role_persona` | ⚠️ `resolve().get("role", "persona")` |
| Error messages | ✅ Clear field-level | ❌ Raw KeyError | ❌ Raw KeyError |
| Backward compat | ⚠️ `to_flat_dict()` for compat | ✅ Flat native | ⚠️ New file structure |
| Dependency | ❌ pydantic | ✅ Zero | ✅ Zero |
| Serialization | ✅ `model_dump(mode="json")` | ✅ `asdict()` | ✅ JSON files |
| Self-documenting | ✅ Class = schema | ❌ Doc external | ❌ Doc external |
| Enum safety | ✅ Type-checked | ⚠️ String comparison | ⚠️ String comparison |
| Complexity | Medium | Low | Medium-High |

---

## Approach C: Layered Config — Base Template + Per-Agent Overrides

### Description

Inspired by Docker Compose's `extends` and environment variable override patterns. Config is resolved by **deep-merging 4 layers**:

1. **BUILTIN_DEFAULTS** — hardcoded fallback (always present, never persisted)
2. **Base config** (`~/.agentia/base.json`) — org-wide defaults, distributed with deployment
3. **Agent env file** (`~/.agentia/env/<agent_id>.json`) — per-agent overrides
4. **Runtime patch** (in-memory dict from API `PATCH /config`) — ephemeral, not persisted

Deep-merge at the dict level: overlay values win. Skills lists are **merged by name** (overlay skills with same name replace base skills). This enables org-wide templates (base.json with default persona/skills/access) with agent-specific overrides.

This is the **best approach for organizations** managing multiple agents with shared conventions.

### 9-Dimension Mapping

Each dimension is a nested dict block in the layered JSON. Only fields that differ from lower layers need to be specified at each layer.

```json
// ~/.agentia/base.json (org-wide defaults)
{
  "role": {
    "persona": "You are an AI assistant representing Acme Corp.",
    "goal": "Help users with their tasks.",
    "backstory": "You were built by the Acme AI team."
  },
  "access_level": "standard",
  "skills": [
    { "name": "ynab", "version": "latest" },
    { "name": "zotero", "version": "latest" }
  ],
  "adapter": { "type": "openclaw", "session": { "id_prefix": "acme" } }
}

// ~/.agentia/env/jarvis.json (agent-specific)
{
  "role": { "goal": "Manage Sen's research, finances, and daily logistics." },
  "skills": [
    { "name": "ynab" },                          <!-- overrides base skill -->
    { "name": "whoop-cli", "version": "latest" } <!-- new agent-specific skill -->
  ]
}
```

Resolved config merges both → jarvis gets Acme base + his specific goal + ynab from base + whoop-cli new.

### How AgentServer Reads/Writes Config

- **Resolve:** `ConfigManagerLayered.resolve(agent_id)` merges Layer 1→2→3→4 and returns `ResolvedConfig`. Optionally writes resolved output to `~/.agentia/resolved/<agent_id>.json` for debugging.
- **Update (env layer):** `update_env(agent_id, patch)` deep-merges patch into the agent's env file (Layer 3). Skills are merged specially (override by name). Base.json is never modified by `update_env`.
- **Update (runtime patch):** `apply_patch(agent_id, patch)` applies an in-memory overlay (Layer 4). Cleared on agent restart.
- **Read base:** `get_base()` / `set_base()` read/write the org-wide base config.
- **List agents:** `list_agents()` returns all agent IDs with env files.
- **Dot-access:** `ResolvedConfig.get("role", "persona")` for convenient access.

### Compatibility with OpenClaw Hidden Harnesses

- ✅ **Role:** Base config sets default `role.persona`; env file can override per-agent. Each agent's workspace dir gets its own bootstrap files (SOUL.md written from resolved role). Inheritance chain: org brand voice in base, agent-specific goals in env.
- ✅ **Access Level:** Base sets default (e.g., "standard"); env file can escalate specific agents (e.g., "privileged" for admin agent). Maps to OpenClaw's tools.allow/deny.
- ✅ **Skills:** Layered merging is most valuable here. Org-wide base skills (ynab, zotero) + agent-specific skills (whoop-cli for health agent). Skills with same name in base are overridden by env.
- ✅ **Lifecycle:** Lives in Layer 4 (runtime patch) — not persisted to env file. Harness updates lifecycle state in-memory.
- ✅ **Multi-agent management:** Single base.json distributed org-wide; each agent has a lightweight env file override. Easy to audit what differs from the org standard.
- ✅ **Agent provisioning:** `export_base_template()` generates a starter base.json from builtin defaults.
- ⚠️ Same OpenClaw harness constraints as Approaches A/B.

### Tradeoffs

| Criterion | Approach C | Approach A | Approach B |
|-----------|-----------|-----------|-----------|
| Org templates | ✅ Native | ❌ Manual merge | ❌ Manual merge |
| Skill conflict resolution | ✅ Named override | ❌ Manual | ❌ Manual |
| Per-agent override ergonomics | ✅ env file | ⚠️ Full config per agent | ⚠️ Full config per agent |
| Schema enforcement | ⚠️ Conventions only | ❌ None | ✅ Full |
| Type safety | ❌ None | ❌ None | ✅ Pydantic |
| Complexity | Medium-High | Low | Medium |
| Debugging | ✅ Resolved JSON output | ✅ Flat JSON | ✅ Typed + validated |
| Agent provisioning | ✅ `export_base_template()` | ❌ Manual | ❌ Manual |
| Shared base + local overrides | ✅ Native | ❌ Manual | ❌ Manual |
| Dependency | ✅ Zero | ✅ Zero | ❌ pydantic |

---

## Comparison Matrix

| Criterion | A: Flat JSON | B: Pydantic | C: Layered |
|-----------|:---:|:---:|:---:|
| Schema enforcement | 1 | 3 | 1 |
| Type safety / validation | 1 | 3 | 1 |
| Nested ergonomics | 1 | 3 | 2 |
| Backward compatibility | 3 | 2 | 1 |
| Zero new dependencies | 3 | 1 | 3 |
| Multi-agent org templates | 1 | 1 | 3 |
| Skill conflict resolution | 1 | 1 | 3 |
| Error clarity | 1 | 3 | 1 |
| Self-documenting schema | 1 | 3 | 1 |
| OpenClaw bootstrap compat | 3 | 3 | 3 |
| Lifecycle state tracking | 2 | 3 | 2 |
| Extensibility (new dimensions) | 1 | 3 | 2 |

**Scoring: 3 = best, 2 = moderate, 1 = weakest**

### Key Findings

- **Approach B (Pydantic) dominates** on type safety, validation, ergonomics, error clarity, and extensibility — the dimensions that matter most for a growing codebase.
- **Approach C (Layered) dominates** on multi-agent org template management — the unique differentiator.
- **Approach A (Flat)** is the lowest-risk evolution of the current code but hits structural limits as the schema grows.
- All three approaches have **equal compatibility** with OpenClaw's hidden harnesses (bootstrap file injection, tool schema injection). This is an external constraint no schema approach can change.
- **Pydantic dependency** is a one-time cost: `pip install pydantic`. It's a mature, well-tested library with no major risks.

---

## Recommendation: **Approach B (Pydantic)**

**Pick Approach B and say why:** Pydantic provides the best tradeoff between type safety, developer experience, and schema enforcement with minimal complexity. The 9-dimension model has nested, typed sub-structures (enums, nested dicts, datetime fields) that flat-key conventions handle poorly. Pydantic's `model_validate` and `model_dump` eliminate the manual mapping code that makes Approaches A and C brittle. Validation errors are field-level and actionable — critical during development. The dependency cost (one `pip install`) is paid once and amortized across the entire lifetime of the project.

**Use Approach C's layering concept as a _feature_ on top of Approach B:** Store base defaults as a Pydantic-validated JSON file and use a thin `LayeredPydanticConfig` wrapper that deep-merges env overrides before validation. This gives you Pydantic's type safety WITH layered override ergonomics — the best of both worlds without Approach C's debugging complexity.

### Implementation Path

1. Keep `agent_side/config.py` as the thin public API (`AgentServerConfig` dataclass)
2. Internally use `AgentServerConfigPydantic` for all new code
3. Add `ConfigManagerPydantic` as the primary manager, with backward-compatible `from_dict()` / `to_flat_dict()` methods
4. For org-wide layering, add a `LayeredPydanticConfig` thin wrapper that resolves base + env files and returns a Pydantic-validated config
5. Write SOUL.md from `role.persona` / `role.backstory` during `adapter.setup()` so OpenClaw's bootstrap injection carries the agent's defined persona
6. Map `access_level` enum → OpenClaw's `tools.allow/deny` in `adapter.setup()`
