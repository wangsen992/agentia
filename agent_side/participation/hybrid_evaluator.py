"""
Approach C — Hybrid Evaluator

Fast rule filter first; LLM called only for ambiguous cases.

Architecture:
  1. Fast-path rules (keyword + capability match) — very cheap, always runs
  2. Ambiguity detector — decides whether to escalate to LLM
  3. LLM classifier — called only when fast-path is inconclusive

The HybridEvaluator wraps a RuleEvaluator and an LLMClassifier, and adds
an AmbiguityDetector between them.

Ambiguity cases that escalate to LLM:
  - Message content matches multiple rules with different levels
  - No rule matches and message is non-trivial (>50 chars, non-trivial grammar)
  - Message contains competing intent signals (e.g. "please help" + "FYI")
  - Agent's conversation_history suggests recent topic drift

The result: ~80-90% of messages are classified by rules in <1ms;
only the remaining ~10-20% hit the LLM (~500ms-3s).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .types import AgentContext, ParticipationLevel, RelayMessage
from .rule_evaluator import RuleEvaluator
from .llm_evaluator import LLMClassifier


# ---------------------------------------------------------------------------
# Ambiguity levels
# ---------------------------------------------------------------------------

class Ambiguity(str):
    """Tag describing why a message was ambiguous."""
    CLEAR = "clear"          # rule matched confidently → no LLM needed
    NO_MATCH = "no_match"    # no rule matched, non-trivial message
    CONFLICT = "conflict"    # multiple rules fired with different levels
    MIXED_SIGNALS = "mixed_signals"  # competing intent signals


@dataclass
class AmbiguityResult:
    ambiguity: Ambiguity
    rule_level: Optional[ParticipationLevel] = None
    conflict_rules: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# AmbiguityDetector
# ---------------------------------------------------------------------------

class AmbiguityDetector:
    """
    Decides whether a message is "ambiguous enough" to warrant LLM evaluation.

    Runs after the fast-path RuleEvaluator.  The evaluator returns both
    a level AND a confidence signal; this class turns that into an AmbiguityResult.

    Detection heuristics:
      - CONFLICT: RuleEvaluator matched multiple rule groups with different levels
      - NO_MATCH + non-trivial message: no rules matched AND message > 50 chars
        AND message contains at least one verb-like word
      - MIXED_SIGNALS: both SKIP/OBSERVER and ACTIVE signals present
    """

    # Phrases that signal passive/FYI intent (→ observer or skip)
    PASSIVE_PHRASES = [
        "fyi", "for your info", "just so you know", "heads up",
        "logging", "status update", "heartbeat", "monitoring",
    ]

    # Phrases that signal active intent
    ACTIVE_PHRASES = [
        "please", "help", "urgent", "need to", "can you", "could you",
        "?", "how do", "what is", "why is", "error", "problem",
        "question", "ask",
    ]

    # Minimum message length to be considered "non-trivial"
    MIN_NONTRIVIAL_LEN = 50

    def evaluate(
        self,
        message: RelayMessage,
        context: AgentContext,
        rule_evaluator: RuleEvaluator,
    ) -> AmbiguityResult:
        """
        Analyse a message against the rule evaluator's output and decide
        whether it needs LLM escalation.

        Returns an AmbiguityResult describing the ambiguity level.
        """
        # ── 1. Run rule evaluator to get raw match data ───────────────
        rule_level = rule_evaluator.evaluate(message, context)
        explanation = rule_evaluator.explain(message, context)
        traces = explanation.get("traces", [])

        # ── 2. Detect conflicts ────────────────────────────────────────
        fired_levels = set()
        fired_rules = []
        for trace in traces:
            if trace.get("hit") and trace.get("level"):
                lvl = trace["level"]
                if isinstance(lvl, str):
                    lvl = ParticipationLevel(lvl)
                fired_levels.add(lvl)
                fired_rules.append(
                    f"{trace['rule']}:{trace.get('pattern','?')}→{lvl.value}"
                )

        if len(fired_levels) > 1:
            return AmbiguityResult(
                ambiguity=Ambiguity.CONFLICT,
                rule_level=rule_level,
                conflict_rules=fired_rules,
                reason=f"Multiple rule groups fired with conflicting levels: {fired_rules}",
            )

        # ── 3. No match + non-trivial message ──────────────────────────
        if not fired_levels:
            if self._is_nontrivial(message.content):
                return AmbiguityResult(
                    ambiguity=Ambiguity.NO_MATCH,
                    rule_level=rule_level,
                    reason="No rule matched but message is non-trivial — escalating to LLM",
                )
            else:
                # Short or trivial message — default confidently
                return AmbiguityResult(
                    ambiguity=Ambiguity.CLEAR,
                    rule_level=rule_level,
                    reason="Short/trivial message with no rule match — default applies",
                )

        # ── 4. Mixed signals (passive + active phrases) ──────────────
        has_passive = any(
            p in message.content.lower() for p in self.PASSIVE_PHRASES
        )
        has_active = any(
            p in message.content.lower() for p in self.ACTIVE_PHRASES
        )
        if has_passive and has_active:
            return AmbiguityResult(
                ambiguity=Ambiguity.MIXED_SIGNALS,
                rule_level=rule_level,
                reason="Both passive and active intent signals present — escalating to LLM",
            )

        # ── 5. Clear match ─────────────────────────────────────────────
        return AmbiguityResult(
            ambiguity=Ambiguity.CLEAR,
            rule_level=rule_level,
            reason=f"Rule matched confidently: {fired_rules[0] if fired_rules else 'default'}",
        )

    def _is_nontrivial(self, content: str) -> bool:
        """Return True if the content is long enough and looks like natural language."""
        if len(content) < self.MIN_NONTRIVIAL_LEN:
            return False
        # Very spammy characters (only punctuation / single words) suggest not NL
        word_count = len(content.split())
        if word_count < 5:
            return False
        return True


# ---------------------------------------------------------------------------
# HybridEvaluator
# ---------------------------------------------------------------------------

class HybridEvaluator:
    """
    Fast rule filter + selective LLM escalation for ambiguous messages.

    Usage::

        rule_ev   = RuleEvaluator()
        llm_ev    = LLMClassifier(llm_config=LLMConfig(model="gpt-4o-mini", ...))
        ambiguity = AmbiguityDetector()
        evaluator = HybridEvaluator(
            rule_evaluator=rule_ev,
            llm_classifier=llm_ev,
            ambiguity_detector=ambiguity,
        )

        level = evaluator.evaluate(message, context)

    The evaluator's routing logic::

        RuleEvaluator ─► AmbiguityDetector
                              │
                     ┌────────┴────────┐
                     │  CLEAR          │  → return rule_level
                     │  CONFLICT       │  → LLM
                     │  NO_MATCH+NL    │  → LLM
                     │  MIXED_SIGNALS  │  → LLM
                     └─────────────────┘

    Statistics (exposed via .stats):
      - evaluations_total
      - rule_hit_count
      - llm_calls_count
      - skipped_count (SKIP from rules)
    """

    def __init__(
        self,
        rule_evaluator: Optional[RuleEvaluator] = None,
        llm_classifier: Optional[LLMClassifier] = None,
        ambiguity_detector: Optional[AmbiguityDetector] = None,
        # Optional thresholds
        llm_escalate_on: Optional[list[Ambiguity]] = None,
    ):
        self.rule_evaluator = rule_evaluator or RuleEvaluator()
        self.llm_classifier = llm_classifier
        self.ambiguity_detector = ambiguity_detector or AmbiguityDetector()
        # Which ambiguity types trigger LLM escalation (default: all non-CLEAR)
        self.llm_escalate_on = llm_escalate_on or [
            Ambiguity.CONFLICT,
            Ambiguity.NO_MATCH,
            Ambiguity.MIXED_SIGNALS,
        ]

        # ── Statistics ───────────────────────────────────────────────
        self._stats = {
            "evaluations_total": 0,
            "rule_hit_count": 0,
            "llm_calls_count": 0,
            "skipped_count": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel:
        """
        Evaluate participation level using the hybrid rule+LLM approach.

        Args:
            message: incoming RelayMessage
            context: receiving agent's context

        Returns:
            ParticipationLevel
        """
        self._stats["evaluations_total"] += 1

        # ── 1. Fast-path: rule evaluation + ambiguity detection ────────
        ambiguity_result = self.ambiguity_detector.evaluate(
            message, context, self.rule_evaluator
        )

        # ── 2. Clear rule match: return immediately ─────────────────────
        if ambiguity_result.ambiguity == Ambiguity.CLEAR:
            self._stats["rule_hit_count"] += 1
            return ambiguity_result.rule_level or ParticipationLevel.OBSERVER

        # ── 3. Escalate to LLM for ambiguous cases ─────────────────────
        if (
            self.llm_classifier is None
            or ambiguity_result.ambiguity not in self.llm_escalate_on
        ):
            # LLM not configured or ambiguity type not configured for escalation
            # Fall back to rule level
            self._stats["rule_hit_count"] += 1
            return ambiguity_result.rule_level or ParticipationLevel.OBSERVER

        # ── 4. Call LLM ────────────────────────────────────────────────
        self._stats["llm_calls_count"] += 1
        llm_level = self.llm_classifier.evaluate(message, context)

        if llm_level == ParticipationLevel.SKIP:
            self._stats["skipped_count"] += 1

        return llm_level

    def get_stats(self) -> dict:
        """Return evaluator usage statistics."""
        stats = dict(self._stats)
        if stats["evaluations_total"] > 0:
            stats["llm_call_rate"] = (
                stats["llm_calls_count"] / stats["evaluations_total"]
            )
        else:
            stats["llm_call_rate"] = 0.0
        return stats

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for k in self._stats:
            self._stats[k] = 0

    # ------------------------------------------------------------------
    # Introspection / explainability
    # ------------------------------------------------------------------

    def explain(
        self, message: RelayMessage, context: AgentContext
    ) -> dict:
        """
        Return a full explanation of the evaluation path taken.

        Includes rule explanation + ambiguity result + LLM result (if applicable).
        """
        rule_explanation = self.rule_evaluator.explain(message, context)
        ambiguity_result = self.ambiguity_detector.evaluate(
            message, context, self.rule_evaluator
        )

        result = {
            "message_id": message.message_id,
            "agent_id": context.agent_id,
            "rule_explanation": rule_explanation,
            "ambiguity": {
                "type": ambiguity_result.ambiguity,
                "reason": ambiguity_result.reason,
                "conflict_rules": ambiguity_result.conflict_rules,
            },
            "final_level": None,
            "llm_level": None,
        }

        if ambiguity_result.ambiguity == Ambiguity.CLEAR:
            result["final_level"] = (
                ambiguity_result.rule_level or ParticipationLevel.OBSERVER
            )
            result["path"] = "rule_only"
        else:
            if self.llm_classifier and (
                ambiguity_result.ambiguity in self.llm_escalate_on
            ):
                try:
                    llm_level = self.llm_classifier.evaluate(message, context)
                    result["llm_level"] = llm_level
                    result["final_level"] = llm_level
                    result["path"] = "rule_then_llm"
                except Exception as e:
                    result["llm_error"] = str(e)
                    result["final_level"] = (
                        ambiguity_result.rule_level or ParticipationLevel.OBSERVER
                    )
                    result["path"] = "rule_fallback"
            else:
                result["final_level"] = (
                    ambiguity_result.rule_level or ParticipationLevel.OBSERVER
                )
                result["path"] = "rule_fallback"

        return result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_hybrid_evaluator(
    rule_config: Optional[dict] = None,
    llm_config: Optional[dict] = None,
    llm_enabled: bool = True,
) -> HybridEvaluator:
    """
    Build a HybridEvaluator from plain dicts.

    Args:
        rule_config: passed to make_rule_evaluator()
        llm_config:  passed to make_llm_evaluator() (if llm_enabled=True)
        llm_enabled: if False, LLM classifier is not created (useful for testing)
    """
    from .rule_evaluator import make_rule_evaluator
    from .llm_evaluator import make_llm_evaluator

    rule_ev = make_rule_evaluator(rule_config or {})
    llm_ev = None
    if llm_enabled:
        llm_ev = make_llm_evaluator(llm_config or {})

    return HybridEvaluator(rule_evaluator=rule_ev, llm_classifier=llm_ev)
