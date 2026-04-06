#!/usr/bin/env python3
"""
Start multiple OpenClaw agent containers on distinct ports.

Usage:
    python3 start_agents.py --count 3 --base-port 18790

Each agent gets its own container with:
    - Unique port mapping (host-port = base-port + index)
    - Unique container name (agent-{index})
    - Isolated gateway on loopback inside container

The relay connects via ws://localhost:<port> from the host.
"""

import argparse
import os
import subprocess
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("start_agents")


IMAGE = os.environ.get("AGENTIA_IMAGE", "agentia")
DEFAULT_BASE_PORT = 18790


def check_image(image: str) -> bool:
    """Check if the gateway image exists."""
    result = subprocess.run(
        ["docker", "images", "-q", image],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        log.error(f"Image '{image}' not found.")
        log.error(f"Build it first: docker build -t {image} .")
        return False
    return True


def start_agent(image: str, index: int, port: int) -> bool:
    """Start a single agent container."""
    container_name = f"agent-{index}"

    # Check if already running
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "-q"],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        log.info(f"  {container_name} already running on port {port}")
        return True

    # Kill any existing container with this name
    subprocess.run(["docker", "kill", container_name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["docker", "rm", "-f", container_name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Start new container
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"{port}:18789",
        image,
        "gateway"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"  Failed to start {container_name}: {result.stderr[:200]}")
        return False

    log.info(f"  {container_name} → ws://localhost:{port}")
    return True


def wait_for_gateway(port: int, timeout: float = 30) -> bool:
    """Wait for the gateway on a port to become responsive."""
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://localhost:{port}/"],
            capture_output=True, text=True
        )
        if result.stdout.strip() == "200":
            return True
        time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description="Start multiple OpenClaw agent containers")
    parser.add_argument("--image", "-i", type=str, default=IMAGE,
                        help=f"Docker image to use (default: {IMAGE})")
    parser.add_argument("--count", "-n", type=int, default=2,
                        help="Number of agents to start (default: 2)")
    parser.add_argument("--base-port", "-p", type=int, default=DEFAULT_BASE_PORT,
                        help=f"Base port (default: {DEFAULT_BASE_PORT})")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for all gateways to be ready")
    args = parser.parse_args()

    image = args.image
    if not check_image(image):
        sys.exit(1)

    log.info(f"Starting {args.count} agents on ports {args.base_port}–{args.base_port + args.count - 1}...")
    log.info(f"Image: {image}")
    log.info("")

    for i in range(args.count):
        port = args.base_port + i
        ok = start_agent(image, i, port)
        if not ok:
            log.error(f"Failed to start agent-{i}")
            continue

    log.info("")
    log.info("Container status:")
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
        capture_output=True, text=True
    )
    for line in result.stdout.strip().split("\n"):
        if "agent-" in line:
            log.info(f"  {line}")

    if args.wait:
        log.info("")
        log.info("Waiting for gateways to be ready...")
        all_ready = True
        for i in range(args.count):
            port = args.base_port + i
            ready = wait_for_gateway(port)
            status = "✓" if ready else "✗"
            log.info(f"  [{status}] agent-{i} ws://localhost:{port}")
            if not ready:
                all_ready = False

        if all_ready:
            log.info("")
            log.info("All gateways ready. Relay can now connect.")
        else:
            log.error("")
            log.error("Some gateways failed to respond.")

    else:
        log.info("")
        log.info("To wait for gateways: python3 start_agents.py --wait")


if __name__ == "__main__":
    main()
