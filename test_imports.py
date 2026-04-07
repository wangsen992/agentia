#!/usr/bin/env python3
"""Quick import + interface check for changed modules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── 1. Import all changed modules ──────────────────────────────────────────────
print("=== Import Check ===")
try:
    from relay.base import BaseRelay, RelayMessage
    print("  relay.base          OK")
except Exception as e:
    print(f"  relay.base          FAIL: {e}")

try:
    from relay.moderator import Moderator, ModeratorConfig, AgentConfig
    print("  relay.moderator     OK")
except Exception as e:
    print(f"  relay.moderator     FAIL: {e}")

try:
    from relay.exec_relay import ExecRelay
    print("  relay.exec_relay    OK")
except Exception as e:
    print(f"  relay.exec_relay    FAIL: {e}")

try:
    from agents.adapters.openclaw import OpenClawAdapter
    print("  agents.adapters    OK")
except Exception as e:
    print(f"  agents.adapters     FAIL: {e}")

try:
    from constants import (
        GATEWAY_PORT, GATEWAY_CTL_PORT, GATEWAY_TOKEN,
        POLL_INTERVAL_DEFAULT, RESPONSE_TIMEOUT_DEFAULT, AGENT_TIMEOUT_DEFAULT,
    )
    print("  constants           OK")
except Exception as e:
    print(f"  constants           FAIL: {e}")

# ── 2. ExecRelay inherits BaseRelay ──────────────────────────────────────────
print("\n=== ExecRelay implements BaseRelay ===")
try:
    assert issubclass(ExecRelay, BaseRelay), "ExecRelay should inherit BaseRelay"
    print("  inherits BaseRelay  OK")
except Exception as e:
    print(f"  inherits BaseRelay  FAIL: {e}")

# ── 3. ExecRelay has all required methods ─────────────────────────────────────
print("\n=== ExecRelay interface completeness ===")
required = ['connect', 'disconnect', 'send', 'send_async', 'broadcast', 'is_connected', 'close_all']
for method in required:
    has = hasattr(ExecRelay, method)
    print(f"  {method:<20} {'OK' if has else 'MISSING'}")

# ── 4. ModeratorConfig fields match test_moderator_e2e.py ───────────────────
print("\n=== ModeratorConfig compatibility ===")
fields = {f.name for f in ModeratorConfig.__dataclass_fields__.values()}
expected = {'agents', 'topic', 'max_turns', 'topology', 'context_policy',
            'context_window', 'moderator_injects', 'stop_condition', 'intro_message', 'relay'}
missing = expected - fields
extra = fields - expected
print(f"  Expected fields present: {'OK' if not missing else 'MISSING: ' + str(missing)}")
print(f"  Extra fields:             {'OK (none)' if not extra else str(extra)}")

# ── 5. AgentConfig fields ──────────────────────────────────────────────────────
print("\n=== AgentConfig compatibility ===")
afields = {f.name for f in AgentConfig.__dataclass_fields__.values()}
exp_agent = {'id', 'name', 'role', 'system_prompt', 'ws_url', 'token', 'container_name'}
missing_a = exp_agent - afields
extra_a = afields - exp_agent
print(f"  Expected fields present: {'OK' if not missing_a else 'MISSING: ' + str(missing_a)}")
print(f"  Extra fields:            {'OK (none)' if not extra_a else str(extra_a)}")

# ── 6. Context manager support ────────────────────────────────────────────────
print("\n=== ExecRelay context manager ===")
try:
    with ExecRelay() as r:
        pass
    print("  __enter__/__exit__    OK")
except Exception as e:
    print(f"  __enter__/__exit__    FAIL: {e}")

# ── 7. Constants values ───────────────────────────────────────────────────────
print("\n=== Constants values ===")
from constants import GATEWAY_PORT, GATEWAY_TOKEN, POLL_INTERVAL_DEFAULT
print(f"  GATEWAY_PORT          = {GATEWAY_PORT}  (was hardcoded 18789)")
print(f"  GATEWAY_TOKEN         = {GATEWAY_TOKEN}")
print(f"  POLL_INTERVAL_DEFAULT = {POLL_INTERVAL_DEFAULT}")

# ── 8. Moderator uses relay.connect (not register_agent) ─────────────────────
print("\n=== Moderator relay wiring ===")
import inspect
src = inspect.getsource(Moderator._create_relay_for_config)
calls_register = "register_agent" in src
calls_connect = "relay.connect" in src
print(f"  Uses relay.connect:   {'OK' if calls_connect else 'STILL USES register_agent'}")
print(f"  Uses register_agent:   {'WARNING — old API' if calls_register else 'OK (not used)'}")

# ── 9. ExecRelay.connect signature ─────────────────────────────────────────────
print("\n=== ExecRelay.connect signature ===")
sig = inspect.signature(ExecRelay.connect)
params = list(sig.parameters.keys())
print(f"  Params: {params}")
has_container = 'container_name' in params
has_agent_id = 'agent_id' in params
print(f"  Has agent_id:   {'OK' if has_agent_id else 'MISSING'}")
print(f"  Has container_name: {'OK' if has_container else 'MISSING'}")

print("\n=== DONE ===")
