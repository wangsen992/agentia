# Synthesis and Recommendations — Single Agent Composition Model

**Date:** 2026-04-07
**Based on:** Units 1-3 (Framework Survey, Literature Review, Comparative Evaluation)
**Output:** Issue-ready content for Agentia GitHub

---

## Executive Summary

After surveying 7 agent frameworks and the academic literature, our 7-dimension single agent composition model holds up well. Two dimensions need expansion, two are missing entirely, and one represents genuinely novel territory that existing frameworks and literature do not cover.

The most important finding: **access level, memory, and knowledge are correctly treated as core (required) dimensions** — frameworks either handle them poorly or not at all. Agentia's explicit treatment of these is a strength.

---

## The Revised Composition Model

### Required Dimensions

```json
{
  "agent_id": "string",
  
  "role": {
    "persona": "string — who the agent is (SOUL equivalent)",
    "goal": "string — what the agent is trying to achieve",
    "backstory": "string — context shaping how the agent approaches problems"
  },
  
  "adapter": {
    "type": "openclaw | claude_code | custom",
    "config": { ... },
    "session": {
      "id_prefix": "string",
      "fork_enabled": true,
      "resume_enabled": true
    }
  },
  
  "access_level": "none | read_only | standard | privileged | explicit_confirm",
  
  "memory": {
    "short_term": { "type": "buffer", "max_tokens": 50000 },
    "long_term": {
      "episodic": { "enabled": true, "retention": "30d" },
      "semantic": { "enabled": true, "backend": "vector | graph | unified" }
    }
  },
  
  "knowledge": {
    "sources": ["collection_1", "collection_2"],
    "retrieval": { "top_k": 5, "threshold": 0.7 },
    "update_policy": "read_only | agent_contributed"
  }
}
```

### Optional Dimensions

```json
{
  "skills": [
    {
      "name": "web_search",
      "version": "1.0",
      "interface": { "query": "str" },
      "adapter_impl": { "type": "openclaw", "tool": "websearch" }
    }
  ],
  
  "participation": {
    "evaluator": "function_name",
    "default": "active"
  }
}
```

### Missing — Add to Model

```json
{
  "lifecycle": {
    "state": "dormant | active | suspended | decommissioned",
    "last_active": "ISO timestamp"
  }
}
```

---

## Key Recommendations

### Recommendation 1: Adopt CrewAI's Three-Field Role Structure

Role currently says "SOUL/prompt template." This is too loose. Adopt CrewAI's empirically validated structure:
- `persona` — who the agent is
- `goal` — what the agent wants to achieve individually
- `backstory` — context that shapes problem approach

This is the most well-designed role definition in the surveyed frameworks.

### Recommendation 2: Expand the AgentAdapter Contract

The "prompt in → response out" abstraction may be too thin. The adapter should expose:
- `send(prompt) → str`
- `send_stream(prompt) → Iterator[str]`
- `healthcheck() → bool`
- `tool_schema() → dict` — what tools does this adapter expose?

The tool schema is critical for Skills portability. If the adapter publishes what it implements, Skills can bind at runtime.

### Recommendation 3: Design Access Level Against Claude Agent SDK's Model

Access level is the most forward-thinking dimension in our model. The literature shows no one else handles it. Use Claude Agent SDK's confirmation model as the reference:
- `none` — sandboxed, no external access
- `read_only` — read files/APIs but no writes
- `standard` — normal workspace access
- `privileged` — system modification, network calls
- `explicit_confirm` — sensitive actions pause for human approval; everything logged

### Recommendation 4: Implement Three-Level Memory

Memory is well-understood in the literature. Implement all three levels:
- **Short-term** — rolling context buffer within session
- **Long-term episodic** — past events, conversations, tool invocations
- **Long-term semantic** — facts, concepts, learned patterns

Design the episodic/semantic split carefully — they have different update patterns:
- Episodic: written by agent's own actions
- Semantic: written by RAG ingestion or agent summarization

### Recommendation 5: Design the Participation Evaluator as a Distinguishing Feature

The participation evaluator function is the most novel part of our model. Literature and frameworks don't have this. It deserves investment:
- Define the function signature clearly
- Build an intent classification capability
- Support composition: topic_match + capability_match + load check

This enables federated multi-agent without a central Moderator — a genuine research contribution.

### Recommendation 6: Add Lifecycle as a Required Dimension

Lifecycle state (dormant/active/suspended/decommissioned) is missing. For federated systems, the organization needs to know which agents exist and their current state. This is not the same as process health (healthcheck) — it's the organizational state of the agent resource.

### Recommendation 7: Build a Skill Registry

Skills as portable capability interfaces are the right abstraction (confirmed by literature), but no framework has implemented them properly. Design a skill registry:
- Skills are versioned
- Each skill has an interface contract
- Adapter implementations bind to skill interfaces
- Agents declare which skills they support

This enables runtime-swappable implementations and cross-agent skill sharing.

---

## Open Questions

1. **How does Session interact with Conversation ID?** When an agent participates in a new conversation, does it fork its session or create a new one?
2. **How are Skills discovered?** Static registration at config time, or dynamic discovery from a registry?
3. **Who owns the Participation Evaluator?** Is it per-agent (each agent evaluates for itself) or per-relay (BaseRelay evaluates before sending)?
4. **How does Access Level compose with Skills?** If an agent has a "web_search" skill but `access_level: none`, does it work?
5. **Should Knowledge be typed?** Different collections might have different schemas. Should the knowledge definition include a schema?

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Final synthesis producing revised composition model with full JSON schema, 7 specific recommendations, and 5 open questions for Agentia issue. Core model validated: Role/A/Access Level/Memory/Knowledge confirmed, Skills needs work, Participation is novel.
next_trigger: File issue to agentia repo
```
