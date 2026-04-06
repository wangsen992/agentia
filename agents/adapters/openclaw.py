"""
OpenClaw Agent Adapter

Implements AgentAdapter using `openclaw agent` subprocess.
This is the current production adapter.

Lifecycle:
    adapter.setup()    → onboard + gateway run + approve pairings
    adapter.start()    → openclaw agent --session-id <id>
    adapter.send()     → openclaw agent --message <msg>
    adapter.stop()     → no-op (process exits after send)
    adapter.teardown() → kill gateway process
"""

import json
import os
import subprocess
import time
import uuid
from typing import Optional

from .base import AgentAdapter, AgentResponse


FIXED_TOKEN = "multi-agent-relay-token"
GATEWAY_PORT = 18789


class OpenClawAdapter(AgentAdapter):
    """
    AgentAdapter backed by `openclaw agent`.

    Lifecycle:
        setup()    — onboard + gateway run + wait + approve pairings
        start()    — openclaw agent --session-id <id> (non-blocking session init)
        send()     — openclaw agent --message <msg> (blocking)
        stop()     — no-op
        teardown() — kill gateway

    Args:
        workspace: OPENCLAW_WORKSPACE env var for the agent
        timeout: seconds before subprocess times out (default 120)
    """

    def __init__(self, workspace: Optional[str] = None, timeout: int = 120):
        self._workspace = workspace
        self._timeout = timeout
        self._gateway_proc = None

    # ─── Lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Provision identity, patch config, start gateway, approve pairings."""
        cfg_path = "/root/.openclaw/openclaw.json"

        # Patch config: lan bind + token auth
        cfg = json.load(open(cfg_path))
        cfg["gateway"]["bind"] = "lan"
        cfg["gateway"]["auth"]["mode"] = "token"
        cfg["gateway"]["auth"]["token"] = FIXED_TOKEN
        cfg["gateway"].setdefault("controlUi", {})[
            "dangerouslyAllowHostHeaderOriginFallback"
        ] = True
        json.dump(cfg, open(cfg_path, "w"), indent=2)
        print(f"[OpenClawAdapter] Config patched: lan bind + token auth")

        # Start gateway in background
        self._gateway_proc = subprocess.Popen(
            [
                "openclaw", "gateway", "run",
                "--port", str(GATEWAY_PORT),
                "--bind", "lan",
                "--token", FIXED_TOKEN,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print(f"[OpenClawAdapter] Gateway started (PID {self._gateway_proc.pid})")

        # Wait for gateway to be ready
        self._wait_gateway_ready()

        # Approve any pending pairings
        self._approve_pairings()

    def _wait_gateway_ready(self, timeout: int = 30) -> bool:
        """Poll gateway until it responds with 200."""
        for i in range(timeout):
            time.sleep(1)
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 f"http://127.0.0.1:{GATEWAY_PORT}/"],
                capture_output=True, text=True
            )
            if r.stdout.strip() == "200":
                print(f"[OpenClawAdapter] Gateway ready after {i+1}s")
                return True
            if i >= 5:
                print(f"[OpenClawAdapter] Waiting... ({i+1}s)", flush=True)
        print("[OpenClawAdapter] Gateway failed to start")
        self._gateway_proc.kill()
        return False

    def _approve_pairings(self) -> None:
        """Approve any pending device pairings."""
        r = subprocess.run(
            ["openclaw", "devices", "list", "--json"],
            capture_output=True, text=True
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
                                capture_output=True
                            )
                            print(f"[OpenClawAdapter] Auto-approved: {req_id[:20]}...")
                else:
                    print("[OpenClawAdapter] No pending pairings")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[OpenClawAdapter] Pairing list parse error: {e}")
        else:
            print(f"[OpenClawAdapter] Could not list pairings: {r.stderr[:100]}")

    def teardown(self) -> None:
        """Kill the gateway process."""
        if self._gateway_proc:
            print(f"[OpenClawAdapter] Killing gateway (PID {self._gateway_proc.pid})")
            self._gateway_proc.kill()
            self._gateway_proc.wait()
            self._gateway_proc = None

    # ─── Agent Loop ─────────────────────────────────────────────────────────────

    def start(self, session_id: Optional[str] = None, **opts) -> str:
        if session_id is None:
            session_id = f"agent-{uuid.uuid4().hex[:8]}"
        self.session_id = session_id
        return self.session_id

    def send(self, message: str) -> AgentResponse:
        if self.session_id is None:
            self.start()

        cmd = [
            "openclaw", "agent",
            "--session-id", self.session_id,
            "--message", message
        ]

        env = os.environ.copy()
        if self._workspace:
            env["OPENCLAW_WORKSPACE"] = self._workspace

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            env=env
        )

        return AgentResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode
        )

    def stop(self) -> None:
        """Stop is a no-op for subprocess-based adapter (process exits after send)."""
        self.session_id = None

    def is_running(self) -> bool:
        """Always False — subprocess exits after each send."""
        return False

    def get_session_trace(self, session_id: Optional[str] = None) -> list:
        """
        Read session trace JSONL for this adapter's session.

        Returns list of trace entries from OpenClaw's session JSONL file.
        """
        import json
        from pathlib import Path

        sid = session_id or self.session_id
        if not sid:
            return []

        sessions_dir = Path.home() / ".openclaw" / "agents" / "main" / "sessions"
        if not sessions_dir.exists():
            return []

        session_files = sorted(
            sessions_dir.glob(f"{sid}*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )

        if not session_files:
            return []

        entries = []
        with open(session_files[0]) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries
