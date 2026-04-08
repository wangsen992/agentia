# Literature Review — Academic and Research Systems for Agent Composition

**Date:** 2026-04-07
**Researcher:** Jarvis (autonomous research)
**Coverage:** Agent architectures, skill/tool systems, memory models, capability frameworks, participation/routing

---

## 1. Agent Architectures

### The LLM Agent as Software Engineering Object

The academic literature increasingly treats AI agents not as language models but as **software engineering constructs** — systems with defined interfaces, state, and behavior. This reframing treats the LLM as the "reasoning engine" inside an architecture that handles memory, tools, goals, and execution.

Key reference: "Agentic AI with LangChain & LangGraph" (Codecademy, 2024) frames agents as graph-based runtimes where:
- The LLM is the cognitive processor
- Tools are graph nodes
- State is managed by the runtime
- Execution is deterministic (unlike pure LLM inference)

This matches our dimension model: the LLM is the runtime (Adapter in our model), and the architecture layers around it define Role, Memory, Skills, etc.

### Taxonomy of Agent Types

Research identifies several agent architectural patterns:

| Pattern | Description | Example |
|---------|-------------|---------|
| **ReAct agents** | Reasoning + Acting in loop; LLM generates reasoning trace and tool calls | LangChain, AutoGen |
| **Plan-then-execute** | LLM plans first, then executes steps | BabyAGI, LangChain Plan-and-Execute |
| **Hierarchical agents** | Manager agent decomposes tasks to sub-agents | AutoGen, Semantic Kernel group chat |
| **Tool-augmented agents** | LLM calls external functions as needed | Universal across all frameworks |
| **Memory-augmented agents** | External memory store (vector, KG, episodic) | MemGPT, AutoGen TeachableAgent |

### Agent as Cognitive System

The literature on "agentic" AI (AI Agent Index, MIT, 2024-2025) distinguishes agents from standard LLMs by four properties:
1. **Goal-oriented** — pursues defined objectives
2. **Environment-aware** — uses tools to interact with external systems
3. **Memory-enabled** — retains information across interactions
4. **Autonomously decisional** — can make choices without human intervention per step

These map to our dimensions: Goal-oriented → Role/Goal; Environment-aware → Skills/Tools; Memory-enabled → Memory/Knowledge; Autonomously decisional → Participation.

---

## 2. Skill and Tool Systems

### Tool Use as the Core Capability Primitive

Tool use is the most mature and well-studied aspect of agent capability systems. The literature is rich here.

**MCP (Model Context Protocol)** — Anthropic's November 2024 open-source standard — is the most significant recent development. It provides:
- A unified JSON-RPC interface for tool discovery
- Standardized authentication across external systems
- Dynamic tool loading on demand (preserves context by only loading relevant tools)
- Cross-platform: AI agents can use tools from databases, APIs, file systems through a single protocol

**ToolUniverse's Tool Discover** goes further — tools can be generated from natural language descriptions, suggesting a future of self-expanding tool registries.

### Skill as a Higher-Order Capability

Research on "Agent Skills" (e.g., "Agent Skills: A Data-Driven Analysis of Claude Skills for Extending Large Language Model Functionality", 2024) distinguishes **skills** from **tools**:

| | Tool | Skill |
|--|------|-------|
| Granularity | Single function call | Composed sequence of actions |
| Abstraction | Low-level | High-level |
| Example | `search_web(query)` | "Research a topic end-to-end" |
| LLM awareness | Direct call | LLM decides when/how to deploy |

This suggests our distinction (Skills as portable capabilities) is well-founded. A skill is a **capability contract** that the adapter implements in runtime-specific ways.

### Skill Registration and Discovery

Key research findings:
- **SkillsBench** (2024) — benchmark for evaluating skill performance across tasks; highlights that skills need evaluation frameworks
- **Reinforcement Learning for Self-Improving Agent with Skill Library** — agents can autonomously learn and manage skill libraries; suggests skills should be versioned and evaluable
- **ConAgents** ("Learning to Use Tools via Cooperative and Interactive Agents") — dedicated tool-selection agents; skills can be handled by specialized agents rather than a monolithic agent

### The Portability Problem

The literature consistently notes: **skills/tools are not portable across frameworks.** Each framework defines its own tool schema (OpenAI function calling, LangChain tool format, Semantic Kernel's `[KernelFunction]`, etc.). MCP is the first serious attempt at a cross-framework standard, but adoption is early.

**Implication for Agentia:** Designing a portable skill interface (our AgentAdapter's approach) is correct and needed, but the ecosystem lacks a standard to align with. This is both a risk and an opportunity.

---

## 3. Memory Architectures

### The Three-Level Memory Model

Academic literature converges on a three-level memory architecture for AI agents:

**Short-Term Memory (STM) / Working Memory:**
- Maintains immediate context within a session
- Rolling buffer of recent messages/tool outputs
- Limited by context window size
- Discarded at session end
- Implementation: context window, message list

**Long-Term Memory (LTM) / Persistent Memory:**
- Survives session boundaries
- Enables personalization and learning from past interactions
- Three subtypes (inspired by human cognition):
  - **Episodic** — specific past events and interactions ("what happened when")
  - **Semantic** — structured facts and concepts ("knowing that")
  - **Procedural** — skills and learned behaviors ("knowing how")

**Knowledge (Distinct from Memory):**
- The literature increasingly separates **memory** (experience of the agent) from **knowledge** (facts the agent has access to)
- Knowledge typically implemented via RAG — vector store + semantic search
- Memory is learned; knowledge is retrieved

### Key Reference: LOCOMO Benchmark (2024)

The LOCOMO (Long-term Conversational Memory) benchmark established that:
- Memory architectures must be evaluated on: retention, recall accuracy, interference, temporal ordering
- Vector-only approaches underperform on multi-hop reasoning
- Graph-based memory improves factual accuracy in constrained contexts
- Unified database approaches (PostgreSQL + pgvector) reduce operational complexity

### Memory as First-Class Component (2025-2026)

By 2026, memory is recognized as a distinct architectural layer with its own research literature:
- **Mem0**, **Zep**, **Letta**, **Cognee** — dedicated memory infrastructure frameworks
- Graph RAG matures from experimental to production (entity extraction, relationship tracking)
- "Agentic RAG" — agents decide dynamically when to retrieve, what to ask, how to refine queries

### Memory vs. Knowledge — The Definitive Distinction

Based on the literature:
- **Memory** = agent's accumulated experience (episodes, preferences, learned procedures)
- **Knowledge** = external facts the agent can access (documents, databases, RAG sources)
- Both use vector stores for semantic retrieval, but semantics differ
- Memory is written by the agent's own actions; Knowledge is written by external sources

**Implication for Agentia:** Our model (Memory + Knowledge as separate required dimensions) is supported by literature. They share infrastructure (vector DB) but have different semantic origins and update patterns.

---

## 4. Capability Frameworks

### How Frameworks Model Agent Capabilities

The literature reveals two dominant models:

**Tier 1 — Direct Tool List:**
- Agent has a flat list of tools
- LLM selects from available tools in each step
- Simple but scales poorly as tool count grows

**Tier 2 — Organized Capability Groups:**
- Tools grouped into skills/capabilities
- Skills have metadata (description, preconditions, outputs)
- LLM reasons about capabilities before selecting specific tools
- CrewAI's Action/Context split is the best example of this

**Tier 3 — Dynamic Skill Discovery:**
- Agent can discover new capabilities at runtime
- MCP's tool search is an example
- Agent evaluates its own skill gaps and acquires new tools
- Most research-aligned but least mature

### Capability Registration Patterns

Research identifies three registration patterns:

1. **Static registration** — tools registered at agent creation time (most frameworks)
2. **Lazy registration** — tools registered on first use (MCP's on-demand loading)
3. **Dynamic discovery** — agent searches a registry and registers new tools autonomously

### Open Problem: Cross-Framework Skill Standards

No academic paper or standard has yet established a universal skill interface. MCP is the most promising candidate but is:
- Anthropic-led (not a neutral body)
- Early adoption (2024)
- Focused on tools, not the higher-level skill concept

This represents a genuine gap in the field that Agentia could contribute to.

---

## 5. Participation and Routing Models

### How Agents Decide to Participate

This is the most underdeveloped area in both literature and frameworks. The research identifies several approaches:

**Explicit addressing** (most common):
- Message includes target agent ID
- No participation decision needed — message goes directly to addressed agent
- Limitation: requires a router/orchestrator that knows agent capabilities

**Topic-based routing:**
- Messages tagged with topics
- Agents subscribe to topics
- Agents receive messages matching their subscriptions
- Example: event bus pattern in multi-agent systems

**Intent-based routing:**
- Incoming message analyzed for intent
- Matching agent selected based on capability alignment
- Requires intent classification as a sub-system

**Auction/bidding:**
- Task published to agent pool
- Agents bid based on their capabilities and current load
- Most complex but most flexible
- Used in market-based multi-agent systems

### Research Gap: Participation Decision Function

The literature does not have a well-established formal model for what we're calling the "participation evaluator." The concept of an explicit function that takes `(message, agent_context) → participation_level` is not prominent in existing research.

Most systems rely on:
- Orchestrator/hub to route correctly (hierarchical)
- Topic subscription (pub/sub)
- Explicit targeting (Moderator pattern)

**Implication for Agentia:** The participation model we've discussed — a function that evaluates whether an agent should engage — is genuinely novel territory. This is worth explicitly noting in our design.

### Multi-Agent Coordination Mechanisms

Literature identifies these coordination mechanisms:
- **Contract Net Protocol** — manager publishes task; agents bid; manager awards
- **Market-based** — agents trade resources/tasks
- **Blackboard systems** — shared knowledge space; agents contribute when relevant
- **Behavior-based** — agents follow predefined rules; emergence from rule interaction

For federated AI agents specifically, the literature focuses on:
- Message routing topologies (centralized, hierarchical, decentralized)
- Communication protocol design
- Trust and authentication between agents

---

## 6. Summary of Literature Findings

### Strongly Supported by Literature

| Our Dimension | Literature Support |
|---------------|-------------------|
| Role | Universal — all frameworks have role/persona concept |
| Adapter (runtime) | Universal — frameworks are runtime-specific |
| Skills as portable | Supported at tool level; skill-as-higher-abstraction emerging |
| Memory (required) | Strongly supported; three-level model (STM/LTM/Knowledge) |
| Knowledge (required) | Distinct from memory; RAG literature is mature |
| Access Level | Sparse — implicit in some frameworks; Claude SDK explicit confirmation is best model |

### Supported but Less Mature

| Our Dimension | Literature Support |
|---------------|-------------------|
| Skills portability | Tool portability studied; skill portability is emerging (MCP) |
| Participation as function | Novel territory; no established formal model |

### Novel / Not in Literature

| Our Concept | Status |
|------------|--------|
| Participation evaluator function | Not prominent in existing research |
| Universal skill interface | Gap in field; MCP is first attempt |
| Federated multi-agent with this architecture | Research area but specific design not covered |

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Literature review covering agent architectures (4 patterns), skill/tool systems (MCP, ToolUniverse, portability gap), memory (3-level STM/LTM/Knowledge model with LOCOMO benchmark), capability frameworks (3 tiers), and participation/routing (4 mechanisms + research gap on explicit participation functions).
next_trigger: Unit 3 (comparative evaluation) — waiting for Unit 2 sub-agent completion; parent will run comparative evaluation after both units complete
```
