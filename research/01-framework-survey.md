# Framework Survey — Single Agent Composition in Existing Agent Systems

**Date:** 2026-04-07
**Researcher:** Jarvis (autonomous research)
**Coverage:** AutoGen, CrewAI, LangChain/LangGraph, Semantic Kernel, Claude Agent SDK, IBM Bee/Maya, Vertex AI Agent Builder

---

## 1. Microsoft AutoGen / AutoGen Studio

### Agent Configuration
AutoGen agents are defined primarily through:
- **LLM Configuration** — API endpoints, model choice
- **System message** — persona, capabilities, instructions
- **Agent type** — determines interaction pattern

AutoGen v0.4 (early 2025) introduced a complete redesign with an event-driven architecture:
- **AutoGen Core** — foundational event-driven building blocks
- **AutoGen AgentChat** — high-level task-driven API on top of Core
- AgentStudio offers a low-code drag-and-drop GUI for designing multi-agent workflows

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Role | Agent type (ConversableAgent, AssistantAgent, UserProxyAgent) |
| Persona | `system_message` string |
| Tools | `autogen_core.tools` module; custom tool decorators; MCP integration |
| Memory | `ListMemory` (short-term); `TeachableAgent` (long-term, vector); MemGPT, Zep, Mem0 integrations |
| Execution | Code executor types (Docker, local) for sandboxing |

### Capability Registration
Tools registered via `@tool` decorator or `autogen_core.tools` module. MCP (Model Context Protocol) enables external resource access. No formal skill registry — tools are ad-hoc per agent.

### Memory Architecture
- **Short-term:** Message list, appended to model context
- **Long-term:** TeachableAgent with vector embeddings; MemGPT for enhanced context management; Zep for knowledge graph from conversations; Mem0 for cloud/local memory

### Instantiation
Code-based: `ConversableAgent("name", llm_config=..., system_message=...)`

---

## 2. CrewAI

### Agent Configuration
CrewAI has the most well-defined single-agent schema. Every agent has explicit fields for:

```python
Agent(
    role="Financial Analyst",
    goal="Produce accurate market analysis",
    backstory="Expert in market trends...",
    llm=...,
    tools=[...],
    memory=True,
    max_iter=...,
    verbose=True,
    allow_delegation=False,
    cache=True,
    max_rpm=...,
)
```

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Role | `role` string (specific profession/expertise) |
| Goal | `goal` string (individual objective) |
| Backstory | `backstory` string (personality, expertise context) |
| LLM | `llm` field — model or provider |
| Tools | `tools` list — BaseTool instances |
| Memory | `memory: bool | Memory instance` — per-agent or crew-level |
| Participation | `allow_delegation` bool — can this agent delegate? |
| Execution limits | `max_iter`, `max_execution_time`, `max_rpm` |

### Capability Registration — Split into Two Tiers
CrewAI explicitly splits capabilities into:

**Action Capabilities** (what the agent can *do*):
- Tools (web search, file ops, API calls, code execution)
- MCP Servers — remote tool servers via Model Context Protocol
- Apps — platform integrations

**Context Capabilities** (what shapes how the agent *thinks*):
- **Skills** — domain expertise and guidelines, injected into prompt
- **Knowledge** — semantic search/RAG from documents, files, URLs

This two-tier split (action vs. context) is notable and aligns well with the Skills/Memory/Knowledge distinction in our model.

### Memory Architecture
- Per-agent memory: `memory=True` creates a default `Memory()` instance
- Memory uses LLM to analyze content for scope/categories/importance
- Crews can share unified memory; agents can have private scoped views

### Instantiation
Code or YAML. CrewAI AMP offers a visual builder. Agents belong to a Crew; crews define orchestration (sequential, parallel, hierarchical).

---

## 3. LangChain / LangGraph

### Agent Configuration
LangChain agents are configured via:
```python
create_agent(
    model=...,
    tools=[...],
    system_prompt=...,
    state_schema=AgentState,  # TypedDict extending AgentState
)
```

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Model | `model` — the LLM |
| Tools | `tools` list; ToolNode for advanced configs |
| System Prompt | `system_prompt` string or prompt template |
| Middleware | `middleware` list — intercept/modify behavior |
| State | `state_schema` — custom TypedDict extending AgentState |
| Runtime config | `RunnableConfig` — tags, metadata, callbacks, timeout, recursion_limit, max_concurrency |

### Capability Registration
Tools via `@tool` decorator (simple) or `ToolNode` (production). LangChain hub for prompt templates. No formal skill registry beyond tool definitions.

### Memory Architecture
Memory types:
- **Short-term:** `messages` key in AgentState, persisted via `checkpointer`
- **Buffer Memory** — full conversation history
- **Buffer Window Memory** — N most recent interactions
- **Entity Memory** — extracts entities into entity store
- **Conversation Summary Memory** — LLM-generated summary
- **Conversation Knowledge Graph Memory** — external KG integration

### Instantiation
LangGraph API — agents are graph-based runtimes with persistence, streaming, human-in-the-loop, checkpointing.

---

## 4. Microsoft Semantic Kernel

### Agent Configuration
Semantic Kernel agents are built on the Kernel (orchestration container):
```python
kernel = Kernel()
kernel.add_service(...)
# Plugins added with [KernelFunction] decorators
agent = ChatCompletionAgent(kernel=kernel, ...)
```

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Kernel | Central orchestrator; holds services, plugins, memory |
| Plugins | Groups of functions exposed to AI; defined via `[KernelFunction]` |
| Memory | Volatile (short-term) and non-volatile (persistent/vector) |
| Services | AI models (OpenAI, Azure OpenAI, HuggingFace, etc.) |
| Orchestration | Planner or direct invocation |

### Capability Registration
**Plugins (Skills):**
- **Native plugins** — C#/Python/Java functions with `[KernelFunction]` decorator
- **OpenAPI plugins** — from OpenAPI specs
- **MCP plugins** — from MCP servers
- 2024 addition: Logic Apps as plugins (no-code integration)

### Memory Architecture
- **Volatile Memory** — temporary, session-scoped
- **Non-Volatile Memory** — persistent, long-term
- **Vector Store abstractions** — recommended over legacy Memory Store; RAG-ready
- **Kernel Memory Service** — open-source RAG service (separate from core SK)

### Instantiation
SDK-based: C#, Python, Java. `ChatCompletionAgent`, `FunctionCallingAgent`, etc. on top of Kernel.

---

## 5. Anthropic Claude Agent SDK

### Agent Configuration
The Claude Agent SDK (formerly Claude Code SDK) is notable for being the runtime that powers Claude Code itself.

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Tools | Built-in: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, AskUserQuestion |
| Memory | `memory` tool (beta, 2025) — client-side file-based `/memory` directory; session-based context |
| Skills | Markdown files in workspace (`skills/` directory) |
| Context | `CLAUDE.md` files for project-level context |
| Session | Session ID for resumption; session forking |
| Configuration | Filesystem-based, layered (user/project/local) |

### Capability Registration
- **Tool Search Tool (2025)** — discovers and loads tools on-demand; preserves context by only adding tool defs when relevant
- **Programmatic Tool Calling** — orchestrate tools via Python scripts rather than individual API calls
- **Tool Use Examples** — standardized demonstrations of correct invocation patterns

### Memory Architecture
- **Session memory:** Full conversation history within a session
- **Memory Tool (beta):** Client-side `/memory` directory; agents call memory tools, application executes locally
- **Context files:** Manual Markdown/text files created by developer

### Instantiation
SDK-based: Python or TypeScript. Configuration via filesystem (`skills/`, `CLAUDE.md`, project config files).

---

## 6. IBM Bee / Maya Agent

### Configuration
IBM's agent offerings (Bee runtime, Maya Agent) are enterprise-focused. Public documentation is less detailed than other frameworks.

### Dimensions (inferred from public docs)
| Dimension | How defined |
|-----------|-------------|
| Role | Agent persona and specialization |
| Tools | Enterprise integrations (IBM cloud services, data sources) |
| Memory | Enterprise memory/knowledge management |
| Orchestration | Orchestrator agent type for managing sub-agents |

### Notable
IBM's approach emphasizes enterprise security, compliance, and auditability. Agents are designed for regulated industries. The Maya Agent is the more recent, agent-oriented layer.

### Memory Architecture
Enterprise-focused: likely includes persistent memory, knowledge base integration, and audit logging. Specifics not well-documented publicly.

### Instantiation
IBM Cloud / Watsonx platform. Not open-source; enterprise deployment only.

---

## 7. Vertex AI Agent Builder (Google)

### Agent Configuration
Google's managed agent platform on Vertex AI.

### Dimensions
| Dimension | How defined |
|-----------|-------------|
| Model | Vertex AI model selection (Gemini, etc.) |
| Tools | Vertex search, conversation tools; custom tool functions |
| Knowledge | Vertex AI Search integration — RAG from managed knowledge bases |
| Session | Managed session by Vertex; context window managed automatically |
| Data stores | Ground with enterprise data via Vertex RAG Engine |

### Notable
Vertex AI Agent Builder is a managed platform rather than a code framework. Agents are configured through the Google Cloud console or APIs. Integrates directly with Google's search and knowledge management infrastructure.

### Memory Architecture
Managed by Vertex — session context handled automatically. RAG via Vertex AI Search or Vertex RAG Engine.

### Instantiation
Google Cloud Console or REST API. Managed service; no self-hosted option.

---

## Summary Comparison Table

| Framework | Role Dimension | Memory | Capabilities | Participation | Config Medium |
|-----------|----------------|--------|--------------|---------------|---------------|
| AutoGen | Agent type + system message | Short + long (vector) | Tools + MCP | Via agent type | Code |
| CrewAI | Role + Goal + Backstory | Per-agent or crew | Action + Context caps | allow_delegation flag | Code or YAML |
| LangChain | System prompt | Messages + checkpointer | Tools | Middleware/hooks | Code |
| Semantic Kernel | Kernel + plugins | Volatile + vector store | Native + OpenAPI + MCP | Planner | SDK code |
| Claude Agent SDK | Tools + skills files | Session + Memory tool (beta) | Built-in + programmatic | Explicit confirmation | Filesystem |
| IBM Bee/Maya | Persona + specialization | Enterprise memory | Enterprise integrations | Orchestrator pattern | Cloud platform |
| Vertex AI | Model + tools | Managed sessions | Vertex search + custom | Managed | GCP Console/API |

---

## Key Observations

### What frameworks get right:
1. **Explicit role definition** — all frameworks have some concept of role/persona (CrewAI's Role/Goal/Backstory is the most explicit)
2. **Tool as capability unit** — universal across all frameworks
3. **Memory as distinct from tools** — most frameworks distinguish memory from tools (though implementations vary widely)
4. **Code-based configuration** — all frameworks use code or config files; none have truly portable agent definitions

### What frameworks get wrong or leave ambiguous:
1. **Participation/routing** — mostly implicit or hardcoded. No framework has an explicit "should this agent participate in this message?" mechanism
2. **Portable skill registries** — skills/tools are ad-hoc per framework. No cross-framework skill standard
3. **Adapter abstraction** — frameworks are tightly coupled to their own runtime. Claude Agent SDK assumes Anthropic; AutoGen assumes OpenAI-compatible LLMs
4. **Knowledge vs. memory distinction** — often blurred. Is RAG "memory" or "knowledge"?
5. **Access level / permissions** — largely absent from framework design (except Claude Agent SDK's explicit confirmation model)

---

## CHECKPOINT_FIELDS
```
status: done
output_summary: Comprehensive survey of 7 agent frameworks covering agent configuration dimensions, memory architectures, capability registration patterns, and instantiation methods. Key finding: frameworks are explicit about role/tools/memory but ambiguous about participation, skills portability, and access control.
next_trigger: Unit 2 (literature review) parallel sub-agent spawned; Unit 3 (comparative evaluation) queued after Units 1+2 complete
```
