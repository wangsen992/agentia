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
RUN mkdir -p /workspace /root/.openclaw/identity /root/.openclaw/agents/main/agent

# Copy harness scripts + entrypoint
COPY runners/ /workspace/runners/
RUN chmod +x /workspace/runners/entrypoint.sh

# Copy OpenClaw config (BUILD TIME — not a volume mount)
# These files are baked into the image at docker build time.
COPY openclaw.json /root/.openclaw/openclaw.json
COPY auth-profiles.json /root/.openclaw/agents/main/agent/auth-profiles.json

WORKDIR /workspace

# ─── Usage ────────────────────────────────────────────────────────────────────
#
#   docker run -it openclaw-harness                      # interactive REPL
#   docker run -it openclaw-harness interactive          # same as above
#   docker run openclaw-harness multi --prompt "..."     # multi-turn automated
#   docker run openclaw-harness single "Hello world"     # single-shot
#
ENTRYPOINT ["/workspace/runners/entrypoint.sh"]
