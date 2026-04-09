# Agentia Agent Container
#
# Generic base image for agent containers.
#
# Layout in image:
#   /agent/       ← agent source code (baked in, not affected by workspace mount)
#   /workspace/  ← user workspace (mounted from ~/.agentia/<name>/ at runtime)
#
# Agent-side CLI: agentia-agent setup | agentia-agent serve
#
# Usage:
#   docker build -t agentia .
#   docker run -d --name my-agent -p 18000:8080 \
#       -e MINIMAX_API_KEY=$MINIMAX_API_KEY \
#       -v ~/.agentia/my-agent:/workspace \
#       agentia-agent serve \
#         --install pi-agent \
#         --config ~/.agentia/my-agent/agent.json \
#         --provider minimax \
#         --model MiniMax-M2.7 \
#         --workspace /workspace \
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
COPY relay/ /agent/relay/
COPY agent_side/ /agent/agent_side/
COPY setup/ /agent/setup/
COPY constants.py /agent/
COPY cli/ /agent/cli/

# Entrypoint + ENTRYPOINT both use the source at /agent/ (never mounted over)
COPY agentia-agent /usr/local/bin/agentia-agent
RUN chmod +x /usr/local/bin/agentia-agent

HEALTHCHECK CMD curl -sf http://localhost:8080/status || exit 1

ENTRYPOINT ["agentia-agent"]
CMD ["serve"]
