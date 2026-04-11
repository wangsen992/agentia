"""
Approach B: Typed Python Dataclasses with Pydantic

Full nested dataclasses with Pydantic validators for maximum type safety,
runtime validation, and self-documenting schema.

Requires: pip install pydantic

9-Dimension Mapping:
  1. role.persona          → RoleConfig.persona (str, min_length=1)
  2. role.goal            → RoleConfig.goal (str)
  3. role.backstory       → RoleConfig.backstory (str)
  4. adapter.type         → AdapterConfig.type_ (Literal adapter type enum)
  5. adapter.config        → AdapterConfig.config (dict[str, Any])
  6. adapter.session.id_prefix     → SessionConfig.id_prefix (str)
  7. adapter.session.fork_enabled  → SessionConfig.fork_enabled (bool)
  8. adapter.session.resume_enabled → SessionConfig.resume_enabled (bool)
  9. access_level          → AccessLevel literal (NONE/READ_ONLY/STANDARD/PRIVILEGED/EXPLICIT_CONFIRM)
  10. memory.short_term.type        → ShortTermMemory.type (MemoryTypeEnum)
  11. memory.short_term.max_tokens  → ShortTermMemory.max_tokens (int, gt=0)
  12. memory.long_term.episodic     → LongTermMemory.episodic (bool)
  13. memory.long_term.semantic     → LongTermMemory.semantic (bool)
  14. knowledge.sources             → KnowledgeConfig.sources (list[str])
  15. knowledge.retrieval.top_k     → RetrievalConfig.top_k (int, ge=1)
  16. knowledge.retrieval.threshold → RetrievalConfig.threshold (float, 0..1)
  17. knowledge.update_policy       → KnowledgeConfig.update_policy (UpdatePolicyEnum)
  18. skills               → SkillEntry list (each: name/version/interface/adapter_impl)
  19. participation.evaluator → ParticipationConfig.evaluator (bool)
  20. participation.default   → ParticipationConfig.default (ParticipationDefaultEnum)
  21. lifecycle.state         → LifecycleConfig.state (LifecycleStateEnum)
  22. lifecycle.last_active    → LifecycleConfig.last_active (datetime)

Storage: JSON file at ~/.agentia/agent.json (Pydantic JSON serialization)
Read/Write: Pydantic's .model_dump() and .model_validate() — no manual mapping needed.

Compatibility with OpenClaw Hidden Harnesses:
  - RoleConfig persona/backstory CANNOT replace SOUL.md content injected by OpenClaw,
    but can be used to SET the SOUL.md file before startup (via setup()).
  - AccessLevel enum maps to OpenClaw's tools.allow/deny config in openclaw.json.
  - Memory types map directly to OpenClaw's memory types (context_window, sqlite).
  - Skills list: Pydantic model defines skill entry schema; adapter resolves to SKILL.md.
  - Lifecycle state enables tracking agent state (stopped/running/error) in the harness.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ConfigDict,
    ValidationError,
)


DEFAULT_CONFIG_PATH = Path.home() / ".agentia" / "agent.json"


# ─── Enums ────────────────────────────────────────────────────────────────────

class AccessLevel(str, Enum):
    NONE             = "none"
    READ_ONLY        = "read_only"
    STANDARD         = "standard"
    PRIVILEGED       = "privileged"
    EXPLICIT_CONFIRM = "explicit_confirm"


class AdapterType(str, Enum):
    OPENCLAW = "openclaw"
    PI_AGENT = "pi-agent"
    DOCKER   = "docker"
    SSH      = "ssh"


class MemoryType(str, Enum):
    CONTEXT_WINDOW = "context_window"
    SQLITE         = "sqlite"
    REDIS          = "redis"
    NONE           = "none"


class UpdatePolicy(str, Enum):
    APPEND  = "append"
    REPLACE = "replace"
    UPSERT  = "upsert"
    NEVER   = "never"


class ParticipationDefault(str, Enum):
    ACTIVE    = "active"
    PASSIVE   = "passive"
    EVAL_ONLY = "eval_only"


class LifecycleState(str, Enum):
    STOPPED  = "stopped"
    STARTING = "starting"
    RUNNING  = "running"
    ERROR    = "error"
    STOPPING = "stopping"


# ─── Nested Models ───────────────────────────────────────────────────────────

class SessionConfig(BaseModel):
    """Session sub-config for the adapter."""
    id_prefix:      str  = "agent"
    fork_enabled:   bool = False
    resume_enabled: bool = False


class AdapterConfig(BaseModel):
    """Adapter configuration (type + adapter-specific config dict)."""
    type_:   AdapterType = AdapterType.OPENCLAW
    config:  dict[str, Any] = Field(default_factory=dict)
    session: SessionConfig = Field(default_factory=SessionConfig)

    # Alias "type" since it's a Python keyword
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("type_", mode="before")
    @classmethod
    def _resolve_type(cls, v):
        if isinstance(v, str) and not isinstance(v, AdapterType):
            return AdapterType(v)
        return v


class RoleConfig(BaseModel):
    """Agent persona, goal, and backstory."""
    persona:   str = ""
    goal:      str = ""
    backstory: str = ""

    @model_validator(mode="after")
    def check_persona_or_goal(self):
        if not self.persona and not self.goal:
            raise ValueError("At least one of role.persona or role.goal must be set")
        return self


class ShortTermMemory(BaseModel):
    """Short-term memory configuration."""
    type:       MemoryType = MemoryType.CONTEXT_WINDOW
    max_tokens: int = Field(default=64000, gt=0)


class LongTermMemory(BaseModel):
    """Long-term memory configuration."""
    episodic: bool = True
    semantic: bool = True


class MemoryConfig(BaseModel):
    """Full memory configuration."""
    short_term: ShortTermMemory = Field(default_factory=ShortTermMemory)
    long_term:  LongTermMemory  = Field(default_factory=LongTermMemory)


class RetrievalConfig(BaseModel):
    """Knowledge retrieval parameters."""
    top_k:     int   = Field(default=5, ge=1)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeConfig(BaseModel):
    """Knowledge sources and retrieval config."""
    sources:        list[str] = Field(default_factory=list)
    retrieval:       RetrievalConfig = Field(default_factory=RetrievalConfig)
    update_policy:   UpdatePolicy = UpdatePolicy.APPEND

    @field_validator("update_policy", mode="before")
    @classmethod
    def _resolve_policy(cls, v):
        if isinstance(v, str) and not isinstance(v, UpdatePolicy):
            return UpdatePolicy(v)
        return v


class SkillEntry(BaseModel):
    """A single skill reference."""
    name:          str
    version:       str = "latest"
    interface:     Optional[str] = None   # e.g. "tool", "skill", "plugin"
    adapter_impl:  Optional[str] = None   # adapter-specific implementation key


class ParticipationConfig(BaseModel):
    """How the agent participates in multi-agent scenarios."""
    evaluator: bool = False
    default:   ParticipationDefault = ParticipationDefault.ACTIVE

    @field_validator("default", mode="before")
    @classmethod
    def _resolve_default(cls, v):
        if isinstance(v, str) and not isinstance(v, ParticipationDefault):
            return ParticipationDefault(v)
        return v


class LifecycleConfig(BaseModel):
    """Agent lifecycle state tracking."""
    state:       LifecycleState = LifecycleState.STOPPED
    last_active: Optional[datetime] = None


# ─── Root Config ──────────────────────────────────────────────────────────────

class AgentServerConfigPydantic(BaseModel):
    """
    Full nested configuration for AgentServer with 9-dimension agent composition.

    Stored as a single JSON file. Pydantic handles all validation and serialization.
    """
    # ── Infrastructure (original flat fields) ──────────────────────────────
    host:          str   = "0.0.0.0"
    port:          int   = 8080
    delivery:      str   = "inbox"
    poll_interval: float = 2.0
    inbox_dir:     str   = "/workspace/inbox"
    responses_dir: str   = "/workspace/inbox/responses"
    agent_timeout: int   = 120
    log_level:     str   = "info"

    # ── Agent Composition Dimensions ────────────────────────────────────────
    role:         RoleConfig         = Field(default_factory=RoleConfig)
    adapter:      AdapterConfig      = Field(default_factory=AdapterConfig)
    access_level: AccessLevel        = AccessLevel.STANDARD
    memory:       MemoryConfig       = Field(default_factory=MemoryConfig)
    knowledge:    KnowledgeConfig    = Field(default_factory=KnowledgeConfig)
    skills:       list[SkillEntry]   = Field(default_factory=list)
    participation: ParticipationConfig = Field(default_factory=ParticipationConfig)
    lifecycle:    LifecycleConfig    = Field(default_factory=LifecycleConfig)

    @field_validator("access_level", mode="before")
    @classmethod
    def _resolve_access(cls, v):
        if isinstance(v, str) and not isinstance(v, AccessLevel):
            return AccessLevel(v)
        return v

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", round_trip=False)

    def to_flat_dict(self) -> dict:
        """
        Flatten to dotted keys for backward compatibility with tools expecting flat JSON.
        E.g. role.persona → "role.persona", adapter.type → "adapter.type"
        """
        def flatten(obj: dict, prefix: str = "") -> dict:
            items = {}
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    items.update(flatten(v, key))
                elif isinstance(v, list):
                    items[key] = json.dumps([i.model_dump() if hasattr(i, "model_dump") else i for i in v])
                elif isinstance(v, Enum):
                    items[key] = v.value
                elif isinstance(v, datetime):
                    items[key] = v.isoformat()
                else:
                    items[key] = v
            return items
        return flatten(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "AgentServerConfigPydantic":
        return cls.model_validate(data)

    @classmethod
    def from_flat_dict(cls, data: dict) -> "AgentServerConfigPydantic":
        """
        Reconstruct from flat dotted-key dict (e.g. from legacy flat config).
        """
        def unflatten(d: dict) -> dict:
            result: dict = {}
            for key, value in d.items():
                parts = key.split(".")
                current = result
                for part in parts[:-1]:
                    current = current.setdefault(part, {})
                current[parts[-1]] = value
            return result
        return cls.model_validate(unflatten(data))

    def update_lifecycle(self, state: LifecycleState) -> None:
        """Update lifecycle state with timestamp."""
        self.lifecycle.state = state
        self.lifecycle.last_active = datetime.utcnow()


# ─── Config Manager ───────────────────────────────────────────────────────────

class ConfigManagerPydantic:
    """
    Manages Pydantic-validated config with atomic save/load.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._config: Optional[AgentServerConfigPydantic] = None
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentServerConfigPydantic:
        with self._lock:
            if self._config_path.exists():
                try:
                    data = json.loads(self._config_path.read_text())
                    self._config = AgentServerConfigPydantic.from_dict(data)
                    return self._config
                except (json.JSONDecodeError, ValidationError) as e:
                    print(f"[ConfigManagerPydantic] Load failed: {e}, using defaults")
            self._config = AgentServerConfigPydantic()
            self._save()
            return self._config

    def _save(self):
        tmp = self._config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config.to_dict(), indent=2))
        tmp.rename(self._config_path)

    def get(self) -> AgentServerConfigPydantic:
        with self._lock:
            return self._config

    def update(self, patch: dict) -> AgentServerConfigPydantic:
        """
        Apply a partial update. Patch is merged into current config.
        Validated by Pydantic before saving.
        """
        with self._lock:
            # Merge patch into current
            current = self._config.to_dict()
            for k, v in patch.items():
                if k in current and isinstance(current[k], dict) and isinstance(v, dict):
                    current[k].update(v)
                else:
                    current[k] = v
            self._config = AgentServerConfigPydantic.from_dict(current)
            self._save()
            return self._config

    def replace(self, config: AgentServerConfigPydantic) -> AgentServerConfigPydantic:
        with self._lock:
            self._config = config
            self._save()
            return self._config
