#!/usr/bin/env python3
"""
Patch openclaw config and start gateway for multi-agent container.
Waits for the gateway to be ready, then approves any pending pairings.
"""

import json, subprocess, sys, time

FIXED_TOKEN = "multi-agent-relay-token"

# Patch config: lan bind + token auth with known token
cfg = json.load(open("/root/.openclaw/openclaw.json"))
cfg["gateway"]["bind"] = "lan"
cfg["gateway"]["auth"]["mode"] = "token"
cfg["gateway"]["auth"]["token"] = FIXED_TOKEN
cfg["gateway"].setdefault("controlUi", {})[
    "dangerouslyAllowHostHeaderOriginFallback"
] = True
json.dump(cfg, open("/root/.openclaw/openclaw.json", "w"), indent=2)
print(f"Config patched: lan bind + token auth ({FIXED_TOKEN})")

# Start gateway in background
gateway_proc = subprocess.Popen(
    [
        "openclaw",
        "gateway",
        "run",
        "--port",
        "18789",
        "--bind",
        "lan",
        "--token",
        FIXED_TOKEN,
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)


# Wait for gateway to be ready and approve any pending pairings
def wait_and_approve():
    for i in range(30):
        time.sleep(1)
        # Check if gateway is up
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "http://127.0.0.1:18789/",
            ],
            capture_output=True,
            text=True,
        )
        if r.stdout.strip() == "200":
            break
        if i >= 5:
            print(f"  Waiting... ({i}s)", flush=True)
    else:
        print("Gateway failed to start")
        gateway_proc.kill()
        return False

    print("Gateway ready. Checking for pending pairings...")

    # Approve any pending pairings
    r = subprocess.run(
        ["openclaw", "devices", "list", "--json"], capture_output=True, text=True
    )
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout)
            pending = data.get("pending", [])
            if pending:
                for req in pending:
                    req_id = req.get("requestId")
                    if req_id:
                        subprocess.run(
                            ["openclaw", "devices", "approve", req_id],
                            capture_output=True,
                        )
                        print(f"  Auto-approved pairing: {req_id[:20]}...")
            else:
                print("  No pending pairings.")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Could not parse pairing list: {e}")
    else:
        print(f"  Could not list pairings: {r.stderr[:100]}")

    return True


ok = wait_and_approve()
if not ok:
    sys.exit(1)

print("Gateway running. Keeping alive...")
gateway_proc.wait()
sys.exit(gateway_proc.returncode)
