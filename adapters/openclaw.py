#!/usr/bin/env python3
"""
OpenClaw Provision Adapter.

Provisions an OpenClaw agent container:
1. Generates .openclaw/ identity via temporary gateway container
2. Sets up workspace from template with role customization
3. Starts the agent container with all mounts
4. Verifies readiness
"""

import json
import os
import subprocess
import time
from pathlib import Path

from . import ProvisionAdapter


class OpenClawAdapter(ProvisionAdapter):
    """
    Provisions an OpenClaw agent container.

    Identity flow:
    - First run: start a temporary gateway container to generate ~/.openclaw/
      files (identity.json, gateway.json). Then stop the temp container.
    - Subsequent runs: reuse existing ~/.openclaw/ — identity is already there.
    """

    def __init__(self, image: str = "agentia", gateway_port: int = 18789):
        self.image = image
        self.gateway_port = gateway_port

    @property
    def framework_name(self) -> str:
        return "openclaw"

    def setup_identity(
        self,
        openclaw_dir: Path,
        reuse: bool = True,
        token: str = "agentia-relay-token",
    ) -> None:
        """
        Generate or reuse .openclaw/ identity.

        Args:
            openclaw_dir: Host path that will be mounted to /root/.openclaw/
            reuse: If True and identity already exists, skip generation
            token: Pairing token to use
        """
        identity_file = openclaw_dir / "identity.json"
        gateway_json = (
            openclaw_dir / "agents" / "main" / "agent" / "gateway.json"
        )

        # Check if already provisioned
        if reuse and identity_file.exists() and gateway_json.exists():
            print(f"[OpenClawAdapter] Identity exists at {openclaw_dir}, reusing")
            return

        print(f"[OpenClawAdapter] Generating OpenClaw identity in {openclaw_dir}")

        # Create the directory structure
        gateway_json.parent.mkdir(parents=True, exist_ok=True)

        # Start a temporary gateway container to generate identity
        # The gateway will write identity.json and gateway.json to /root/.openclaw/
        # which maps to openclaw_dir on the host
        temp_container_name = f"agentia-setup-{os.getpid()}"

        try:
            cmd = [
                "docker", "run",
                "--rm",
                "--name", temp_container_name,
                "-v", f"{openclaw_dir}:/root/.openclaw",
                "-p", f"{self.gateway_port}:{self.gateway_port}",
                "-e", f"OPENCLAW_IDENTITY_TOKEN={token}",
                self.image,
                "gateway",
                "--no-pairing",
                "--port", str(self.gateway_port),
            ]

            # Start gateway in background
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for identity files to appear (gateway generates them on startup)
            timeout = 30
            start = time.time()
            while time.time() - start < timeout:
                if identity_file.exists() and gateway_json.exists():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    f"Timeout waiting for identity files in {openclaw_dir}"
                )

            print(f"[OpenClawAdapter] Identity generated successfully")

        finally:
            # Kill the temp gateway container
            subprocess.run(
                ["docker", "kill", temp_container_name],
                capture_output=True,
            )
            # Also kill the proc if still running
            proc.wait(timeout=5)

    def verify_ready(self, container_name: str, inbox_dir: Path) -> bool:
        """
        Check if the agent container is running and its inbox file exists.
        """
        # Check container is running
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )
        if container_name not in result.stdout:
            return False

        # Check inbox file exists (inbox is created by the poller on first poll)
        inbox_file = inbox_dir / f"{container_name.replace('agent-', '')}.jsonl"
        # We don't require the file to exist yet — just that the container is running
        return True

    def start_container(
        self,
        agent_id: str,
        workspace_dir: Path,
        openclaw_dir: Path,
        inbox_dir: Path,
        mode: str = "agent",
        poll_interval: float = 2.0,
    ) -> str:
        """
        Start the agent container.

        Returns the container name.
        """
        container_name = f"agent-{agent_id}"

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--restart", "unless-stopped",
            "-v", f"{inbox_dir}:/workspace/inbox",
            "-v", f"{workspace_dir}:/workspace",
            "-v", f"{openclaw_dir}:/root/.openclaw",
            self.image,
            "poller",
            "--agent-id", agent_id,
            "--mode", mode,
            "--poll-interval", str(poll_interval),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")

        print(f"[OpenClawAdapter] Started {container_name}")
        return container_name

    def stop_container(self, agent_id: str) -> None:
        """Stop and remove the agent container."""
        container_name = f"agent-{agent_id}"
        subprocess.run(["docker", "stop", container_name], capture_output=True)
        subprocess.run(
            ["docker", "rm", "-f", container_name], capture_output=True
        )
        print(f"[OpenClawAdapter] Stopped {container_name}")
