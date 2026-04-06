# SPEC: Adapter-Specific Container Images — 2026-04-05

## Decision

Each agent adapter owns its container image definition. The Dockerfile is an implementation detail of the adapter, not a universal artifact.

## Rationale

With the AgentAdapter abstraction, different agent runtimes may have different dependencies:
- OpenClaw adapter needs: Node.js, npm, openclaw npm package
- pi-agent adapter needs: Node.js, pi-agent npm package
- AutoGen adapter needs: Python, autogen package, possibly LiteLLM

These are different stacks. One universal Dockerfile either wastes resources (installing everything) or can't express the differences cleanly.

## Model

```
adapters/
├── openclaw/
│   ├── adapter.py         ← OpenClawAdapter
│   └── Dockerfile         ← adapter-specific: Node + openclaw
│
├── pi/
│   ├── adapter.py         ← PiAgentAdapter
│   └── Dockerfile         ← adapter-specific: Node + pi-agent
│
└── autogen/
    ├── adapter.py          ← AutoGenAdapter
    └── Dockerfile          ← adapter-specific: Python + autogen
```

Each adapter class may declare:
```python
class OpenClawAdapter(AgentAdapter):
    DOCKER_IMAGE = "agentia/openclaw:latest"   # which image this adapter uses
    # or for local builds:
    DOCKERFILE = "adapters/openclaw/Dockerfile"
```

## Factory Integration

`get_adapter("openclaw")` would:
1. Check if image is built
2. If not, build from the adapter's Dockerfile
3. Start a container from that image
4. Return the adapter instance connected to that container

## Current Status

Only OpenClaw adapter exists. The current `Dockerfile` at repo root is the OpenClaw-specific image. It lives at `containers/Dockerfile.openclaw` when pi-agent is added.

## Why Not Multi-Stage / Shared Layers Now

Premature complexity. Extract shared base when:
- Two or more adapters actually exist
- Common dependencies are genuinely shared
- The duplication is painful enough to warrant abstraction

Until then: simple per-adapter Dockerfiles.
