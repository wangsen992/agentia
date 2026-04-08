"""
Agentia Config Schemas — 3 Approaches for 9-Dimension Agent Composition

Each approach lives in its own file:
  approach_a_flat.py      — Flat JSON with dotted-key conventions
  approach_b_pydantic.py  — Nested Pydantic models with full validation
  approach_c_layered.py   — Layered config with base + env override merging

Import example:
  from agent_side.config_schemas.approach_b_pydantic import (
      AgentServerConfigPydantic,
      ConfigManagerPydantic,
  )
"""

from .approach_a_flat import (
    AgentServerConfigFlat,
    ConfigManagerFlat,
)
from .approach_b_pydantic import (
    AgentServerConfigPydantic,
    ConfigManagerPydantic,
    AccessLevel,
    AdapterType,
    MemoryType,
    UpdatePolicy,
    LifecycleState,
)
from .approach_c_layered import (
    ConfigManagerLayered,
    ResolvedConfig,
    LayeredConfig,
    BUILTIN_DEFAULTS,
)
