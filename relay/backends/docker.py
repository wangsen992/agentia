"""
DockerBackend — HostContainerBackend implementation using HTTP to AgentServer.

Agent endpoints are configured via static config dict:
    { agent_id: AgentEndpoint(host, port, container_name) }

Uses requests library for HTTP calls to AgentServer endpoints.
"""

import logging
import time
import uuid
from typing import Optional

import requests

from relay.base import RelayMessage
from .base import HostContainerBackend, AgentEndpoint

logger = logging.getLogger("docker_backend")


class DockerBackend(HostContainerBackend):
    """
    HostContainerBackend using HTTP to AgentServer.

    AgentServer is expected to be running inside each container/VM
    at a configured host:port. This backend makes HTTP calls to
    AgentServer endpoints for all messaging operations.

    Usage:
        backend = DockerBackend({
            "agent-a": AgentEndpoint("agent-a", "172.17.0.2", 8080),
            "agent-b": AgentEndpoint("agent-b", "172.17.0.3", 8080),
        })
        backend.send_message(RelayMessage(to_agent="agent-a", content="hello"))
    """

    def __init__(
        self,
        endpoints: Optional[dict[str, AgentEndpoint]] = None,
        default_timeout: float = 60.0,
        poll_interval: float = 1.0,
    ):
        """
        Args:
            endpoints: Static mapping of agent_id -> AgentEndpoint.
                       Can be updated via register_endpoint().
            default_timeout: Default timeout for sync operations.
            poll_interval: Default interval for polling responses.
        """
        self._endpoints: dict[str, AgentEndpoint] = endpoints or {}
        self._default_timeout = default_timeout
        self._poll_interval = poll_interval

    def register_endpoint(self, endpoint: AgentEndpoint) -> None:
        """Register or update an agent endpoint."""
        self._endpoints[endpoint.agent_id] = endpoint

    def _get_endpoint(self, agent_id: str) -> Optional[AgentEndpoint]:
        return self._endpoints.get(agent_id)

    def send_message(self, message: RelayMessage, agent_id: str) -> Optional[str]:
        """
        Sync: HTTP POST /message -> block until agent finishes -> return response.
        """
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            logger.error(f"Unknown agent_id: {agent_id}")
            return None

        correlation_id = message.correlation_id or str(uuid.uuid4())

        payload = {
            "content": message.content,
            "from_agent": message.from_agent or "moderator",
            "correlation_id": correlation_id,
        }

        try:
            response = requests.post(
                endpoint.url("/message"),
                json=payload,
                timeout=self._default_timeout,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("content", "")
            else:
                logger.error(
                    f"Agent {agent_id} /message failed: {response.status_code} {response.text[:200]}"
                )
                return None
        except requests.exceptions.Timeout:
            logger.error(f"Timeout calling {agent_id} /message")
            return None
        except Exception as e:
            logger.error(f"Error calling {agent_id} /message: {e}")
            return None

    def send_message_async(self, message: RelayMessage, agent_id: str) -> bool:
        """
        Fire-and-forget: HTTP POST /message/async -> return immediately.
        """
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            logger.error(f"Unknown agent_id: {agent_id}")
            return False

        correlation_id = message.correlation_id or str(uuid.uuid4())
        message.correlation_id = correlation_id

        payload = {
            "content": message.content,
            "from_agent": message.from_agent or "moderator",
            "correlation_id": correlation_id,
        }

        try:
            response = requests.post(
                endpoint.url("/message/async"),
                json=payload,
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("queued"):
                    logger.debug(
                        f"Message queued for {agent_id}, correlation_id={correlation_id}"
                    )
                    return True
            logger.warning(
                f"Async send to {agent_id} returned {response.status_code}: {response.text[:100]}"
            )
            return False
        except Exception as e:
            logger.error(f"Error async send to {agent_id}: {e}")
            return False

    def poll_response(self, correlation_id: str, timeout: float) -> Optional[dict]:
        """
        Poll GET /response/{correlation_id} until timeout.
        """
        if not self._endpoints:
            logger.error("No endpoints configured for poll_response")
            return None

        endpoint = next(iter(self._endpoints.values()))
        start = time.time()
        last_error = None

        while time.time() - start < timeout:
            try:
                response = requests.get(
                    endpoint.url(f"/response/{correlation_id}"),
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    time.sleep(self._poll_interval)
                    continue
                else:
                    last_error = f"status {response.status_code}"
            except Exception as e:
                last_error = str(e)

            time.sleep(self._poll_interval)

        logger.warning(
            f"poll_response({correlation_id}) timed out. Last error: {last_error}"
        )
        return None

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        """
        Fan-out: send to each agent in message.to_agents.
        """
        results = {}
        for agent_id in message.to_agents or []:
            endpoint = self._get_endpoint(agent_id)
            if not endpoint:
                results[agent_id] = False
                continue

            correlation_id = message.correlation_id or str(uuid.uuid4())
            payload = {
                "content": message.content,
                "from_agent": message.from_agent or "moderator",
                "correlation_id": correlation_id,
            }

            try:
                response = requests.post(
                    endpoint.url("/message"),
                    json=payload,
                    timeout=self._default_timeout,
                )
                results[agent_id] = response.status_code == 200
            except Exception as e:
                logger.error(f"broadcast to {agent_id} failed: {e}")
                results[agent_id] = False

        return results

    def get_status(self, agent_id: str) -> dict:
        """
        GET /status -> health + readiness of AgentServer.
        """
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            return {
                "status": "unknown",
                "ready": False,
                "error": f"Unknown agent_id: {agent_id}",
            }

        try:
            response = requests.get(endpoint.url("/status"), timeout=5.0)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 503:
                return {"status": "not_ready", "ready": False}
            else:
                return {"status": "error", "ready": False, "code": response.status_code}
        except Exception as e:
            return {"status": "error", "ready": False, "error": str(e)}

    def discover(self) -> list[str]:
        """
        List configured agent IDs.
        """
        return list(self._endpoints.keys())

    def close(self) -> None:
        """
        Cleanup. No persistent connections to close in HTTP client model.
        """
        self._endpoints.clear()
