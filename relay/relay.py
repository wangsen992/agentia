#!/usr/bin/env python3
"""
Relay — WebSocket transport layer for multi-agent communication.

Routes messages between the moderator and isolated agent containers.
Each agent's gateway exposes a port on the host.

Usage:
    from relay import Relay
    relay = Relay()
    relay.connect("agent-1", "ws://localhost:18790")
    response = relay.send("agent-1", {"type": "user", "content": "Hello"})
    relay.close_all()
"""

import asyncio
import json
import uuid
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional
import websockets
import logging

logger = logging.getLogger("relay")


@dataclass
class AgentConnection:
    id: str
    ws_url: str
    ws: Optional[websockets.WebSocketClientProtocol] = None
    response_buffer: asyncio.Queue = field(default_factory=asyncio.Queue)
    connected: bool = False


class Relay:
    """
    WebSocket relay for multi-agent message routing.

    Manages connections to multiple agent gateways and handles
    message send/receive with async threading support.
    """

    def __init__(self, timeout: float = 60.0):
        self.agents: dict[str, AgentConnection] = {}
        self.timeout = timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    def _ensure_loop(self):
        """Ensure we have an event loop running in a thread."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            # Give the loop a moment to start
            time.sleep(0.1)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_connect(self, agent_id: str, ws_url: str) -> bool:
        """Async connect to an agent gateway."""
        conn = AgentConnection(id=agent_id, ws_url=ws_url)
        self.agents[agent_id] = conn

        try:
            conn.ws = await asyncio.wait_for(
                websockets.connect(ws_url),
                timeout=10.0
            )
            conn.connected = True
            logger.info(f"Connected to {agent_id} at {ws_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {agent_id}: {e}")
            conn.connected = False
            return False

    def connect(self, agent_id: str, ws_url: str, token: str = "") -> bool:
        """Connect to an agent gateway. Thread-safe."""
        if token:
            # Append token as query param
            separator = "?" if "?" not in ws_url else "&"
            ws_url = f"{ws_url}{separator}token={token}"
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            self._async_connect(agent_id, ws_url),
            self._loop
        ).result(timeout=15)

    async def _async_send(self, agent_id: str, message: dict) -> Optional[dict]:
        """Async send a message and wait for response."""
        conn = self.agents.get(agent_id)
        if not conn or not conn.connected or not conn.ws:
            logger.error(f"Agent {agent_id} not connected")
            return None

        try:
            # Send the message
            await conn.ws.send(json.dumps(message))

            # Wait for response with timeout
            response = await asyncio.wait_for(
                conn.ws.recv(),
                timeout=self.timeout
            )
            return json.loads(response)

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from {agent_id}")
            return None
        except Exception as e:
            logger.error(f"Error communicating with {agent_id}: {e}")
            return None

    def send(self, agent_id: str, message: dict) -> Optional[dict]:
        """Send a message to an agent and get response. Thread-safe."""
        if agent_id not in self.agents:
            logger.error(f"Unknown agent: {agent_id}")
            return None

        return asyncio.run_coroutine_threadsafe(
            self._async_send(agent_id, message),
            self._loop
        ).result(timeout=self.timeout + 5)

    async def _async_close(self, agent_id: str):
        """Async close an agent connection."""
        conn = self.agents.get(agent_id)
        if conn and conn.ws:
            await conn.ws.close()
            conn.connected = False
            logger.info(f"Disconnected {agent_id}")

    def close(self, agent_id: str):
        """Close connection to an agent."""
        asyncio.run_coroutine_threadsafe(
            self._async_close(agent_id),
            self._loop
        ).result(timeout=5)

    def close_all(self):
        """Close all agent connections."""
        for agent_id in list(self.agents.keys()):
            try:
                self.close(agent_id)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is connected."""
        return self.agents.get(agent_id, AgentConnection(id=agent_id, ws_url="")).connected

    def send_with_history(self, agent_id: str, messages: list[dict]) -> Optional[dict]:
        """
        Send a conversation history to an agent.
        The last message is the current prompt; prior messages provide context.
        """
        return self.send(agent_id, messages[-1])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    relay = Relay()

    # Example: connect to two agents
    # relay.connect("agent-1", "ws://localhost:18790")
    # relay.connect("agent-2", "ws://localhost:18791")

    # Example: send a message
    # response = relay.send("agent-1", {
    #     "type": "user",
    #     "content": "What is your name?"
    # })
    # print(response)

    print("Relay module. Import and use in your code.")
