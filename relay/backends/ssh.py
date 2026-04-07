"""
SSHBackend — HostContainerBackend stub using SSH + curl for HTTP calls.

Implements the same HostContainerBackend interface as DockerBackend,
but uses SSH to run curl commands on remote hosts instead of direct HTTP.

This is a functional stub sufficient for testing. Production use would
benefit from a proper SSH client library (e.g., paramiko) or HTTP-over-SSH
tunneling.
"""

import json
import logging
import subprocess
import time
import uuid
from typing import Optional

from relay.base import RelayMessage
from .base import HostContainerBackend, AgentEndpoint

logger = logging.getLogger("ssh_backend")


class SSHBackend(HostContainerBackend):
    """
    HostContainerBackend using SSH + curl to call AgentServer HTTP endpoints.

    Each agent is accessed via SSH to a remote host, where curl is used
    to make HTTP requests to the local AgentServer.

    Usage:
        backend = SSHBackend({
            "agent-a": AgentEndpoint("agent-a", "ssh://user@host-a", 8080),
        })
    """

    def __init__(
        self,
        endpoints: Optional[dict[str, AgentEndpoint]] = None,
        default_timeout: float = 60.0,
        poll_interval: float = 1.0,
        ssh_user: str = "root",
    ):
        """
        Args:
            endpoints: Static mapping of agent_id -> AgentEndpoint.
            default_timeout: Default timeout for sync operations.
            poll_interval: Default interval for polling responses.
            ssh_user: Default SSH user (overridden by endpoint host if contains user@).
        """
        self._endpoints: dict[str, AgentEndpoint] = endpoints or {}
        self._default_timeout = default_timeout
        self._poll_interval = poll_interval
        self._ssh_user = ssh_user

    def register_endpoint(self, endpoint: AgentEndpoint) -> None:
        """Register or update an agent endpoint."""
        self._endpoints[endpoint.agent_id] = endpoint

    def _get_endpoint(self, agent_id: str) -> Optional[AgentEndpoint]:
        return self._endpoints.get(agent_id)

    def _ssh_url(self, endpoint: AgentEndpoint) -> str:
        host = endpoint.host
        if "://" in host:
            return host
        return f"ssh://{self._ssh_user}@{host}"

    def _run_ssh(self, host: str, curl_cmd: list[str], timeout: float) -> dict:
        """Run curl via SSH, return parsed response dict."""
        ssh_host = (
            host.replace("ssh://", "").replace("http://", "").replace("https://", "")
        )
        full_cmd = ["ssh", ssh_host] + curl_cmd
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            try:
                return {"data": json.loads(result.stdout), "rc": result.returncode}
            except json.JSONDecodeError:
                return {
                    "raw": result.stdout,
                    "stderr": result.stderr,
                    "rc": result.returncode,
                }
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "rc": -1}
        except Exception as e:
            return {"error": str(e), "rc": -1}

    def send_message(self, message: RelayMessage, agent_id: str) -> Optional[str]:
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            logger.error(f"Unknown agent_id: {agent_id}")
            return None

        correlation_id = message.correlation_id or str(uuid.uuid4())
        payload = json.dumps(
            {
                "content": message.content,
                "from_agent": message.from_agent or "moderator",
                "correlation_id": correlation_id,
            }
        )

        curl_cmd = [
            "curl",
            "-s",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
            f"http://127.0.0.1:{endpoint.port}/message",
        ]

        result = self._run_ssh(self._ssh_url(endpoint), curl_cmd, self._default_timeout)
        if result.get("rc") == 0 and "data" in result:
            return result["data"].get("content", "")
        logger.error(f"send_message to {agent_id} failed: {result}")
        return None

    def send_message_async(self, message: RelayMessage, agent_id: str) -> bool:
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            logger.error(f"Unknown agent_id: {agent_id}")
            return False

        correlation_id = message.correlation_id or str(uuid.uuid4())
        message.correlation_id = correlation_id

        payload = json.dumps(
            {
                "content": message.content,
                "from_agent": message.from_agent or "moderator",
                "correlation_id": correlation_id,
            }
        )

        curl_cmd = [
            "curl",
            "-s",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
            f"http://127.0.0.1:{endpoint.port}/message/async",
        ]

        result = self._run_ssh(self._ssh_url(endpoint), curl_cmd, 10.0)
        if result.get("rc") == 0 and "data" in result:
            return result["data"].get("queued", False)
        return False

    def poll_response(self, correlation_id: str, timeout: float) -> Optional[dict]:
        if not self._endpoints:
            return None

        endpoint = next(iter(self._endpoints.values()))
        start = time.time()

        while time.time() - start < timeout:
            curl_cmd = [
                "curl",
                "-s",
                f"http://127.0.0.1:{endpoint.port}/response/{correlation_id}",
            ]
            result = self._run_ssh(self._ssh_url(endpoint), curl_cmd, 10.0)
            if result.get("rc") == 0:
                if "data" in result:
                    return result["data"]
                elif "raw" in result and result["raw"]:
                    try:
                        return json.loads(result["raw"])
                    except json.JSONDecodeError:
                        pass
            time.sleep(self._poll_interval)
        return None

    def broadcast(self, message: RelayMessage) -> dict[str, bool]:
        results = {}
        for agent_id in message.to_agents or []:
            result = self.send_message(message, agent_id)
            results[agent_id] = result is not None
        return results

    def get_status(self, agent_id: str) -> dict:
        endpoint = self._get_endpoint(agent_id)
        if not endpoint:
            return {
                "status": "unknown",
                "ready": False,
                "error": f"Unknown agent_id: {agent_id}",
            }

        curl_cmd = [
            "curl",
            "-s",
            f"http://127.0.0.1:{endpoint.port}/status",
        ]
        result = self._run_ssh(self._ssh_url(endpoint), curl_cmd, 5.0)
        if result.get("rc") == 0 and "data" in result:
            return result["data"]
        return {
            "status": "error",
            "ready": False,
            "error": result.get("error", "unknown"),
        }

    def discover(self) -> list[str]:
        return list(self._endpoints.keys())

    def close(self) -> None:
        self._endpoints.clear()
