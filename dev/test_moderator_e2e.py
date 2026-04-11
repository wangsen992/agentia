#!/usr/bin/env python3
"""
Moderator E2E Test — Two containers talking via DockerBackend.

Run from the agentia project root:
    python3 dev/test_moderator_e2e.py

Prerequisites:
    - analyst-001 and critic-001 containers running with AgentServer
    - Ports: analyst-001 at 18081, critic-001 at 18082
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from relay.backends import DockerBackend, AgentEndpoint
from examples.moderator import Moderator, ModeratorConfig, AgentConfig


ANALYST_SYSTEM_PROMPT = """You are The Analyst — a research-focused AI assistant.

Your job: investigate topics thoroughly, build well-reasoned arguments, ground claims in evidence.

Style: clear, structured, evidence-driven responses. Cite sources when possible."""

CRITIC_SYSTEM_PROMPT = """You are The Critic — a sharp, skeptical AI assistant.

Your job: find weaknesses in arguments, challenge assumptions, identify what could go wrong.

Style: direct, probing, not easily impressed. Push back on shaky reasoning."""


def main():
    topic = "Is AI helping or hurting scientific research?"
    max_turns = 4

    backend = DockerBackend(
        {
            "analyst-001": AgentEndpoint("analyst-001", "localhost", 18081),
            "critic-001": AgentEndpoint("critic-001", "localhost", 18082),
        }
    )

    agents = [
        AgentConfig(
            id="analyst-001",
            name="The Analyst",
            role="research analyst",
            system_prompt=ANALYST_SYSTEM_PROMPT,
            agent_host="localhost",
            agent_port=18081,
        ),
        AgentConfig(
            id="critic-001",
            name="The Critic",
            role="critical reviewer",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            agent_host="localhost",
            agent_port=18082,
        ),
    ]

    config = ModeratorConfig(
        agents=agents,
        topic=topic,
        max_turns=max_turns,
        topology="sequential",
        context_policy="full",
    )

    moderator = Moderator(config)

    print("=== Moderator E2E Test ===")
    print(f"Topic: {topic}")
    print(f"Agents: {[a.name for a in agents]}")
    print(f"Max turns: {max_turns}")
    print()

    print("Setting up agents...\n")
    moderator.setup()
    print("Starting conversation...\n")
    moderator.run()

    print("\n=== CONVERSATION TRANSCRIPT ===\n")
    for record in moderator.turns:
        print(f"[Turn {record.turn}] {record.agent_name}:")
        print(record.response.strip())
        print()

    print(f"\nTotal turns: {len(moderator.turns)}")

    backend.close()

    output_path = Path(__file__).parent / "transcript_e2e.json"
    moderator.save_transcript(str(output_path))


if __name__ == "__main__":
    main()
