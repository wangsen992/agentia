"""
Approach C: Layered Config — Base Template + Per-Agent Overrides

Like Docker Compose: a base config provides defaults, per-agent configs
override or extend specific layers. Enables org-wide templates with
agent-specific customization.

Layer order (later wins):
  1. Built-in defaults        — hardcoded fallback values
  2. Base config file         — ~/.agentia/base.json
  3. Environment overlays     — ~/.agentia/env/<AGENT_ID>.json
  4. Runtime patch            — in-memory only, from API call

9-Dimension Mapping:
  Each dimension is a nested dict in the layered JSON. The layer merger
  does deep dict merge (override at the key level). Example:
    {
      "role": {
        "persona": "You are a helpful assistant",  # from base
        "goal": "Answer questions",                 # overridden by agent env
        "backstory": ""                            # only in base
      },
      "adapter": {
        "type": "openclaw",                         # base
        "session": {
          "id_prefix": "agent",                     # base
          "fork_enabled": true                      # agent env override
        }
      }
    }

Storage:
  - Base config:     ~/.agentia/base.json
  - Agent overrides:  ~/.agentia/env/<agent_id>.json
  - Resolved config:  ~/.agentia/resolved/<agent_id>.json (generated, not edited)

Read/Write:
  - ConfigManagerLayered.resolve(agent_id) merges layers and returns resolved dict.
  - update() writes to agent env file (layer 3), NOT base.
  - Base remains pristine — safe for org-wide distribution.

Compatibility with OpenClaw Hidden Harnesses:
  - Base config can define workspace template path; agent env overrides set
    per-agent workspace directory. OpenClaw injects SOUL.md/IDENTITY.md per workspace,
    so layering gives each agent its own persona files.
  - Access level in base (e.g., "standard") can be overridden per-agent for
    escalation. Maps directly to OpenClaw's tools.allow/deny.
  - Skills layering: base can define org-wide skills (e.g., "zotero", "ynab");
    agent env adds agent-specific skills. Final skills list is merged.
  - Lifecycle state lives in runtime patch layer — not persisted in env file.
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Optional, Any


DEFAULT_BASE_PATH     = Path.home() / ".agentia" / "base.json"
DEFAULT_ENV_DIR       = Path.home() / ".agentia" / "env"
DEFAULT_RESOLVED_DIR  = Path.home() / ".agentia" / "resolved"


# ─── Default Built-in Config ─────────────────────────────────────────────────

BUILTIN_DEFAULTS: dict[str, Any] = {
    # Infrastructure
    "host":           "0.0.0.0",
    "port":           8080,
    "delivery":       "inbox",
    "poll_interval":   2.0,
    "inbox_dir":      "/workspace/inbox",
    "responses_dir":  "/workspace/inbox/responses",
    "agent_timeout":  120,
    "log_level":      "info",
    # Role
    "role": {
        "persona":   "You are a helpful AI assistant.",
        "goal":      "",
        "backstory": "",
    },
    # Adapter
    "adapter": {
        "type":   "openclaw",
        "config": {},
        "session": {
            "id_prefix":      "agent",
            "fork_enabled":   False,
            "resume_enabled": False,
        },
    },
    # Access Level
    "access_level": "standard",
    # Memory
    "memory": {
        "short_term": {
            "type":        "context_window",
            "max_tokens":  64000,
        },
        "long_term": {
            "episodic": True,
            "semantic": True,
        },
    },
    # Knowledge
    "knowledge": {
        "sources":          [],
        "retrieval": {
            "top_k":      5,
            "threshold":  0.7,
        },
        "update_policy": "append",
    },
    # Skills
    "skills": [],
    # Participation
    "participation": {
        "evaluator": False,
        "default":   "active",
    },
    # Lifecycle (runtime only — not in base/env files)
    # "lifecycle": { "state": "stopped", "last_active": "" }
}


# ─── Layer Merger ─────────────────────────────────────────────────────────────

def _deep_merge(base: dict, overlay: dict) -> dict:
    """
    Deep-merge overlay into base. Overlay values win.
    Lists are replaced (not concatenated) — use append strategy in caller for skills.
    """
    result = deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_skills_lists(base_skills: list, overlay_skills: list) -> list:
    """
    Merge skills: overlay items with same name override base items.
    New skills in overlay are appended.
    """
    override_names = {s.get("name") for s in overlay_skills if "name" in s}
    base_filtered = [s for s in base_skills if s.get("name") not in override_names]
    return base_filtered + overlay_skills


# ─── Layered Config ───────────────────────────────────────────────────────────

class LayeredConfig:
    """
    Represents a single config layer (base or per-agent env).

    Each layer is a JSON file containing a partial config
    (only fields that differ from layers below it).
    """

    def __init__(self, data: Optional[dict] = None):
        self.data: dict = data or {}

    @classmethod
    def from_file(cls, path: Path) -> "LayeredConfig":
        if not path.exists():
            return cls({})
        try:
            return cls(json.loads(path.read_text()))
        except json.JSONDecodeError:
            return cls({})

    def to_file(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.rename(path)

    def is_empty(self) -> bool:
        return not self.data


# ─── Resolved Config ──────────────────────────────────────────────────────────

class ResolvedConfig:
    """
    A fully-resolved config after merging all layers.
    This is what AgentServer actually uses at runtime.
    """

    def __init__(self, agent_id: str, data: dict):
        self.agent_id = agent_id
        self.data = data

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dot-access into resolved config."""
        current = self.data
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k, default)
            else:
                return default
        return current

    def to_dict(self) -> dict:
        return deepcopy(self.data)

    def to_file(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, indent=2))


# ─── Config Manager ───────────────────────────────────────────────────────────

class ConfigManagerLayered:
    """
    Manages layered config with deep-merging across 4 layers:

      Layer 1: BUILTIN_DEFAULTS  (hardcoded, always present)
      Layer 2: Base config file   (~/.agentia/base.json)
      Layer 3: Agent env file     (~/.agentia/env/<agent_id>.json)
      Layer 4: Runtime patch      (in-memory dict from API PATCH)

    Resolved config is cached in memory and optionally written to
    ~/.agentia/resolved/<agent_id>.json for inspection/debugging.

    Usage:
        mgr = ConfigManagerLayered()
        cfg = mgr.resolve("jarvis")           # ResolvedConfig for agent "jarvis"
        cfg = mgr.resolve("jarvis", patch={"role": {"goal": "..."}})  # with runtime patch
        mgr.update("jarvis", {"access_level": "privileged"})  # writes to env file
        mgr.set_base({"adapter": {"type": "openclaw"}, ...})   # writes base.json
    """

    def __init__(
        self,
        base_path:    Optional[Path] = None,
        env_dir:      Optional[Path] = None,
        resolved_dir: Optional[Path] = None,
    ):
        self._base_path    = base_path    or DEFAULT_BASE_PATH
        self._env_dir      = env_dir      or DEFAULT_ENV_DIR
        self._resolved_dir = resolved_dir or DEFAULT_RESOLVED_DIR
        self._lock         = threading.RLock()

        # In-memory cache of resolved configs per agent_id
        self._cache: dict[str, ResolvedConfig] = {}

        # Runtime patches (layer 4) — not persisted
        self._patches: dict[str, dict] = {}

        self._base_layer = LayeredConfig.from_file(self._base_path)
        self._ensure_dirs()

    def _ensure_dirs(self):
        self._base_path.parent.mkdir(parents=True, exist_ok=True)
        self._env_dir.mkdir(parents=True, exist_ok=True)
        self._resolved_dir.mkdir(parents=True, exist_ok=True)

    # ─── Layer Access ────────────────────────────────────────────────────────

    def _get_env_layer(self, agent_id: str) -> LayeredConfig:
        return LayeredConfig.from_file(self._env_dir / f"{agent_id}.json")

    def get_base(self) -> dict:
        return deepcopy(self._base_layer.data)

    def set_base(self, data: dict) -> None:
        """Set base config (Layer 2). Overwrites base.json."""
        self._base_layer = LayeredConfig(data)
        self._base_layer.to_file(self._base_path)
        self._invalidate_all()

    def get_env(self, agent_id: str) -> dict:
        """Get raw env layer for an agent (Layer 3)."""
        return deepcopy(self._get_env_layer(agent_id).data)

    def update_env(self, agent_id: str, patch: dict) -> None:
        """
        Update agent env layer (Layer 3). Deep-merges into existing env file.
        Skills are merged specially (override by name).
        """
        env_layer = self._get_env_layer(agent_id)
        merged = _deep_merge(env_layer.data, patch)

        # Special handling: merge skills lists
        if "skills" in patch and "skills" in env_layer.data:
            merged["skills"] = _merge_skills_lists(
                env_layer.data.get("skills", []),
                patch.get("skills", [])
            )

        env_layer = LayeredConfig(merged)
        env_layer.to_file(self._env_dir / f"{agent_id}.json")
        self._invalidate(agent_id)

    # ─── Resolution ─────────────────────────────────────────────────────────

    def resolve(
        self,
        agent_id: str,
        patch: Optional[dict] = None,
        write_resolved: bool = False,
    ) -> ResolvedConfig:
        """
        Resolve all layers into a final config for agent_id.

        Args:
            agent_id: The agent's ID (determines which env file to use)
            patch: Optional runtime patch (Layer 4, not persisted)
            write_resolved: If True, write resolved config to ~/.agentia/resolved/<agent_id>.json

        Returns:
            ResolvedConfig wrapping the fully-merged dict.
        """
        with self._lock:
            # Layer 1 → Layer 2
            result = _deep_merge(BUILTIN_DEFAULTS, self._base_layer.data)
            # Layer 3
            env_layer = self._get_env_layer(agent_id)
            result = _deep_merge(result, env_layer.data)
            # Layer 4 (runtime patch)
            runtime_patch = self._patches.get(agent_id, {})
            result = _deep_merge(result, runtime_patch)
            if patch:
                result = _deep_merge(result, patch)

            resolved = ResolvedConfig(agent_id, result)

            if write_resolved:
                resolved.to_file(self._resolved_dir / f"{agent_id}.json")

            return resolved

    def resolve_cached(self, agent_id: str) -> ResolvedConfig:
        """Resolve using in-memory cache (Layers 1-3, no runtime patch)."""
        with self._lock:
            if agent_id not in self._cache:
                self._cache[agent_id] = self.resolve(agent_id)
            return self._cache[agent_id]

    def _invalidate(self, agent_id: str):
        self._cache.pop(agent_id, None)

    def _invalidate_all(self):
        self._cache.clear()

    # ─── Runtime Patch ──────────────────────────────────────────────────────

    def apply_patch(self, agent_id: str, patch: dict) -> ResolvedConfig:
        """Apply a runtime patch (Layer 4) — not persisted to disk."""
        with self._lock:
            self._patches[agent_id] = _deep_merge(
                self._patches.get(agent_id, {}), patch
            )
            self._invalidate(agent_id)
            return self.resolve(agent_id)

    def clear_patch(self, agent_id: str) -> None:
        """Clear runtime patch for agent."""
        with self._lock:
            self._patches.pop(agent_id, None)
            self._invalidate(agent_id)

    # ─── Convenience ────────────────────────────────────────────────────────

    def list_agents(self) -> list[str]:
        """List all agent IDs that have env files."""
        if not self._env_dir.exists():
            return []
        return [p.stem for p in self._env_dir.glob("*.json")]

    def get_resolved_path(self, agent_id: str) -> Path:
        return self._resolved_dir / f"{agent_id}.json"

    def get_env_path(self, agent_id: str) -> Path:
        return self._env_dir / f"{agent_id}.json"

    def export_base_template(self, path: Optional[Path] = None) -> Path:
        """Export the builtin defaults as a base template JSON file."""
        out = path or (DEFAULT_BASE_PATH.parent / "base_template.json")
        Path(out).write_text(json.dumps(BUILTIN_DEFAULTS, indent=2))
        return out
