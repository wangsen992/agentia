"""
AgentServer configuration management.

Config is stored on disk at ~/.agentia/agent.json.
AgentServer reads config at startup and can receive runtime updates via PATCH /config.
"""

import json
import os
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_PATH = Path.home() / ".agentia" / "agent.json"


@dataclass
class AgentServerConfig:
    """Configuration for AgentServer."""

    host: str = "0.0.0.0"
    port: int = 8080
    delivery: str = "inbox"
    poll_interval: float = 2.0
    inbox_dir: str = "/workspace/inbox"
    responses_dir: str = "/workspace/inbox/responses"
    agent_timeout: int = 120
    log_level: str = "info"

    adapter_type: str = "pi-agent"
    adapter_provider: str = "minimax"
    adapter_model: str = "MiniMax-M2.7"
    adapter_workspace: str = "/workspace"

    session_idle_ttl: int = 1800
    max_sessions: int = 10
    context_threshold_pct: int = 75

    role_persona: str = ""
    role_goal: str = ""
    role_backstory: str = ""

    skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentServerConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfigManager:
    """
    Manages AgentServer config persistence and runtime updates.

    Config is stored on disk. Runtime updates are atomic (write-then-reload).
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._config: Optional[AgentServerConfig] = None
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentServerConfig:
        """Load config from disk, or return default if none exists."""
        with self._lock:
            if self._config_path.exists():
                try:
                    data = json.loads(self._config_path.read_text())
                    self._config = AgentServerConfig.from_dict(data)
                    return self._config
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[ConfigManager] Failed to load config: {e}, using defaults")
            self._config = AgentServerConfig()
            self._save()
            return self._config

    def _save(self):
        """Save current config to disk atomically."""
        tmp = self._config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config.to_dict(), indent=2))
        tmp.rename(self._config_path)

    def get(self) -> AgentServerConfig:
        """Get current config."""
        with self._lock:
            return self._config

    def update(self, patch: dict) -> AgentServerConfig:
        """
        Apply a partial update to config and save.

        Args:
            patch: dict with fields to update (e.g. {"delivery": "sync"})

        Returns:
            Updated config.
        """
        with self._lock:
            current = self._config.to_dict()
            current.update(patch)
            self._config = AgentServerConfig.from_dict(current)
            self._save()
            return self._config

    def replace(self, config: AgentServerConfig) -> AgentServerConfig:
        """
        Replace entire config and save.

        Args:
            config: Full AgentServerConfig to save.

        Returns:
            New config.
        """
        with self._lock:
            self._config = config
            self._save()
            return self._config
