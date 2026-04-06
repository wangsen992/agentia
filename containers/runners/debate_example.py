#!/usr/bin/env python3
"""
Debate Example — 2-agent moderated research debate.

Uses docker exec to drive agents in isolated containers.
Each agent runs in its own container with its own gateway.
The moderator sends messages via docker exec and reads responses.

Usage:
    # First, build and start agents:
    cd container/
    docker build -f Dockerfile.gateway -t openclaw-agent .
    python3 runners/start_agents.py --count 2 --wait

    # Then run the debate:
    python3 runners/debate_example.py
"""

import sys, os, time

# Add runners dir to path so we can import
sys.path.insert(0, os.path.dirname(__file__))

from moderator import Moderator, ModeratorConfig, AgentConfig
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("debate")


def main():
    agents = [
        AgentConfig(
            id="critic",
            name="Critic",
            role="skeptical reviewer",
            system_prompt="""You are the Critic in a research debate.
Your job: Challenge claims, demand evidence, point out weaknesses.
Rules:
- Be specific about what you disagree with and why
- Ask for paper citations before accepting empirical claims
- Do not agree just to reach consensus
- Be intellectually honest and rigorous

The Defender will make claims about the research topic.
Your job is to stress-test their arguments.""",
            ws_url="docker://agent-0",  # docker exec to agent-0
        ),
        AgentConfig(
            id="defender",
            name="Defender",
            role="knowledgeable advocate",
            system_prompt="""You are the Defender in a research debate.
Your job: Support claims with evidence, cite literature, rebut criticism.
Rules:
- Reference specific papers and findings when making claims
- Acknowledge valid criticisms honestly
- Defend well-established findings with appropriate confidence
- Be precise and avoid overstating evidence

The Critic will challenge your claims.
Your job is to defend sound science while acknowledging genuine uncertainties.""",
            ws_url="docker://agent-1",  # docker exec to agent-1
        ),
    ]

    config = ModeratorConfig(
        agents=agents,
        topic="Is the mixing efficiency in sustained stratified turbulence approximately 0.2?",
        max_turns=4,
        topology="sequential",
        context_policy="full",
        moderator_injects=False,
        stop_condition="fixed-turns",
        intro_message=(
            "Welcome to the debate.\n\n"
            "TOPIC: Is mixing efficiency in sustained stratified turbulence approximately 0.2?\n\n"
            "Defender: present the evidence for this claim.\n"
            "Critic: challenge the Defender's arguments.\n"
            "Defender: respond to the Critic.\n"
            "Critic: make your final case.\n\n"
            "Be rigorous, cite papers, and engage with each other's points."
        )
    )

    log.info("=" * 60)
    log.info("RESEARCH DEBATE")
    log.info(f"Topic: {config.topic}")
    log.info(f"Agents: {[a.name for a in config.agents]}")
    log.info("=" * 60)
    log.info("")

    moderator = Moderator(config)

    try:
        moderator.setup()
        moderator.run()
    except Exception as e:
        log.error(f"Debate failed: {e}")
        moderator.close()
        return 1

    log.info("")
    log.info("=" * 60)
    log.info("DEBATE COMPLETE")
    log.info("=" * 60)

    for record in moderator.transcript:
        log.info("")
        log.info(f"[Turn {record.turn}] {record.agent_name}:")
        preview = record.response[:300].replace("\n", " ")
        log.info(f"  {preview}...")

    log.info("")
    log.info("Full transcript:")
    print(moderator.summarize())

    moderator.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
