#!/usr/bin/env python3
"""
Moderator — multi-agent conversation orchestration example.

This is an EXAMPLE SCRIPT demonstrating how to orchestrate
multi-agent conversations using DockerBackend directly.

Usage:
    from examples.moderator import Moderator, ModeratorConfig, AgentConfig
    config = ModeratorConfig(...)
    mod = Moderator(config)
    mod.setup()
    mod.run()
    mod.print_transcript()
"""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from relay.base import RelayMessage
from relay.backends import DockerBackend, AgentEndpoint

logger = logging.getLogger("moderator")


@dataclass
class AgentConfig:
    id: str
    name: str
    role: str
    system_prompt: str
    agent_host: str = "localhost"
    agent_port: int = 8080


@dataclass
class ModeratorConfig:
    agents: list[AgentConfig]
    topic: str
    max_turns: int = 6
    topology: str = "sequential"
    context_policy: str = "full"
    context_window: int = 10
    moderator_injects: bool = False
    stop_condition: str = "fixed-turns"
    intro_message: str = ""


@dataclass
class TurnRecord:
    turn: int
    agent_id: str
    agent_name: str
    prompt: str
    response: str
    timestamp: float = field(default_factory=time.time)


class Moderator:
    def __init__(self, config: ModeratorConfig):
        self.config = config
        self._setup_done = False
        self._current_agent_index = 0
        self._backend = self._create_backend(config)
        self.turns: list[TurnRecord] = []

    def _create_backend(self, config: ModeratorConfig) -> DockerBackend:
        endpoints = {
            agent.id: AgentEndpoint(
                agent_id=agent.id,
                host=agent.agent_host,
                port=agent.agent_port,
            )
            for agent in config.agents
        }
        return DockerBackend(endpoints)

    def setup(self):
        logger.info(f"Setting up {len(self.config.agents)} agents...")

        intro = (
            self.config.intro_message or f"Welcome. Today's topic: {self.config.topic}"
        )

        for agent in self.config.agents:
            logger.info(f"  {agent.id} ({agent.name}): setting up")
            setup_msg = RelayMessage(
                to_agent=agent.id,
                content=agent.system_prompt,
                from_agent="moderator",
                metadata={"type": "system"},
            )
            response = self._backend.send_message(setup_msg, agent.id)
            logger.info(f"  {agent.id} setup response: {str(response)[:100]}")

            msg = RelayMessage(
                to_agent=agent.id,
                content=intro,
                from_agent="moderator",
                metadata={"type": "user"},
            )
            self._backend.send_message(msg, agent.id)

        self._setup_done = True
        logger.info("Setup complete.")

    def _get_visible_history(
        self, agent_id: str, current_turn: int
    ) -> list[TurnRecord]:
        if self.config.context_policy == "none":
            return []
        if self.config.context_policy == "full":
            return self.turns
        return self.turns[-self.config.context_window :]

    def _build_prompt(self, agent: AgentConfig, turn: int) -> str:
        history = self._get_visible_history(agent.id, turn)

        if not history:
            return f"Topic: {self.config.topic}\n\nRespond to the topic."

        lines = [f"TOPIC: {self.config.topic}", "", "CONVERSATION HISTORY:"]
        for record in history:
            lines.append(f"[Turn {record.turn}] {record.agent_name}:")
            lines.append(record.response)
            lines.append("")
        lines.append(f"You are {agent.name} ({agent.role}).")
        lines.append("Respond to the conversation above.")
        return "\n".join(lines)

    def _next_agent(self) -> AgentConfig:
        agent = self.config.agents[self._current_agent_index]
        self._current_agent_index = (self._current_agent_index + 1) % len(
            self.config.agents
        )
        return agent

    def _send_to_agent(self, agent: AgentConfig, prompt: str) -> str:
        msg = RelayMessage(to_agent=agent.id, content=prompt, from_agent="moderator")
        response = self._backend.send_message(msg, agent.id)
        return str(response) if response else ""

    def run(self):
        if not self._setup_done:
            raise RuntimeError("Must call setup() before run()")

        logger.info(
            f"Starting conversation: {self.config.max_turns} turns, {self.config.topology}"
        )

        for turn in range(1, self.config.max_turns + 1):
            agent = self._next_agent()
            prompt = self._build_prompt(agent, turn)
            logger.info(f"[Turn {turn}] {agent.name} speaking...")

            response_text = self._send_to_agent(agent, prompt)

            record = TurnRecord(
                turn=turn,
                agent_id=agent.id,
                agent_name=agent.name,
                prompt=prompt,
                response=response_text,
            )
            self.turns.append(record)
            logger.info(f"[Turn {turn}] {agent.name} responded:\n {response_text}\n\n)")

        logger.info("Conversation complete.")

    def save_transcript(self, path: str = "conversation_transcript.json") -> str:
        data = {
            "topic": self.config.topic,
            "agents": [
                {"id": a.id, "name": a.name, "role": a.role} for a in self.config.agents
            ],
            "topology": self.config.topology,
            "max_turns": self.config.max_turns,
            "turns": [
                {
                    "turn": r.turn,
                    "agent_id": r.agent_id,
                    "agent_name": r.agent_name,
                    "prompt": r.prompt,
                    "response": r.response,
                    "timestamp": r.timestamp,
                }
                for r in self.turns
            ],
        }

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2))
        print(f"Transcript saved to: {output_path.absolute()}")
        return str(output_path.absolute())

    def print_transcript(self) -> None:
        print("\n" + "=" * 70)
        print("CONVERSATION TRANSCRIPT")
        print("=" * 70)
        for record in self.turns:
            print(f"\n--- Turn {record.turn} | {record.agent_name} ---")
            print(f"\n[Prompt]\n{record.prompt}")
            print(f"\n[Response]\n{record.response}")
        print("\n" + "=" * 70)

    def summarize(self) -> str:
        lines = [
            f"## Moderated Conversation Summary",
            f"",
            f"Topic: {self.config.topic}",
            f"Agents: {', '.join(a.name for a in self.config.agents)}",
            f"Topology: {self.config.topology}",
            f"Total turns: {len(self.turns)}",
            f"",
            f"## Transcript",
            f"",
        ]
        for record in self.turns:
            lines.append(f"### Turn {record.turn} — {record.agent_name}")
            lines.append(f"**Response:**\n{record.response}")
            lines.append("")
        return "\n".join(lines)

    @property
    def transcript(self) -> list[TurnRecord]:
        return self.turns

    def close(self):
        self._backend.close()


if __name__ == "__main__":
    print("Moderator example. Import and use in your code.")
