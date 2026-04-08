# Agentia Agent Container
#
# Generic base image for agent containers.
# Runtime (pi-agent, OpenClaw, etc.) is installed at container start via:
#   agentia install <adapter> --config /etc/agentia/agent.json
#
# Usage:
#   docker build -t agentia .
#   docker run -d --name my-agent -p 18000:8080 agentia agentserver

FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install requests jinja2 --break-system-packages

COPY agents/ /workspace/agents/
COPY relay/ /workspace/relay/
COPY agent_side/ /workspace/agent_side/
COPY setup/ /usr/local/bin/setup/
COPY constants.py /workspace/

WORKDIR /workspace

COPY agentia /usr/local/bin/agentia
RUN chmod +x /usr/local/bin/agentia

ENTRYPOINT ["agentia"]
CMD ["agentserver"]
