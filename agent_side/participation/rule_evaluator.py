"""
Approach A — Rule-Based Evaluator

Fast, deterministic, auditable.  No LLM needed.

Configuration (passed in via constructor):
  - topic_rules   : list of {topic, level} dicts   — topic keyword → participation level
  - skill_rules   : list of {skill, level} dicts   — skill name → participation level
  - keyword_rules : list of {keyword, level} dicts  — arbitrary substring → level
  - default_level : ParticipationLevel              — when nothing matches

The evaluator tries rules in order; first match wins (priority order).
A weight field (0-100) on each rule lets future extensions do score aggregation.
"""

import re
from typing import Optional

from .types import AgentContext, ParticipationLevel, RelayMessage


# ---------------------------------------------------------------------------
# Default rules bundled with the evaluator
# ---------------------------------------------------------------------------

DEFAULT_TOPIC_RULES = [
    # High-stakes topics always get active engagement
    {"topic": "error",      "level": ParticipationLevel.ACTIVE,   "weight": 90},
    {"topic": "critical",   "level": ParticipationLevel.ACTIVE,   "weight": 95},
    {"topic": "question",   "level": ParticipationLevel.ACTIVE,   "weight": 80},
    {"topic": "help",       "level": ParticipationLevel.ACTIVE,   "weight": 85},
    # Observer for passive monitoring topics
    {"topic": "log",        "level": ParticipationLevel.OBSERVER, "weight": 60},
    {"topic": "status",     "level": ParticipationLevel.OBSERVER, "weight": 50},
    {"topic": "heartbeat",  "level": ParticipationLevel.SKIP,     "weight": 40},
]

DEFAULT_SKILL_RULES = [
    # Skill-tagged messages route to the agent that owns that skill
    {"skill": "weather",    "level": ParticipationLevel.ACTIVE,   "weight": 95},
    {"skill": "reminders", "level": ParticipationLevel.ACTIVE,   "weight": 90},
    {"skill": "email",     "level": ParticipationLevel.ACTIVE,   "weight": 90},
    {"skill": "zotero",    "level": ParticipationLevel.ACTIVE,   "weight": 85},
    {"skill": "ynab",      "level": ParticipationLevel.ACTIVE,   "weight": 85},
]

DEFAULT_KEYWORD_RULES = [
    # Catch-all substrings
    {"keyword": "@agent",    "level": ParticipationLevel.ACTIVE,   "weight": 80},
    {"keyword": "urgent",   "level": ParticipationLevel.ACTIVE,   "weight": 90},
    {"keyword": "please",   "level": ParticipationLevel.ACTIVE,   "weight": 50},
    {"keyword": "?",        "level": ParticipationLevel.ACTIVE,   "weight": 60},
    # Passive
    {"keyword": "FYI",      "level": ParticipationLevel.OBSERVER, "weight": 50},
    {"keyword": "status",   "level": ParticipationLevel.OBSERVER, "weight": 40},
]


# ---------------------------------------------------------------------------
# RuleEvaluator
# ---------------------------------------------------------------------------

class RuleEvaluator:
    """
    Config-driven rule engine for participation decisions.

    Usage::

        evaluator = RuleEvaluator(
            topic_rules=DEFAULT_TOPIC_RULES,
            skill_rules=DEFAULT_SKILL_RULES,
            keyword_rules=DEFAULT_KEYWORD_RULES,
            default_level=ParticipationLevel.OBSERVER,
        )

        level = evaluator.evaluate(message, context)

    The evaluator processes rules in this order::

        1. topic_rules   — checks message.metadata["topic"] and content
        2. skill_rules   — checks whether any skill in AgentContext matches
        3. keyword_rules — substring scan of message.content

    Any rule can match and return immediately (first-match wins).
    """

    def __init__(
        self,
        topic_rules: Optional[list[dict]] = None,
        skill_rules: Optional[list[dict]] = None,
        keyword_rules: Optional[list[dict]] = None,
        default_level: ParticipationLevel = ParticipationLevel.OBSERVER,
    ):
        self.topic_rules   = topic_rules   or DEFAULT_TOPIC_RULES
        self.skill_rules   = skill_rules   or DEFAULT_SKILL_RULES
        self.keyword_rules = keyword_rules or DEFAULT_KEYWORD_RULES
        self.default_level = default_level

        # Build compiled regex for speed (keyword → pattern)
        self._keyword_patterns = [
            (rule["keyword"], re.compile(re.escape(rule["keyword"]), re.IGNORECASE))
            for rule in self.keyword_rules
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel:
        """
        Evaluate a message and return the participation level.

        Order of checks (first match returns):

        1. Agent capability filter — does this agent have the needed skill?
        2. Topic keyword scan      — message content + metadata["topic"]
        3. Skill tag match         — message metadata["skill"] in agent.skills
        4. Arbitrary keyword scan  — substring / regex on content
        5. Default                 — default_level

        Args:
            message: incoming RelayMessage
            context: receiving agent's context

        Returns:
            ParticipationLevel — one of active / observer / skip
        """
        # ── 1. Capability filter ───────────────────────────────────────
        required_skill = message.metadata.get("required_skill")
        if required_skill and required_skill not in context.skills:
            return ParticipationLevel.SKIP

        # ── 2. Topic scan ───────────────────────────────────────────────
        level = self._match_topic(message, context)
        if level is not None:
            return level

        # ── 3. Skill tag match ──────────────────────────────────────────
        level = self._match_skill_tag(message, context)
        if level is not None:
            return level

        # ── 4. Arbitrary keyword scan ──────────────────────────────────
        level = self._match_keywords(message)
        if level is not None:
            return level

        # ── 5. Default ─────────────────────────────────────────────────
        return self.default_level

    # ------------------------------------------------------------------
    # Internal match helpers
    # ------------------------------------------------------------------

    def _match_topic(
        self, message: RelayMessage, context: AgentContext
    ) -> Optional[ParticipationLevel]:
        """Scan topic keywords in message content and metadata."""
        text = message.content.lower()
        # Also include metadata["topic"] if present
        topic_tags = message.metadata.get("topic", "")
        if isinstance(topic_tags, str):
            text = f"{text} {topic_tags}".lower()
        else:
            text = f"{text} {' '.join(topic_tags)}".lower()

        for rule in self.topic_rules:
            kw = rule["topic"].lower()
            if kw in text:
                return ParticipationLevel(rule["level"])
        return None

    def _match_skill_tag(
        self, message: RelayMessage, context: AgentContext
    ) -> Optional[ParticipationLevel]:
        """Check message metadata skill tag against agent's known skills."""
        skill_tag = message.metadata.get("skill")
        if not skill_tag:
            return None
        if skill_tag in context.skills:
            return ParticipationLevel.ACTIVE
        return None

    def _match_keywords(
        self, message: RelayMessage
    ) -> Optional[ParticipationLevel]:
        """Substring scan of message content against keyword rules."""
        text = message.content.lower()
        for keyword, pattern in self._keyword_patterns:
            if pattern.search(text):
                # Find the corresponding rule's level
                for rule in self.keyword_rules:
                    if rule["keyword"].lower() == keyword.lower():
                        return ParticipationLevel(rule["level"])
        return None

    # ------------------------------------------------------------------
    # Introspection (for debugging / audit)
    # ------------------------------------------------------------------

    def explain(
        self, message: RelayMessage, context: AgentContext
    ) -> dict:
        """
        Return a full audit trail of what each rule group matched.

        Useful for debugging and for generating explainability reports.
        """
        traces = []
        final_level = self.default_level

        # Topic scan trace
        text = message.content.lower()
        topic_tags = message.metadata.get("topic", "")
        if isinstance(topic_tags, str):
            combined = f"{text} {topic_tags}".lower()
        else:
            combined = f"{text} {' '.join(topic_tags)}".lower()

        for rule in self.topic_rules:
            hit = rule["topic"].lower() in combined
            if hit:
                traces.append(
                    {"rule": "topic", "pattern": rule["topic"], "hit": True,
                     "level": rule["level"], "weight": rule.get("weight")}
                )
                final_level = ParticipationLevel(rule["level"])
                break
        else:
            traces.append({"rule": "topic", "pattern": None, "hit": False})

        # Skill tag trace
        skill_tag = message.metadata.get("skill")
        if skill_tag:
            hit = skill_tag in context.skills
            traces.append(
                {"rule": "skill_tag", "pattern": skill_tag, "hit": hit,
                 "level": ParticipationLevel.ACTIVE if hit else None}
            )
            if hit:
                final_level = ParticipationLevel.ACTIVE
        else:
            traces.append({"rule": "skill_tag", "pattern": None, "hit": False})

        # Keyword scan trace
        for keyword, pattern in self._keyword_patterns:
            hit = bool(pattern.search(text))
            if hit:
                for rule in self.keyword_rules:
                    if rule["keyword"].lower() == keyword.lower():
                        traces.append(
                            {"rule": "keyword", "pattern": keyword, "hit": True,
                             "level": rule["level"], "weight": rule.get("weight")}
                        )
                        final_level = ParticipationLevel(rule["level"])
                        break
                break
        else:
            traces.append({"rule": "keyword", "pattern": None, "hit": False})

        return {
            "message_id": message.message_id,
            "agent_id": context.agent_id,
            "final_level": final_level,
            "traces": traces,
        }


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_rule_evaluator(config: Optional[dict] = None) -> RuleEvaluator:
    """
    Build a RuleEvaluator from a plain dict (e.g. loaded from JSON/YAML).

    Config shape::

        {
            "topic_rules":   [{"topic": "error", "level": "active", "weight": 90}, ...],
            "skill_rules":   [{"skill": "weather", "level": "active"}, ...],
            "keyword_rules": [{"keyword": "@agent", "level": "active"}, ...],
            "default_level": "observer",
        }
    """
    cfg = config or {}
    default_raw = cfg.get("default_level", "observer")
    default = ParticipationLevel(default_raw)

    def _parse_level(raw):
        return ParticipationLevel(raw) if isinstance(raw, str) else raw

    topic_rules = [
        {**r, "level": _parse_level(r["level"])}
        for r in cfg.get("topic_rules", DEFAULT_TOPIC_RULES)
    ]
    skill_rules = [
        {**r, "level": _parse_level(r["level"])}
        for r in cfg.get("skill_rules", DEFAULT_SKILL_RULES)
    ]
    keyword_rules = [
        {**r, "level": _parse_level(r["level"])}
        for r in cfg.get("keyword_rules", DEFAULT_KEYWORD_RULES)
    ]

    return RuleEvaluator(
        topic_rules=topic_rules,
        skill_rules=skill_rules,
        keyword_rules=keyword_rules,
        default_level=default,
    )
