"""
SessionLogger — context manager for per-run session logging.

Wraps StructuredLogger with harness-specific helpers and auto-naming.

Usage:
    with SessionLogger("openclaw", session_id="abc") as logger:
        logger.log_lifecycle("setup_start")
        adapter.setup()
        logger.log_lifecycle("setup_done", duration_ms=...)
        logger.log_send(prompt, result, duration_ms=...)
    # Log file is automatically closed on exit

The log file lives at /workspace/logs/session_<SESSION_ID>.jsonl
Can be accessed via logger.path after the context exits.
"""

import time
from typing import Optional, TYPE_CHECKING

from .logger import StructuredLogger

if TYPE_CHECKING:
    from agents.adapters.base import AgentResponse


class SessionLogger:
    """
    Context manager that creates a session log file and provides helpers.

    Creates: logs/session_<session_id>.jsonl

    Args:
        adapter_type: e.g., "openclaw", "pi" (written to every event)
        session_id: Session identifier (used in filename and every event)
        base_dir: Directory for log files (default: /workspace/logs)
    """

    def __init__(
        self,
        adapter_type: str,
        session_id: str,
        base_dir: str = "/workspace/logs",
    ):
        self.adapter_type = adapter_type
        self.session_id = session_id
        self._logger: Optional[StructuredLogger] = None
        self._start_time: Optional[float] = None

    def _ensure_logger(self) -> StructuredLogger:
        if self._logger is None:
            self._logger = StructuredLogger(
                stream="session",
                key=self.session_id,
                base_dir="/workspace/logs",
                adapter_type=self.adapter_type,
            )
        return self._logger

    # ─── Lifecycle helpers ──────────────────────────────────────────────────────

    def lifecycle_start(self, event: str) -> None:
        """Mark a lifecycle event start (logs start time)."""
        self._start_time = time.perf_counter()
        self._ensure_logger().log("lifecycle_event", phase="start", event_name=event)

    def lifecycle_end(self, event: str) -> None:
        """Mark a lifecycle event end with duration since lifecycle_start()."""
        duration_ms = 0.0
        if self._start_time is not None:
            duration_ms = (time.perf_counter() - self._start_time) * 1000
            self._start_time = None
        self._ensure_logger().log("lifecycle_event", phase="end", event_name=event, duration_ms=round(duration_ms, 2))

    def log(self, event: str, **fields) -> None:
        """General log event."""
        self._ensure_logger().log(event, **fields)

    # ─── Send/response helpers ─────────────────────────────────────────────────

    def log_send(
        self,
        prompt: str,
        response: "AgentResponse",
        duration_ms: float,
        turn: Optional[int] = None,
        trace: Optional[list] = None,
    ) -> None:
        """
        Log a send() call with response and full trace analysis.

        Args:
            prompt: The message sent
            response: AgentResponse object
            duration_ms: Time from send_start to send_end
            turn: Optional turn number
            trace: Optional session trace list (from get_session_trace)
        """
        entry = {
            "turn": turn,
            "prompt_preview": prompt[:200] if prompt else "",
            "response_preview": response.stdout[:500] if response.stdout else "",
            "stderr_preview": response.stderr[:200] if response.stderr else "",
            "returncode": response.returncode,
            "duration_ms": round(duration_ms, 2),
        }

        if trace:
            from .session_trace import parse_trace
            parsed = parse_trace(trace)
            entry["trace_entries"] = len(trace)
            entry["has_thinking"] = parsed["has_thinking"]
            entry["has_subagents"] = parsed["has_subagents"]
            entry["thinking_count"] = len(parsed["thinking"])
            entry["tool_call_count"] = len(parsed["tool_calls"])
            entry["subagent_count"] = len(parsed["subagents"])
            # Log thinking separately as a linked event
            if parsed["thinking"]:
                self._ensure_logger().log(
                    "thinking_snapshot",
                    turn=turn,
                    thinking_blocks=parsed["thinking"],
                )
            # Log subagent IDs
            if parsed["subagents"]:
                self._ensure_logger().log(
                    "subagents_spawned",
                    turn=turn,
                    subagents=parsed["subagents"],
                )

        self._ensure_logger().log("send", **entry)

    # ─── Subagent detection ──────────────────────────────────────────────────────

    def log_subagent_check(self, had_subagents: bool, trace_length: int) -> None:
        """Log result of had_subagents() check."""
        self._ensure_logger().log(
            "subagent_check",
            had_subagents=had_subagents,
            trace_entries=trace_length,
        )

    def capture_subagent_traces(
        self,
        parent_trace: list,
        get_trace_func=None,
    ) -> None:
        """
        After a send, capture traces of any subagents spawned in that turn.

        Call this after log_send() when subagents were spawned.
        Reads subagent session IDs from parent_trace and fetches their traces.

        Args:
            parent_trace: The session trace from the parent agent's send
            get_trace_func: Callable(session_id) -> trace list.
                           If None, uses agent's get_session_trace method if available.
        """
        from .session_trace import extract_subagent_ids, parse_trace

        subagents = extract_subagent_ids(parent_trace)
        if not subagents:
            return

        if get_trace_func is None:
            # Try to get it from the logger's stored agent ref
            get_trace_func = getattr(self, "_get_trace", None)

        for sa in subagents:
            sa_id = sa["session_id"]
            if not sa_id:
                continue

            self._ensure_logger().log(
                "subagent_session_start",
                parent_session_id=self.session_id,
                subagent_session_id=sa_id,
                subagent_agent_id=sa.get("agent_id", ""),
                subagent_message=sa.get("message", ""),
            )

            if get_trace_func:
                try:
                    sa_trace = get_trace_func(sa_id)
                    if sa_trace:
                        parsed = parse_trace(sa_trace)
                        self._ensure_logger().log(
                            "subagent_trace",
                            subagent_session_id=sa_id,
                            trace_entries=len(sa_trace),
                            has_thinking=parsed["has_thinking"],
                            thinking_count=len(parsed["thinking"]),
                            tool_call_count=len(parsed["tool_calls"]),
                            # Include thinking blocks directly
                            thinking=parsed["thinking"],
                        )
                except Exception as e:
                    self._ensure_logger().log(
                        "subagent_trace_error",
                        subagent_session_id=sa_id,
                        error=str(e),
                    )

            self._ensure_logger().log(
                "subagent_session_end",
                subagent_session_id=sa_id,
            )

    # ─── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> "SessionLogger":
        self._ensure_logger().log(
            "session_start",
            adapter_type=self.adapter_type,
            session_id=self.session_id,
        )
        return self

    def __exit__(self, *args) -> None:
        if self._logger:
            self._logger.log("session_end", session_id=self.session_id)
            self._logger.close()
            self._logger = None

    @property
    def path(self) -> str:
        """Return the log file path (useful after context exits)."""
        if self._logger:
            return str(self._logger.path)
        return f"/workspace/logs/session_{self.session_id}.jsonl"
