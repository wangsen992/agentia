"""
Participation Evaluator Subsystem

Exports the shared types and the three evaluator implementations.

Usage::

    from agent_runtime.participation import (
        ParticipationLevel,
        RelayMessage,
        AgentContext,
        RuleEvaluator,
        LLMClassifier,
        HybridEvaluator,
        make_rule_evaluator,
        make_llm_evaluator,
        make_hybrid_evaluator,
    )

Single import for the recommended factory::

    from agent_runtime.participation import make_hybrid_evaluator
"""

from .types import (
    ParticipationLevel,
    RelayMessage,
    AgentContext,
    RoleConfig,
)
from .rule_evaluator import (
    RuleEvaluator,
    make_rule_evaluator,
    DEFAULT_TOPIC_RULES,
    DEFAULT_SKILL_RULES,
    DEFAULT_KEYWORD_RULES,
)
from .llm_evaluator import (
    LLMClassifier,
    LLMConfig,
    make_llm_evaluator,
    ClassificationError,
)
from .hybrid_evaluator import (
    HybridEvaluator,
    AmbiguityDetector,
    AmbiguityResult,
    Ambiguity,
    make_hybrid_evaluator,
)

__all__ = [
    # Types
    "ParticipationLevel",
    "RelayMessage",
    "AgentContext",
    "RoleConfig",
    # Approach A
    "RuleEvaluator",
    "make_rule_evaluator",
    "DEFAULT_TOPIC_RULES",
    "DEFAULT_SKILL_RULES",
    "DEFAULT_KEYWORD_RULES",
    # Approach B
    "LLMClassifier",
    "LLMConfig",
    "make_llm_evaluator",
    "ClassificationError",
    # Approach C
    "HybridEvaluator",
    "AmbiguityDetector",
    "AmbiguityResult",
    "Ambiguity",
    "make_hybrid_evaluator",
]
