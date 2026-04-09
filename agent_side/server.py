#!/usr/bin/env python3
"""
AgentServer — universal HTTP/WebSocket server for agent-side messaging.

Exposes:
  Control plane: GET/PUT/PATCH /config, GET /status, POST /restart, GET /metrics
  Host messaging: POST /message, POST /message/async, GET /response/{correlation_id}

Manages agent subprocess lifecycle via Harness.
"""

import json
import os
import re
import sys
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_side.config import AgentServerConfig, ConfigManager, DEFAULT_CONFIG_PATH
from agent_side.harness import Harness
from agents.adapters.pi_agent import SessionManager


class AgentServer:
    """
    HTTP/WebSocket server that manages agent subprocess lifecycle
    and handles host messaging.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        agent_id: Optional[str] = None,
    ):
        config_path = config_path or Path(
            os.environ.get("AGENTIA_CONFIG", str(DEFAULT_CONFIG_PATH))
        )
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get()
        self.agent_id = agent_id or os.environ.get("AGENT_ID", "agent-001")
        self._harness: Optional[Harness] = None
        self._start_time = time.time()
        self._server: Optional[HTTPServer] = None
        # Session manager for multi-session support
        self._session_manager: Optional[SessionManager] = None

    def start(self):
        """Start the harness and session manager."""
        self._harness = Harness(self.agent_id, self.config)
        self._harness.start()
        self._session_manager = SessionManager(
            workspace=self.config.adapter_workspace,
            provider=self.config.adapter_provider,
            model=self.config.adapter_model,
            timeout=self.config.agent_timeout,
            idle_ttl=self.config.session_idle_ttl,
            max_sessions=self.config.max_sessions,
            context_threshold_pct=self.config.context_threshold_pct,
        )
        print(f"[AgentServer] Started on {self.config.host}:{self.config.port}")
        print(f"[AgentServer] Session manager: idle_ttl={self.config.session_idle_ttl}s, max_sessions={self.config.max_sessions}, context_threshold={self.config.context_threshold_pct}%")

    def stop(self):
        """Stop the harness and server."""
        if self._harness is not None:
            self._harness.stop()
            self._harness.teardown()

    def stop(self):
        """Stop the harness and server."""
        if self._harness is not None:
            self._harness.stop()
            self._harness.teardown()
            self._harness = None
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        print("[AgentServer] Stopped")

    def run(self):
        """Start server and run until interrupted."""
        self.start()
        self._server = HTTPServer(
            (self.config.host, self.config.port),
            lambda *args, **kwargs: AgentServerHandler(*args, harness=self, **kwargs),
        )
        print(f"[AgentServer] Listening on {self.config.host}:{self.config.port}")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            self.stop()


class AgentServerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for AgentServer endpoints."""

    def __init__(self, *args, harness: AgentServer, **kwargs):
        self._harness = harness
        super().__init__(*args, **kwargs)

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        return json.loads(body) if body else {}

    def do_GET(self):
        path = self.path

        if path == "/config":
            open('/tmp/debug_config_hit.txt', 'w').write("config route hit")
            self._send_json(200, self._harness.config.to_dict())
            return

        if path == "/status":
            status = (
                self._harness._harness.get_status() if self._harness._harness else {}
            )
            status.update(
                {
                    "ready": self._harness._harness is not None
                    and self._harness._harness._running,
                    "uptime": time.time() - self._harness._start_time,
                }
            )
            self._send_json(200, status)
            return

        if path == "/metrics":
            self._send_json(
                200,
                {
                    "agent_id": self._harness.agent_id,
                    "uptime": time.time() - self._harness._start_time,
                },
            )
            return

        if path.startswith("/response/"):
            correlation_id = path.split("/response/")[1]
            resp = self._get_async_response(correlation_id)
            if resp:
                self._send_json(200, resp)
            else:
                self._send_json(404, {"error": "not found"})
            return

        if path == "/inbox":
            inbox_messages = (
                self._harness._harness._delivery.read_inbox()
                if self._harness._harness
                else []
            )
            self._send_json(200, {"messages": inbox_messages})
            return

        # Files API: GET /files/<path>, LIST /files/<path>
        if path.startswith("/files/"):
            self._handle_files(path.removeprefix("/files/"), "GET")
            return

        # Session management
        sm = self._harness._session_manager
        if sm is None:
            self._send_json(503, {"error": "session manager not initialized"})
            return

        if path == "/sessions":
            self._send_json(200, sm.list_sessions())
            return

        if path.startswith("/sessions/"):
            parts = path.split("/sessions/")[1].split("/", 1)
            name = parts[0]
            rest = parts[1] if len(parts) > 1 else ""

            if not name:
                self._send_json(400, {"error": "session name required"})
                return

            if rest == "":
                # GET /sessions/<name> — get session details
                result = sm.get_session(name)
                if result is None:
                    self._send_json(404, {"error": f"session not found: {name}"})
                else:
                    self._send_json(200, result)
                return

            if rest == "message":
                # POST /sessions/<name>/message
                self._handle_session_message(name)
                return

            if rest == "compact":
                # POST /sessions/<name>/compact
                data = self._read_json()
                result = sm.compact(name, data.get("message", ""))
                if "error" in result:
                    self._send_json(400, result)
                else:
                    self._send_json(200, result)
                return

            # GET /sessions/<name>/... — check for sub-resources
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        if self.path == "/config":
            data = self._read_json()
            config = AgentServerConfig.from_dict(data)
            new_config = self._harness.config_manager.replace(config)
            self._harness.config = new_config
            self._harness._harness.config = new_config
            self._send_json(200, new_config.to_dict())
            return

        if self.path.startswith("/files/"):
            self._handle_files(self.path.removeprefix("/files/"), "PUT")
            return

        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path.startswith("/files/"):
            self._handle_files(self.path.removeprefix("/files/"), "DELETE")
            return

        sm = self._harness._session_manager
        if sm is None:
            self._send_json(503, {"error": "session manager not initialized"})
            return

        if self.path.startswith("/sessions/"):
            raw = self.path.split("/sessions/")[1]
            name = raw.split("?")[0]
            hard = "hard" in raw
            result = sm.delete_session(name, hard=hard)
            if "error" in result:
                self._send_json(404, result)
            else:
                self._send_json(200, result)
            return

        self._send_json(404, {"error": "not found"})

    def do_PATCH(self):
        if self.path == "/config":
            patch = self._read_json()

            # Extract _restart before it reaches config_manager.update()
            # (AgentServerConfig dataclass doesn't have _restart field)
            do_restart = bool(patch.pop("_restart", False))

            new_config = self._harness.config_manager.update(patch)
            self._harness.config = new_config
            if self._harness._harness is not None:
                self._harness._harness.config = new_config

            if do_restart and self._harness._harness is not None:
                self._harness._harness.restart_agent()

            self._send_json(200, new_config.to_dict())
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path

        if path == "/restart":
            if self._harness._harness is not None:
                self._harness._harness.restart_agent()
            self._send_json(200, {"status": "restarting"})
            return

        if path == "/message":
            self._handle_message()
            return

        if path == "/message/async":
            self._handle_message_async()
            return

        sm = self._harness._session_manager

        if path == "/sessions/new":
            if sm is None:
                self._send_json(503, {"error": "session manager not initialized"})
                return
            data = self._read_json()
            result = sm.new_session(
                name=data.get("name"),
                title=data.get("title"),
            )
            self._send_json(200, result)
            return

        if path.startswith("/sessions/"):
            if sm is None:
                self._send_json(503, {"error": "session manager not initialized"})
                return
            parts = path.split("/sessions/")[1].split("/", 1)
            name = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            if rest == "message":
                self._handle_session_message(name)
                return
            if rest == "compact":
                data = self._read_json()
                result = sm.compact(name, data.get("message", ""))
                if "error" in result:
                    self._send_json(400, result)
                else:
                    self._send_json(200, result)
                return
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(404, {"error": "not found"})

    def _handle_message(self):
        """
        Sync send: block until agent finishes, return response.
        For sync delivery: call harness directly.
        For inbox delivery: queue message, poll for response.
        """
        data = self._read_json()
        content = data.get("content", "")
        correlation_id = data.get("correlation_id") or str(uuid.uuid4())

        if self._harness.config.delivery == "sync":
            response = self._harness._harness.process_message_sync(
                content, correlation_id
            )
            self._send_json(200, response)
        else:
            message = {
                "id": str(uuid.uuid4()),
                "from_agent": data.get("from_agent", "moderator"),
                "to_agent": self._harness.agent_id,
                "content": content,
                "correlation_id": correlation_id,
                "timestamp": time.time(),
            }
            self._harness._harness._delivery.append_message(message)
            timeout = self._harness.config.agent_timeout
            resp = self._poll_response(correlation_id, timeout)
            if resp:
                self._send_json(200, resp)
            else:
                self._send_json(
                    504, {"error": "timeout", "correlation_id": correlation_id}
                )

    def _handle_message_async(self):
        """
        Async send: queue immediately, return correlation_id.
        """
        data = self._read_json()
        content = data.get("content", "")
        correlation_id = data.get("correlation_id") or str(uuid.uuid4())

        message = {
            "id": str(uuid.uuid4()),
            "from_agent": data.get("from_agent", "moderator"),
            "to_agent": self._harness.agent_id,
            "content": content,
            "correlation_id": correlation_id,
            "timestamp": time.time(),
        }
        self._harness._harness._delivery.append_message(message)
        self._send_json(200, {"queued": True, "correlation_id": correlation_id})

    def _get_async_response(self, correlation_id: str) -> Optional[dict]:
        """Read response from responses directory."""
        resp_dir = Path(self._harness.config.responses_dir)
        resp_path = resp_dir / f"{correlation_id}.jsonl"
        if resp_path.exists():
            try:
                with open(resp_path, "r") as f:
                    content = f.read().strip()
                resp_path.unlink()
                return json.loads(content)
            except Exception:
                return None
        return None

    def _poll_response(self, correlation_id: str, timeout: float) -> Optional[dict]:
        """Poll for response until timeout."""
        resp_dir = Path(self._harness.config.responses_dir)
        resp_dir.mkdir(parents=True, exist_ok=True)
        start = time.time()
        poll_interval = self._harness.config.poll_interval

        while time.time() - start < timeout:
            resp = self._get_async_response(correlation_id)
            if resp:
                return resp
            time.sleep(poll_interval)
        return None

    def _handle_session_message(self, name: str):
        """Handle POST /sessions/<name>/message."""
        sm = self._harness._session_manager
        data = self._read_json()
        content = data.get("content", "")
        result = sm.send_message(name, content)
        if "error" in result:
            if result.get("error", "").startswith("session not"):
                self._send_json(404, result)
            elif "not running" in result.get("error", ""):
                self._send_json(409, result)
            else:
                self._send_json(400, result)
        else:
            self._send_json(200, result)

    def _handle_files(self, file_path: str, method: str = "GET"):
        """
        Serve files from the agent workspace, scoped to /workspace.

        GET  /files/<path>  → read file
        PUT  /files/<path>  → write file (body = content)
        DELETE /files/<path> → delete file/directory
        LIST /files/<path>  → list directory
        """
        workspace = Path(os.path.expanduser(self._harness.config.adapter_workspace))
        target = (workspace / file_path).resolve()

        # Reject path traversal — ensure resolved path is under workspace
        try:
            target.relative_to(workspace)
        except ValueError:
            self._send_json(403, {"error": "forbidden", "reason": "path traversal"})
            return

        if method == "GET":
            if target.is_file():
                content = target.read_text()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content.encode())
            elif target.is_dir():
                entries = []
                for entry in sorted(target.iterdir()):
                    entries.append({"name": entry.name, "type": "directory" if entry.is_dir() else "file"})
                self._send_json(200, {"path": file_path, "entries": entries})
            else:
                self._send_json(404, {"error": "not found"})
            return

        if method == "PUT":
            target.parent.mkdir(parents=True, exist_ok=True)
            content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            target.write_bytes(content)
            created = not any(p.name == target.name for p in target.parent.iterdir())
            self._send_json(201 if created else 200, {"path": file_path})
            return

        if method == "DELETE":
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
            else:
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, {"deleted": file_path})
            return

    def log_message(self, format, *args):
        print(f"[AgentServer] {args[0]}", flush=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AgentServer")
    parser.add_argument("--config", help="Config file path (default: from AGENTIA_CONFIG env or ~/.agentia/agents/agent.json)")
    parser.add_argument("--agent-id", help="Agent ID (overrides config)")
    parser.add_argument("--host", help="Host to bind (overrides config)")
    parser.add_argument("--port", type=int, help="Port to bind (overrides config)")
    parser.add_argument(
        "--delivery",
        choices=["inbox", "sync"],
        help="Delivery pattern (overrides config)",
    )
    parser.add_argument("--provider", help="LLM provider (overrides config)")
    parser.add_argument("--model", help="LLM model (overrides config)")
    parser.add_argument("--workspace", help="Agent workspace path (overrides config)")
    parser.add_argument("--session-ttl", type=int, default=None,
                        help="Session idle TTL in seconds (overrides config)")
    parser.add_argument("--max-sessions", type=int, default=None,
                        help="Max concurrent running sessions (overrides config)")
    parser.add_argument("--context-threshold", type=int, default=None,
                        help="Context %% threshold for auto-compact (overrides config)")
    args = parser.parse_args()

    config_path_arg = (
        Path(args.config) if args.config
        else Path(os.environ.get("AGENTIA_CONFIG", str(DEFAULT_CONFIG_PATH)))
    )
    server = AgentServer(
        config_path=config_path_arg,
        agent_id=args.agent_id,
    )

    if args.host is not None:
        server.config.host = args.host
    if args.port is not None:
        server.config.port = args.port
    if args.delivery is not None:
        server.config.delivery = args.delivery
    if args.provider is not None:
        server.config.adapter_provider = args.provider
    if args.model is not None:
        server.config.adapter_model = args.model
    if args.workspace is not None:
        server.config.adapter_workspace = args.workspace
    if args.session_ttl is not None:
        server.config.session_idle_ttl = args.session_ttl
    if args.max_sessions is not None:
        server.config.max_sessions = args.max_sessions
    if args.context_threshold is not None:
        server.config.context_threshold_pct = args.context_threshold

    print(
        f"[AgentServer] Config: {os.environ.get('AGENTIA_CONFIG', 'default')} | adapter={server.config.adapter_type} provider={server.config.adapter_provider} model={server.config.adapter_model}"
    )
    server.run()


if __name__ == "__main__":
    main()
