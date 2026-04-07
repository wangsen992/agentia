#!/usr/bin/env python3
"""
Moderator E2E Test — Two containers talking via InboxRelay.

Run from the agentia project root:
    python3 test_moderator_e2e.py

Prerequisites:
    - analyst-001 and critic-001 containers running
    - Shared inbox at ~/.agentia/inbox/
"""

import json
import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from relay.inbox_relay import InboxRelay
from relay.moderator import Moderator, ModeratorConfig, AgentConfig


# ── Agent configurations ──────────────────────────────────────────────────────

ANALYST_SYSTEM_PROMPT = """You are The Analyst — a research-focused AI assistant.

Your job: investigate topics thoroughly, build well-reasoned arguments, ground claims in evidence.

Style: clear, structured, evidence-driven responses. Cite sources when possible."""

CRITIC_SYSTEM_PROMPT = """You are The Critic — a sharp, skeptical AI assistant.

Your job: find weaknesses in arguments, challenge assumptions, identify what could go wrong.

Style: direct, probing, not easily impressed. Push back on shaky reasoning."""


def main():
    topic = "Is AI helping or hurting scientific research?"
    max_turns = 4  # 2 analyst turns + 2 critic turns

    # ── InboxRelay on host ──────────────────────────────────────────────────
    inbox_base = Path.home() / ".agentia" / "inbox"
    relay = InboxRelay(
        base_dir=str(inbox_base),
        responses_dir=str(inbox_base / "responses"),
        poll_interval=2.0,
        response_timeout=120.0,
    )

    # ── Register agents (container names from docker) ───────────────────────
    relay.register_agent(
        agent_id="analyst-001",
        container_name="agentia-analyst-001",
        name="The Analyst",
        role="research analyst",
    )
    relay.register_agent(
        agent_id="critic-001",
        container_name="agentia-critic-001",
        name="The Critic",
        role="critical reviewer",
    )

    # ── Moderator config ────────────────────────────────────────────────────
    agents = [
        AgentConfig(
            id="analyst-001",
            name="The Analyst",
            role="research analyst",
            system_prompt=ANALYST_SYSTEM_PROMPT,
            ws_url="docker://agentia-analyst-001",
            container_name="agentia-analyst-001",
        ),
        AgentConfig(
            id="critic-001",
            name="The Critic",
            role="critical reviewer",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            ws_url="docker://agentia-critic-001",
            container_name="agentia-critic-001",
        ),
    ]

    config = ModeratorConfig(
        agents=agents,
        topic=topic,
        max_turns=max_turns,
        topology="sequential",
        context_policy="full",
        relay=relay,
    )

    moderator = Moderator(config)

    # ── Setup agents (skip exec-based setup — roles baked into prompts) ────
    print("=== Moderator E2E Test ===")
    print(f"Topic: {topic}")
    print(f"Agents: {[a.name for a in agents]}")
    print(f"Max turns: {max_turns}")
    print()

    # ── Run conversation ─────────────────────────────────────────────────────
    print("Setting up agents...\n")
    moderator.setup()
    print("Starting conversation...\n")
    moderator.run()

    # ── Print transcript ────────────────────────────────────────────────────
    print("\n=== CONVERSATION TRANSCRIPT ===\n")
    for record in moderator.turns:
        print(f"[Turn {record.turn}] {record.agent_name}:")
        print(record.response.strip())
        print()

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\nTotal turns: {len(moderator.turns)}")
    print(f"Stop reason: conversation complete")

    # ── Cleanup ────────────────────────────────────────────────────────────
    relay.close_all()

    # Save transcript to file
    output_path = Path(__file__).parent / "transcript_e2e.json"
    with open(output_path, "w") as f:
        json.dump({
            "topic": topic,
            "turns": [
                {
                    "turn": r.turn,
                    "agent_id": r.agent_id,
                    "agent_name": r.agent_name,
                    "prompt": r.prompt,
                    "response": r.response,
                }
                for r in moderator.turns
            ],
        }, f, indent=2)
    print(f"\nTranscript saved to: {output_path}")


if __name__ == "__main__":
    main()
