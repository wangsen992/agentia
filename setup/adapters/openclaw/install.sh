#!/bin/bash
# OpenClaw runtime installer (legacy)
# Usage: install.sh <workspace> <config_path>
set -e

WS="${1:-/workspace}"
CONFIG="${2:-/etc/agentia/agent.json}"

echo "[agentia-setup] Installing OpenClaw runtime..."

mkdir -p "$WS/.openclaw/identity" "$WS/.openclaw/agents/main/agent"

if command -v openclaw &> /dev/null; then
    echo "[agentia-setup] OpenClaw already installed"
else
    echo "[agentia-setup] Installing OpenClaw..."
    npm install -g openclaw@latest
    echo "[agentia-setup] OpenClaw installed"
fi

echo "[agentia-setup] OpenClaw runtime ready at $WS"
