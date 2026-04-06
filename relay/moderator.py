#!/usr/bin/env python3
"""
Moderator — conversation orchestration layer.

Defines agent roles, controls who speaks when, maintains history,
and decides when the conversation ends.

Usage:
    from moderator import Moderator, ModeratorConfig, AgentConfig
    config = ModeratorConfig(...)
    mod = Moderator(config)
    mod.setup()
    mod.run()
    print(mod.transcript)
"""

import time
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from relay import Relay

logger = logging.getLogger("moderator")


@dataclass
class AgentConfig:
    """Configuration for a single agent in the conversation."""

    id: str  # Unique identifier, e.g. "critic"
    name: str  # Display name, e.g. "The Critic"
    role: str  # Role description, e.g. "critical reviewer"
    system_prompt: str  # Full system prompt for this agent
    ws_url: str  # WebSocket URL to this agent's gateway
    token: str = "multi-agent-gateway-token"  # Gateway auth token


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
    """

    def __init__(self, config: ModeratorConfig):
        self.config = config
        self.relay = Relay(timeout=90.0)
        self.turns: list[TurnRecord] = []
        self._setup_done = False
        self._current_agent_index = 0

    def _exec_agent(self, agent: AgentConfig, message: str, timeout: int = 120) -> str:
        """Send message to agent via docker exec."""
        container = agent.ws_url.replace("docker://", "")

        # Reuse the same session ID for this agent
        if not hasattr(self, "_exec_sessions"):
            self._exec_sessions = {}
        session_id = self._exec_sessions.get(agent.id)
        if session_id is None:
            session_id = f"mod-{agent.id}-{int(time.time())}"
            self._exec_sessions[agent.id] = session_id
            logger.info(f"  {agent.id} using session: {session_id}")

        cmd = [
            "docker",
            "exec",
            "-i",
            container,
            "openclaw",
            "agent",
            "--session-id",
            session_id,
            "--message",
            message,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
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

        for agent in self.config.agents:
            if agent.ws_url.startswith("docker://"):
                logger.info(
                    f"  {agent.id} ({agent.name}): docker exec to {agent.ws_url}"
                )
                # Send system prompt as first message
                response = self._exec_agent(agent, agent.system_prompt)
                logger.info(f"  {agent.id} setup response: {response[:100]}")
            else:
                # WebSocket path
                logger.info(
                    f"  Connecting to {agent.id} ({agent.name}) at {agent.ws_url}"
                )
                connected = self.relay.connect(
                    agent.id, agent.ws_url, token=agent.token
                )
                if not connected:
                    logger.error(f"  Failed to connect to {agent.id}")
                    raise ConnectionError(f"Cannot connect to {agent.id}")

                setup_msg = {"type": "system", "content": agent.system_prompt}
                response = self.relay.send(agent.id, setup_msg)
                logger.info(f"  {agent.id} setup response: {str(response)[:100]}")

        # Send topic / intro to all agents
        if self.config.intro_message:
            intro = self.config.intro_message
        else:
            intro = f"Welcome. Today's topic: {self.config.topic}"

        for agent in self.config.agents:
            if agent.ws_url.startswith("docker://"):
                # Use exec path for docker agents
                self._exec_agent(agent, intro)
            else:
                self.relay.send(agent.id, {"type": "user", "content": intro})

        self._setup_done = True
        logger.info("Setup complete.")

    def _get_visible_history(
        self, agent_id: str, current_turn: int
    ) -> list[TurnRecord]:
        """Get the conversation history visible to an agent on this turn."""
        if self.config.context_policy == "none":
            return []

        if self.config.context_policy == "full":
            return self.turns

        # last-N policy
        return self.turns[-self.config.context_window :]

    def _build_prompt(self, agent: AgentConfig, turn: int) -> str:
        """Build the full prompt for an agent on this turn."""
        history = self._get_visible_history(agent.id, turn)

        if not history:
            # First turn — just give the topic
            return f"Topic: {self.config.topic}\n\nRespond to the topic."

        lines = [
            f"TOPIC: {self.config.topic}",
            "",
            "CONVERSATION HISTORY:",
        ]

        for record in history:
            lines.append(f"[Turn {record.turn}] {record.agent_name}:")
            lines.append(record.response)
            lines.append("")

        lines.append(f"You are {agent.name} ({agent.role}).")
        lines.append("Respond to the conversation above.")

        return "\n".join(lines)

    def _next_agent(self) -> AgentConfig:
        """Get the next agent to speak, according to topology."""
        if self.config.topology == "sequential":
            agent = self.config.agents[self._current_agent_index]
            self._current_agent_index = (self._current_agent_index + 1) % len(
                self.config.agents
            )
            return agent
        elif self.config.topology == "ring":
            # Ring: each agent responds to the previous agent's turn
            # Implemented as sequential for now
            return self._next_agent()
        else:
            return self._next_agent()

    def run(self):
        """
        Run the main conversation loop.

        Each turn: select agent → build prompt → send → record response
        """
        if not self._setup_done:
            raise RuntimeError("Must call setup() before run()")

        logger.info(
            f"Starting conversation: {self.config.max_turns} turns, {self.config.topology}"
        )

        for turn in range(1, self.config.max_turns + 1):
            agent = self._next_agent()
            prompt = self._build_prompt(agent, turn)

            logger.info(f"[Turn {turn}] {agent.name} speaking...")

            if agent.ws_url.startswith("docker://"):
                response_text = self._exec_agent(agent, prompt)
            else:
                response = self.relay.send(
                    agent.id, {"type": "user", "content": prompt}
                )
                response_text = ""
                if response and "content" in response:
                    content = response["content"]
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                response_text = block.get("text", "")
                                break
                    elif isinstance(content, str):
                        response_text = content

            record = TurnRecord(
                turn=turn,
                agent_id=agent.id,
                agent_name=agent.name,
                prompt=prompt,
                response=response_text,
            )
            self.turns.append(record)
            # logger.info(
            #     f"[Turn {turn}] {agent.name} responded ({len(response_text)} chars)"
            # )
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
            # lines.append(f"**Prompt:**\n{record.prompt}")
            lines.append(f"**Response:**\n{record.response}")
            lines.append("")
        return "\n".join(lines)

    @property
    def transcript(self) -> list[TurnRecord]:
        """Full conversation transcript."""
        return self.turns

    def close(self):
        """Clean up all connections."""
        self.relay.close_all()


if __name__ == "__main__":
    print("Moderator module. Import and use in your code.")
