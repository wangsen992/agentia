# Final Implementation Options — Single Agent Composition

**Date:** 2026-04-08
**Deliverable for:** Sen Wang
**Context:** Agentia federated multi-agent system design

---

## What Was Researched

Over the past session we covered:
1. **Current state audit** — Agentia's existing config is infrastructure-only, no composition dimensions
2. **Framework + literature survey** — Role, Adapter, Access Level, Memory, Knowledge confirmed; Skills and Participation are novel; Session and Lifecycle missing
3. **OpenClaw hidden harnesses** — system prompt, tool schemas, bootstrap files always injected; adapter is a control plane wrapper, not a replacement harness
4. **Schema formalization** — 3 approaches prototyped
5. **Participation evaluator** — 3 approaches prototyped
6. **Integration analysis** — how schema and evaluator fit together within OpenClaw constraints

---

## Option 1: Pragmatic Incremental

**Approach:** Extend the current flat config + add Hybrid participation evaluator

### What to build:
1. Extend `AgentServerConfig` with new fields (role, access_level, memory, knowledge, skills, lifecycle, session sub-config)
2. Implement `HybridEvaluator` (rule-based fast path + LLM for ambiguous)
3. Update `OpenClawAdapter` to read new config fields and apply them (write SOUL.md, set tool policies)
4. Keep flat dataclass structure — add fields as needed

### Code layout:
```
agent_side/config.py              # extended flat dataclass
agent_side/participation/         # HybridEvaluator
  ├── rule_evaluator.py
  ├── llm_evaluator.py
  └── hybrid_evaluator.py
```

### Pros:
- Minimal new code — extends what exists
- Fast to implement
- Hybrid evaluator is auditable and deterministic for 80-90% of messages
- Fail-open design means routing never blocks

### Cons:
- Flat config gets unwieldy as fields accumulate
- Role persona → SOUL.md must happen at adapter.setup() — fragile
- No type safety beyond dataclass field names
- Validation is manual

### Effort estimate: ~1-2 weeks of implementation

---

## Option 2: Pydantic + Typed Config + Hybrid Evaluator

**Approach:** Full typed schema with Pydantic + Hybrid participation evaluator

### What to build:
1. Nested Pydantic models for all 9 dimensions
2. `LayeredConfigManager` — reads base defaults + per-agent overrides + runtime patches
3. `HybridEvaluator` with full rule + LLM pipeline
4. `AgentServer` updated to use typed config and evaluator

### Code layout:
```
agent_side/config/
  ├── approach_b_pydantic.py   # full typed schema
  ├── layered.py               # base+override merging
  └── manager.py               # LayeredConfigManager
agent_side/participation/
  └── (same as Option 1)
```

### Pros:
- Type safety catches errors at validation time
- Self-documenting schema with enums for constrained fields
- Base template + override ergonomics for org-wide defaults
- Most maintainable long-term

### Cons:
- Pydantic dependency
- Steeper initial implementation
- Schema changes require model migrations

### Effort estimate: ~2-3 weeks of implementation

---

## Option 3: Staged Rollout (Recommended)

**Approach:** Start with Option 1, migrate to Option 2 in Phase 2

### Phase 1 — Quick foundation:
- Flat config extension with the 9 dimensions
- HybridEvaluator (same as Option 1)
- OpenClawAdapter updated to apply role/access-level

### Phase 2 — Type safety:
- Migrate flat config to Pydantic models
- Add LayeredConfigManager for templates
- Full validation and schema documentation

### Why this order:
- You get a working system quickly
- Schema design gets validated by real usage before committing to types
- Phase 2 migration is straightforward (flat → nested)

### Effort estimate: Phase 1 ~1-2 weeks, Phase 2 ~1 week

---

## Decision Criteria

| Criteria | Option 1 | Option 2 | Option 3 |
|----------|----------|----------|----------|
| Speed to first working system | ✅ Fastest | ❌ Slowest | ✅ Fast |
| Long-term maintainability | ❌ Flat config grows unwieldy | ✅ Best | ✅ Good |
| Type safety | ❌ None | ✅ Full | ⚠️ Phase 2 |
| Org template support | ❌ Manual | ✅ Built-in | ⚠️ Phase 2 |
| Learning curve | ✅ Low | ⚠️ Pydantic | ✅ Low at first |
| Risk | ❌ Rework later | ❌ Over-engineered | ✅ Low |

---

## Participation Evaluator: One Recommendation

All three approaches (rule-based, LLM, hybrid) were prototyped. **Recommend Hybrid** regardless of which schema option you choose:

| Approach | Speed | Cost | Accuracy | Production-ready |
|----------|-------|------|----------|-----------------|
| Rule-based | Sub-ms | Free | Good for clear cases | ✅ |
| LLM | ~200-500ms | Per-call cost | Best for ambiguous | ⚠️ Cost uncontrolled |
| **Hybrid** | Sub-ms for 80-90% | LLM only for ~10-20% | Best of both | ✅ |

The hybrid evaluator:
1. Runs keyword + capability tag rules first (free, fast)
2. Escalates to LLM only when: topic conflict, no-match+nontrivial, or mixed signals
3. Fails open (defaults to OBSERVER if LLM is unavailable)

This is the right balance for a federated system where you don't want to pay LLM costs for every message routing decision.

---

## The OpenClaw Reality

No matter which option you choose, this is the reality:

- **Adapter is a control plane wrapper** — OpenClaw's system prompt, tool schemas, and bootstrap files are always present
- **Role persona goes into SOUL.md** — written by adapter.setup(), not injected at runtime
- **Access level maps to tools.allow/deny** — enforced by OpenClaw's gateway
- **Participation evaluator runs outside OpenClaw** — can't see system prompt, only message + config
- **Tool schemas (~30KB) can't be stripped** — external constraint

These aren't problems — they're the ground truth. Options 1-3 all accept these constraints.

---

## Next Steps

**If you pick Option 1 or 3:**
- Start with: extend `AgentServerConfig`, implement `HybridEvaluator`
- Then: update `OpenClawAdapter.setup()` to write SOUL.md and apply tool policies
- Then: wire evaluator into AgentServer message handler

**If you pick Option 2:**
- Start with: define Pydantic models, build LayeredConfigManager
- Then: everything else

---

## What to Hand Off

The research files are ready:
- `research/06-agents-current-state.md` — audit
- `research/07-schema-options.md` — schema approaches
- `research/08-participation-evaluator-options.md` — evaluator approaches
- `research/09-integration-analysis.md` — how they fit together
- `research/10-final-options.md` — this file

The prototype code is in:
- `agent_side/config_schemas/` — all three schema approaches
- `agent_side/participation/` — all three evaluator approaches

Recommendation: **Option 3 (Staged Rollout)** — fast first system, then type safety.
