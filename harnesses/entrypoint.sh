#!/bin/bash
#
# Unified Entrypoint for Agentia Harness Container
#
# Each harness manages its own lifecycle via AgentAdapter.
# setup() / teardown() handle gateway provisioning automatically.
# No separate gateway-startup.py needed.
#
# Usage:
#   docker run -it agentia [harness] [args...]
#
# Harnesses:
#   interactive    Turn-by-turn interactive REPL (default)
#   multi          Multi-turn automated harness (spawns subagents)
#   single         Single-shot prompt → response
#   gateway        Gateway-only — starts gateway, keeps container alive
#   list           Show available harnesses
#   help           Show full help documentation
#
# Examples:
#   docker run -it agentia                      # interactive mode
#   docker run -it agentia interactive           # same as above
#   docker run agentia single "Hello world"     # single prompt
#   docker run agentia multi --prompt "..."     # multi-turn automated
#   docker run -it agentia gateway               # gateway-only (debugging)
#   docker run -d agentia inbox --agent-id foo   # inbox poller (long-running daemon)
#

set -e

# Workspace — set once, inherited by all harnesses and openclaw agent subprocesses
export OPENCLAW_WORKSPACE=/workspace

WORKSPACE_DIR="/workspace"
RUNNERS_DIR="${WORKSPACE_DIR}/runners"

# Parse harness name (first arg or default to interactive)
HARNESS="${1:-interactive}"
shift 2>/dev/null || true

# ─── Info-Only Modes ─────────────────────────────────────────────────────────

if [ "$HARNESS" = "list" ]; then
	echo "Available harnesses:"
	echo ""
	echo "  interactive   Turn-by-turn REPL — human controls each turn via stdin"
	echo "  multi         Multi-turn automated — spawns subagents, waits, synthesizes"
	echo "  single        One-shot — sends one prompt, prints response, exits"
	echo "  gateway       Gateway-only — starts gateway, keeps container alive"
	echo "  inbox         Inbox poller — long-running daemon, processes inbox messages"
	echo "  list          Show this list"
	echo "  help          Show full help documentation"
	echo ""
	exit 0
fi

if [ "$HARNESS" = "help" ]; then
	echo "Agentia Harness Container — Usage Guide"
	echo "========================================"
	echo ""
	echo "USAGE:"
	echo "  docker run -it agentia [harness] [args...]"
	echo ""
	echo "HARNESSES:"
	echo ""
	echo "  interactive"
	echo "    Turn-by-turn REPL. Human types messages, agent responds."
	echo "    Gateway is started/stopped by the harness via AgentAdapter."
	echo ""
	echo "  multi [--prompt P] [--wait N] [--max-turns N]"
	echo "    Automated multi-turn workflow. Agent spawns subagents, waits for"
	echo "    completion, synthesizes results."
	echo ""
	echo "  single 'prompt text'"
	echo "    One-shot: sends prompt, prints response, exits immediately."
	echo ""
	echo "  gateway"
	echo "    Gateway-only mode for debugging. Starts gateway, keeps container alive."
	echo ""
	echo "  poller [--agent-id ID] [--poll-interval N] [--mode echo|agent]"
	echo "    Long-running inbox poller. Processes messages from shared inbox."
	echo "    Use --mode agent to drive OpenClaw agent for each message."
	echo ""
	echo "NOTES:"
	echo "  - Each harness calls adapter.setup() / adapter.teardown() for lifecycle"
	echo "  - Config files are COPY'd at build time — no host ~/.openclaw mounts"
	echo "  - Device identity provisioned fresh on each run"
	echo ""
	exit 0
fi

# ─── Harness Dispatch ────────────────────────────────────────────────────────
# Each harness manages its own adapter lifecycle (setup/teardown).

case "$HARNESS" in
interactive)
	echo "=== Starting INTERACTIVE harness ===" >&2
	echo "Adapter will call setup() → start gateway, then run REPL." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/interactive_harness.py"
	;;

multi)
	echo "=== Starting MULTI-TURN harness ===" >&2
	echo "Adapter will call setup() → start gateway, then run workflow." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/multi_turn_harness.py" "$@"
	;;

single)
	echo "=== Starting SINGLE-SHOT harness ===" >&2
	echo "Adapter will call setup() → start gateway, then run one prompt." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/single_harness.py" "$@"
	;;

gateway)
	echo "=== Starting GATEWAY harness (gateway + poller) ===" >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/gateway_harness.py" "$@"
	;;

inbox)
	echo "=== Starting INBOX POLLER harness ===" >&2
	exec python3 "${RUNNERS_DIR}/inbox_poller_harness.py" "$@"
	;;

*)
	echo "ERROR: Unknown harness '$HARNESS'" >&2
	echo "Run 'docker run agentia list' to see available harnesses." >&2
	exit 1
	;;
esac
