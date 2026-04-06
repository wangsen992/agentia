"""
Observability — structured logging for agentia.

Usage:
    from observability import StructuredLogger, SessionLogger

    # Direct usage
    logger = StructuredLogger("session", session_id="abc")
    logger.log("send", message="Hello", duration_ms=100)

    # Context manager (creates log file, cleans up on exit)
    with SessionLogger("openclaw", session_id="abc") as logger:
        logger.log_send(prompt, response, duration_ms)
"""

from .logger import StructuredLogger
from .session import SessionLogger

__all__ = ["StructuredLogger", "SessionLogger"]
