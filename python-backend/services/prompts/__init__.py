"""Prompt templates for Claude API calls."""

from .clause_extraction_prompt import (
    CLAUSE_EXTRACTION_SYSTEM_PROMPT,
    CLAUSE_EXTRACTION_USER_PROMPT,
    build_extraction_prompt,
    build_chunk_extraction_prompt,
)

from .discovery_prompt import (
    DISCOVERY_SYSTEM_PROMPT,
    DISCOVERY_USER_PROMPT,
    build_discovery_prompt,
    build_chunk_discovery_prompt,
)

from .categorization_prompt import (
    CATEGORIZATION_SYSTEM_PROMPT,
    build_categorization_prompt,
    build_batch_categorization_prompt,
)

from .clause_examples import CLAUSE_EXAMPLES

from .targeted_extraction_prompt import (
    TARGETED_CATEGORIES,
    build_targeted_extraction_prompt,
    get_missing_categories,
)

from .payload_enrichment_prompt import (
    build_enrichment_prompt,
    build_batch_enrichment_prompt,
    get_enrichment_candidates,
)

__all__ = [
    # Single-pass extraction
    'CLAUSE_EXTRACTION_SYSTEM_PROMPT',
    'CLAUSE_EXTRACTION_USER_PROMPT',
    'build_extraction_prompt',
    'build_chunk_extraction_prompt',
    # Two-pass extraction
    'DISCOVERY_SYSTEM_PROMPT',
    'DISCOVERY_USER_PROMPT',
    'build_discovery_prompt',
    'build_chunk_discovery_prompt',
    'CATEGORIZATION_SYSTEM_PROMPT',
    'build_categorization_prompt',
    'build_batch_categorization_prompt',
    # Examples
    'CLAUSE_EXAMPLES',
    # Targeted extraction
    'TARGETED_CATEGORIES',
    'build_targeted_extraction_prompt',
    'get_missing_categories',
    # Payload enrichment
    'build_enrichment_prompt',
    'build_batch_enrichment_prompt',
    'get_enrichment_candidates',
]
