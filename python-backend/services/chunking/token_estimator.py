"""
Token estimation utilities for chunking contract text.

Uses Anthropic's count_tokens API when available, with character-based fallback.
"""

import logging
from typing import Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)


class TokenEstimator:
    """
    Estimates token counts for text using Anthropic API or heuristics.

    Primary: Uses client.messages.count_tokens() for accurate counting
    Fallback: Character-based estimation (1 token ~ 4 chars)
    """

    CHARS_PER_TOKEN = 4  # Conservative estimate for English text

    def __init__(self, client: Optional[Anthropic] = None):
        """
        Initialize token estimator.

        Args:
            client: Optional Anthropic client for API-based counting
        """
        self.client = client
        self._use_api = client is not None

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for given text.

        Args:
            text: The text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        if self._use_api:
            try:
                return self._count_tokens_api(text)
            except Exception as e:
                logger.warning(f"API token counting failed, using fallback: {e}")

        return self._estimate_tokens_heuristic(text)

    def _count_tokens_api(self, text: str) -> int:
        """Count tokens using Anthropic API."""
        response = self.client.messages.count_tokens(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": text}]
        )
        return response.input_tokens

    def _estimate_tokens_heuristic(self, text: str) -> int:
        """Fallback character-based estimation."""
        return len(text) // self.CHARS_PER_TOKEN

    def estimate_prompt_overhead(self, system_prompt: str, user_template: str) -> int:
        """
        Estimate token overhead for prompt template (without contract text).

        Args:
            system_prompt: The system prompt text
            user_template: The user prompt template (with placeholder)

        Returns:
            Estimated overhead tokens
        """
        # Remove contract placeholder for estimation
        template_text = user_template.replace("{contract_text}", "")
        return self.estimate_tokens(system_prompt + template_text)
