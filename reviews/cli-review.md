# CLI Review: README vs. Actual Implementation

**Reviewer:** Subagent (readme-vet-cli)
**Files reviewed:** `README.md`, `cli/host.py`, `cli/agent.py`
**Scope:** Host Side CLI commands + quick-start Docker run example

---

## Host Side CLI (`cli/host.py`)

### ✅ Fully documented and correctly implemented

| Command | Status |
|---------|--------|
| `register <url> --name <name>` | ✅ Matches |
| `agents` | ✅ Matches |
| `status <name>` | ✅ Matches |
| `update <name> --role-goal ... --backstory ... --skills ...` | ✅ Matches |
| `deregister <name>` | ✅ Matches |
| `prune` | ✅ Matches |
| `send <name> <message> [--conv <session-name>]` | ✅ Matches |
| `compact <name> --conv <session>` | ✅ Matches |
| `session delete <name> <conv> [--hard]` | ✅ Matches |
| `sessions <name>` | ✅ Matches |
| `files <name> ls/get/put/edit/delete <path>` | ✅ Matches |
| `snapshot <name> [output]` | ✅ Matches |
| `forward <name> <method> <path>` | ✅ Matches |

---

### ⚠️ Minor flag shorthand discrepancy in `compact`

**README (Host Side CLI section) says:**
```bash
python3 cli/host.py compact my-agent --conv hawaii
```

**But the Session Management section says:**
```bash
python3 cli/host.py compact my-agent -c hawaii
```

**Code (`cli/host.py`, line ~argparse compact subparser):**
```python
p_comp.add_argument("--conv", "-c", dest="conv", required=True, ...)
```

**Verdict:** `-c` works as a shorthand for `--conv` in the `compact` command because the code defines `-c` explicitly. The Session Management example using `-c` is valid. However, the Host Side CLI table shows `--conv` but the Session Management section shows `-c` — minor inconsistency in which form appears where. Both work.

---

### ⚠️ `configure` command — README examples may confuse users

**README says:**
```bash
python3 cli/host.py configure <name> delivery sync
```

**Code argparse:**
```python
p_conf.add_argument("name", help="Agent name")
p_conf.add_argument("key", help="Config key (supports dot notation, e.g. role.goal)")
p_conf.add_argument("value", help="New value")
```

The command is correct, but the example `configure <name> delivery sync` sets `delivery` to `sync`. This is fine, but it could confuse readers who might think `configure <name> delivery` with no value would be valid. Worth noting the example works as documented.

---

## Agent Side CLI (`cli/agent.py`) — Quick-Start Docker Run

### ✅ Quick-start Docker run example vs. `serve` command args

**README quick-start says:**
```bash
docker run -d --name my-agent -p 18080:8080 \
    -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
    -v ~/.agentia/my-research-agent:/workspace \
    agentia serve \
      --install pi-agent \
      --config ~/.agentia/my-research-agent/agent.json \
      --provider minimax \
      --model MiniMax-M2.7 \
      --workspace /workspace
```

**Code (`cli/agent.py` serve subparser):**
```python
p_serve.add_argument("--install", choices=["pi-agent", "openclaw"], default=None, ...)
p_serve.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), ...)
p_serve.add_argument("--agent-id", default="agent-001", ...)
p_serve.add_argument("--provider", default="minimax", ...)
p_serve.add_argument("--model", default="MiniMax-M2.7", ...)
p_serve.add_argument("--workspace", default=str(DEFAULT_WORKSPACE), ...)
p_serve.add_argument("--role-goal", default="", ...)
p_serve.add_argument("--backstory", default="", ...)
p_serve.add_argument("--skills", action="append", default=[], ...)
p_serve.add_argument("--var", action="append", default=[], ...)
p_serve.add_argument("--session-ttl", type=int, default=1800, ...)
p_serve.add_argument("--max-sessions", type=int, default=10, ...)
p_serve.add_argument("--context-threshold", type=int, default=75, ...)
```

All flags used in the quick-start (`--install`, `--config`, `--provider`, `--model`, `--workspace`) are correctly implemented.

---

### ⚠️ Session lifecycle flags — undocumented deviations from argparse defaults

**README (Session lifecycle flags section) says:**
```bash
docker run ... agentia serve \
    --session-ttl 300 \
    --max-sessions 5 \
    --context-threshold 80
```

**Code defaults:**
- `--session-ttl`: default = **1800** (not 300)
- `--max-sessions`: default = **10** (not 5)
- `--context-threshold`: default = **75** (not 80)

The README is showing explicitly-passed values that differ from the actual defaults. This is not a documentation error per se (the values are valid), but it means:

1. If a user runs `agentia-agent serve` without these flags, they get 1800s / 10 sessions / 75% context threshold — **not** what the Session lifecycle flags section implies are "the" values.
2. The quick-start docker run example correctly uses `--session-ttl 300` and `--max-sessions 5`, but the Session lifecycle flags section header says `--context-threshold 80` while the quick-start docker example doesn't include it at all (uses the default 75).

**Summary table:**

| Flag | README example | Argparse default |
|------|---------------|-----------------|
| `--session-ttl` | 300 | 1800 |
| `--max-sessions` | 5 | 10 |
| `--context-threshold` | 80 | 75 |

---

## Summary

1. **All documented host CLI commands are implemented** — no missing commands.
2. **`compact` command shorthand**: `-c` is valid in code (defined explicitly), so the Session Management section's `compact my-agent -c hawaii` works. The Host Side CLI table uses `--conv` form. Minor inconsistency in which form is shown where.
3. **Quick-start docker run example** — all flags match the `serve` subparser. No incorrect flags.
4. **Session lifecycle flags section** — the example values (300, 5, 80) **do not match** the actual argparse defaults (1800, 10, 75). This should be clarified: either update the defaults in the code, or update the README to reflect what the actual defaults are. The discrepancy could mislead users about what happens when they omit these flags.
