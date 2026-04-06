#!/bin/bash
#
# Unified Entrypoint for OpenClaw Harness Container
#
# Usage:
#   docker run -it openclaw-harness [harness] [args...]
#
# Harnesses:
#   interactive    Turn-by-turn interactive REPL (default)
#   multi         Multi-turn automated harness (spawns subagents)
#   single        Single-shot prompt → response
#   gateway       Gateway-only — starts gateway, keeps container alive
#
# Examples:
#   docker run -it openclaw-harness                    # interactive mode
#   docker run -it openclaw-harness interactive        # same as above
#   docker run openclaw-harness single "Hello world"   # single prompt
#   docker run openclaw-harness multi --prompt "..."   # multi-turn automated
#   docker run -it openclaw-harness gateway            # gateway-only mode
#

set -e

OPENCLAW_DIR="/root/.openclaw"
WORKSPACE_DIR="/workspace"
RUNNERS_DIR="${WORKSPACE_DIR}/runners"
GATEWAY_LOG="/tmp/gateway.log"

# Parse harness name (first arg or default to interactive)
HARNESS="${1:-interactive}"
shift 2>/dev/null || true # Remove harness name, keep rest

# ─── Info-Only Modes (no gateway needed) ───────────────────────────────────────

if [ "$HARNESS" = "list" ]; then
	echo "Available harnesses:"
	echo ""
	echo "  interactive   Turn-by-turn REPL — human controls each turn via stdin"
	echo "  multi        Multi-turn automated — spawns subagents, waits, synthesizes"
	echo "  single       One-shot — sends one prompt, prints response, exits"
	echo "  gateway      Gateway-only — starts gateway, keeps container alive"
	echo "  list         Show this list"
	echo "  help         Show full help documentation"
	echo ""
	exit 0
fi

if [ "$HARNESS" = "help" ]; then
	echo "OpenClaw Harness Container — Usage Guide"
	echo "=========================================="
	echo ""
	echo "USAGE:"
	echo "  docker run -it openclaw-harness [harness] [args...]"
	echo ""
	echo "HARNESSES:"
	echo ""
	echo "  interactive"
	echo "    Turn-by-turn REPL. Human types messages, agent responds."
	echo "    Example:  docker run -it openclaw-harness"
	echo ""
	echo "  multi [--prompt P] [--wait N] [--max-turns N]"
	echo "    Automated multi-turn workflow. Agent spawns subagents, waits for"
	echo "    completion, synthesizes results. Good for delegation experiments."
	echo "    Example:  docker run openclaw-harness multi \\"
	echo "                --prompt 'Review all 6 system docs' \\"
	echo "                --wait 30 --max-turns 5"
	echo ""
	echo "  single 'prompt text'"
	echo "    One-shot: sends prompt, prints response, exits immediately."
	echo "    Example:  docker run --rm openclaw-harness single 'What is 2+2?'"
	echo ""
	echo "  gateway"
	echo "    Starts the gateway and keeps the container alive. No harness script"
	echo "    runs — an external harness or tool connects to the gateway directly."
	echo "    Useful for debugging, testing external clients, or manual exploration."
	echo "    Example:  docker run -it openclaw-harness gateway"
	echo ""
	echo "  list"
	echo "    Show available harnesses."
	echo ""
	echo "  help"
	echo "    Show this documentation."
	echo ""
	echo "NOTES:"
	echo "  - Config files are COPY'd at build time — no host ~/.openclaw mounts"
	echo "  - Each run gets a fresh device identity (isolated, no host impact)"
	echo "  - Gateway runs in container, cleaned up on exit"
	echo ""
	exit 0
fi

# ─── Gateway Startup ────────────────────────────────────────────────────────────

echo "=== Generating device identity ===" >&2
openclaw onboard --non-interactive --accept-risk --skip-health 2>&1 | head -3 >&2
echo "" >&2

echo "=== Starting gateway (background) ===" >&2
python3 ${RUNNERS_DIR}/gateway-startup.py &
GW_PID=$!
echo "Gateway Python PID: $GW_PID" >&2

# Cleanup on exit, including child process in python script
cleanup() {
	echo "=== Cleaning up ===" >&2
	kill -9 $GW_PID 2>/dev/null || true
	wait $GW_PID 2>/dev/null || true
}
trap cleanup EXIT

# ─── Harness Dispatch ─────────────────────────────────────────────────────────

case "$HARNESS" in
interactive)
	echo "=== Starting INTERACTIVE harness (stdin/stdout) ===" >&2
	echo "Session controls turns. Type your message, press Enter." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/interactive_harness.py"
	;;

multi)
	echo "=== Starting MULTI-TURN harness ===" >&2
	echo "Automates delegation workflow: spawn subagents → wait → synthesize." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/multi_turn_harness.py" "$@"
	;;

single)
	echo "=== Starting SINGLE-SHOT harness ===" >&2
	echo "Runs one prompt, returns response, exits." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/single_harness.py" "$@"
	;;

gateway)
	echo "=== Starting GATEWAY-ONLY harness ===" >&2
	echo "Gateway is running. Connect an external harness or tool to drive the agent." >&2
	echo "---" >&2
	exec python3 "${RUNNERS_DIR}/gateway_harness.py"
	;;

*)
	echo "ERROR: Unknown harness '$HARNESS'" >&2
	echo "Run 'docker run openclaw-harness list' to see available harnesses." >&2
	exit 1
	;;
esac
