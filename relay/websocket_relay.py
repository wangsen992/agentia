#!/usr/bin/env python3
"""
WebSocketRelay — WebSocket transport layer for multi-agent communication.

Routes messages between the moderator and isolated agent containers.
Each agent's gateway exposes a port on the host.

Usage:
    from relay import WebSocketRelay
    relay = WebSocketRelay()
    relay.connect("agent-1", "ws://localhost:18790")
    response = relay.send(RelayMessage(to_agent="agent-1", content="Hello"))
    relay.close_all()
"""

import asyncio
import json
import time
import threading
from dataclasses import dataclass, field
from typing import Optional
import websockets
import logging

from .base import BaseRelay, RelayMessage

logger = logging.getLogger("relay")


@dataclass
class AgentConnection:
    id: str
    ws_url: str
    ws: Optional[websockets.WebSocketClientProtocol] = None
    response_buffer: asyncio.Queue = field(default_factory=asyncio.Queue)
    connected: bool = False


class WebSocketRelay(BaseRelay):
    """
    BaseRelay implementation using WebSocket connections.

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
            time.sleep(0.1)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_connect(self, agent_id: str, ws_url: str) -> bool:
        """Async connect to an agent gateway."""
        conn = AgentConnection(id=agent_id, ws_url=ws_url)
        self.agents[agent_id] = conn

        try:
            conn.ws = await asyncio.wait_for(websockets.connect(ws_url), timeout=10.0)
            conn.connected = True
            logger.info(f"Connected to {agent_id} at {ws_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {agent_id}: {e}")
            conn.connected = False
            return False

    def connect(self, agent_id: str, ws_url: str = "", **kwargs) -> bool:
        """Connect to an agent gateway. Thread-safe."""
        token = kwargs.get("token", "")
        if token and ws_url:
            separator = "?" if "?" not in ws_url else "&"
            ws_url = f"{ws_url}{separator}token={token}"
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            self._async_connect(agent_id, ws_url), self._loop
        ).result(timeout=15)

    def disconnect(self, agent_id: str) -> None:
        """Close connection to an agent."""
        asyncio.run_coroutine_threadsafe(
            self._async_close(agent_id), self._loop
        ).result(timeout=5)

    async def _async_send(self, agent_id: str, ws_message: dict) -> Optional[dict]:
        """Async send a message and wait for response."""
        conn = self.agents.get(agent_id)
        if not conn or not conn.connected or not conn.ws:
            logger.error(f"Agent {agent_id} not connected")
            return None

        try:
            await conn.ws.send(json.dumps(ws_message))
            response = await asyncio.wait_for(conn.ws.recv(), timeout=self.timeout)
            return json.loads(response)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from {agent_id}")
            return None
        except Exception as e:
            logger.error(f"Error communicating with {agent_id}: {e}")
            return None

    def send(self, message: RelayMessage) -> Optional[str]:
        """Send a message to an agent and get response. Thread-safe."""
        if not message.to_agent:
            logger.error("send() requires message.to_agent")
            return None
        if message.to_agent not in self.agents:
            logger.error(f"Unknown agent: {message.to_agent}")
            return None

        ws_message = {"type": "user", "content": message.content}
        response = asyncio.run_coroutine_threadsafe(
            self._async_send(message.to_agent, ws_message), self._loop
        ).result(timeout=self.timeout + 5)

        if response and isinstance(response, dict):
            return response.get("content", str(response))
        return str(response) if response else None

    def send_async(self, message: RelayMessage) -> bool:
        """Fire-and-forget: send without waiting for response."""
        if not message.to_agent or message.to_agent not in self.agents:
            return False

        ws_message = {"type": "user", "content": message.content}
        try:
            asyncio.run_coroutine_threadsafe(
                self._async_send_no_wait(message.to_agent, ws_message), self._loop
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send async to {message.to_agent}: {e}")
            return False

    async def _async_send_no_wait(self, agent_id: str, ws_message: dict):
        """Send without waiting for response."""
        conn = self.agents.get(agent_id)
        if conn and conn.connected and conn.ws:
            try:
                await conn.ws.send(json.dumps(ws_message))
            except Exception as e:
                logger.error(f"Error sending to {agent_id}: {e}")

    async def _async_close(self, agent_id: str):
        """Async close an agent connection."""
        conn = self.agents.get(agent_id)
        if conn and conn.ws:
            await conn.ws.close()
            conn.connected = False
            logger.info(f"Disconnected {agent_id}")

    def close_all(self) -> None:
        """Close all agent connections."""
        for agent_id in list(self.agents.keys()):
            try:
                self.disconnect(agent_id)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is connected."""
        return self.agents.get(
            agent_id, AgentConnection(id=agent_id, ws_url="")
        ).connected

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """Send a message to all agents in message.to_agents. Returns agent_id -> success."""
        results = {}
        for agent_id in message.to_agents or []:
            if agent_id in self.agents and self.is_connected(agent_id):
                ws_message = {"type": "user", "content": message.content}
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._async_send_no_wait(agent_id, ws_message), self._loop
                    )
                    results[agent_id] = True
                except Exception:
                    results[agent_id] = False
            else:
                results[agent_id] = False
        return results

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close_all()


if __name__ == "__main__":
    print("WebSocketRelay module. Import and use in your code.")
