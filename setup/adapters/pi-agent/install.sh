#!/bin/bash
# pi-agent runtime installer
# Usage: install.sh <workspace> <config_path>
set -e

WS="${1:-/workspace}"
CONFIG="${2:-/etc/agentia/agent.json}"

echo "[agentia-setup] Installing pi-agent runtime..."

mkdir -p "$WS/.pi/extensions" "$WS/.pi/skills" "$WS/.pi/prompts" "$WS/.pi/sessions"

if command -v pi &> /dev/null; then
    echo "[agentia-setup] pi-agent already installed: $(pi --version 2>/dev/null || echo 'version unknown')"
else
    echo "[agentia-setup] Installing @mariozechner/pi-coding-agent..."
    npm install -g @mariozechner/pi-coding-agent@latest
    echo "[agentia-setup] pi-agent installed: $(pi --version 2>/dev/null || echo 'version unknown')"
fi

echo "[agentia-setup] pi-agent runtime ready at $WS"
