# Participation Evaluator Prototypes

**Date:** 2026-04-08
**Author:** Jarvis (research sub-agent)
**Task:** Design and implement three approaches to the participation evaluator
**Output directory:** `agent_side/participation/`

---

## 1. Problem Statement

Currently `AgentServer` has a **static** `delivery` config (`inbox` / `sync` / `stream`) that determines how messages are routed to the agent. This is binary and inflexible — every message for an agent gets the same treatment regardless of its content or the agent's current state.

The participation evaluator replaces this with a **function**:

```python
def evaluate(message: RelayMessage, context: AgentContext) -> ParticipationLevel:
    return "active" | "observer" | "skip"
```

The evaluator runs **before** the message is routed, inside `AgentServer`, and its output determines the delivery behavior.

---

## 2. Shared Types

All three approaches share the same input/output types, defined in `agent_side/participation/types.py`.

### Input: `RelayMessage`

```python
@dataclass
class RelayMessage:
    message_id: str
    from_agent: str
    to_agent: str
    content: str
    conversation_id: str
    correlation_id: str
    timestamp: str          # ISO-8601
    metadata: dict = field(default_factory=dict)   # free-form; may carry topic/skill tags
```

### Input: `AgentContext`

```python
@dataclass
class RoleConfig:
    name: str
    description: str = ""
    topics: list[str] = []      # topic keywords from agent config
    keywords: list[str] = []    # additional keyword triggers

@dataclass
class AgentContext:
    agent_id: str
    role: RoleConfig
    skills: list[str]                     # skill names this agent has
    memory_state: str                    # free-form summary of current state
    conversation_history: list[str]       # recent message content strings
```

### Output: `ParticipationLevel`

```python
class ParticipationLevel(str, Enum):
    ACTIVE   = "active"    # process + respond
    OBSERVER = "observer"   # read but do not respond
    SKIP     = "skip"       # ignore entirely
```

---

## 3. Integration Architecture

### Where the Evaluator Fits in AgentServer

```
Host / Moderator
    │
    │  POST /message  (or /message/async)
    ▼
┌─────────────────────────────────────────────┐
│           AgentServer (HTTP handler)         │
│                                              │
│  1. Build RelayMessage from request body     │
│  2. Build AgentContext (from config/redis)  │
│  3. ──► PARTICIPATION EVALUATOR ◄──           │  ← NEW: evaluate() called here
│  4. Switch on ParticipationLevel:            │
│       ACTIVE   → process via Harness         │
│       OBSERVER → append to observer buffer   │
│       SKIP     → discard (no routing)        │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  Harness (inbox / sync delivery pattern)   │
│  → OpenClawAdapter → openclaw agent process │
└─────────────────────────────────────────────┘
```

### How AgentServer Calls the Evaluator

The evaluator is injected into `AgentServer` at construction time. A `PATCH /config` endpoint accepts `{ "evaluator": "rule" | "llm" | "hybrid" }` to switch strategies at runtime without restarting.

```python
# In server.py — proposed integration point
class AgentServer:
    def __init__(self, config_path=None, evaluator=None):
        ...
        self._evaluator = evaluator or self._build_evaluator(
            self.config.evaluator_type
        )

    def _build_evaluator(self, evaluator_type: str):
        if evaluator_type == "rule":
            from .participation import make_rule_evaluator
            return make_rule_evaluator(self.config.evaluator_config)
        elif evaluator_type == "llm":
            from .participation import make_llm_evaluator
            return make_llm_evaluator(self.config.evaluator_config)
        elif evaluator_type == "hybrid":
            from .participation import make_hybrid_evaluator
            return make_hybrid_evaluator(
                rule_config=self.config.evaluator_config.get("rule"),
                llm_config=self.config.evaluator_config.get("llm"),
                llm_enabled=True,
            )

    def _handle_message(self):
        data = self._read_json()
        context = self._build_agent_context(data)
        message = self._build_relay_message(data)

        # ── EVALUATE BEFORE ROUTING ──
        level = self._evaluator.evaluate(message, context)

        if level == ParticipationLevel.SKIP:
            self._send_json(200, {"status": "skipped", "message_id": message.message_id})
            return

        if level == ParticipationLevel.OBSERVER:
            # Buffer in observer store; do not send to agent
            self._observer_buffer.append(message)
            self._send_json(200, {"status": "observed", "message_id": message.message_id})
            return

        # ACTIVE: proceed with normal routing
        self._route_active(message, context, data)
```

### How Config Data Flows In

```
~/.agentia/agent.json
    │
    ├── delivery: "inbox"           ← existing (becomes default/fallback)
    ├── evaluator_type: "hybrid"   ← NEW: which evaluator to use
    └── evaluator_config:          ← NEW: evaluator-specific config
          ├── topic_rules: [...]
          ├── skill_rules: [...]
          ├── keyword_rules: [...]
          └── llm:
                ├── model: "gpt-4o-mini"
                ├── api_key: "sk-..."
                └── base_url: "https://api.openai.com/v1"
```

---

## 4. Approach A — Rule-Based Evaluator

**File:** `agent_side/participation/rule_evaluator.py`

### Description

Fast, deterministic, fully-auditable rule engine. No LLM callout. Rules are expressed as plain dicts and can be shipped as JSON config.

### `evaluate()` Signature

```python
class RuleEvaluator:
    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel: ...
```

### How It Works

Checks run in priority order, first match returns immediately:

1. **Capability filter** — `required_skill` in `message.metadata` must be in `context.skills`, else `SKIP`
2. **Topic scan** — keyword substring match of `message.content` + `metadata["topic"]` against `topic_rules`
3. **Skill tag match** — `metadata["skill"]` in `context.skills` → `ACTIVE`
4. **Keyword scan** — pre-compiled regex patterns on `message.content` against `keyword_rules`
5. **Default** — `default_level` (configurable, default `OBSERVER`)

### Default Rules (bundled)

```python
# topic_rules: topic keyword → level
DEFAULT_TOPIC_RULES = [
    {"topic": "error",    "level": ACTIVE,   "weight": 90},
    {"topic": "critical", "level": ACTIVE,   "weight": 95},
    {"topic": "question", "level": ACTIVE,   "weight": 80},
    {"topic": "help",     "level": ACTIVE,   "weight": 85},
    {"topic": "log",      "level": OBSERVER, "weight": 60},
    {"topic": "status",   "level": OBSERVER, "weight": 50},
    {"topic": "heartbeat","level": SKIP,     "weight": 40},
]

# skill_rules: skill name → level
DEFAULT_SKILL_RULES = [
    {"skill": "weather",    "level": ACTIVE},
    {"skill": "reminders",  "level": ACTIVE},
    {"skill": "email",      "level": ACTIVE},
    {"skill": "zotero",     "level": ACTIVE},
    {"skill": "ynab",       "level": ACTIVE},
]

# keyword_rules: arbitrary substring → level
DEFAULT_KEYWORD_RULES = [
    {"keyword": "@agent",  "level": ACTIVE},
    {"keyword": "urgent",  "level": ACTIVE},
    {"keyword": "please",  "level": ACTIVE, "weight": 50},
    {"keyword": "?",       "level": ACTIVE},
    {"keyword": "FYI",     "level": OBSERVER},
]
```

### Configuration

```python
make_rule_evaluator({
    "topic_rules":   [{"topic": "fire", "level": "active", "weight": 95}, ...],
    "skill_rules":   [{"skill": "code", "level": "active"}, ...],
    "keyword_rules": [{"keyword": "@jarvis", "level": "active"}, ...],
    "default_level": "observer",
})
```

### How AgentServer Uses It

```python
# Replace static delivery check:
# OLD:
if self.config.delivery == "inbox": ...

# NEW:
level = rule_evaluator.evaluate(message, context)
if level == ParticipationLevel.SKIP:
    return  # discard
elif level == ParticipationLevel.OBSERVER:
    self._observer_buffer.append(message)
    return
# else ACTIVE: continue with normal routing
```

### Tradeoffs

| ✅ Pros | ❌ Cons |
|--------|---------|
| Sub-millisecond latency | Cannot handle semantic nuance |
| Fully deterministic + auditable | No understanding of intent |
| Zero external dependencies | Rules must be manually authored and maintained |
| Easy to test and debug | Brittle to paraphrasing ("help me" vs "could you help") |
| Config-changeable at runtime | |

---

## 5. Approach B — LLM-Based Classifier

**File:** `agent_side/participation/llm_evaluator.py`

### Description

An LLM classifies each message. Passes the full `RelayMessage` + `AgentContext` + conversation history to the LLM with a rubric explaining the three participation levels. Response is parsed JSON.

### `evaluate()` Signature

```python
class LLMClassifier:
    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel: ...
```

### How It Works

1. **Prompt construction** — assembles a structured prompt with message content, agent profile (role, skills, memory summary), and the last N conversation turns
2. **LLM call** — sends to an OpenAI-compatible API (configurable via `LLMConfig`)
3. **Response parsing** — parses `{"level": "active"|"observer"|"skip", "reason": "..."}`
4. **Fail-open** — on any error (timeout, parse failure, API error), defaults to `OBSERVER` rather than blocking routing

### Prompt Structure

```
SYSTEM RUBRIC (explains participation levels)

=== INCOMING MESSAGE ===
message_id     : ...
from_agent     : ...
to_agent       : ...
conversation_id: ...
timestamp      : ...
content        : ...

Message metadata: {...}

=== RECEIVING AGENT PROFILE ===
agent_id       : ...
role_name      : ...
role_topics    : ...
skills         : ...
memory_summary : ...

Recent conversation history:
  - [1] ...
  - [2] ...
```

### Configuration

```python
make_llm_evaluator({
    "llm": {
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-...",
        "timeout": 30.0,
        "max_history_turns": 5,
    }
})
```

### How AgentServer Uses It

Same interface as `RuleEvaluator` — drop-in replacement:

```python
level = llm_evaluator.evaluate(message, context)
# ... same routing switch as above
```

### Tradeoffs

| ✅ Pros | ❌ Cons |
|--------|---------|
| Understands intent, nuance, context | 500ms–3s latency per evaluation |
| No rule authoring required | Non-deterministic — same message can get different results |
| Handles paraphrasing, ambiguity | API cost per evaluation |
| Can leverage full conversation history | Requires API key + network access |
| | Fail-open defaults may not be appropriate for all cases |
| | Hidden harness context (from OpenClaw) is NOT visible to the LLM evaluator |

### OpenClaw Hidden Harnesses Note

> **Important:** The `LLMClassifier` runs **outside** OpenClaw's agent process — it sees the message as a data structure, not as it appears inside OpenClaw's system prompt. This means OpenClaw's injected content (SOUL.md, AGENTS.md, `<available_skills>`, tool schemas) is **not visible** to the LLM evaluator. If the evaluator needs to know what OpenClaw has already injected, that context must be explicitly passed via `message.metadata` or a custom `AgentContext` field.

---

## 6. Approach C — Hybrid Evaluator

**File:** `agent_side/participation/hybrid_evaluator.py`

### Description

Combines Approach A's speed with Approach B's flexibility. A fast **rule filter** runs first; only messages that are ambiguous trigger the LLM call. In practice, ~80-90% of messages are ruled on by rules alone; only ~10-20% escalate to the LLM.

### Components

1. **`RuleEvaluator`** — fast-path filter (sub-ms)
2. **`AmbiguityDetector`** — decides whether result is trustworthy
3. **`LLMClassifier`** — called only for ambiguous cases

### `evaluate()` Signature

```python
class HybridEvaluator:
    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel: ...
```

### How It Works

```
RelayMessage + AgentContext
        │
        ▼
┌─────────────────────────┐
│   RuleEvaluator         │  (sub-ms, always runs first)
│   evaluate() → level    │
│   explain() → traces     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  AmbiguityDetector      │
│  evaluate(message,      │
│    context, rule_ev)     │
│                         │
│  Returns AmbiguityResult │
│  with type:             │
│    CLEAR        → return rule_level
│    CONFLICT     → LLM
│    NO_MATCH+NL  → LLM     (non-trivial, no rule)
│    MIXED_SIGNALS→ LLM     (passive + active signals)
└───────────┬─────────────┘
            │
    ┌───────┴───────┐
    │  CLEAR        │  LLM escalation types
    │  return       │  │
    │  rule_level   │  ▼
    └───────────────┘  ┌─────────────────┐
                        │  LLMClassifier  │
                        │  evaluate()     │──► ParticipationLevel
                        └─────────────────┘
```

### Ambiguity Detection Logic

```python
# CONFLICT: multiple rule groups fired with different levels
#   e.g. keyword "@agent" (ACTIVE) + "FYI" (OBSERVER) in same message

# NO_MATCH + nontrivial: no rule matched AND message is:
#   - ≥50 chars AND
#   - ≥5 words AND
#   - not purely punctuation
#   → escalating because we have no signal to base a decision on

# MIXED_SIGNALS: both passive and active phrases detected
#   passive: "fyi", "for your info", "heads up", "logging", "heartbeat"
#   active:  "please", "help", "urgent", "?", "error", "question"
#   → ambiguous intent, let LLM decide

# CLEAR: anything else → return rule_level directly
```

### Exposed Statistics

```python
evaluator = make_hybrid_evaluator(...)
level = evaluator.evaluate(message, context)
stats = evaluator.get_stats()
# {
#   "evaluations_total": 1523,
#   "rule_hit_count": 1380,
#   "llm_calls_count": 143,      # ~9% LLM call rate
#   "skipped_count": 12,
#   "llm_call_rate": 0.094,
# }
```

### Configuration

```python
make_hybrid_evaluator(
    rule_config={
        "topic_rules": [...],
        "skill_rules": [...],
        "keyword_rules": [...],
        "default_level": "observer",
    },
    llm_config={
        "llm": {
            "model": "gpt-4o-mini",
            "api_key": "sk-...",
        }
    },
    llm_enabled=True,
)
```

### How AgentServer Uses It

Same drop-in interface as both other approaches:

```python
level = hybrid_evaluator.evaluate(message, context)
# ... same routing switch
```

### Tradeoffs

| ✅ Pros | ❌ Cons |
|--------|---------|
| ~80-90% of messages evaluated in sub-ms | More complex than either pure approach |
| LLM called only when genuinely ambiguous | AmbiguityDetector adds its own tuning burden |
| Handles nuance while staying fast | Still requires LLM API key |
| Exposes `explain()` for full audit trail | Fail-open (→ OBSERVER) on LLM error |
| `get_stats()` for monitoring LLM call rate | |
| No semantic understanding required for most messages | |

---

## 7. Comparison Matrix

| Dimension | RuleEvaluator (A) | LLMClassifier (B) | HybridEvaluator (C) |
|-----------|------------------|-------------------|---------------------|
| **Latency** | < 1ms | 500ms – 3s | < 1ms for ~80-90%; LLM latency for ~10-20% |
| **Determinism** | Fully deterministic | Non-deterministic | Mostly deterministic |
| **Dependencies** | None | LLM API key + network | LLM API key + network (partial) |
| **Nuance handling** | Poor (paraphrasing breaks rules) | Excellent | Good (LLM for hard cases) |
| **Auditability** | Full rule trace via `explain()` | `reason` field in response | Full dual trace |
| **Config-driven** | Yes (JSON/YAML rules) | Prompt + model config | Rules + LLM config |
| **Failure mode** | Returns `default_level` | Fail-open → OBSERVER | Rule fallback on LLM error |
| **Maintenance** | Manual rule authoring | No rule maintenance | Reduced rule maintenance |
| **Conversation awareness** | None (unless encoded in rules) | Yes (last N turns passed) | Yes (via LLM path) |
| **OpenClaw harness visibility** | None (operates outside harness) | None (operates outside harness) | None (operates outside harness) |
| **Complexity** | Low | Medium | Medium-high |

---

## 8. Recommendation

**Recommended: Approach C — HybridEvaluator**

Rationale:

1. **Production-relevant latency profile** — the vast majority of messages in a multi-agent system are routine (status checks, heartbeats, acknowledgments). The hybrid approach handles these in sub-millisecond with rules, reserving LLM cost and latency only for messages that genuinely need judgment.

2. **Observable and auditable** — `explain()` produces a full trace of which rule fired, whether LLM was called, and why the ambiguity detector escalated. This is critical for debugging in production.

3. **Observable LLM call rate** — `get_stats()` lets operators monitor the LLM escalation rate. If it climbs above ~30%, it's a signal that rules need tuning.

4. **Graceful degradation** — LLM failures fall back to rule-based result, so the system never blocks on an unavailable API.

5. **Easiest migration path** — it is a superset of Approach A: if the LLM is disabled or unreachable, it behaves exactly like the RuleEvaluator.

### Why Not Approach B (LLM-only)?

The LLM call overhead (~500ms minimum) per message would make every routing decision slow by default. In a high-throughput multi-agent system, this is unacceptable for the 80% of messages that are trivially classifiable by rules.

### Why Not Approach A (Rules-only)?

The rule evaluator is the right **default** but will fail on nuance. The hybrid approach preserves all of its benefits while adding a safety valve for hard cases. Start with Approach A; graduate to C when the rule false-positive/negative rate becomes problematic.

### Runtime Evaluator Switching

All three evaluators implement the same interface. `AgentServer` accepts `{ "evaluator_type": "rule" | "llm" | "hybrid" }` via `PATCH /config` to switch at runtime. This means:

- **Development / testing**: use `rule` (fast, no API costs)
- **Production (low volume)**: use `llm` 
- **Production (high volume)**: use `hybrid`

---

## 9. File Inventory

```
agent_side/participation/
├── __init__.py           # Public API exports + single import convenience
├── types.py               # Shared dataclasses: RelayMessage, AgentContext,
│                          #   RoleConfig, ParticipationLevel
├── rule_evaluator.py      # Approach A: RuleEvaluator + make_rule_evaluator()
├── llm_evaluator.py       # Approach B: LLMClassifier + make_llm_evaluator()
└── hybrid_evaluator.py    # Approach C: HybridEvaluator + AmbiguityDetector
                             #   + make_hybrid_evaluator()
```

---

## 10. Open Questions & Future Work

1. **Observer buffer semantics** — When `OBSERVER` is returned, messages are buffered but not processed. Should they be: (a) processed after X messages accumulate, (b) processed on a timer, or (c) discarded? Need a policy.

2. **Evaluator composition** — Can multiple evaluators be chained (e.g. skill-match rules → LLM → fallback)? The current interface doesn't support this. A `CompositeEvaluator` would be a natural extension.

3. **OpenClaw harness visibility** — All three evaluators operate **outside** OpenClaw's agent process. They cannot see what OpenClaw has injected into the agent's system prompt. If evaluators need this context, it must be explicitly passed via `message.metadata` or a new `HarnessContext` field.

4. **Learning from feedback** — None of the three approaches currently support online learning (e.g. reinforcement learning from user responses to "should this have been skipped?"). This would require a feedback loop back into the rule engine or LLM prompt.

5. **Message metadata standardisation** — The evaluator relies on `message.metadata` carrying fields like `topic`, `skill`, `required_skill`. The relay/moderator must be updated to consistently populate these fields. Currently this is ad hoc.

---

*Checkpoint: research complete. All prototype files written to `agent_side/participation/`. Document written to `research/08-participation-evaluator-options.md`.*
