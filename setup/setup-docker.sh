#!/bin/sh
# Docker-based Agentia setup helper.
# Builds the image (unless skipped), prepares a local agent home, and starts
# an AgentServer container with sane defaults.
#
# Usage:
#   ./setup/setup-docker.sh --name my-agent --provider minimax --model MiniMax-M2.7
#
# Environment variables:
#   MINIMAX_API_KEY   Required. API key for your AI provider.
#   IMAGE_NAME        Docker image tag to build/run (default: agentia)
#   HOST_BASE         Host base dir for agent homes (default: ~/.agentia/agents)
#   CONTAINER_PORT    Container port for AgentServer (default: 8080)

set -e

IMAGE_NAME="${IMAGE_NAME:-agentia}"
HOST_BASE="${HOST_BASE:-$HOME/.agentia/agents}"
CONTAINER_PORT="${CONTAINER_PORT:-8080}"

NAME=""
PROVIDER=""
MODEL=""
HOST_PORT="18080"
WORKSPACE="/workspace"
ROLE_GOAL=""
BACKSTORY=""
SKIP_BUILD=0
REBUILD=0
FORCE_REPLACE=0
DETACH=1

usage() {
  echo "Usage: $0 \\\" 
    echo " --name <agent-name >\\\"
  echo "    --provider <provider> \\\" 
    echo " --model <model >\\\"
  echo "    [--host-port <port>] \\\" 
    echo " [--workspace \\\" <container-path >]
  echo "    [--role-goal <goal>] \\\" 
    echo " [--backstory \\\" <text >]
  echo "    [--skip-build] [--rebuild] [--force-replace] [--foreground]"
  echo ""
  echo "Environment variables:"
  echo "  MINIMAX_API_KEY   Required. API key for your AI provider."
  echo "  IMAGE_NAME        Docker image tag (default: agentia)"
  echo "  HOST_BASE         Host base dir for agent homes (default: ~/.agentia/agents)"
  echo "  CONTAINER_PORT    Container port (default: 8080)"
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
  --name)
    NAME="$2"
    shift 2
    ;;
  --provider)
    PROVIDER="$2"
    shift 2
    ;;
  --model)
    MODEL="$2"
    shift 2
    ;;
  --host-port)
    HOST_PORT="$2"
    shift 2
    ;;
  --workspace)
    WORKSPACE="$2"
    shift 2
    ;;
  --role-goal)
    ROLE_GOAL="$2"
    shift 2
    ;;
  --backstory)
    BACKSTORY="$2"
    shift 2
    ;;
  --skip-build)
    SKIP_BUILD=1
    shift 1
    ;;
  --rebuild)
    REBUILD=1
    shift 1
    ;;
  --force-replace)
    FORCE_REPLACE=1
    shift 1
    ;;
  --foreground)
    DETACH=0
    shift 1
    ;;
  -h | --help) usage ;;
  *)
    echo "Unknown option: $1"
    usage
    ;;
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

command -v docker >/dev/null 2>&1 || {
  echo "Error: docker not found." >&2
  exit 1
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

AGENT_HOME="$HOST_BASE/$NAME"
mkdir -p "$AGENT_HOME"

if [ "$SKIP_BUILD" -ne 1 ]; then
  echo "[setup-docker] Building Docker image: $IMAGE_NAME"
  if [ "$REBUILD" -eq 1 ]; then
    docker build --no-cache -t "$IMAGE_NAME" .
  else
    docker build -t "$IMAGE_NAME" .
  fi
else
  echo "[setup-docker] Skipping image build"
fi

if docker ps -a --format '{{.Names}}' | grep -Fx "$NAME" >/dev/null 2>&1; then
  if [ "$FORCE_REPLACE" -eq 1 ]; then
    echo "[setup-docker] Removing existing container: $NAME"
    docker rm -f "$NAME" >/dev/null
  else
    echo "Error: container '$NAME' already exists. Use --force-replace to replace it." >&2
    exit 1
  fi
fi

RUN_ARGS=""
if [ "$DETACH" -eq 1 ]; then
  RUN_ARGS="-d"
fi

CMD="docker run $RUN_ARGS --name $NAME -p ${HOST_PORT}:${CONTAINER_PORT} \
  -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
  -v $AGENT_HOME:$WORKSPACE \
  $IMAGE_NAME serve \
    --install pi-agent \
    --config $WORKSPACE/agent.json \
    --provider $PROVIDER \
    --model $MODEL \
    --workspace $WORKSPACE"

if [ -n "$ROLE_GOAL" ]; then
  CMD="$CMD --role-goal $(printf %s "$ROLE_GOAL" | sed "s/'/'\\''/g" | sed "s/^/'/;s/$/'/")"
fi
if [ -n "$BACKSTORY" ]; then
  CMD="$CMD --backstory $(printf %s "$BACKSTORY" | sed "s/'/'\\''/g" | sed "s/^/'/;s/$/'/")"
fi

echo "[setup-docker] Starting container '$NAME' ..."
# shellcheck disable=SC2086
eval "$CMD"

echo ""
echo "=========================================="
echo "[setup-docker] Agent '$NAME' is starting."
echo ""
echo "  Image:            $IMAGE_NAME"
echo "  AgentServer URL:  http://localhost:$HOST_PORT"
echo "  Host agent home:  $AGENT_HOME"
echo "  Workspace mount:  $WORKSPACE"
echo ""
echo "  To register from your host:"
echo "    python3 cli/host.py register http://localhost:$HOST_PORT --name $NAME"
echo ""
echo "  To check status:"
echo "    python3 cli/host.py status $NAME"
echo ""
echo "  To stop the container:"
echo "    docker stop $NAME"
echo "=========================================="
