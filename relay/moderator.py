#!/usr/bin/env python3
"""
Moderator — conversation orchestration layer using BaseRelay.

Refactored to work with any BaseRelay implementation
(ExecRelay, InboxRelay, WebSocketRelay) without isinstance checks.

Usage:
    from relay.moderator import Moderator, ModeratorConfig, AgentConfig
    config = ModeratorConfig(...)
    mod = Moderator(config)
    mod.setup()
    mod.run()
    print(mod.transcript)
"""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseRelay, RelayMessage
from .exec_relay import ExecRelay

logger = logging.getLogger("moderator")


@dataclass
class AgentConfig:
    """Configuration for a single agent in the conversation."""

    id: str
    name: str
    role: str
    system_prompt: str
    ws_url: str
    token: str = "multi-agent-gateway-token"
    container_name: Optional[str] = None
    agent_host: Optional[str] = None
    agent_port: Optional[int] = None


@dataclass
class ModeratorConfig:
    """Configuration for the entire moderated conversation."""

    agents: list[AgentConfig]
    topic: str
    max_turns: int = 6
    topology: str = "sequential"
    context_policy: str = "full"
    context_window: int = 10
    moderator_injects: bool = False
    stop_condition: str = "fixed-turns"
    intro_message: str = ""
    relay: Optional[BaseRelay] = None


@dataclass
class TurnRecord:
    """A single turn in the conversation."""

    turn: int
    agent_id: str
    agent_name: str
    prompt: str
    response: str
    timestamp: float = field(default_factory=time.time)


class Moderator:
    """
    Orchestrates a multi-agent conversation.

    Works with any BaseRelay implementation.
    """

    def __init__(self, config: ModeratorConfig):
        self.config = config
        self._setup_done = False
        self._current_agent_index = 0

        if config.relay is not None:
            self._relay = config.relay
        else:
            self._relay = self._create_relay_for_config(config)

        self.turns: list[TurnRecord] = []

    def _create_relay_for_config(self, config: ModeratorConfig):
        if not config.agents:
            raise ValueError("No agents configured")

        first_url = config.agents[0].ws_url
        if (
            first_url.startswith("docker://")
            or first_url.startswith("http://")
            or first_url.startswith("https://")
        ):
            relay = ExecRelay()
            for agent in config.agents:
                container = agent.container_name or agent.ws_url.replace(
                    "docker://", ""
                ).replace("http://", "").replace("https://", "")
                relay.connect(
                    agent.id,
                    container_name=container,
                    name=agent.name,
                    role=agent.role,
                    system_prompt=agent.system_prompt,
                    agent_host=agent.agent_host or "localhost",
                    agent_port=agent.agent_port or 8080,
                )
            return relay
        else:
            from .websocket_relay import WebSocketRelay

            relay = WebSocketRelay(timeout=90.0)
            for agent in config.agents:
                relay.connect(agent.id, agent.ws_url, token=agent.token)
            return relay

    def setup(self):
        """Set up all agents and send their system prompts."""
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
            response = self._relay.send(setup_msg)
            logger.info(f"  {agent.id} setup response: {str(response)[:100]}")

            msg = RelayMessage(
                to_agent=agent.id,
                content=intro,
                from_agent="moderator",
                metadata={"type": "user"},
            )
            self._relay.send(msg)

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
        response = self._relay.send(msg)
        return str(response) if response else ""

    def run(self):
        """Run the main conversation loop."""
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
        """Clean up all connections."""
        self._relay.close_all()


if __name__ == "__main__":
    print("Moderator module. Import and use in your code.")
