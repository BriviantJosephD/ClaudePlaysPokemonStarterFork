"""Knowledge base critic.

Runs a small secondary model (default: Claude Haiku) after each summarization
event to review the agent's long-term knowledge base. The critic emits short
feedback that is injected into the next turn so the main agent self-corrects
its KB hygiene.

Design goals:
- Cheap: small input, small output, runs only at summarization time.
- Quiet: returns None (no nag) when the KB is fine.
- Robust: any API error is logged and swallowed; the main loop never blocks.
"""

import logging

from anthropic import Anthropic

logger = logging.getLogger(__name__)


CRITIC_SYSTEM_PROMPT = """You are reviewing the long-term knowledge base of an autonomous agent playing Pokemon Red.

Your job is narrow: identify entries that are missing, stale, or vague, and return a SHORT bulleted list of suggestions.

Rules:
- Be terse. Maximum 5 bullets. Each bullet under 20 words.
- If the knowledge base is fine, reply with exactly: KB_OK
- Do NOT play the game. Do NOT add narrative. Do NOT invent facts.
- Focus on three failure modes:
  1. MISSING: entries the agent should have added given recent progress.
  2. STALE: entries contradicted by the recent progress summary.
  3. VAGUE: entries too generic to be useful (suggest deletion or sharpening).
- Output bullets only. No preamble, no closing remarks."""


class KnowledgeBaseCritic:
    """Calls a small model to review the knowledge base after summarization."""

    def __init__(
        self,
        model: str,
        max_tokens: int = 500,
        enabled: bool = True,
        client=None,
    ):
        # Reuse a shared Anthropic client when provided to avoid duplicate
        # connection pools. Falls back to constructing one if not supplied.
        self.client = client if client is not None else Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.enabled = enabled

    def review(self, knowledge_base_xml: str, summary_text: str):
        """Review the KB and return feedback string, or None if disabled / no issues / error.

        Args:
            knowledge_base_xml: The rendered knowledge base XML (from KnowledgeBase.render()).
            summary_text: The recent-progress summary just produced by the main agent.

        Returns:
            A short feedback string to inject into the next turn, or None.
        """
        if not self.enabled:
            return None

        # Log the model name once per review so silent failures (e.g. an
        # invalid model snapshot string) become diagnosable from the run log.
        logger.info(f"[Critic] Reviewing KB with model {self.model!r}")

        # If KB is empty, give the critic a hint instead of an empty XML blob.
        kb_for_review = knowledge_base_xml.strip() or "<knowledge_base></knowledge_base> (empty)"

        user_msg = (
            f"Recent progress summary:\n{summary_text}\n\n"
            f"Current knowledge base:\n{kb_for_review}\n\n"
            "Review the knowledge base. Reply with bullets or KB_OK."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=CRITIC_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:
            logger.error(f"[Critic] Review API call failed: {e}")
            return None

        try:
            text = " ".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
        except Exception as e:
            logger.error(f"[Critic] Failed to parse response: {e}")
            return None

        # Tolerant KB_OK detection: accept "KB_OK", " kb_ok ", "KB_OK.",
        # "KB_OK!" etc. We strip non-alphanumeric chars from the first token
        # and compare case-insensitively. This survives common LLM stylistic
        # variations on the suppression sentinel.
        first_token = text.split(maxsplit=1)[0] if text else ""
        normalized = "".join(ch for ch in first_token if ch.isalnum()).upper()
        if not text or normalized == "KBOK":
            logger.info("[Critic] KB looks fine, no feedback.")
            return None

        logger.info(f"[Critic] Feedback:\n{text}")
        return text
