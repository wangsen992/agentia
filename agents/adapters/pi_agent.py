"""
pi-agent Agent Adapter

Implements AgentAdapter using `pi --mode rpc` subprocess.
pi-agent is Agentia's primary agent runtime.

Lifecycle:
    adapter.setup()     → verify pi-agent is installed
    adapter.start()     → spawn pi --mode rpc subprocess
    adapter.send()      → write prompt to stdin, collect agent_end response
    adapter.stop()      → abort current operation
    adapter.teardown()  → terminate subprocess
"""

import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional

from .base import AgentAdapter, AgentResponse


class PiAgentAdapter(AgentAdapter):
    """
    AgentAdapter backed by `pi --mode rpc`.

    Lifecycle:
        setup()     — verify pi-agent is installed
        start()     — spawn pi --mode rpc subprocess
        send()      — write prompt, collect response
        stop()      — abort current operation
        teardown()  — terminate subprocess

    Args:
        workspace: Path to agent workspace (contains .pi/ dirs)
        provider: LLM provider name (e.g., "minimax", "anthropic", "openai")
        model: Model name or pattern (e.g., "MiniMax-M2.7", "claude-sonnet-4-20250514")
        timeout: Seconds before subprocess times out (default 120)
    """

    def __init__(
        self,
        workspace: str = "/workspace",
        provider: str = "minimax",
        model: str = "MiniMax-M2.7",
        timeout: int = 120,
    ):
        self._workspace = Path(workspace)
        self._provider = provider
        self._model = model
        self._timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._session_id: Optional[str] = None
        self._response_buffer: list[str] = []
        self._response_event: threading.Event = threading.Event()
        self._event_thread: Optional[threading.Thread] = None

    def setup(self) -> None:
        """Verify pi-agent is installed and workspace exists."""
        try:
            subprocess.run(
                ["pi", "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ) as e:
            raise RuntimeError(
                f"pi-agent not found or not working: {e}. Run: agentia install pi-agent"
            )

    def teardown(self) -> None:
        """Terminate subprocess if alive."""
        self._terminate()

    def start(self, session_id: Optional[str] = None, **opts) -> str:
        """
        Start pi-agent subprocess.

        Args:
            session_id: Optional session ID. Generated if not provided.

        Returns:
            The session_id used.
        """
        if session_id is None:
            session_id = f"agent-{uuid.uuid4().hex[:8]}"
        self._session_id = session_id

        session_dir = self._workspace / ".pi" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Build pi command args — inject AGENTS.md content as system prompt
        pi_args = [
            "pi",
            "--mode",
            "rpc",
            "--provider",
            self._provider,
            "--model",
            self._model,
            "--session-dir",
            str(session_dir),
        ]

        # Load AGENTS.md and pass as appended system prompt
        agents_file = self._workspace / "AGENTS.md"
        if agents_file.exists():
            content = agents_file.read_text().strip()
            if content:
                pi_args += ["--append-system-prompt", content]

        self._proc = subprocess.Popen(
            pi_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(self._workspace),
        )

        self._response_buffer.clear()
        self._response_event.clear()

        self._event_thread = threading.Thread(
            target=self._read_events,
            name=f"pi-event-reader-{session_id}",
            daemon=True,
        )
        self._event_thread.start()

        return self._session_id

    def send(self, message: str) -> AgentResponse:
        """
        Send a message to the running pi-agent and wait for response.

        Writes a prompt command to stdin, blocks until agent_end event,
        collects all text_delta chunks into a single response string.

        Returns:
            AgentResponse with stdout = collected response text.
        """
        if self._proc is None or self._proc.poll() is not None:
            self.start()

        self._response_buffer.clear()
        self._response_event.clear()

        cmd = {"type": "prompt", "message": message}
        try:
            self._proc.stdin.write(json.dumps(cmd) + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError:
            return AgentResponse(
                stdout="",
                stderr="pi-agent subprocess died",
                returncode=1,
            )

        timed_out = not self._response_event.wait(timeout=self._timeout)

        if timed_out:
            self._proc.stdin.write(json.dumps({"type": "abort"}) + "\n")
            self._proc.stdin.flush()
            return AgentResponse(
                stdout="".join(self._response_buffer),
                stderr=f"timeout after {self._timeout}s",
                returncode=124,
            )

        return AgentResponse(
            stdout="".join(self._response_buffer),
            returncode=0,
        )

    def stop(self) -> None:
        """Abort the current operation."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(json.dumps({"type": "abort"}) + "\n")
                self._proc.stdin.flush()
            except BrokenPipeError:
                pass

    def is_running(self) -> bool:
        """Return True if the subprocess is alive."""
        return self._proc is not None and self._proc.poll() is None

    def get_session_id(self) -> Optional[str]:
        """Return current session ID."""
        return self._session_id

    def get_session_trace(self, session_id: Optional[str] = None) -> list:
        """
        Read session JSONL file and return entries.

        pi-agent stores sessions as JSONL in the session directory.
        """
        import json as _json

        sid = session_id or self._session_id
        if not sid:
            return []

        session_dir = self._workspace / ".pi" / "sessions"
        if not session_dir.exists():
            return []

        session_files = sorted(
            session_dir.glob(f"{sid}*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not session_files:
            return []

        entries = []
        with open(session_files[0]) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(_json.loads(line))
                    except _json.JSONDecodeError:
                        pass
        return entries

    def _read_events(self):
        """
        Event reader thread — parses JSONL from stdout.

        Routes events:
          - message_update (text_delta) → append to response buffer
          - agent_end → set response event
          - extension_ui_request → fire-and-forget auto-confirm
          - tool_execution_* → log only
        """
        if self._proc is None:
            return

        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "message_update":
                    delta = event.get("assistantMessageEvent", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("delta", "")
                        if text:
                            self._response_buffer.append(text)

                elif etype == "agent_end":
                    self._response_event.set()

                elif etype == "extension_ui_request":
                    req_id = event.get("id")
                    if req_id and self._proc and self._proc.poll() is None:
                        resp = {
                            "type": "extension_ui_response",
                            "id": req_id,
                            "cancelled": True,
                        }
                        try:
                            self._proc.stdin.write(json.dumps(resp) + "\n")
                            self._proc.stdin.flush()
                        except BrokenPipeError:
                            pass

        except Exception:
            pass

    def _terminate(self):
        """Terminate the subprocess."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            except Exception:
                pass
        self._proc = None
