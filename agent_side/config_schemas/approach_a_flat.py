"""
Approach A: Flat JSON with Conventions

Extends the current flat dataclass pattern.
Nested objects are flattened via dotted keys or stored as JSON strings.
Conventions govern structure rather than schema enforcement.

9-Dimension Mapping:
  1. role.persona          → role.persona (string, INLINE in agent_id comment or separate field)
  2. role.goal             → role.goal (string)
  3. role.backstory        → role.backstory (string, possibly multi-line)
  4. adapter.type          → adapter.type (string enum)
  5. adapter.config         → adapter.config (JSON string)
  6. adapter.session.id_prefix     → session.id_prefix (string)
  7. adapter.session.fork_enabled  → session.fork_enabled (bool)
  8. adapter.session.resume_enabled → session.resume_enabled (bool)
  9. access_level          → access_level (string enum)
  10. memory.short_term.type        → memory.short_term.type (string)
  11. memory.short_term.max_tokens  → memory.short_term.max_tokens (int)
  12. memory.long_term.episodic     → memory.long_term.episodic (bool)
  13. memory.long_term.semantic     → memory.long_term.semantic (bool)
  14. knowledge.sources     → knowledge.sources (JSON list string)
  15. knowledge.retrieval.top_k     → knowledge.retrieval.top_k (int)
  16. knowledge.retrieval.threshold → knowledge.retrieval.threshold (float)
  17. knowledge.update_policy → knowledge.update_policy (string enum)
  18. skills               → skills (JSON list, each item has name/version/interface/adapter_impl)
  19. participation.evaluator → participation.evaluator (bool)
  20. participation.default  → participation.default (string)
  21. lifecycle.state       → lifecycle.state (string)
  22. lifecycle.last_active → lifecycle.last_active (ISO8601 string)

Storage: Single JSON file at ~/.agentia/agent.json
Read/Write: ConfigManager reads/writes flat dict; dot-access helpers resolve nested paths.

Compatibility with OpenClaw Hidden Harnesses:
  - OpenClaw's SOUL.md/IDENTITY.md/AGENTS.md bootstrap files are injected per-agent.
    Flat config can set workspace path to point at per-agent workspace directories,
    so each agent gets its own bootstrap files — clean separation.
  - Tool schemas and system prompt injection are controlled by OpenClaw, not this config.
  - Access level maps to OpenClaw's per-agent tools.allow/deny in openclaw.json.
  - Memory: short_term maps to context window, long_term maps to memory_search.
  - Skills: listed as names/versions; OpenClaw resolves to SKILL.md at runtime.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, Any


DEFAULT_CONFIG_PATH = Path.home() / ".agentia" / "agent.json"


# ─── Enums / Constants ────────────────────────────────────────────────────────

class AccessLevel:
    NONE             = "none"
    READ_ONLY        = "read_only"
    STANDARD         = "standard"
    PRIVILEGED       = "privileged"
    EXPLICIT_CONFIRM = "explicit_confirm"
    DEFAULT = "standard"


ADAPTER_TYPES = ("openclaw", "pi-agent", "docker", "ssh")
MEMORY_TYPES  = ("context_window", "sqlite", "redis", "none")
UPDATE_POLICIES = ("append", "replace", "upsert", "never")
PARTICIPATION_DEFAULTS = ("active", "passive", "eval_only")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _flatten(data: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten nested dict into dotted keys."""
    items = {}
    for k, v in data.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten(v, new_key, sep))
        else:
            items[new_key] = v
    return items


def _unflatten(data: dict, sep: str = ".") -> dict:
    """Unflatten dotted keys back into nested dict."""
    result: dict = {}
    for key, value in data.items():
        parts = key.split(sep)
        current = result
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
    return result


def _json_str(value: Any) -> str:
    """Serialize value to JSON string (for JSON-serialized fields)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2)


def _parse_json_str(value: str) -> Any:
    """Parse JSON string back to Python object."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


# ─── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class AgentServerConfigFlat:
    """
    Flat configuration for AgentServer, extended for 9-dimension agent composition.

    Nested objects are stored as dotted keys OR JSON strings.
    Use `get()` / `set()` for nested access; `to_dict()` / `from_dict()` for serialization.
    """

    # ── Infrastructure (original fields) ─────────────────────────────────────
    host:           str  = "0.0.0.0"
    port:           int  = 8080
    delivery:       str  = "inbox"
    poll_interval:  float = 2.0
    inbox_dir:      str  = "/workspace/inbox"
    responses_dir:   str  = "/workspace/inbox/responses"
    agent_timeout:  int  = 120
    log_level:      str  = "info"

    # ── Role ─────────────────────────────────────────────────────────────────
    role_persona:   str  = ""
    role_goal:      str  = ""
    role_backstory: str  = ""

    # ── Adapter ─────────────────────────────────────────────────────────────
    adapter_type:   str  = "openclaw"
    adapter_config: str  = "{}"          # JSON string for adapter-specific config
    session_id_prefix:    str = "agent"
    session_fork_enabled:  bool = False
    session_resume_enabled: bool = False

    # ── Access Level ─────────────────────────────────────────────────────────
    access_level: str = "standard"

    # ── Memory ──────────────────────────────────────────────────────────────
    memory_short_term_type:       str = "context_window"
    memory_short_term_max_tokens: int = 64000
    memory_long_term_episodic:    bool = True
    memory_long_term_semantic:    bool = True

    # ── Knowledge ───────────────────────────────────────────────────────────
    knowledge_sources:     str = "[]"   # JSON list of source IDs / URLs
    knowledge_retrieval_top_k:     int = 5
    knowledge_retrieval_threshold: float = 0.7
    knowledge_update_policy: str = "append"

    # ── Skills ──────────────────────────────────────────────────────────────
    skills: str = "[]"   # JSON list: [{"name": "...", "version": "...", "interface": "...", "adapter_impl": "..."}]

    # ── Participation ────────────────────────────────────────────────────────
    participation_evaluator: bool = False
    participation_default:   str = "active"

    # ── Lifecycle ───────────────────────────────────────────────────────────
    lifecycle_state:      str = "stopped"
    lifecycle_last_active: str = ""    # ISO8601

    # ── Convenience nested accessors ────────────────────────────────────────

    def role(self) -> dict:
        return {
            "persona":   self.role_persona,
            "goal":      self.role_goal,
            "backstory": self.role_backstory,
        }

    def adapter_session(self) -> dict:
        return {
            "id_prefix":      self.session_id_prefix,
            "fork_enabled":   self.session_fork_enabled,
            "resume_enabled": self.session_resume_enabled,
        }

    def memory_short_term(self) -> dict:
        return {
            "type":       self.memory_short_term_type,
            "max_tokens": self.memory_short_term_max_tokens,
        }

    def memory_long_term(self) -> dict:
        return {
            "episodic": self.memory_long_term_episodic,
            "semantic": self.memory_long_term_semantic,
        }

    def knowledge_retrieval(self) -> dict:
        return {
            "top_k":     self.knowledge_retrieval_top_k,
            "threshold": self.knowledge_retrieval_threshold,
        }

    def skills_list(self) -> list:
        return _parse_json_str(self.skills)

    def knowledge_sources_list(self) -> list:
        return _parse_json_str(self.knowledge_sources)

    # ── Serialization ───────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    def to_nested_dict(self) -> dict:
        """Serialize to a clean nested dict (useful for API responses)."""
        flat = self.to_dict()
        nested = _unflatten(flat)
        # Unpack role, adapter.session, memory.short_term, memory.long_term,
        # knowledge.retrieval into proper nesting
        result = {}
        for key, value in nested.items():
            if key == "role":
                result["role"] = value
            elif key == "adapter":
                # adapter fields: type, config, session: {id_prefix, fork_enabled, resume_enabled}
                result["adapter"] = {
                    "type":   value.get("type"),
                    "config": _parse_json_str(value.get("config", "{}")),
                    "session": {
                        "id_prefix":      value.get("session_id_prefix"),
                        "fork_enabled":   value.get("session_fork_enabled"),
                        "resume_enabled": value.get("session_resume_enabled"),
                    }
                }
            elif key == "memory":
                result["memory"] = {
                    "short_term": value.get("short_term"),
                    "long_term":  value.get("long_term"),
                }
            elif key == "knowledge":
                sources = value.get("sources", "[]")
                result["knowledge"] = {
                    "sources":   _parse_json_str(sources) if isinstance(sources, str) else sources,
                    "retrieval": value.get("retrieval"),
                    "update_policy": value.get("update_policy"),
                }
            elif key == "skills":
                result["skills"] = _parse_json_str(value)
            elif key == "participation":
                result["participation"] = value
            elif key == "lifecycle":
                result["lifecycle"] = value
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AgentServerConfigFlat":
        # Accept both flat and partially-nested input
        flat = _flatten(data) if any("." in k or isinstance(v, dict)
                                     for k, v in data.items()) else data
        # Only use fields that exist on the dataclass
        valid = {f: flat[f] for f in flat if f in cls.__dataclass_fields__}
        return cls(**valid)


# ─── Config Manager (extends original) ───────────────────────────────────────

class ConfigManagerFlat:
    """
    Extends ConfigManager to handle flat nested config with dotted keys.
    Supports both flat JSON and partially-nested input for ergonomics.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._config: Optional[AgentServerConfigFlat] = None
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentServerConfigFlat:
        with self._lock:
            if self._config_path.exists():
                try:
                    data = json.loads(self._config_path.read_text())
                    self._config = AgentServerConfigFlat.from_dict(data)
                    return self._config
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[ConfigManagerFlat] Load failed: {e}, using defaults")
            self._config = AgentServerConfigFlat()
            self._save()
            return self._config

    def _save(self):
        tmp = self._config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config.to_dict(), indent=2))
        tmp.rename(self._config_path)

    def get(self) -> AgentServerConfigFlat:
        with self._lock:
            return self._config

    def update(self, patch: dict) -> AgentServerConfigFlat:
        """
        Apply a partial update. Accepts nested or flat dict.
        """
        with self._lock:
            # Normalize to flat
            flat_patch = _flatten(patch) if any("." in k or isinstance(v, dict)
                                                  for k, v in patch.items()) else patch
            current = self._config.to_dict()
            current.update(flat_patch)
            self._config = AgentServerConfigFlat.from_dict(current)
            self._save()
            return self._config

    def replace(self, config: AgentServerConfigFlat) -> AgentServerConfigFlat:
        with self._lock:
            self._config = config
            self._save()
            return self._config
