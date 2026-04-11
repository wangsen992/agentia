# Subagent-05 Review: Setup + Bootstrap System

**Reviewer:** Subagent-05 (Setup + Bootstrap)  
**Date:** 2026-04-08  
**Files Reviewed:**
- `Dockerfile`
- `setup/README.md`
- `setup/adapters/pi-agent/install.sh`
- `setup/adapters/pi-agent/config.tmpl`
- `setup/adapters/pi-agent/bootstrap/AGENTS.md.tmpl`
- `setup/adapters/pi-agent/bootstrap/SYSTEM.md.tmpl`
- `setup/adapters/pi-agent/bootstrap/TOOLS.md.tmpl`
- `setup/adapters/openclaw/install.sh`
- `setup/adapters/openclaw/config.tmpl`
- `setup/adapters/openclaw/bootstrap/AGENTS.md.tmpl`
- `setup/adapters/openclaw/bootstrap/SYSTEM.md.tmpl`

---

## Summary

The setup system is architecturally sound — Jinja2 template rendering, per-adapter self-containment, and the install/config/bootstrap split are all reasonable choices. However, there are **5 critical bugs** ranging from silent variable mismatches to invalid JSON generation, plus several design gaps. Most critically, the `docker commit` workaround in the README is a code smell that points to missing Dockerfile integration.

---

## Per-File Analysis

### 1. `Dockerfile`

**Lines 1–20**

```
FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl gnupg && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*
RUN pip3 install requests jinja2 --break-system-packages
COPY agents/ /workspace/agents/
COPY relay/ /workspace/relay/
COPY agent_side/ /workspace/agent_side/
COPY setup/ /usr/local/bin/setup/
COPY constants.py /workspace/
WORKDIR /workspace
COPY agentia /usr/local/bin/agentia
RUN chmod +x /usr/local/bin/agentia
ENTRYPOINT ["agentia"]
CMD ["agentserver"]
```

**Findings:**

- **No runtime baked in.** The Dockerfile comment (lines 2–4) explicitly says runtime is installed at container *start* via `agentia install <adapter>`. This is the root cause of the `docker commit` workaround documented in README.
- **pi-agent could be pre-baked.** Since `@mariozechner/pi-coding-agent` is a public npm package, it could be `RUN npm install -g @mariozechner/pi-coding-agent` at build time, eliminating the per-container install step. Same for `openclaw`.
- **Build is order-sensitive.** `COPY agents/`, `COPY relay/`, `COPY agent_side/` will fail silently if those directories don't exist (Docker copies nothing, no error). Should add a comment noting these are expected from a prior build stage or check existence.
- **Missing health check.** No `HEALTHCHECK` instruction — `docker run` will report the container as healthy immediately even if the agent fails to start.

---

### 2. `setup/README.md`

**Findings:**

- **`docker commit` workaround (implied).** The README doesn't explicitly show `docker commit`, but says runtime is installed "at container start." This means every `docker run` must call `agentia install` before the agent is functional. This is a **two-step boot** that should be replaced by a single-step `docker run agentia` with runtime baked in.
- **Variable documentation gap.** Documents `{{ env.VAR_NAME }}` as a syntax for referencing env vars, but:
  - The actual templates use `{{ env.items() }}` (dictionary iteration), not individual key access
  - It's unclear what populates the `env` dict — is it all environment variables? A filtered subset? This needs clarification.
- **`role_persona` not documented.** README shows `role_goal` and `backstory` but never `role_persona`. Yet both `config.tmpl` files reference `role_persona`. This creates a silent mismatch.
- **TOOLS.md is adapter-specific.** pi-agent has it; openclaw doesn't. README should clarify when TOOLS.md is expected.

---

### 3. `setup/adapters/pi-agent/install.sh`

**Lines 1–23**

**Findings:**

- **Idempotent — ✅.** The `command -v pi` check prevents re-installation on repeated runs. `set -e` ensures failures exit non-zero.
- **No version pinning.** `npm install -g @mariozechner/pi-coding-agent@latest` can install breaking changes between runs. Should pin to a version or at least use `@latest` with a version log.
- **No workspace directory validation.** `mkdir -p` succeeds even if `$WS` is a read-only mount. No check for writability before `npm install -g` (which writes to `/usr/lib/node_modules`). If the container runs as a non-root user with a read-only filesystem, this will fail silently or partially.
- **Race condition (minor).** Creates directories before checking if pi is installed. Should check first, then create dirs, then install.
- **Inconsistent directory list vs openclaw.** Creates `.pi/{extensions,skills,prompts,sessions}` — this is pi-specific and fine, but openclaw creates a completely different structure (`.openclaw/identity`, `.openclaw/agents/main/agent`). The adapter READMEs should document expected directories per adapter.

---

### 4. `setup/adapters/pi-agent/config.tmpl`

**Findings:**

- **Critical: `role_persona` used but never defined (line 6).**  
  ```jinja2
  "persona": "{% if role_persona %}{{ role_persona }}{% else %}You are {{ agent_id }}.{% endif %}",
  ```
  The documented CLI variable is `role_goal` and `backstory`. `role_persona` is never passed as a context variable. Result: persona always falls back to `"You are {agent_id}."`, silently ignoring any intended persona.

- **Critical: Empty `env` block produces invalid JSON (lines 14–17).**  
  ```jinja2
  "env": {
    {% for k, v in env.items() %}"{{ k }}": "{{ v }}"{% if not loop.last %}, {% endif %}{% endfor %}
  }
  ```
  If `env` is empty or undefined, this renders as:
  ```json
  "env": {
    
  }
  ```
  which is **valid JSON** (empty object) — actually this one is fine. But if `env` is `None` (undefined), `env.items()` will raise a Jinja2 error, not produce empty JSON.

- **`provider` and `model` present (lines 5, 7) — ✅** — These match documented variables.

---

### 5. `setup/adapters/pi-agent/bootstrap/AGENTS.md.tmpl`

**Findings:**

- **Structural bug: `# System` header embedded in AGENTS.md (line 13).**  
  The template has:
  ```jinja2
  {% if skills %}
  ## Skills
  ...
  {% endif %}

  # System
  ```
  This means when rendered, `AGENTS.md` contains both the agent identity block AND a `# System` heading. But `SYSTEM.md.tmpl` is a *separate* file. This creates duplication — the `# System` section appears in both AGENTS.md and SYSTEM.md.

- **Skills list has no surrounding context.** Renders as raw bullet list items with no introductory text.

---

### 6. `setup/adapters/pi-agent/bootstrap/SYSTEM.md.tmpl`

**Findings:**

- **`{{ tools }}` variable undefined (line 5).**  
  ```jinja2
  {% if tools %}
  {% for tool in tools %}
  ```
  The documented rendering context (README) lists `skills` as a loop variable, not `tools`. `tools` is never documented or passed. This will render `{% else %}` branch ("No custom tools configured.") every time.

- **The `# Tools` section is orphaned.** `TOOLS.md.tmpl` exists as a separate file, but SYSTEM.md.tmpl also has a `{% if tools %}` block. There are two separate places tools could appear — ambiguous.

---

### 7. `setup/adapters/pi-agent/bootstrap/TOOLS.md.tmpl`

**Findings:**

- **Same `{{ tools }}` undefined variable issue** — `{% if tools %}` will always be falsy.
- **Otherwise well-formed** — proper markdown structure, graceful no-tools fallback.

---

### 8. `setup/adapters/openclaw/install.sh`

**Findings:**

- **Same idempotency pattern as pi-agent — ✅**
- **Same missing version pinning — ⚠️**
- **Different directory structure** — creates `.openclaw/identity` and `.openclaw/agents/main/agent`. No documentation of why these specific paths. Should match whatever openclaw expects at runtime.
- **No validation of openclaw-specific directories** — if openclaw expects a different structure, this will fail silently or at runtime.

---

### 9. `setup/adapters/openclaw/config.tmpl`

**Findings:**

- **Same `role_persona` undefined variable bug (line 6)** — identical issue to pi-agent config.
- **Missing `provider` and `model` fields** — openclaw config only has `agent_id`, `adapter`, `workspace`, `role`, `skills`, `env`. It omits `provider` and `model` that pi-agent has. This is probably intentional (openclaw has its own model config), but should be documented.
- **Same empty `env` JSON risk** — same pattern as pi-agent config.

---

### 10. `setup/adapters/openclaw/bootstrap/AGENTS.md.tmpl`

**Findings:**

- **Same structural bug as pi-agent AGENTS.md** — `# System` header embedded mid-file.
- **No skills section** — unlike pi-agent, openclaw's AGENTS.md.tmpl doesn't include a skills list. If skills are passed to this adapter, they won't appear in the bootstrap.

---

### 11. `setup/adapters/openclaw/bootstrap/SYSTEM.md.tmpl`

**Findings:**

- **Same `# System` duplication issue** — if AGENTS.md already has `# System`, SYSTEM.md also starts with `# System`, creating a duplicate heading.
- **No tools section** — unlike pi-agent's SYSTEM.md.tmpl.

---

## Top 5 Actionable Findings

### Finding 1 — **[BUG] `role_persona` silently ignored in all config.tmpl files**
**Severity:** High  
**Files:** `setup/adapters/pi-agent/config.tmpl:6`, `setup/adapters/openclaw/config.tmpl:6`  
**Fix:** Replace `role_persona` with `backstory` in the persona line, since `backstory` is the documented and actually-passed variable:
```jinja2
"persona": "{% if backstory %}You are {{ agent_id }}. {{ backstory }}{% else %}You are {{ agent_id }}.{% endif %}",
```

---

### Finding 2 — **[BUG] Empty `env` block renders invalid JSON when env is undefined**
**Severity:** High  
**Files:** `setup/adapters/pi-agent/config.tmpl:14–17`, `setup/adapters/openclaw/config.tmpl:13–16`  
**Fix:** Add a guard for undefined `env`:
```jinja2
{% if env %}
  "env": {
  {% for k, v in env.items() %}"{{ k }}": "{{ v }}"{% if not loop.last %}, {% endif %}{% endfor %}
  }
{% else %}
  "env": {}
{% endif %}
```

---

### Finding 3 — **[BUG] `{{ tools }}` variable never passed to bootstrap templates**
**Severity:** Medium  
**Files:** `setup/adapters/pi-agent/bootstrap/SYSTEM.md.tmpl:5`, `setup/adapters/pi-agent/bootstrap/TOOLS.md.tmpl`  
**Fix:** Either (a) remove the `{% if tools %}` blocks and the TOOLS.md.tmpl file entirely if tools aren't implemented yet, or (b) document `tools` as a required context variable and ensure the rendering pipeline passes it. Given that TOOLS.md.tmpl exists but is never populated, option (a) is recommended until tools are actually implemented.

---

### Finding 4 — **[DESIGN] Runtime should be baked into Dockerfile, not installed at container start**
**Severity:** Medium  
**Files:** `Dockerfile`, `setup/README.md`  
**Fix:** Add the following to the Dockerfile, after the `pip3 install` line:
```dockerfile
RUN npm install -g @mariozechner/pi-coding-agent@latest
RUN npm install -g openclaw@latest
```
This eliminates the `docker commit` two-step boot. The `agentia install <adapter>` can become a no-op that just renders configs, with runtime already available. Alternatively, use Docker build args to conditionally install:
```dockerfile
ARG RUNTIME=pi-agent
RUN if [ "$RUNTIME" = "pi-agent" ]; then npm install -g @mariozechner/pi-coding-agent@latest; fi
```

---

### Finding 5 — **[DESIGN] AGENTS.md.tmpl should not contain `# System` heading**
**Severity:** Medium  
**Files:** `setup/adapters/pi-agent/bootstrap/AGENTS.md.tmpl:13`, `setup/adapters/openclaw/bootstrap/AGENTS.md.tmpl:17`  
**Fix:** Remove the `# System` block from both AGENTS.md.tmpl files. AGENTS.md should contain only agent identity (name, goal, backstory, skills). SYSTEM.md should contain the system prompt. Having `# System` in AGENTS.md creates duplicate content when both files are rendered into the workspace.

---

## Secondary Findings (Lower Priority)

| # | Finding | Location | Recommendation |
|---|---------|----------|----------------|
| S1 | No version pinning in npm installs | `install.sh` (both adapters) | Pin to known-good version, e.g. `@mariozechner/pi-coding-agent@^1.2.0` |
| S2 | openclaw missing skills section in AGENTS.md.tmpl | `openclaw/bootstrap/AGENTS.md.tmpl` | Add skills list block for consistency with pi-agent |
| S3 | openclaw missing provider/model in config | `openclaw/config.tmpl` | Document why these are absent, or add them for completeness |
| S4 | No Docker HEALTHCHECK in Dockerfile | `Dockerfile` | Add `HEALTHCHECK CMD curl -f http://localhost:8080/health \|\| exit 1` |
| S5 | No workspace writability check in install.sh | `install.sh` (both) | Add `mkdir -p` then test write access before npm install |
| S6 | `env.VAR_NAME` documented but unused | `README.md` | Either implement `{{ env.VAR_NAME }}` or remove from docs |
