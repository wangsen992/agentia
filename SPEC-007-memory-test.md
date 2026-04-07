# SPEC 007b: Gateway Self-Restart + Memory Infrastructure Test ✅ PASSED 2026-04-06

## Objective
Verify that a containerized OpenClaw agent can:
1. Enable QMD + vector search memory infrastructure via config changes
2. Trigger a gateway self-restart via the HTTP control endpoint
3. Come back up with the upgraded config

## Architecture

```
Host                          Container (agentia-memory-test)
~/.agentia/containers/memory-test/openclaw/  →  /root/.openclaw/  (config, rw)
~/.agentia/inbox/             →  /workspace/inbox/  (relay messages)

agentia CLI (host)  ──inbox relay──►  agent inbox  →  poller  →  OpenClaw agent
                                        │                          │
                                        │                     Modifies config
                                        │                     /root/.openclaw/
                                        │                     openclaw.json
                                        │                          │
                                        ◄──response.jsonl───────────┤
                                        │                          │
                                        │                     curl POST to
                                        │                     http://127.0.0.1:18790/restart
                                        │                     (gwctl server in harness)
                                        │                          │
                                        ◄───gateway tears down─────┤
                                              + restarts              │
```

## Steps

### Phase 1: Setup ✅
- [x] Build agentia image with latest gateway_harness.py
- [x] agentia create analyst memory-test --harness gateway
- [x] Wait for gateway + gwctl server to come up
- [x] Verify gwctl /status returns "ready"

### Phase 2: Agent Enables Memory Infra ✅
- [x] agentia ask memory-test: enable QMD backend + vector search + restart
- [x] Agent modifies /root/.openclaw/openclaw.json
- [x] Agent calls curl POST to /restart
- [x] Gateway restarts (PID 12 killed → PID 118 started)
- [x] Agent receives restart response (HTTP 200 "restarting")

### Phase 3: Verification ✅
- [x] Check host config: `memory.backend = "qmd"`, `memorySearch.provider = "openai"`
- [x] Check container logs for successful restart (#1 requested, PID changed, poller resumed)
- [x] gwctl /status returns "ready" again

## Final Config (verified)
```json
{
  "memory": {
    "backend": "qmd"
  },
  "agents": {
    "defaults": {
      "memorySearch": {
        "provider": "openai",
        "model": "embeddinggemma:300m"
      }
    }
  }
}
```

## Test Output (agent response)
> **Changes Made:**
> 1. Added top-level `memory` section: `{"backend": "qmd"}`
> 2. Updated `agents.defaults.memorySearch.provider` from `"ollama"` to `"openai"`
> **Restart Status:** ✅ Successfully triggered — the gateway returned `restarting`.

## Gateway Restart Log
```
[OpenClawAdapter] Gateway started (PID 12)
[OpenClawAdapter] Gateway ready after 5s
Gateway running.
[memory-test] Gateway poller started
[gwctl] Restart requested via HTTP from 127.0.0.1
[!!] Gateway restart #1 requested
[OpenClawAdapter] Killing gateway (PID 12)
[OpenClawAdapter] Gateway started (PID 118)
[OpenClawAdapter] Gateway ready after 1s
[!!] Gateway restarted.
[memory-test] Gateway poller started
[!!] Restart complete.
```

## Risks / Failure Modes
- ✅ Agent knew to use curl (available in container)
- ✅ Config write path /root/.openclaw/openclaw.json was writable
- ✅ Restart endpoint returned 200 (no 503 collision)
- ✅ Container filesystem was writable
