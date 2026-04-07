# SPEC 009: AgentServer API Specification

## Goal

Document the HTTP API exposed by AgentServer on the agent side. This is the contract between the host-side `HostContainerBackend` and the agent-side `AgentServer`.

---

## Overview

AgentServer is an HTTP server running inside each agent container (or on each remote host). It exposes two planes:

1. **Control Plane** — management endpoints for config, status, restart
2. **Host Messaging Plane** — endpoints for sending messages to the agent

```
┌─────────────────────────────────────────────────────────────────┐
│ AgentServer (inside container)                                   │
│                                                                 │
│  Control Plane              Host Messaging Plane                 │
│  ─────────────              ───────────────────                 │
│  GET  /config               POST /message                       │
│  PUT  /config               POST /message/async                │
│  PATCH /config              GET  /response/{correlation_id}    │
│  GET  /status                                            │
│  POST /restart               Internal                          │
│  GET  /metrics               GET  /inbox                       │
│                              POST /response (internal)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Control Plane

### GET /config

Read current AgentServer configuration.

**Response 200:**
```json
{
  "host": "0.0.0.0",
  "port": 8080,
  "delivery": "inbox",
  "poll_interval": 2.0,
  "inbox_dir": "/workspace/inbox",
  "responses_dir": "/workspace/inbox/responses",
  "agent_timeout": 120,
  "log_level": "info"
}
```

---

### PUT /config

Replace entire configuration.

**Request body:** Full `AgentServerConfig` object (same shape as GET response)

**Response 200:** Updated config object

---

### PATCH /config

Partial configuration update.

**Request body:** Partial object with fields to update

Example — switch to sync delivery:
```json
{
  "delivery": "sync"
}
```

Example — update poll interval:
```json
{
  "poll_interval": 5.0
}
```

**Response 200:** Updated full config object

---

### GET /status

Health and readiness check.

**Response 200:**
```json
{
  "agent_id": "agent-001",
  "delivery": "inbox",
  "uptime": 1234.5,
  "running": true,
  "ready": true
}
```

**Response 503 (not ready):**
```json
{
  "agent_id": "agent-001",
  "delivery": "inbox",
  "uptime": 1234.5,
  "running": false,
  "ready": false
}
```

---

### POST /restart

Restart the agent subprocess. This tears down the current agent and re-initializes it.

**Response 200:**
```json
{
  "status": "restarting"
}
```

**Response 503 (restart already in progress):**
```json
{
  "status": "restart in progress"
}
```

---

### GET /metrics

Returns basic telemetry.

**Response 200:**
```json
{
  "agent_id": "agent-001",
  "uptime": 1234.5
}
```

---

## Host Messaging Plane

These endpoints are called by `HostContainerBackend` implementations (DockerBackend, SSHBackend).

### POST /message

Synchronous send — blocks until agent finishes processing, returns response.

**Request body:**
```json
{
  "content": "What is 2+2?",
  "from_agent": "moderator",
  "correlation_id": "optional-uuid"
}
```

**Response 200:**
```json
{
  "content": "2+2 equals 4",
  "from_agent": "agent-001",
  "correlation_id": "optional-uuid",
  "timestamp": 1234567890.123
}
```

**Response 504 (timeout):**
```json
{
  "error": "timeout",
  "correlation_id": "optional-uuid"
}
```

---

### POST /message/async

Asynchronous send — queues message immediately, returns correlation ID.

**Request body:**
```json
{
  "content": "Process this in background",
  "from_agent": "moderator",
  "correlation_id": "optional-uuid"
}
```

**Response 200:**
```json
{
  "queued": true,
  "correlation_id": "uuid-assigned-or-provided"
}
```

---

### GET /response/{correlation_id}

Poll for an async response.

**Response 200:**
```json
{
  "content": "Background task result",
  "from_agent": "agent-001",
  "correlation_id": "uuid",
  "timestamp": 1234567890.123
}
```

**Response 404 (not ready yet):**
```json
{
  "error": "not found"
}
```

---

## Internal Endpoints

These are used by the harness inside AgentServer, not called by HostContainerBackend.

### GET /inbox

Read pending messages from inbox (for inbox delivery pattern).

**Response 200:**
```json
{
  "messages": [
    {
      "id": "msg-uuid",
      "from_agent": "moderator",
      "to_agent": "agent-001",
      "content": "Hello",
      "correlation_id": "corr-uuid",
      "timestamp": 1234567890.123
    }
  ]
}
```

---

## Configuration

AgentServer config is stored at `~/.agentia/agent.json` and loaded at startup.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"0.0.0.0"` | Bind address |
| `port` | int | `8080` | Bind port |
| `delivery` | string | `"inbox"` | Delivery pattern: `"inbox"` or `"sync"` |
| `poll_interval` | float | `2.0` | Inbox polling interval (seconds) |
| `inbox_dir` | string | `"/workspace/inbox"` | Inbox directory path |
| `responses_dir` | string | `"/workspace/inbox/responses"` | Responses directory path |
| `agent_timeout` | int | `120` | Agent subprocess timeout (seconds) |
| `log_level` | string | `"info"` | Logging level |

---

## Relationship to SPEC 005

This API is the "AgentServer" box in SPEC 005's architecture diagram:

```
BaseRelay → HostContainerBackend → [HTTP] → AgentServer → AgentAdapter → Agent
```

AgentServer is agent-side, deployment-agnostic, and handles:
- Configurable delivery patterns (inbox/sync)
- AgentAdapter lifecycle
- HTTP/WebSocket interface to host

---

## References

- Issue #12: AgentServer meta-issue
- SPEC 005: Relay & Inbox Architecture
- SPEC 006: Orchestration Patterns (Moderator uses BaseRelay → AgentServer)