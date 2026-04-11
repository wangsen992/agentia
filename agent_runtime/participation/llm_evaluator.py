"""
Approach B — LLM-Based Classifier

Flexible participation classification driven by an LLM.
Slow and non-deterministic, but can handle nuance that rules can't.

Architecture:
  - The LLM is called with a structured prompt containing:
      * the RelayMessage (content + metadata)
      * the AgentContext (agent profile: role, skills, memory summary)
      * conversation_history (last N turns)
      * a short rubric explaining each ParticipationLevel
  - Response is parsed as JSON: {"level": "active"|"observer"|"skip", "reason": "..."}

Requirements:
  - An LLM client callable from Python (openai, anthropic, ollama, etc.)
  - Configured via an LLMConfig dataclass (model, base_url, api_key, etc.)
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from .types import AgentContext, ParticipationLevel, RelayMessage


# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    """
    Configuration for the LLM backend used by LLMClassifier.

    Compatible with OpenAI, Anthropic, Ollama, or any OpenAI-compatible API.
    """

    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    timeout: float = 30.0
    max_history_turns: int = 5   # how many recent history turns to include
    extra_headers: dict = field(default_factory=dict)  # e.g. {"HTTP-Additional": "value"}


# ---------------------------------------------------------------------------
# Default system prompt (rubric)
# ---------------------------------------------------------------------------

SYSTEM_RUBRIC = """You are a participation classifier for a multi-agent messaging system.

Given an incoming message and the receiving agent's profile, decide whether the agent
should:
  - ACTIVE   : Process the message fully and send a response.
  - OBSERVER : Read the message but do not respond (passive monitoring).
  - SKIP     : Ignore the message entirely — do not route it to the agent.

Respond ONLY with a valid JSON object:
  {"level": "active"|"observer"|"skip", "reason": "<1-sentence explanation>"}

Do not include any text outside the JSON object.
"""


# ---------------------------------------------------------------------------
# LLMClassifier
# ---------------------------------------------------------------------------

class LLMClassifier:
    """
    LLM-driven participation evaluator.

    Usage::

        classifier = LLMClassifier(
            llm_config=LLMConfig(model="gpt-4o-mini", api_key="sk-..."),
        )

        level = classifier.evaluate(message, context)

    The evaluate() call is **synchronous** and blocks until the LLM responds.
    For async use, wrap in asyncio or run in a thread pool.

    Cost & latency note:
      - Typical latency: 500ms–3s depending on model and network
      - Each evaluate() call costs LLM tokens
      - Use in production only when evaluation nuance matters more than speed
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        rubric: str = SYSTEM_RUBRIC,
        client_factory: Optional[Callable[["LLMConfig"], object]] = None,
        # client_factory should return an LLM client with a .chat/completions endpoint
        # If None, uses _default_openai_client
    ):
        self.llm_config = llm_config or LLMConfig()
        self.rubric = rubric
        self._client_factory = client_factory or self._default_openai_client
        self._client = None   # lazily initialised

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self, message: RelayMessage, context: AgentContext
    ) -> ParticipationLevel:
        """
        Ask the LLM to classify participation level for a message.

        Args:
            message: incoming RelayMessage
            context: receiving agent's context

        Returns:
            ParticipationLevel — one of active / observer / skip

        Raises:
            ClassificationError: if the LLM returns unparseable output
        """
        prompt = self._build_prompt(message, context)

        try:
            raw = self._call_llm(prompt)
            parsed = self._parse_response(raw)
            return ParticipationLevel(parsed["level"])
        except Exception as e:
            # Fail open — treat as observer rather than blocking message routing
            print(f"[LLMClassifier] Classification failed: {e}. Defaulting to observer.")
            return ParticipationLevel.OBSERVER

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self, message: RelayMessage, context: AgentContext
    ) -> str:
        """Build the full user-prompt string sent to the LLM."""

        history_section = ""
        if context.conversation_history:
            turns = context.conversation_history[-self.llm_config.max_history_turns:]
            history_lines = "\n".join(
                f"  - [{i+1}] {turn}" for i, turn in enumerate(turns)
            )
            history_section = f"\nRecent conversation history:\n{history_lines}\n"

        metadata_section = ""
        if message.metadata:
            metadata_section = f"\nMessage metadata: {json.dumps(message.metadata)}\n"

        return (
            f"{self.rubric}\n\n"
            f"=== INCOMING MESSAGE ===\n"
            f"message_id     : {message.message_id}\n"
            f"from_agent     : {message.from_agent}\n"
            f"to_agent       : {message.to_agent}\n"
            f"conversation_id: {message.conversation_id}\n"
            f"timestamp      : {message.timestamp}\n"
            f"content        : {message.content}\n"
            f"{metadata_section}"
            f"\n=== RECEIVING AGENT PROFILE ===\n"
            f"agent_id       : {context.agent_id}\n"
            f"role_name      : {context.role.name}\n"
            f"role_description: {context.role.description}\n"
            f"role_topics    : {', '.join(context.role.topics) or '(none)'}\n"
            f"skills         : {', '.join(context.skills) or '(none)'}\n"
            f"memory_summary : {context.memory_state or '(empty)'}\n"
            f"{history_section}"
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazily create the LLM client."""
        if self._client is None:
            self._client = self._client_factory(self.llm_config)
        return self._client

    def _call_llm(self, prompt: str) -> str:
        """
        Make the actual LLM API call and return the raw response text.

        Default implementation uses the OpenAI SDK (openai package).
        Override _client_factory to use a different backend.
        """
        client = self._get_client()

        # OpenAI-compatible chat completion
        response = client.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {"role": "system", "content": self.rubric},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,   # low temperature for deterministic output
            max_tokens=128,
            timeout=self.llm_config.timeout,
        )
        return response.choices[0].message.content

    def _parse_response(self, raw: str) -> dict:
        """Parse the LLM's JSON response."""
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            # Find the JSON inside ```json ... ```
            lines = raw.splitlines()
            json_lines = [l for l in lines if not l.startswith("```") and l.strip()]
            raw = "\n".join(json_lines)

        parsed = json.loads(raw)
        if "level" not in parsed:
            raise ClassificationError(f"No 'level' field in LLM response: {raw}")
        level = parsed["level"]
        if level not in ("active", "observer", "skip"):
            raise ClassificationError(f"Invalid level '{level}' from LLM: {raw}")
        return parsed

    # ------------------------------------------------------------------
    # Default client factory (OpenAI-compatible)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_openai_client(cfg: LLMConfig):
        """
        Build an OpenAI SDK client from LLMConfig.

        Requires the `openai` package.  For Anthropic, Ollama, etc.,
        pass a custom client_factory instead.
        """
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "LLMClassifier requires the `openai` package. "
                "Install it with: pip install openai\n"
                "Or pass a custom client_factory for your LLM backend."
            ) from e

        return OpenAI(
            api_key=cfg.api_key or None,
            base_url=cfg.base_url if cfg.base_url else None,
            timeout=cfg.timeout,
            default_headers=cfg.extra_headers,
        )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ClassificationError(Exception):
    """Raised when the LLM returns an unparseable or invalid response."""
    pass


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_llm_evaluator(config: Optional[dict] = None) -> LLMClassifier:
    """
    Build an LLMClassifier from a plain dict (e.g. from agent.json).

    Config shape::

        {
            "llm": {
                "model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-...",
                "timeout": 30.0,
                "max_history_turns": 5,
            }
        }
    """
    cfg = (config or {}).get("llm", {})
    llm_cfg = LLMConfig(
        model=cfg.get("model", "gpt-4o-mini"),
        base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        api_key=cfg.get("api_key", ""),
        timeout=cfg.get("timeout", 30.0),
        max_history_turns=cfg.get("max_history_turns", 5),
        extra_headers=cfg.get("extra_headers", {}),
    )
    return LLMClassifier(llm_config=llm_cfg)
