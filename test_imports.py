#!/usr/bin/env python3
"""Quick import + interface check for changed modules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=== Import Check ===")

try:
    from relay.base import BaseRelay, RelayMessage

    print("  relay.base          OK")
except Exception as e:
    print(f"  relay.base          FAIL: {e}")

try:
    from relay import DockerBackend, SSHBackend, HostContainerBackend, AgentEndpoint

    print("  relay               OK")
except Exception as e:
    print(f"  relay               FAIL: {e}")

try:
    from relay.backends import DockerBackend, SSHBackend

    print("  relay.backends      OK")
except Exception as e:
    print(f"  relay.backends      FAIL: {e}")

try:
    from agents.adapters import AgentAdapter, AgentResponse, get_adapter

    print("  agents.adapters     OK")
except Exception as e:
    print(f"  agents.adapters     FAIL: {e}")

try:
    from examples.moderator import Moderator, ModeratorConfig, AgentConfig

    print("  examples.moderator  OK")
except Exception as e:
    print(f"  examples.moderator  FAIL: {e}")

try:
    from agent_side import AgentServer

    print("  agent_side          OK")
except Exception as e:
    print(f"  agent_side          FAIL: {e}")

try:
    from constants import (
        GATEWAY_PORT,
        GATEWAY_CTL_PORT,
        GATEWAY_TOKEN,
        POLL_INTERVAL_DEFAULT,
        RESPONSE_TIMEOUT_DEFAULT,
        AGENT_TIMEOUT_DEFAULT,
    )

    print("  constants           OK")
except Exception as e:
    print(f"  constants           FAIL: {e}")

print("\n=== DockerBackend interface ===")
try:
    backend = DockerBackend()
    methods = [
        "send_message",
        "send_message_async",
        "poll_response",
        "broadcast",
        "get_status",
        "discover",
        "close",
    ]
    for m in methods:
        has = hasattr(backend, m)
        print(f"  {m:<25} {'OK' if has else 'MISSING'}")
    backend.close()
except Exception as e:
    print(f"  DockerBackend init  FAIL: {e}")

print("\n=== AgentEndpoint ===")
try:
    ep = AgentEndpoint("test-agent", "localhost", 8080)
    assert ep.agent_id == "test-agent"
    assert ep.host == "localhost"
    assert ep.port == 8080
    assert ep.url() == "http://localhost:8080"
    assert ep.url("/message") == "http://localhost:8080/message"
    print("  AgentEndpoint       OK")
except Exception as e:
    print(f"  AgentEndpoint       FAIL: {e}")

print("\n=== RelayMessage ===")
try:
    msg = RelayMessage(content="test", from_agent="a", to_agent="b")
    assert msg.content == "test"
    msg.ensure_id()
    msg.ensure_timestamp()
    json_str = msg.to_json()
    msg2 = RelayMessage.from_json(json_str)
    assert msg2.content == msg.content
    print("  RelayMessage        OK")
except Exception as e:
    print(f"  RelayMessage        FAIL: {e}")

print("\n=== Moderator example ===")
try:
    config = ModeratorConfig(
        agents=[
            AgentConfig(
                id="test-agent",
                name="Test",
                role="Testing",
                system_prompt="You are a test agent.",
                agent_host="localhost",
                agent_port=8080,
            )
        ],
        topic="Test topic",
        max_turns=2,
    )
    mod = Moderator(config)
    assert len(mod.turns) == 0
    print("  Moderator           OK")
except Exception as e:
    print(f"  Moderator           FAIL: {e}")

print("\n=== DONE ===")
