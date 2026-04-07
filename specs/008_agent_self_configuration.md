# SPEC 008: Agent Self-Configuration with Verify Loop

**Status:** Active pattern — confirmed working 2026-04-07
**Supersedes:** partial notes in SPEC-007_agent_provision.md

---

## The Problem

When an agent is asked to "configure X" (enable memory search, set up an integration, etc.), it typically:
1. Modifies a config file
2. Reports success

But if the underlying service doesn't pick up the change automatically, the agent's config is written but the system is still broken. The agent doesn't know — it already moved on.

Example from this session:
- Agent told to enable QMD memory → wrote `openclaw.json` with correct config → reported done
- But `qmd` binary wasn't installed in the image → memory search silently failed
- And even after switching to `ollama`, the Ollama endpoint was `127.0.0.1:11434` (unreachable from inside container) → still failed
- Agent never re-ran `openclaw memory status` to verify — it just assumed the config write was sufficient

Result: "set up" was reported as complete when it was broken at two layers.

---

## The Solution: Self-Configure + Restart + Verify Loop

For any infrastructure setup task, the agent should follow this pattern:

```
configure(task):
  1. Read current state — know what the starting point is
  2. Identify fix — what needs to change and what tools are needed
  3. Apply fix — modify config, install packages, etc.
  4. Trigger reload — if config file changed but service doesn't hot-reload
  5. Verify — re-read state to confirm the change actually took effect
  6. If broken → loop to step 2 with the new diagnostic info
  7. If working → report success
```

### Step 4 (Trigger Reload) — The Gateway Restart Mechanism

When the agent modifies `/root/.openclaw/openclaw.json`, the **running gateway process** still has the old config in memory. Writing the file doesn't reload it. The agent needs:

```bash
curl -X POST http://127.0.0.1:18790/restart
```

The gateway harness exposes this endpoint via `gwctl`. The call:
- Returns `"restarting"` immediately
- Gateway tears down the old process, starts a new one with the new config
- New instance is ready within ~5-10 seconds
- The agent waits for `/status` to return `"ready"` before continuing

**Why this matters:** The agent can apply-and-verify programmatically without human intervention. Without this endpoint, any config change would require the user to manually restart the container.

### Step 5 (Verify) — The Critical Missing Piece

Writing config → calling restart is not sufficient. The agent must verify:

```bash
# For memory infrastructure:
openclaw memory index
openclaw memory status

# For any config change:
<service>-status or <service>-verify
```

If verification fails, the agent has diagnostic information to try the next fix. If it passes, the task is done.

---

## Verified Working Pattern (2026-04-07)

```
Agent receives: "Configure memory search with Ollama embedding"

1. openclaw memory status
   → "qmd binary not found" / "ECONNREFUSED 127.0.0.1:11434"

2. npm install -g @tobilu/qmd
   → qmd installed

3. cat /root/.openclaw/openclaw.json
   → "memorySearch.provider": "ollama"
   → Ollama not reachable because baseUrl is 127.0.0.1

4. Update config: memorySearch.remote.baseUrl = "http://host.docker.internal:11434"

5. curl -X POST http://127.0.0.1:18790/restart
   → "restarting"

6. sleep 10

7. openclaw memory status
   → "Provider: ollama, Model: embeddinggemma:300m, Vector: ready"

8. openclaw memory index

9. Inject test phrase + verify memory search finds it

10. Report success
```

---

## Config Change That Required Restart (Not Just Config Write)

The `qmd` binary was missing, but that wasn't enough — the agent also needed to:
1. Change `memorySearch.provider` from `openai` → `ollama`
2. Change `memorySearch.remote.baseUrl` from `127.0.0.1` → `host.docker.internal`
3. Trigger restart to pick up new provider + new endpoint

Without step 3, even correct config wouldn't be active.

---

## Key Endpoints

These endpoints are provided by **AgentServer** (see SPEC 005):

### Gateway Restart (via AgentServer)
```
POST http://127.0.0.1:18790/restart
Response: "restarting"
```

### Gateway Status (via AgentServer)
```
GET http://127.0.0.1:18790/status
Response: "ready" | "not_ready"
```

### Memory Verification (inside container)
```bash
openclaw memory status          # show current provider + index state
openclaw memory index           # force reindex
openclaw memory search "test"   # verify search actually works
```

---

## Failure Handling

| Failure | Agent Action |
|---------|-------------|
| Package not found | Try `npm install -g <package>` or equivalent |
| Service not reachable | Identify correct endpoint (e.g., Docker networking: `host.docker.internal`) |
| Config written but not picked up | Trigger `/restart` and wait for ready |
| Restart doesn't help | Check logs: `tail /workspace/logs/gateway.log` |
| Still broken after N attempts | Escalate to human with diagnostic info |

---

## The Fundamental Pattern

```
Agent has agency over:    Agent needs human for:
─────────────────────     ───────────────────
Config file edits         Package installation (requires persistence across restarts)
Runtime package install   Network topology (can't discover host.docker.internal itself)
Triggering restart       Rebuilding Docker image
Verifying outcome

The gap: package installs at runtime are ephemeral (don't persist across restart).
The fix: bake packages into Dockerfile. Agent does runtime config + verify.
```

---

## Related Specs

- [SPEC-005_relay_inbox.md](./005_relay_inbox.md) — AgentServer architecture (gateway_harness absorbed into AgentServer)
- [SPEC-006_orchestration_patterns.md](./006_orchestration_patterns.md) — Orchestration + delegation patterns

---

## Test History

| Date | Test | Result | Notes |
|------|------|--------|-------|
| 2026-04-06 | Agent triggers self-restart via `/restart` | ✅ PASS | Gateway PID changed, poller resumed |
| 2026-04-07 | Agent configures Ollama memory with verify loop | ✅ PASS | Required `host.docker.internal:11434` fix |
| 2026-04-07 | Agent installs neovim at runtime | ✅ PASS | Confirmed agent can install packages |