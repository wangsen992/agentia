# Agentia Hardening Plan — 2026-04-10

## Goal
Identify remaining gaps in the current Agentia surface and add comprehensive tests so the implemented behavior is validated, documented, and trustworthy.

## Current validated areas
- host conversation command semantics
- smart router active pointer bookkeeping
- session deletion by resolved title
- files PUT created-vs-updated semantics
- host CLI E2E against fake AgentServer (`register`, `agents`, `status`, `configure`, `sessions`, `send`, `compact`, `session delete`, `files`)
- host CLI coverage for `snapshot`, `clean`, `prune`
- direct API safety check for file path traversal
- in-process AgentServer handler tests for `/status`, `/config`, `/sessions`, session messaging, deletion, and file PUT/GET

## Remaining gap buckets
1. AgentServer core endpoints not yet covered deeply
   - broader async/inbox-oriented behavior beyond current handler-level coverage
2. Host CLI gaps
   - `update`
   - `forward`
   - more failure-path assertions
   - possible `files edit` behavior (likely mock-based)
3. Conversation management gaps
   - `conv list/show/use/tag/delete` positive-path persistence and active pointer updates
   - smart-router fallback behavior from stale `.active/`
4. Session manager behavior gaps
   - `new_session()` semantics
   - `get_session()` title resolution
   - hard delete behavior
5. Documentation sync after each completed coverage increment

## Execution order
1. Expand AgentServer endpoint tests (highest value)
2. Expand host CLI command coverage
3. Expand conversation/session-manager behavioral tests
4. Re-audit for uncovered public surface
5. Update README/tests docs
6. Commit cleanly

## New findings during hardening
- `AgentServerHandler._handle_session_message()` had an error-mapping bug: `"session not running"` was being classified as 404 due to condition ordering. Fixed.
- `AgentServerHandler._handle_files()` had a real macOS path-resolution bug (`/var` vs `/private/var`) causing false path-traversal rejections. Fixed.
- `SessionManager.new_session()` always reloads manifest, which clears in-memory runtime state and rehydrates entries as stopped. This weakens no-op/LRU semantics unless manifest is the full source of truth. Not fixed yet; keep flagged as architectural follow-up.

CHECKPOINT_FIELDS = {
  status: "in_progress",
  output_summary: "Expanded AgentServer handler coverage, fixed two real server bugs, and identified a remaining SessionManager manifest/runtime-state design gap.",
  next_trigger: "Finish conversation/session-manager positive-path tests, then re-audit remaining host CLI gaps and sync docs."
}
