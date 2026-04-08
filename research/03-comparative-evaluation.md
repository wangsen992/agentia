# Comparative Evaluation — Single Agent Composition Model

**Date:** 2026-04-07
**Based on:** Framework Survey (Unit 1) + Literature Review (Unit 2)
**Subject:** Our 7-dimension single agent composition model

---

## The Model Under Review

```
Core Dimensions (required):
  Role         — who the agent is
  Adapter      — how it runs (runtime)
  Access Level — what it can touch (permissions)
  Memory       — how it remembers
  Knowledge    — what it knows (RAG sources)

Optional Dimensions:
  Skills       — portable capability interface
  Participation — when it gets called (intent evaluator)
```

---

## Finding 1: Role — Well-Supported, Framework-Defined

**Status:** ✅ Confirmed by both survey and literature

Every framework has an explicit role/persona concept. CrewAI's is the most detailed (Role + Goal + Backstory), but all frameworks agree that an agent needs an identity.

**Refinement needed:** Our "Role" is underspecified. It should include:
- **Persona** — who the agent is (SOUL equivalent)
- **Goal** — what the agent is trying to achieve (individual objective)
- **Backstory** — context that shapes how the agent approaches problems

CrewAI's three-field model (role, goal, backstory) is empirically the most well-designed. We should adopt it as the structure for Role.

**Gap in our model:** Role currently only mentions "SOUL/prompt template." We should formalize it as a structured object:
```json
{
  "role": {
    "persona": "string",
    "goal": "string", 
    "backstory": "string"
  }
}
```

---

## Finding 2: Adapter — Universal but Under-Abstracted

**Status:** ⚠️ Confirmed, but abstraction challenge

All frameworks are runtime-specific. AutoGen assumes OpenAI-compatible LLMs; Claude Agent SDK assumes Anthropic; Semantic Kernel provides multi-runtime abstractions but they're heavy.

**Our model correctly identifies this as a dimension.** The AgentAdapter interface (prompt in → response out) is the right abstraction.

**Refinement:** Literature shows that adapter implementations vary significantly:
- AutoGen agents call tools natively through model function calling
- Claude Agent SDK uses a specific tool-calling protocol with on-demand loading
- Semantic Kernel uses `[KernelFunction]` decorators

The "prompt in → response out" abstraction may be too thin. We may need to define a richer adapter contract:
- `send(prompt) → str` (basic)
- `send_stream(prompt) → Iterator[str]` (streaming)
- `healthcheck() → bool`
- `tool_schema() → dict` (what tools does this adapter expose?)

The tool schema question is important — it connects Adapter to Skills. If the adapter exposes a tool schema, Skills become portable across adapters that expose compatible schemas.

---

## Finding 3: Access Level — Mostly Absent, Needs Design

**Status:** ❌ Gap in frameworks, gap in our model

Access level (permissions, sandboxing) is largely absent from framework design. The notable exception is Claude Agent SDK's explicit confirmation model:
- Certain actions (file deletion, network calls) require explicit confirmation
- Every tool invocation is logged
- Principle of least privilege

The literature on multi-agent systems discusses security and authentication between agents, but the internal access control model (what can an agent do to its own environment) is underexplored.

**Our model has this as a dimension, which is forward-thinking.** Frameworks don't model this at all — it's typically handled at the infrastructure level (Docker sandbox, container permissions).

**Recommendation:** Keep Access Level as a dimension but design it carefully:
- **No Access** — no external resources
- **Read-Only** — can read files, APIs, but no writes
- **Standard** — can read and write within workspace
- **Privileged** — can modify system, make network calls, etc.
- **Explicit Confirm** — Claude-style: sensitive actions pause for human approval

---

## Finding 4: Memory — Well-Understood, Three-Level Model

**Status:** ✅ Confirmed and well-supported

The literature is mature here. Three-level model:
- **Short-term** — session-scoped, rolling context
- **Long-term episodic** — past events and interactions
- **Long-term semantic** — structured facts and concepts

**Refinement for our model:** Memory should explicitly support these three levels:

```json
{
  "memory": {
    "short_term": { "type": "buffer", "max_tokens": 50000 },
    "long_term": {
      "type": "vector | graph | unified",
      "episodic": { "enabled": true, "retention": "30d" },
      "semantic": { "enabled": true, "index": "shared_kb" }
    }
  }
}
```

**Gap in our current model:** We don't distinguish episodic vs semantic memory. We also don't specify how memory is updated (who writes to it). Literature suggests:
- Memory is written by the agent's own actions (tool calls, conversation turns)
- Knowledge is written by external sources (RAG ingestion)

---

## Finding 5: Knowledge — Required but Design Varies

**Status:** ✅ Confirmed, but implementation varies widely

Knowledge (RAG from documents, databases) is treated differently across frameworks:
- **LangChain:** RAG via retriever + chat completion; memory is separate
- **Semantic Kernel:** Vector store connectors + Kernel Memory service
- **Vertex AI:** Managed RAG via Vertex AI Search
- **AutoGen:** Integration with MemGPT, Zep, Mem0 for knowledge
- **CrewAI:** Explicit "Knowledge" as Context Capability alongside Skills

**Our model correctly treats Knowledge as required (every agent has some relationship to external knowledge, even if null).**

**Refinement:** Knowledge should be explicitly scoped:
- **Sources:** what document/database collections are available
- **Retrieval:** how is relevant context fetched (top-k, threshold, hybrid)
- **Update policy:** can the agent write to knowledge, or only read?

CrewAI's Context Capabilities model (Skills + Knowledge) is clean — Knowledge shapes how the agent thinks; Skills shape what it can do. We should adopt this framing.

---

## Finding 6: Skills — Most Underspecified Dimension

**Status:** ⚠️ Concept confirmed, but our implementation needs work

Skills as portable capability interfaces are supported by literature (Agent Skills research, MCP), but:
- No framework has a true portable skill interface
- MCP is the best attempt but focuses on tools, not composite skills
- Skills vs. tools distinction is still being formalized

**Our model correctly identifies Skills as optional-but-powerful.**

**Refinement:** Skills should be versioned and evaluable (per SkillsBench research):
```json
{
  "skill": {
    "name": "web_search",
    "version": "1.0",
    "interface": { "query": "str" },
    "adapter_impl": { "type": "openclaw", "tool": "websearch" }
  }
}
```

**Key gap:** How do Skills connect to the Adapter? We need a protocol:
- Adapter exposes which Skill interfaces it implements
- Agent config references Skill names
- At runtime, AgentServer binds Skill name → Adapter's implementation

This is essentially a plugin system with a well-defined interface contract.

---

## Finding 7: Participation — Novel and Needed

**Status:** 🔵 Novel, not in existing frameworks or literature

This is the most innovative part of our model, and the least supported by existing work.

The literature on participation/routing focuses on:
- Centralized routing (orchestrator knows capabilities)
- Topic subscription (agents subscribe to topics)
- Explicit addressing (Moderator sends to specific agent)

No framework has an explicit "should this agent participate?" function evaluated at message delivery time.

**Our intent evaluator concept is genuinely novel.** It fills a gap:
- In federated systems without a central Moderator, agents need to decide whether to engage with a message
- Topic subscription is too coarse (all messages on topic → all subscribers notified)
- Explicit addressing requires a capable router

**Recommendation:** Pursue this as a distinguishing feature of Agentia. The participation evaluator should be:
```python
def evaluate(message: RelayMessage, context: AgentContext) -> ParticipationLevel:
    # topic_match: is this message's topic relevant?
    # capability_match: does this agent have skills for this?
    # intent_classification: does the message intent match agent expertise?
    # current_load: is agent available?
    return "active" | "observer" | "skip"
```

This requires investment in intent classification, but the literature on intent detection in MAS is applicable here.

---

## Finding 8: Missing Dimension — Session Management

**Status:** ❌ Not in our model, gap identified

Our model doesn't include a Session dimension — how the agent manages its runtime session. The literature and frameworks all have some concept of:
- Session ID (for resumption)
- Session history (what happened in this session)
- Session forking (branching a conversation)

This is separate from Memory:
- **Session** = runtime working context (what the agent is doing right now)
- **Memory** = persistent knowledge (what the agent has learned)

**Recommendation:** Add Session as a required sub-dimension of Adapter:
```json
{
  "session": {
    "id_prefix": "analyst-001",
    "fork_enabled": true,
    "resume_enabled": true
  }
}
```

---

## Finding 9: Missing Dimension — Lifecycle/State

**Status:** ❌ Not in our model, gap identified

No framework or literature captures the lifecycle state of an agent (not the agent's process, but its organizational state):
- **Dormant** — exists but not participating
- **Active** — running and processing
- **Suspended** — paused, can resume
- **Decommissioned** — no longer in use

This is relevant for federated systems where agents may come and go, and where the organization needs to know the state of its agents.

**Recommendation:** Add Lifecycle as a required sub-dimension:
```json
{
  "lifecycle": {
    "state": "active",  // dormant | active | suspended | decommissioned
    "last_active": "2026-04-07T..."
  }
}
```

---

## Overall Assessment

### Dimensions We Got Right

| Dimension | Assessment |
|-----------|------------|
| Role | ✅ Correct — formalize as persona/goal/backstory structure |
| Adapter | ✅ Correct — keep but expand adapter contract |
| Access Level | ✅ Correct — forward-thinking; design carefully |
| Memory | ✅ Correct — adopt 3-level model (STM/episodic/semantic) |
| Knowledge | ✅ Correct — treat as required, design retrieval policy |

### Dimensions Needing Work

| Dimension | Assessment |
|-----------|------------|
| Skills | ⚠️ Correct concept, underspecified; needs versioning, interface contract, adapter binding |
| Participation | 🔵 Novel; requires intent evaluator design; literature gap |

### Missing Dimensions

| Gap | Assessment |
|-----|------------|
| Session management | ❌ Required — runtime session vs. persistent memory distinction |
| Lifecycle state | ❌ Required — organizational state of agent |

---

## Revised Composition Model

```
REQUIRED:
  role           { persona, goal, backstory }
  adapter        { type, config, session, tool_schema }
  access_level   none | read_only | standard | privileged | explicit_confirm
  memory         { short_term, long_term: { episodic, semantic } }
  knowledge      { sources, retrieval, update_policy }

OPTIONAL:
  skills         [{ name, version, interface, adapter_impl }]
  participation  { evaluator_fn, default_level }
```

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Comparative evaluation against 7 frameworks and literature. Finds Role, Adapter, Access Level, Memory, Knowledge all confirmed and well-grounded. Skills concept confirmed but underspecified. Participation evaluator is novel territory. Two gaps identified: Session management and Lifecycle state, both missing from current model. Full revised model produced.
next_trigger: Unit 4 (synthesis + recommendations) — parent agent synthesis pending
```
