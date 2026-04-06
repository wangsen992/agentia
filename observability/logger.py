"""
StructuredLogger — thread-safe JSON Lines logger.

Writes timestamped JSON events to a log file.
One file per log stream (e.g., session_<id>.jsonl, agent_<id>.jsonl).

Usage:
    logger = StructuredLogger("session", session_id="abc")
    logger.log("send", message="Hello", duration_ms=100)

Output (one JSON object per line):
    {"timestamp": "2026-04-06T02:57:00.123Z", "event": "send", "session_id": "abc", "message": "Hello", "duration_ms": 100}
"""

import json
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any


# Module-level registry of open loggers (so SessionLogger can find them)
_OPEN_LOGGERS: dict[str, "StructuredLogger"] = {}
_LOGGERS_LOCK = threading.Lock()


class StructuredLogger:
    """
    Thread-safe JSON Lines logger.

    Writes one JSON object per line to a file in logs/<stream>_<key>.jsonl.

    Args:
        stream: Log stream name (e.g., "session", "agent", "relay")
        key: Stream-specific key (e.g., session_id, agent_id)
        base_dir: Directory for log files (default: /workspace/logs)
        extra_fields: Always-included fields (e.g., adapter_type)
    """

    def __init__(
        self,
        stream: str,
        key: str = "",
        base_dir: str = "/workspace/logs",
        **extra_fields: Any,
    ):
        self.stream = stream
        self.key = key
        self.extra_fields = extra_fields
        self._lock = threading.Lock()
        self._closed = False

        log_dir = Path(base_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{stream}_{key}.jsonl" if key else f"{stream}.jsonl"
        self._path = log_dir / filename
        self._file = open(self._path, "a", buffering=1)  # line buffering

        # Register so SessionLogger can find this logger
        with _LOGGERS_LOCK:
            logger_id = f"{stream}:{key}"
            _OPEN_LOGGERS[logger_id] = self

    def log(self, event: str, **fields: Any) -> None:
        """
        Write a structured log event.

        Args:
            event: Event name (e.g., "send", "gateway_start")
            **fields: Arbitrary event data
        """
        if self._closed:
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "stream": self.stream,
            "key": self.key,
            **self.extra_fields,
            **fields,
        }

        # Truncate long string fields for readability
        for k, v in record.items():
            if isinstance(v, str) and len(v) > 500:
                record[k] = v[:500] + f"... [truncated {len(v) - 500} chars]"

        line = json.dumps(record, default=str)

        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        """Close the log file."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._file.close()
                with _LOGGERS_LOCK:
                    logger_id = f"{self.stream}:{self.key}"
                    _OPEN_LOGGERS.pop(logger_id, None)

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        return f"<StructuredLogger {self.stream}:{self.key} -> {self._path}>"
