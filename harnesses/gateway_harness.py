#!/usr/bin/env python3
"""
Gateway Harness — persistent gateway + inbox poller combined.

Starts the OpenClaw gateway AND the inbox poller in the same container.
This allows both:
  - Gateway debugging (gateway stays alive)
  - agentia exec messaging (poller processes inbox messages)

Gateway Restart API:
  The harness runs a control HTTP server on loopback port 18790.
  Agents can trigger a gateway restart via:

    curl -X POST http://127.0.0.1:18790/restart

  Response: 200 OK with body "restarting\n" on success.
  The restart is graceful: poller stops → gateway tears down → gateway
  re-starts → poller resumes. Inflight messages are dropped.

Usage:
    python3 /workspace/runners/gateway_harness.py

LOG=1 to enable structured logging.
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter
from observability import SessionLogger


# ─── Gateway Control Server ───────────────────────────────────────────────────

GWCTL_PORT = 18790  # loopback-only, no security exposure inside container
RESTART_FLAG = "/workspace/.gateway-restart-requested"


class GatewayCtlHandler(BaseHTTPRequestHandler):
    """Handle gateway restart requests via HTTP."""

    def do_POST(self):
        if self.path in ("/restart", "/kill-gateway"):
            self._do_restart()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"restarting\n")
        else:
            self.send_response(404)
            self.end_headers()

    def _do_restart(self):
        # Signal the main loop by touching the flag file
        Path(RESTART_FLAG).touch()
        print(f"[gwctl] Restart requested via HTTP from {self.client_address[0]}")

    def log_message(self, format, *args):
        # Silence default HTTP logging noise
        pass


def start_gateway_ctl_server() -> threading.Thread:
    """Start the HTTP control server on loopback-only port."""
    t = threading.Thread(
        target=lambda: HTTPServer(("127.0.0.1", GWCTL_PORT), GatewayCtlHandler).serve_forever(),
        daemon=True,
        name="gwctl-server",
    )
    t.start()
    print(f"[gwctl] Control server listening on 127.0.0.1:{GWCTL_PORT}")
    return t


# ─── Inbox Poller ─────────────────────────────────────────────────────────────

class InboxPoller:
    """Minimal inbox poller — runs alongside the gateway."""

    def __init__(self, agent_id: str, poll_interval: float = 2.0):
        self.agent_id = agent_id
        self.poll_interval = poll_interval
        self.running = False
        self._thread = None

    def process_message(self, message: dict) -> str:
        """Process a single message via OpenClaw agent subprocess."""
        from agents.adapters import get_adapter
        import uuid, os, subprocess

        session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
        adapter = get_adapter(timeout=120)
        adapter.start(session_id=session_id)
        response = adapter.send(message.get("content", ""))

        if response.returncode == 0:
            return response.stdout.strip()
        return f"[error] exit {response.returncode}: {response.stderr[:200]}"

    def write_response(self, correlation_id: str, content: str):
        """Write response to the responses directory."""
        if not correlation_id:
            return
        resp_dir = Path("/workspace/inbox/responses")
        resp_dir.mkdir(exist_ok=True)
        resp_path = resp_dir / f"{correlation_id}.jsonl"
        entry = {
            "correlation_id": correlation_id,
            "from_agent": self.agent_id,
            "content": content,
            "timestamp": time.time(),
        }
        try:
            with open(resp_path, "w") as f:
                json.dump(entry, f)
                f.write("\n")
        except Exception as e:
            print(f"[{self.agent_id}] Failed to write response: {e}", flush=True)

    def poll_once(self) -> int:
        """Read all pending inbox messages and process them."""
        inbox_file = Path("/workspace/inbox") / f"{self.agent_id}.jsonl"
        if not inbox_file.exists():
            return 0

        # Read all unread messages
        messages = []
        try:
            with open(inbox_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            print(f"[{self.agent_id}] Inbox read error: {e}", flush=True)
            return 0

        if not messages:
            return 0

        processed_ids = []
        for msg in messages:
            msg_id = msg.get("id", "")
            print(f"[{self.agent_id}] Processing: {msg.get('content', '')[:50]}...", flush=True)
            try:
                content = msg.get("content", "")
                response = self.process_message(msg)
                print(f"[{self.agent_id}] Response: {response[:80]}...", flush=True)
                corr_id = msg.get("correlation_id")
                if corr_id:
                    self.write_response(corr_id, response)
                if msg_id:
                    processed_ids.append(msg_id)
            except Exception as e:
                print(f"[{self.agent_id}] Error processing {msg_id[:8]}: {e}", flush=True)

        # Remove processed messages
        if processed_ids:
            remaining = [m for m in messages if (m.get("id", "") or "") not in processed_ids]
            with open(inbox_file, "w") as f:
                for m in remaining:
                    f.write(json.dumps(m) + "\n")

        return len(processed_ids)

    def run(self):
        """Poll loop with restart-flag check."""
        print(f"[{self.agent_id}] Gateway poller started", flush=True)
        while self.running:
            self.poll_once()
            time.sleep(self.poll_interval)

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False


# ─── Main Harness ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gateway Harness")
    parser.add_argument("--agent-id", default="agent-001")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    do_log = os.environ.get("LOG", "0") == "1"
    agent_id = args.agent_id
    poll_interval = args.poll_interval

    session_id = f"gw-{os.getpid()}"

    harness_logger = None
    if do_log:
        harness_logger = SessionLogger("openclaw", session_id=session_id)
        harness_logger.__enter__()
        print(f"[Logging to {harness_logger.path}]", flush=True)

    print("=== Starting GATEWAY HARNESS (gateway + poller) ===", flush=True)

    # Start the control HTTP server (loopback-only, port 18790)
    ctl_thread = start_gateway_ctl_server()

    # Start the gateway via adapter
    adapter = get_adapter(logger=harness_logger)
    adapter.setup()
    print("Gateway running.", flush=True)

    # Start the inbox poller alongside
    poller = InboxPoller(agent_id=agent_id, poll_interval=poll_interval)
    poller.start()
    print(f"Poller running (interval={poll_interval}s).", flush=True)

    # ── Main loop: poll + restart check ────────────────────────────────────────
    restart_count = 0

    def do_gateway_restart():
        """Perform a graceful gateway restart."""
        nonlocal adapter, poller, restart_count
        restart_count += 1
        print(f"\n[!!] Gateway restart #{restart_count} requested", flush=True)
        print("[!!] Stopping poller...", flush=True)
        poller.stop()
        if hasattr(poller, "_thread") and poller._thread.is_alive():
            poller._thread.join(timeout=5)

        print("[!!] Tearing down gateway...", flush=True)
        adapter.teardown()

        # Small delay before re-initializing
        time.sleep(1)

        print("[!!] Re-initializing adapter...", flush=True)
        adapter = get_adapter(logger=harness_logger)
        adapter.setup()
        print("[!!] Gateway restarted.", flush=True)

        print("[!!] Resuming poller...", flush=True)
        poller = InboxPoller(agent_id=agent_id, poll_interval=poll_interval)
        poller.start()

        # Clear the restart flag
        if Path(RESTART_FLAG).exists():
            Path(RESTART_FLAG).unlink()
        print("[!!] Restart complete.", flush=True)

    def shutdown(signum, frame):
        print("\n[Exiting] Stopping poller and gateway...", flush=True)
        poller.stop()
        adapter.teardown()
        if harness_logger:
            harness_logger.__exit__(None, None, None)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Main poll loop with restart-flag inspection
    try:
        while True:
            # Check restart flag (set by HTTP handler)
            if Path(RESTART_FLAG).exists():
                do_gateway_restart()
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
