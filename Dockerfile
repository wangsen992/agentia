# OpenClaw Agent Experiment Harness Container
#
# SAFETY: NEVER mount host ~/.openclaw as a volume into a running container.
# Container processes write to the mounted directory (models.json.tmp, sessions,
# device identity), corrupting the host's OpenClaw configuration.
#
# Instead: COPY config files into the image at build time.
# The container gets its own isolated copy that cannot affect the host.

FROM node:22-bookworm-slim

# Install Python and pip
RUN apt-get update && apt-get install -y \
    python3 python3-venv python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for relay/moderator
RUN pip3 install websockets --break-system-packages

# Install OpenClaw globally
RUN npm install -g openclaw@latest

# Create directory structure
RUN mkdir -p /workspace /workspace/inbox /workspace/inbox/responses /root/.openclaw/identity /root/.openclaw/agents/main/agent

# Copy harness scripts (control plane) → /workspace/runners/
COPY harnesses/ /workspace/runners/
RUN chmod +x /workspace/runners/*.sh

# Copy agent adapter layer
COPY agents/ /workspace/agents/

# Copy observability layer
COPY observability/ /workspace/observability/

# Copy relay layer
COPY relay/ /workspace/relay/

# Copy OpenClaw config (BUILD TIME — not a volume mount)
COPY containers/config/openclaw.json /root/.openclaw/openclaw.json
COPY containers/config/auth-profiles.json /root/.openclaw/agents/main/agent/auth-profiles.json

WORKDIR /workspace

# ─── Usage ────────────────────────────────────────────────────────────────────
#
#   docker build -t agentia .                        # build from repo root
#   docker run -it agentia                           # interactive REPL
#   docker run -it agentia interactive              # same as above
#   docker run agentia single "Hello world"         # single-shot
#   docker run agentia multi --prompt "..."         # multi-turn automated
#   docker run -d -p 18789:18789 agentia            # gateway-only (background)
#
ENTRYPOINT ["/workspace/runners/entrypoint.sh"]
