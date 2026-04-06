#!/usr/bin/env python3
"""
Moderator — conversation orchestration layer using BaseRelay.

Refactored from original to work with any BaseRelay implementation
(ExecRelay, InboxRelay, WebSocketRelay, etc.).

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
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseRelay, RelayMessage
from .relay import Relay
from .exec_relay import ExecRelay

logger = logging.getLogger("moderator")


@dataclass
class AgentConfig:
    """Configuration for a single agent in the conversation."""

    id: str  # Unique identifier, e.g. "critic"
    name: str  # Display name, e.g. "The Critic"
    role: str  # Role description, e.g. "critical reviewer"
    system_prompt: str  # Full system prompt for this agent
    ws_url: str  # Connection URL (docker://container-name or ws://host:port)
    token: str = "multi-agent-gateway-token"  # Gateway auth token
    container_name: Optional[str] = None  # For docker exec agents


@dataclass
class ModeratorConfig:
    """Configuration for the entire moderated conversation."""

    agents: list[AgentConfig]
    topic: str  # Conversation topic / question
    max_turns: int = 6  # Total turns before forcing end
    topology: str = "sequential"  # "sequential" | "parallel" | "ring"
    context_policy: str = "full"  # "full" | "last-N" | "none"
    context_window: int = 10  # How many prior turns to include (if last-N)
    moderator_injects: bool = False  # Can moderator interject?
    stop_condition: str = "fixed-turns"  # "fixed-turns" | "consensus" | "manual"
    intro_message: str = ""  # Opening message to all agents
    relay: Optional[BaseRelay] = None  # Inject a relay instance


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

    Responsibilities:
    - Define and setup agent roles
    - Manage conversation topology (who speaks when)
    - Maintain and serve conversation history
    - Detect conversation end
    - Produce a final transcript

    Works with any BaseRelay implementation.
    """

    def __init__(self, config: ModeratorConfig):
        self.config = config
        self._setup_done = False
        self._current_agent_index = 0

        # Use injected relay, or create one based on config
        if config.relay is not None:
            self._relay = config.relay
        else:
            # Create appropriate relay based on first agent's ws_url
            self._relay = self._create_relay_for_config(config)

        self.turns: list[TurnRecord] = []

    def _create_relay_for_config(self, config: ModeratorConfig) -> BaseRelay:
        """Create the right relay type based on agent connection URLs."""
        # Check first agent to determine relay type
        if not config.agents:
            raise ValueError("No agents configured")

        first_url = config.agents[0].ws_url
        if first_url.startswith("docker://"):
            relay = ExecRelay()
            for agent in config.agents:
                container = agent.container_name or agent.ws_url.replace("docker://", "")
                relay.register_agent(
                    agent.id,
                    container_name=container,
                    name=agent.name,
                    role=agent.role,
                    system_prompt=agent.system_prompt,
                )
            return relay
        else:
            # WebSocket relay
            relay = Relay(timeout=90.0)
            for agent in config.agents:
                relay.connect(agent.id, agent.ws_url, token=agent.token)
            return relay

    def _exec_agent(self, agent: AgentConfig, message: str, timeout: int = 120) -> str:
        """Send message to agent via docker exec (ExecRelay path)."""
        import subprocess

        container = agent.container_name or agent.ws_url.replace("docker://", "")

        # Reuse the same session ID for this agent
        if not hasattr(self, "_exec_sessions"):
            self._exec_sessions = {}
        session_id = self._exec_sessions.get(agent.id)
        if session_id is None:
            session_id = f"mod-{agent.id}-{int(time.time())}"
            self._exec_sessions[agent.id] = session_id

        cmd = [
            "docker", "exec", "-i", container,
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", message,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                logger.warning(f"  {agent.id} exec stderr: {result.stderr[:200]}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"  {agent.id} timed out")
            return ""
        except Exception as e:
            logger.error(f"  {agent.id} exec error: {e}")
            return ""

    def setup(self):
        """Set up all agents and send their system prompts."""
        logger.info(f"Setting up {len(self.config.agents)} agents...")

        # Register all agents with the relay
        if isinstance(self._relay, ExecRelay):
            for agent in self.config.agents:
                logger.info(f"  {agent.id} ({agent.name}): docker exec path")
                # Send system prompt as setup
                response = self._exec_agent(agent, agent.system_prompt)
                logger.info(f"  {agent.id} setup response: {response[:100]}")
        else:
            for agent in self.config.agents:
                logger.info(f"  {agent.id} ({agent.name}): WebSocket path")
                self._relay.connect(agent.id, agent.ws_url, token=agent.token)
                setup_msg = json.dumps({"type": "system", "content": agent.system_prompt})
                response = self._relay.send(agent.id, setup_msg)
                logger.info(f"  {agent.id} setup response: {str(response)[:100]}")

        # Send intro to all agents
        intro = self.config.intro_message or f"Welcome. Today's topic: {self.config.topic}"
        for agent in self.config.agents:
            if isinstance(self._relay, ExecRelay):
                self._exec_agent(agent, intro)
            else:
                self._relay.send(agent.id, json.dumps({"type": "user", "content": intro}))

        self._setup_done = True
        logger.info("Setup complete.")

    def _get_visible_history(self, agent_id: str, current_turn: int) -> list[TurnRecord]:
        """Get the conversation history visible to an agent on this turn."""
        if self.config.context_policy == "none":
            return []
        if self.config.context_policy == "full":
            return self.turns
        return self.turns[-self.config.context_window:]

    def _build_prompt(self, agent: AgentConfig, turn: int) -> str:
        """Build the full prompt for an agent on this turn."""
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
        """Get the next agent to speak, according to topology."""
        agent = self.config.agents[self._current_agent_index]
        self._current_agent_index = (self._current_agent_index + 1) % len(self.config.agents)
        return agent

    def _send_to_agent(self, agent: AgentConfig, prompt: str) -> str:
        """Send prompt to agent via appropriate relay mechanism."""
        if isinstance(self._relay, ExecRelay):
            return self._exec_agent(agent, prompt)
        else:
            response = self._relay.send(agent.id, json.dumps({"type": "user", "content": prompt}))
            if response and isinstance(response, dict) and "content" in response:
                content = response["content"]
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block.get("text", "")
                elif isinstance(content, str):
                    return content
            return str(response) if response else ""

    def run(self):
        """Run the main conversation loop."""
        if not self._setup_done:
            raise RuntimeError("Must call setup() before run()")

        logger.info(f"Starting conversation: {self.config.max_turns} turns, {self.config.topology}")

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
        """Generate a summary of the conversation."""
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
        """Full conversation transcript."""
        return self.turns

    def close(self):
        """Clean up all connections."""
        self._relay.close_all()


if __name__ == "__main__":
    print("Moderator module. Import and use in your code.")
