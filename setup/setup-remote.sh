#!/bin/sh
# Bare-metal AgentServer setup for remote machines.
# No Docker, no pip, no container runtime. Python 3 + curl only.
#
# Usage:
#   ./setup-remote.sh --name my-agent --provider minimax --model MiniMax-M2.7 --port 8080
#
# Environment variables:
#   MINIMAX_API_KEY   (required) — API key for the AI provider
#   PI_DIR            Agent home directory (default: ~/.pi/agent)
#   AGENTIA_REPO     Git URL to clone agentia from (default: ask)
#   PORT             Port for AgentServer to listen on (default: 8080)

set -e

AGENTIA_DIR="${AGENTIA_DIR:-$HOME/agentia}"
PI_DIR="${PI_DIR:-$HOME/.pi/agent}"
AGENTIA_REPO="${AGENTIA_REPO:-}"
PORT="${PORT:-8080}"

# ── Parse arguments ──────────────────────────────────────────────────────────

NAME=""
PROVIDER=""
MODEL=""
WORKSPACE="$PI_DIR"
ROLE_GOAL=""
BACKSTORY=""

usage() {
    echo "Usage: $0 \\"
    echo "    --name <agent-name> \\"
    echo "    --provider <provider> \\"
    echo "    --model <model> \\"
    echo "    [--port <port>] \\"
    echo "    [--workspace <path>] \\"
    echo "    [--role-goal <goal>] \\"
    echo "    [--backstory <text>]"
    echo ""
    echo "Environment variables:"
    echo "  MINIMAX_API_KEY   Required. API key for your AI provider."
    echo "  PI_DIR            Agent home directory (default: ~/.pi/agent)"
    echo "  PORT              AgentServer port (default: 8080)"
    echo "  AGENTIA_REPO      Git URL to clone agentia from (default: ask interactively)"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)      NAME="$2";      shift 2 ;;
        --provider)  PROVIDER="$2";  shift 2 ;;
        --model)     MODEL="$2";     shift 2 ;;
        --port)      PORT="$2";      shift 2 ;;
        --workspace) WORKSPACE="$2"; shift 2 ;;
        --role-goal) ROLE_GOAL="$2"; shift 2 ;;
        --backstory) BACKSTORY="$2"; shift 2 ;;
        -h|--help)   usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [ -z "$NAME" ] || [ -z "$PROVIDER" ] || [ -z "$MODEL" ]; then
    echo "Error: --name, --provider, and --model are required." >&2
    usage
fi

if [ -z "$MINIMAX_API_KEY" ]; then
    echo "Error: MINIMAX_API_KEY environment variable is not set." >&2
    echo "Set it with: export MINIMAX_API_KEY=your_key" >&2
    exit 1
fi

# ── Prerequisites ─────────────────────────────────────────────────────────────

echo "[setup] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "Error: curl not found." >&2; exit 1; }

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$PYTHON_VERSION" \< "3.8" ]; then
    echo "Error: Python 3.8+ required, found $PYTHON_VERSION" >&2
    exit 1
fi
echo "[setup] Python $PYTHON_VERSION OK"

# ── Clone agentia ─────────────────────────────────────────────────────────────

if [ ! -d "$AGENTIA_DIR" ]; then
    if [ -z "$AGENTIA_REPO" ]; then
        echo "[setup] Agentia directory not found at $AGENTIA_DIR"
        echo -n "Git URL to clone from (or press Enter to abort): "
        read AGENTIA_REPO
        if [ -z "$AGENTIA_REPO" ]; then
            echo "Aborted." >&2
            exit 1
        fi
    fi
    echo "[setup] Cloning agentia from $AGENTIA_REPO ..."
    git clone "$AGENTIA_REPO" "$AGENTIA_DIR"
else
    echo "[setup] Agentia found at $AGENTIA_DIR"
fi

cd "$AGENTIA_DIR"

# ── Install pi-agent ───────────────────────────────────────────────────────────

PI_INSTALL_DIR="$PI_DIR" PI_DIR="$PI_DIR" sh setup/adapters/pi-agent/install.sh

# ── Set up agent directories ─────────────────────────────────────────────────

echo "[setup] Setting up agent directories at $PI_DIR ..."
mkdir -p "$PI_DIR"

AGENT_JSON="$PI_DIR/agent.json"
echo "[setup] Writing $AGENT_JSON ..."
cat > "$AGENT_JSON" << EOF
{
    "agent_id": "$NAME",
    "provider": "$PROVIDER",
    "model": "$MODEL",
    "workspace": "$WORKSPACE",
    "role_goal": "${ROLE_GOAL:-You are a helpful AI assistant.}",
    "backstory": "${BACKSTORY:-}"
}
EOF

# ── Create agentia directories ─────────────────────────────────────────────────

mkdir -p "$HOME/.agentia/agents/$NAME"
mkdir -p "$HOME/.agentia/conversations"

# ── Print connection info ─────────────────────────────────────────────────────

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo ""
echo "=========================================="
echo "[setup] Agent '$NAME' is configured."
echo ""
echo "  AgentServer URL:  http://$IP_ADDR:$PORT"
echo "  Workspace:        $WORKSPACE"
echo "  Agent config:     $AGENT_JSON"
echo "  Agentia dir:      $AGENTIA_DIR"
echo ""
echo "  To start AgentServer:"
echo "    cd $AGENTIA_DIR"
echo "    export MINIMAX_API_KEY=\$MINIMAX_API_KEY"
echo "    export PI_DIR=$PI_DIR"
echo "    python3 cli/agent.py serve \\"
echo "      --config $AGENT_JSON \\"
echo "      --provider $PROVIDER \\"
echo "      --model $MODEL \\"
echo "      --workspace $WORKSPACE"
echo ""
echo "  To register from your Mac:"
echo "    python3 cli/host.py register http://$IP_ADDR:$PORT --name $NAME"
echo "=========================================="
