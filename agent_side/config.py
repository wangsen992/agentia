"""
AgentServer configuration management.

Config is stored on disk at ~/.agentia/agents/<name>/agent.json.
AgentServer reads config at startup and can receive runtime updates via PATCH /config.

Design principle: one workspace per agent, mounted at the agent's natural path.
For pi-agent: host ~/.agentia/agents/<name>/ mounted to ~/.pi/agent/ in container.
"""

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


# Default config path: ~/.agentia/agents/<name>/agent.json
# Set dynamically when agent is provisioned (see ConfigManager)
DEFAULT_CONFIG_DIR = Path.home() / ".agentia" / "agents"
DEFAULT_CONFIG_FILENAME = "agent.json"


def default_config_path(agent_name: str) -> Path:
    """Compute the default config path for an agent."""
    return DEFAULT_CONFIG_DIR / agent_name / DEFAULT_CONFIG_FILENAME


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

    # Adapter configuration
    adapter_type: str = "pi-agent"
    adapter_provider: str = "minimax"
    adapter_model: str = "MiniMax-M2.7"
    # adapter_workspace: path inside the container where the agent workspace is mounted.
    # For pi-agent with natural mount: /workspace (mounted from host ~/.agentia/agents/<name>/)
    adapter_workspace: str = "/workspace"

    # Session management
    session_idle_ttl: int = 1800       # seconds before idle session is stopped
    max_sessions: int = 10             # max concurrent sessions (LRU eviction)
    context_threshold_pct: int = 75     # auto-compact at this % of context window

    # pi-agent specific
    # PI_DIR is set via environment variable, not config.
    # session_dir: path for session files (inside adapter_workspace).
    #   Defaults to adapter_workspace / ".pi" / "sessions"
    #   Set explicitly when starting SessionManager.

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
        self._config_path = config_path
        self._lock = threading.RLock()
        self._config: Optional[AgentServerConfig] = None
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        if self._config_path:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentServerConfig:
        """Load config from disk, or return default if none exists."""
        with self._lock:
            if self._config_path and self._config_path.exists():
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
        """Apply a partial update to config and save."""
        with self._lock:
            current = self._config.to_dict()
            current.update(patch)
            self._config = AgentServerConfig.from_dict(current)
            self._save()
            return self._config

    def replace(self, config: AgentServerConfig) -> AgentServerConfig:
        """Replace entire config and save."""
        with self._lock:
            self._config = config
            self._save()
            return self._config
