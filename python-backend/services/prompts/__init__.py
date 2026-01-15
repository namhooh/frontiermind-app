"""Prompt templates for Claude API calls."""

from .clause_extraction_prompt import (
    CLAUSE_EXTRACTION_SYSTEM_PROMPT,
    CLAUSE_EXTRACTION_USER_PROMPT,
    build_extraction_prompt,
)

__all__ = [
    'CLAUSE_EXTRACTION_SYSTEM_PROMPT',
    'CLAUSE_EXTRACTION_USER_PROMPT',
    'build_extraction_prompt',
]
