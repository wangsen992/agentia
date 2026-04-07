#!/usr/bin/env python3
"""
Gateway Harness — persistent gateway + inbox poller combined.

DEPRECATED: This harness is superseded by AgentServer (agent_side/server.py).
AgentServer provides the same functionality with a cleaner HTTP API and
configurable delivery patterns (inbox/sync).

For new deployments, use:
    python3 /workspace/agent_side/server.py --agent-id=<id> --host=0.0.0.0 --port=8080 --delivery=inbox

This harness is kept for backward compatibility.

---

Starts the OpenClaw gateway AND the inbox poller in the same container.
This allows both:
  - Gateway debugging (gateway stays alive)
  - agentia exec messaging (poller processes inbox messages)

Gateway Restart API:
  The harness runs a control HTTP server on loopback port 18790.
  Agents can trigger a gateway restart via:

    curl -X POST http://127.0.0.1:18790/restart

  Response:
    200 OK  — restart initiated (body: "restarting\n")
    503 OK  — restart already in progress (body: "restart in progress\n")
    404     — unknown path

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
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter
from observability import SessionLogger
from relay.inbox import Inbox
from relay.base import RelayMessage

import constants


# ─── Gateway Control Server ───────────────────────────────────────────────────

RESTART_FLAG = "/workspace/.gateway-restart-requested"
RESTARTING = threading.Event()


class GatewayCtlHandler(BaseHTTPRequestHandler):
    """Handle gateway restart requests via HTTP (loopback-only)."""

    def do_POST(self):
        if self.path in ("/restart", "/kill-gateway"):
            self._do_restart()
        elif self.path == "/status":
            self._do_status()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            return

    def _do_status(self):
        status = "restarting" if RESTARTING.is_set() else "ready"
        code = 503 if RESTARTING.is_set() else 200
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(status.encode())

    def _do_restart(self):
        if RESTARTING.is_set():
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"restart in progress\n")
            return

        RESTARTING.set()
        Path(RESTART_FLAG).touch()
        print(
            f"[gwctl] Restart requested via HTTP from {self.client_address[0]}",
            flush=True,
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"restarting\n")

    def log_message(self, format, *args):
        pass


def start_gateway_ctl_server() -> threading.Thread:
    """Start the HTTP control server on loopback-only port."""
    server = HTTPServer(("127.0.0.1", constants.GATEWAY_CTL_PORT), GatewayCtlHandler)
    t = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="gwctl-server",
    )
    t.start()
    print(f"[gwctl] Control server listening on 127.0.0.1:{constants.GATEWAY_CTL_PORT}")
    return t


# ─── Inbox Poller ─────────────────────────────────────────────────────────────


class InboxPoller:
    """Inbox poller that uses relay.inbox.Inbox for message handling."""

    def __init__(
        self,
        agent_id: str,
        poll_interval: float | None = None,
        inbox_dir: str = "/workspace/inbox",
    ):
        self.agent_id = agent_id
        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else constants.POLL_INTERVAL_DEFAULT
        )
        self.inbox_dir = inbox_dir
        self.inbox = Inbox(agent_id=agent_id, base_dir=inbox_dir)
        self.running = False
        self._thread = None

    def process_message(self, message: RelayMessage) -> str:
        """Process a single message via OpenClaw agent subprocess."""
        from agents.adapters import get_adapter

        session_id = f"agent-{self.agent_id}-{uuid.uuid4().hex[:8]}"
        adapter = get_adapter(timeout=constants.AGENT_TIMEOUT_DEFAULT)
        adapter.start(session_id=session_id)
        response = adapter.send(message.content)

        if response.returncode == 0:
            return response.stdout.strip()
        return f"[error] exit {response.returncode}: {response.stderr[:200]}"

    def write_response(self, correlation_id: str, content: str):
        """Write response to the responses directory."""
        if not correlation_id:
            return
        resp_dir = Path(self.inbox_dir) / "responses"
        resp_dir.mkdir(parents=True, exist_ok=True)
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
        messages = self.inbox.read_all()
        if not messages:
            return 0

        processed_ids = []
        for msg in messages:
            print(f"[{self.agent_id}] Processing: {msg.content[:50]}...", flush=True)
            try:
                response = self.process_message(msg)
                print(f"[{self.agent_id}] Response: {response[:80]}...", flush=True)
                if msg.correlation_id:
                    self.write_response(msg.correlation_id, response)
                processed_ids.append(msg.id)
            except Exception as e:
                msg_id_str = (msg.id or "unknown")[:8]
                print(
                    f"[{self.agent_id}] Error processing {msg_id_str}: {e}", flush=True
                )

        if processed_ids:
            self.inbox.mark_processed(processed_ids)

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
    import uuid

    parser = argparse.ArgumentParser(description="Gateway Harness")
    parser.add_argument("--agent-id", default="agent-001")
    parser.add_argument(
        "--poll-interval", type=float, default=constants.POLL_INTERVAL_DEFAULT
    )
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

    ctl_thread = start_gateway_ctl_server()

    adapter = get_adapter(logger=harness_logger)
    adapter.setup()
    print("Gateway running.", flush=True)

    poller = InboxPoller(agent_id=agent_id, poll_interval=poll_interval)
    poller.start()
    print(f"Poller running (interval={poll_interval}s).", flush=True)

    restart_count = 0

    def do_gateway_restart():
        nonlocal adapter, poller, restart_count
        restart_count += 1
        print(f"\n[!!] Gateway restart #{restart_count} requested", flush=True)
        print("[!!] Stopping poller...", flush=True)
        poller.stop()
        if poller._thread is not None and poller._thread.is_alive():
            poller._thread.join(timeout=5)

        print("[!!] Tearing down gateway...", flush=True)
        adapter.teardown()

        time.sleep(1)

        print("[!!] Re-initializing adapter...", flush=True)
        adapter = get_adapter(logger=harness_logger)
        adapter.setup()
        print("[!!] Gateway restarted.", flush=True)

        print("[!!] Resuming poller...", flush=True)
        poller = InboxPoller(agent_id=agent_id, poll_interval=poll_interval)
        poller.start()

        if Path(RESTART_FLAG).exists():
            Path(RESTART_FLAG).unlink()
        RESTARTING.clear()
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

    try:
        while True:
            if Path(RESTART_FLAG).exists():
                do_gateway_restart()
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
