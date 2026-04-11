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
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import AgentAdapter, AgentResponse


# ---------------------------------------------------------------------------
# Model context window sizes (tokens) for context_pct estimation
# ---------------------------------------------------------------------------
MODEL_CONTEXT: dict[str, int] = {
    "MiniMax-M2.7": 32000,
    "MiniMax-M2": 32000,
    "claude-sonnet-4-20250514": 200000,
    "claude-3-5-sonnet": 200000,
    "claude-3-opus": 200000,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "gemini-2.0-flash": 1000000,
    "gemini-1.5-pro": 200000,
}


def estimate_context_pct(session_file: Path, model: str) -> int:
    """Estimate context window usage % based on session file size."""
    if not session_file.exists():
        return 0
    try:
        size_bytes = session_file.stat().st_size
        # Rough estimate: ~4 bytes per token
        tokens = size_bytes / 4
        context_window = MODEL_CONTEXT.get(model, 100000)
        pct = int(tokens / context_window * 100)
        return min(pct, 100)
    except Exception:
        return 0


def slugify_title(title: str) -> str:
    """Slugify a title for use in filenames."""
    slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", title.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


def make_session_name(title: str) -> str:
    """Generate a globally unique session name: timestamp_slug."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    slug = slugify_title(title)
    return f"{ts}_{slug}"


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------
@dataclass
class Session:
    name: str           # globally unique, matches filename without .jsonl
    title: str          # human-readable display name
    status: str = "stopped"  # running | stopped
    pid: Optional[int] = None
    session_file: str = ""
    started_at: str = ""
    message_count: int = 0
    context_pct: int = 0
    last_active: str = ""
    # Runtime-only (not persisted to manifest)
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False)
    _event_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _response_buffer: list = field(default_factory=list, repr=False)
    _response_event: threading.Event = field(default_factory=threading.Event, repr=False)
    # Fired once after spawn: pi sends initial state with actual sessionFile path
    _init_event: threading.Event = field(default_factory=threading.Event, repr=False)
    # Set by event reader when pi reports its actual session file (from get_state response)
    _actual_session_file: str = ""
    # True while waiting for compaction_end after triggering auto-compact
    _compact_pending: bool = field(default=False, repr=False)
    _idle_timer: Optional[threading.Timer] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# SessionManager — owns session lifecycle, manifest, subprocesses
# ---------------------------------------------------------------------------
class SessionManager:
    """
    Manages multiple named pi-agent sessions.

    Each named conversation maps to one pi subprocess with its own session file.
    Manages the manifest, idle timeouts, LRU eviction, and auto-compaction.
    """

    def __init__(
        self,
        workspace: str = "/workspace",
        provider: str = "minimax",
        model: str = "MiniMax-M2.7",
        timeout: int = 120,
        session_dir: Optional[str] = None,
        idle_ttl: int = 1800,
        max_sessions: int = 10,
        context_threshold_pct: int = 75,
    ):
        self._workspace = Path(workspace)
        self._provider = provider
        self._model = model
        self._timeout = timeout
        self._session_dir = Path(session_dir) if session_dir else self._workspace / ".pi" / "sessions"
        self._idle_ttl = idle_ttl
        self._max_sessions = max_sessions
        self._context_threshold_pct = context_threshold_pct

        # Active sessions by name
        self._sessions: dict[str, Session] = {}

        # Ensure session dir exists
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._session_dir / "manifest.jsonl"

        # Lazy load: populate sessions on first access (not on every API call).
        # AgentServer is the single writer; _upsert_manifest keeps disk in sync.

    # -------------------------------------------------------------------------
    # Manifest I/O
    # -------------------------------------------------------------------------
    def _load_manifest(self):
        """Load manifest, rehydrate runtime state (proc=None since they're stopped)."""
        self._sessions.clear()
        if not self._manifest_path.exists():
            return
        for line in self._manifest_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                name = rec.get("name", "")
                if not name:
                    continue
                # Don't restore _proc/_event_thread — subprocess is dead
                self._sessions[name] = Session(
                    name=name,
                    title=rec.get("title", name),
                    status="stopped",
                    pid=None,
                    session_file=rec.get("session_file", ""),
                    started_at=rec.get("started_at", ""),
                    message_count=rec.get("message_count", 0),
                    context_pct=rec.get("context_pct", 0),
                    last_active=rec.get("last_active", ""),
                )
            except Exception:
                continue

    def _resolve_name(self, name: str) -> Optional[str]:
        """
        Resolve a name or title to a session name (key in _sessions dict).

        If name starts with "20" and exists, returns it directly.
        Otherwise searches sessions by title (case-insensitive).
        Returns None if not found.
        """
        if name in self._sessions:
            return name
        # Try title match
        for s in self._sessions.values():
            if s.title.lower() == name.lower():
                return s.name
        return None

    def _save_manifest(self):
        """Persist manifest, stripping runtime-only fields."""
        lines = []
        for s in self._sessions.values():
            rec = {
                "name": s.name,
                "title": s.title,
                "status": s.status,
                "pid": s.pid,
                "session_file": s.session_file,
                "started_at": s.started_at,
                "message_count": s.message_count,
                "context_pct": s.context_pct,
                "last_active": s.last_active,
            }
            lines.append(json.dumps(rec))
        self._manifest_path.write_text("\n".join(lines) + "\n")

    def _upsert_manifest(self, session: Session):
        """Update or append a single manifest entry."""
        # Build dict explicitly, excluding runtime-only (underscore-prefixed) fields
        session_rec = {
            "name": session.name,
            "title": session.title,
            "status": session.status,
            "pid": session.pid,
            "session_file": session.session_file,
            "started_at": session.started_at,
            "message_count": session.message_count,
            "context_pct": session.context_pct,
            "last_active": session.last_active,
        }
        records = []
        found = False
        if self._manifest_path.exists():
            for line in self._manifest_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("name") == session.name:
                        rec = session_rec
                        found = True
                    records.append(rec)
                except Exception:
                    records.append(json.loads(line))
        if not found:
            records.append(session_rec)
        lines = [json.dumps(r) for r in records]
        self._manifest_path.write_text("\n".join(lines) + "\n")

    # -------------------------------------------------------------------------
    # Subprocess lifecycle
    # -------------------------------------------------------------------------
    def _build_pi_args(self, session: Session) -> list[str]:
        """Build the pi command-line args for a session.

        Each Agentia session is bound to an explicit pi session file so distinct
        host/session-manager sessions map to distinct underlying pi histories.
        """
        session_file = self._session_dir / f"{session.name}.jsonl"
        pi_args = [
            "pi",
            "--mode", "rpc",
            "--provider", self._provider,
            "--model", self._model,
            "--session-dir", str(self._session_dir),
            "--session", str(session_file),
        ]
        agents_file = self._workspace / "AGENTS.md"
        if agents_file.exists():
            content = agents_file.read_text().strip()
            if content:
                pi_args += ["--append-system-prompt", content]
        return pi_args

    def _spawn(self, session: Session) -> Session:
        """Spawn a pi subprocess for a session."""
        # Ensure session dir and pre-bind expected session file path
        self._session_dir.mkdir(parents=True, exist_ok=True)
        if not session.session_file:
            session.session_file = f"{session.name}.jsonl"

        pi_args = self._build_pi_args(session)

        proc = subprocess.Popen(
            pi_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(self._workspace),
        )

        session._proc = proc
        session.pid = proc.pid
        session.status = "running"
        session.started_at = session.started_at or datetime.now(timezone.utc).isoformat()

        # Event reader thread
        session._response_buffer.clear()
        session._response_event.clear()
        session._init_event.clear()
        session._actual_session_file = ""
        session._event_thread = threading.Thread(
            target=self._read_events,
            name=f"pi-event-reader-{session.name}",
            daemon=True,
            args=(proc, session),
        )
        session._event_thread.start()

        # pi does not send automatic startup events — we must explicitly request state.
        # Send get_state to discover the actual sessionFile path pi is using.
        # The event reader will capture the response and set _init_event.
        try:
            proc.stdin.write(json.dumps({"type": "get_state"}) + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass  # pi already exited

        # Wait for the get_state response (contains actual sessionFile)
        init_ok = session._init_event.wait(timeout=5)
        if init_ok and session._actual_session_file:
            # pi reports the actual path
            session.session_file = session._actual_session_file
        else:
            # get_state timed out — keep the explicit session-file binding.
            # We launched pi with --session <session.name>.jsonl, so falling back to
            # "most recent file in the directory" would risk aliasing multiple logical
            # sessions onto one underlying pi history.
            session.session_file = session.session_file or f"{session.name}.jsonl"

        self._upsert_manifest(session)
        return session

    def _terminate(self, session: Session, graceful: bool = True):
        """Kill a session's subprocess."""
        if session._proc is None:
            return
        proc = session._proc
        session._proc = None
        session.pid = None
        session.status = "stopped"

        if graceful and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            except Exception:
                pass
        elif proc.poll() is None:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass

        # Cancel idle timer
        if session._idle_timer:
            session._idle_timer.cancel()
            session._idle_timer = None

        self._upsert_manifest(session)

    def _read_events(self, proc: subprocess.Popen, session: Session):
        """Event reader thread for a session's stdout."""
        try:
            for line in proc.stdout:
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
                            session._response_buffer.append(text)

                elif etype == "message":
                    msg = event.get("message", {})
                    if msg.get("role") == "assistant":
                        parts = msg.get("content", []) or []
                        text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
                        if text_parts:
                            session._response_buffer.append("".join(text_parts))
                        elif msg.get("errorMessage"):
                            session._response_buffer.append(f"[agentia] Upstream model error: {msg.get('errorMessage')}")

                elif etype == "agent_end":
                    # Don't signal while a compaction triggered by this agent_end is pending.
                    # The _compact_pending flag is set by send_message when it triggers
                    # auto-compaction after agent_end fires.
                    if not getattr(session, "_compact_pending", False):
                        session._response_event.set()

                elif etype == "response":
                    # pi sends initial state after startup (get_state response).
                    # Capture the actual sessionFile path so _spawn can record it.
                    cmd = event.get("command", "")
                    data = event.get("data", {})
                    if cmd == "get_state" and data.get("sessionFile"):
                        session._actual_session_file = data["sessionFile"]
                        session._init_event.set()
                    elif cmd == "compact":
                        # Compact command acknowledged — will be followed by compaction_end
                        pass

                elif etype == "compaction_end":
                    # Compaction finished — update context_pct and unblock any waiting sender.
                    result = event.get("result", {})
                    ctx = result.get("contextUsage", {})
                    pct = ctx.get("percent") if ctx else None
                    if pct is not None:
                        session.context_pct = int(pct)
                    session._compact_pending = False
                    session._response_event.set()

                elif etype == "extension_ui_request":
                    req_id = event.get("id")
                    if req_id and proc.poll() is None:
                        resp = {
                            "type": "extension_ui_response",
                            "id": req_id,
                            "cancelled": True,
                        }
                        try:
                            proc.stdin.write(json.dumps(resp) + "\n")
                            proc.stdin.flush()
                        except BrokenPipeError:
                            pass
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Idle timer
    # -------------------------------------------------------------------------
    def _reset_idle_timer(self, session: Session):
        """Reset the idle TTL timer for a session."""
        if session._idle_timer:
            session._idle_timer.cancel()
        if session.status != "running":
            return

        def on_idle():
            if session.status == "running":
                self._terminate(session, graceful=True)
                session.status = "stopped"
                self._upsert_manifest(session)

        session._idle_timer = threading.Timer(self._idle_ttl, on_idle)
        session._idle_timer.daemon = True
        session._idle_timer.start()

    # -------------------------------------------------------------------------
    # LRU eviction
    # -------------------------------------------------------------------------
    def _evict_lru(self):
        """Stop the oldest running session to make room for a new one."""
        running = [s for s in self._sessions.values() if s.status == "running"]
        if len(running) < self._max_sessions:
            return
        # Sort by last_active (oldest first)
        running.sort(key=lambda s: s.last_active or "")
        oldest = running[0]
        self._terminate(oldest, graceful=True)
        oldest.status = "stopped"
        self._upsert_manifest(oldest)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def list_sessions(self) -> list[dict]:
        """List all sessions (running and stopped)."""
        if not self._sessions:
            self._load_manifest()
        out = []
        for s in self._sessions.values():
            out.append({
                "name": s.name,
                "title": s.title,
                "status": s.status,
                "message_count": s.message_count,
                "context_pct": s.context_pct,
                "last_active": s.last_active,
            })
        return out

    def get_session(self, name: str) -> Optional[dict]:
        """Get details for one session (resolves by title if not exact name)."""
        if not self._sessions:
            self._load_manifest()
        resolved = self._resolve_name(name)
        if resolved is None:
            return None
        s = self._sessions[resolved]
        return {
            "name": s.name,
            "title": s.title,
            "status": s.status,
            "pid": s.pid,
            "session_file": s.session_file,
            "started_at": s.started_at,
            "message_count": s.message_count,
            "context_pct": s.context_pct,
            "last_active": s.last_active,
        }

    def new_session(self, name: Optional[str] = None, title: Optional[str] = None) -> dict:
        """
        Create or resume a named session.

        Args:
            name: Session name (exact, e.g. "2026-04-09T04-41-15_hawaii") OR title slug
            title: Human-readable title (used for lookup if name not exact match)

        Returns:
            Session dict with status info.
        """
        self._load_manifest()

        # Determine name and title
        if not name and not title:
            title = "default"
            name = None
        if not title:
            title = name or "default"

        # Determine target session_name
        if name and name.startswith("20"):
            # Exact timestamp-name given — use directly
            session_name = name
        else:
            # Title or slug — look up by title in existing sessions
            slug = slugify_title(title)
            found = None
            for s in self._sessions.values():
                # Match by title (case-insensitive)
                if s.title.lower() == title.lower():
                    found = s.name
                    break
            if found:
                session_name = found
            else:
                # New session with timestamp prefix
                session_name = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}_{slug}"

        resumed = False
        if session_name in self._sessions:
            s = self._sessions[session_name]
            if s.status == "running":
                # Already running — no-op
                return {"name": s.name, "title": s.title, "status": "running",
                        "session_file": s.session_file, "resumed": True}
            # Was stopped — resume
            resumed = True
        else:
            s = Session(
                name=session_name,
                title=title,
                status="stopped",
            )
            self._sessions[session_name] = s

        # LRU eviction if at max
        self._evict_lru()

        # Spawn subprocess — _spawn captures the actual sessionFile path from pi
        self._spawn(s)
        self._reset_idle_timer(s)

        return {
            "name": s.name,
            "title": s.title,
            "status": s.status,
            "session_file": s.session_file,
            "resumed": resumed,
        }

    def send_message(self, name: str, content: str) -> dict:
        """
        Send a message to a session. Creates/resumes if needed.
        Returns response dict.
        """
        # Load manifest only once at startup (not on every call).
        # Subsequent calls use in-memory state; _upsert_manifest writes after each modification.
        if not self._sessions:
            self._load_manifest()

        # Resolve name to existing session if needed
        resolved_name = name
        if name not in self._sessions:
            # Try to find by title
            for s in self._sessions.values():
                if s.title.lower() == name.lower():
                    resolved_name = s.name
                    break

        if resolved_name not in self._sessions:
            # Auto-create
            result = self.new_session(name=name, title=name)
            resolved_name = result["name"]

        s = self._sessions[resolved_name]
        if s.status != "running":
            if s.status == "stopped":
                self._spawn(s)  # _spawn captures actual sessionFile from pi
            else:
                return {"error": f"session in invalid state: {s.status}"}

        # Reset idle timer
        self._reset_idle_timer(s)

        # Update last_active
        s.last_active = datetime.now(timezone.utc).isoformat()

        # Send message
        s._response_buffer.clear()
        s._response_event.clear()

        if s._proc is None or s._proc.poll() is not None:
            # Subprocess died — respawn (captures actual sessionFile from pi)
            self._spawn(s)

        cmd = {"type": "prompt", "message": content}
        try:
            s._proc.stdin.write(json.dumps(cmd) + "\n")
            s._proc.stdin.flush()
        except BrokenPipeError:
            return {"error": "pi-agent subprocess died"}

        timed_out = not s._response_event.wait(timeout=self._timeout)

        if timed_out:
            s._proc.stdin.write(json.dumps({"type": "abort"}) + "\n")
            s._proc.stdin.flush()
            response_text = "".join(s._response_buffer)
            return {"response": response_text, "error": f"timeout after {self._timeout}s", "timed_out": True}

        response_text = "".join(s._response_buffer)
        s.message_count += 1

        # Update context_pct — use value set by compaction_end if available,
        # otherwise estimate from current session file
        if s.context_pct == 0:
            sf = self._session_dir / s.session_file
            s.context_pct = estimate_context_pct(sf, self._model)

        # Auto-compact if threshold reached.
        # Set _compact_pending BEFORE waiting so that agent_end won't unblock us
        # (agent_end fires before compaction_end; we need compaction_end to set _response_event).
        compact_triggered = False
        if s.context_pct >= self._context_threshold_pct:
            compact_triggered = self._compact_session(s)
            if compact_triggered:
                s._compact_pending = True
                # Wait for compaction_end (sets _response_event) instead of returning immediately
                timed_out = not s._response_event.wait(timeout=self._timeout)
                if timed_out:
                    s._compact_pending = False
                    return {"response": response_text, "error": "compaction timeout",
                            "message_count": s.message_count, "context_pct": s.context_pct,
                            "compact_triggered": True, "timed_out": True}
                s._compact_pending = False
                # context_pct was updated by compaction_end event handler

        self._upsert_manifest(s)
        self._reset_idle_timer(s)

        return {
            "response": response_text,
            "message_count": s.message_count,
            "context_pct": s.context_pct,
            "compact_triggered": compact_triggered,
        }

    def _compact_session(self, session: Session) -> bool:
        """Send compact command to a running session. Caller sets _compact_pending.

        Returns True if sent. Caller waits for compaction_end via _response_event."""
        if session._proc is None or session._proc.poll() is not None:
            return False
        try:
            session._response_event.clear()
            session._proc.stdin.write(json.dumps({"type": "compact", "message": ""}) + "\n")
            session._proc.stdin.flush()
            return True
        except Exception:
            return False

    def compact(self, name: str, message: str = "") -> dict:
        """Manually trigger compaction on a session. Waits for compaction_end."""
        if not self._sessions:
            self._load_manifest()
        resolved = self._resolve_name(name)
        if resolved is None:
            return {"error": f"session not found: {name}"}
        s = self._sessions[resolved]
        if s.status != "running":
            return {"error": f"session not running: {name}"}

        count_before = s.message_count
        # _compact_session clears _response_event and sends compact command
        sent = self._compact_session(s)
        if not sent:
            return {"error": "failed to send compact command"}

        # Wait for compaction_end (sets _response_event)
        timed_out = not s._response_event.wait(timeout=60)
        if timed_out:
            return {"error": "compaction timeout", "message_count": s.message_count}

        # context_pct was updated by compaction_end event handler
        self._upsert_manifest(s)
        return {"status": "compacted", "message_count_before": count_before,
                "message_count_after": s.message_count, "context_pct": s.context_pct}

    def delete_session(self, name: str, hard: bool = False) -> dict:
        """Stop and optionally delete a session."""
        if not self._sessions:
            self._load_manifest()
        resolved = self._resolve_name(name)
        if resolved is None:
            return {"error": f"session not found: {name}"}
        s = self._sessions[resolved]

        self._terminate(s, graceful=True)
        s.status = "deleted"

        if hard:
            # Delete session file (JSONL in the session dir)
            sf = self._session_dir / s.name
            if sf.is_dir():
                import shutil
                shutil.rmtree(sf)
            elif sf.exists():
                sf.unlink()

        # Remove from sessions dict
        del self._sessions[resolved]

        # Rewrite manifest without this entry
        self._save_manifest()

        return {"name": name, "deleted": True, "hard": hard}


# ---------------------------------------------------------------------------
# PiAgentAdapter — backward-compatible single-session wrapper
# ---------------------------------------------------------------------------
class PiAgentAdapter(AgentAdapter):
    """
    AgentAdapter backed by `pi --mode rpc` subprocess.

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
            "--continue",  # Resume most recent session instead of starting fresh
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
