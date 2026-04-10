# SPEC 022 — Host Folder Cleanup

## Goal

Provide a conservative host-side cleanup mechanism for `~/.agentia/` that distinguishes between safe-to-delete runtime residue and potentially valuable agent state.

The command should support both **audit** and **apply** modes, produce clear user-facing summaries, and avoid deleting live or ambiguous state by default.

---

## Problem

`~/.agentia/` currently mixes several classes of artifacts:

1. **Durable state**
   - registered agent homes
   - agent config
   - memory/session state
   - conversation history

2. **Runtime scratch / disposable residue**
   - empty container directories
   - zero-byte inbox files
   - temporary response files

3. **Legacy / migration overlap**
   - parallel session stores (`.agentia/sessions` and `.pi/sessions`)
   - destroyed container metadata with preserved artifacts
   - unregistered but non-empty agent homes

Without a cleanup command, stale artifacts accumulate and obscure what is real state versus implementation leftovers.

---

## User Story

As a user, I want to:
- inspect `~/.agentia/` for stale or redundant artifacts
- safely remove clearly disposable files/directories
- avoid accidental deletion of live sessions, memory, or useful debug artifacts
- eventually automate cleanup through `host.py`

---

## Command Surface

Primary command:

```bash
python3 cli/host.py clean
```

Recommended modes:

```bash
python3 cli/host.py clean --audit
python3 cli/host.py clean --apply --safe
python3 cli/host.py clean --apply --category containers,inbox
python3 cli/host.py clean --apply --aggressive
```

Optional flags:

```bash
--audit                 # inspect only (default if --apply absent)
--apply                 # execute cleanup actions
--safe                  # only tier-1 safe actions
--aggressive            # include review-tier actions when explicitly requested
--category <list>       # containers,inbox,registry,agents,conversations,sessions,responses
--older-than <duration> # e.g. 24h, 7d
--json                  # machine-readable output
--yes                   # skip confirmation for apply
--trash                 # move to ~/.agentia/.trash instead of deleting
--dry-run               # preview only
```

---

## Safety Model

### Tier 1 — Safe

Safe items are high-confidence disposable artifacts and may be removed by:

```bash
clean --apply --safe
```

Examples:
- empty container directories
- zero-byte inbox files
- empty temp/scratch directories
- stale response temp files if explicitly defined as scratch in implementation

### Tier 2 — Review

Review items should be surfaced in audit output but not deleted by `--safe`.
They require either an additional flag or explicit selection.

Examples:
- unregistered agent homes
- destroyed registry entries with preserved backing artifacts
- empty or suspicious session directories
- orphaned active-conversation pointers
- old non-empty test artifacts

### Tier 3 — Protected

Protected items must never be auto-deleted by the general cleanup command.

Examples:
- non-empty `.pi/sessions/`
- non-empty memory stores
- registered active agent homes
- conversation history in normal use
- `agent.json`, `auth.json`, identity/persona files
- image definitions unless explicitly targeted by a future dedicated command

---

## Scope

Cleanup is limited to `~/.agentia/`.

Relevant paths include:
- `~/.agentia/containers/`
- `~/.agentia/inbox/`
- `~/.agentia/inbox/responses/`
- `~/.agentia/agents/`
- `~/.agentia/conversations/`
- `~/.agentia/history/`
- `~/.agentia/registry.json`
- `~/.agentia/agents.json`

---

## Detection Rules

### 1. Empty container directories

**Rule**
- path under `containers/*`
- directory contains no files and no non-empty descendants

**Classification**
- Tier 1 (Safe)

**Action**
- remove directory

---

### 2. Zero-byte inbox files

**Rule**
- path under `inbox/*.jsonl`
- file size is exactly zero bytes
- file is not tied to a known active runtime (or runtime status is unknown and policy allows)

**Classification**
- Tier 1 (Safe) when clearly stale/inactive
- Tier 2 (Review) if active status cannot be determined safely

**Action**
- remove file

**Implementation note**
- v1 may conservatively use name-based + size-based detection only
- future versions should integrate active runtime checks

---

### 3. Destroyed registry entries

**Rule**
- `registry.json.containers[*].status == "destroyed"`

**Classification**
- Tier 1 if backing directory is absent or empty
- Tier 2 if backing directory still contains files

**Action**
- prune metadata entry only when safe
- otherwise report for review

---

### 4. Unregistered agent homes

**Rule**
- directory under `agents/*`
- name absent from `agents.json`

**Classification**
- Tier 2 (Review)

**Action**
- report summary: file count, size, last modified
- delete only with a dedicated opt-in flag, e.g. `--remove-unregistered-agents`

---

### 5. Dual session stores

**Rule**
- agent home contains both `.agentia/sessions` and `.pi/sessions`

**Classification**
- Tier 2 (Review / architecture warning)

**Action**
- report only
- no deletion in v1

**Rationale**
- this may reflect migration overlap, layered abstractions, or intentional separation between host-managed and runtime-native sessions

---

### 6. Empty session directories

**Rule**
- session directory exists but contains no files

**Classification**
- Tier 2 (Review) by default

**Action**
- report only in v1

---

### 7. Orphaned conversation pointers

**Rule**
- file under `conversations/.active/` or `conversations/*.jsonl`
- referenced agent/session no longer exists

**Classification**
- Tier 2 (Review)

**Action**
- report only in v1
- future version may prune after verification

---

### 8. Old non-empty test artifacts

**Rule**
- names matching patterns such as `test-*`, `smoke-*`, `memory-test*`
- contains files

**Classification**
- Tier 2 (Review)

**Action**
- report only in v1

---

## Audit Output

The audit should group findings by safety tier.

Example:

```text
Agentia host cleanup audit
Root: ~/.agentia

SAFE
  empty container dirs (22)
    - containers/test-session
    - containers/test-gateway
  zero-byte inbox files (24)
    - inbox/test-session.jsonl
    - inbox/analyst-001.jsonl

REVIEW
  unregistered agent homes (1)
    - agents/my-agent (14 KB, 7 files)
  destroyed registry entries with remaining files (2)
    - critic-001 (247 KB, 22 files)
    - test-analyst-001 (11 files)
  dual session stores (1)
    - agents/my-research-agent: .agentia/sessions + .pi/sessions

PROTECTED
  active registered agent homes (1)
    - agents/my-research-agent
```

Footer:

```text
Summary:
  safe deletions: 46 items
  review needed: 4 items
  protected: 1 item

Run with --apply --safe to remove only safe items.
```

---

## Apply Semantics

### `--apply --safe`

Perform Tier 1 actions only.

### `--apply --aggressive`

Allow selected Tier 2 actions, but only when additionally gated by category or explicit flags.

Examples:
- `--remove-unregistered-agents`
- `--prune-destroyed-registry`
- `--prune-orphaned-conversations`

Aggressive mode must still avoid Tier 3 protected artifacts.

---

## JSON Output

`--json` should emit machine-readable structured results, for example:

```json
{
  "root": "~/.agentia",
  "safe": {
    "empty_container_dirs": ["containers/test-session"],
    "zero_byte_inbox_files": ["inbox/test-session.jsonl"]
  },
  "review": {
    "unregistered_agent_homes": [
      {"path": "agents/my-agent", "size_bytes": 14167, "file_count": 7}
    ],
    "dual_session_stores": [
      {"path": "agents/my-research-agent", "stores": [".agentia/sessions", ".pi/sessions"]}
    ]
  },
  "protected": {
    "active_registered_agent_homes": ["agents/my-research-agent"]
  }
}
```

---

## v1 Recommendation

v1 should automatically clean only:
- empty container directories
- zero-byte inbox files
- other clearly empty scratch directories if unambiguous

v1 should only report:
- unregistered agent homes
- non-empty destroyed containers
- dual session stores
- orphaned conversation pointers
- old non-empty test artifacts

This keeps the first implementation useful and low-risk.

---

## Future Improvements

1. Distinguish canonical state vs cache in the folder layout
   - e.g. `state/`, `cache/`, `tmp/`, `artifacts/`
2. Integrate live runtime checks before deleting inbox/session artifacts
3. Add trash-based recovery mode
4. Add age thresholds and last-access heuristics
5. Add a doctor command that combines audit + health diagnostics

---

## Open Questions

1. Is `.agentia/sessions/` still canonical anywhere, or is `.pi/sessions/` the sole runtime source of truth?
2. Should destroyed containers remain in `registry.json` for audit/history, or be pruned once they are no longer recoverable?
3. Should non-empty `test-*` artifacts be reclassified into a dedicated `artifacts/` or `fixtures/` namespace?
4. Should inbox placeholders exist at all, or should they be created lazily on first write?
