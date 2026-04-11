# Agentia Agent Container
#
# Generic base image for agent containers.
#
# Design principle: one mount per agent, at the agent's natural path.
# For pi-agent: host ~/.agentia/agents/<name>/ mounted to ~/.pi/agent/ (pi's natural home).
#
# Container layout:
#   /agent/       ← agent source code (baked in, never shadowed by mount)
#   ~/.pi/agent/  ← agent workspace (mounted from host ~/.agentia/agents/<name>/)
#
# Agent-side CLI: agentia-agent setup | agentia-agent serve
#
# Usage:
#   docker build -t agentia .
#   docker run -d --name my-agent -p 18000:8080 \
#       -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
#       -e PI_DIR=/root/.pi/agent \
#       -v ~/.agentia/agents/my-agent:/root/.pi/agent \
#       agentia-agent serve \
#         --install pi-agent \
#         --config /root/.pi/agent/agent.json \
#         --provider minimax \
#         --model MiniMax-M2.7 \
#         --workspace /root/.pi/agent \
#         --role-goal "You are a helpful assistant"

FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install requests jinja2 --break-system-packages

# Agent source baked into /agent/ — never shadowed by /workspace mount
COPY agents/ /agent/agents/
COPY agent_runtime/ /agent/agent_runtime/
COPY setup/ /agent/setup/
COPY constants.py /agent/
COPY cli/ /agent/cli/

# Entrypoint + ENTRYPOINT both use the source at /agent/ (never mounted over)
COPY agentia-agent /usr/local/bin/agentia-agent
RUN chmod +x /usr/local/bin/agentia-agent

HEALTHCHECK CMD curl -sf http://localhost:8080/status || exit 1

ENTRYPOINT ["agentia-agent"]
CMD ["serve"]
