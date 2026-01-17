"""
Contract text chunking with section awareness and overlap handling.

Splits long contracts into manageable chunks while preserving:
- Section boundaries where possible
- Overlap for clauses that span chunk boundaries
- Context for accurate extraction
"""

import re
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

from .token_estimator import TokenEstimator

logger = logging.getLogger(__name__)


@dataclass
class ChunkMetadata:
    """Metadata for a text chunk."""
    chunk_index: int
    total_chunks: int
    start_section: Optional[str]
    end_section: Optional[str]
    has_overlap_before: bool
    has_overlap_after: bool
    estimated_tokens: int


@dataclass
class TextChunk:
    """A chunk of contract text with metadata."""
    text: str
    metadata: ChunkMetadata


class ContractChunker:
    """
    Splits contract text into chunks for processing.

    Strategy:
    1. Detect section boundaries (ARTICLE, Section, numbered headers)
    2. Group sections into chunks within token budget
    3. Add overlap at boundaries
    4. Include chunk context in metadata
    """

    # Section detection patterns (ordered by priority)
    SECTION_PATTERNS = [
        r'^(ARTICLE\s+[IVXLCDM]+\.?)',           # ARTICLE I, ARTICLE II
        r'^(ARTICLE\s+\d+\.?)',                   # ARTICLE 1, ARTICLE 2
        r'^(Section\s+\d+(?:\.\d+)*\.?)',         # Section 1.2.3
        r'^(\d+(?:\.\d+)*\.?\s+[A-Z][A-Z\s]+)',   # 1.2 TITLE IN CAPS
        r'^(\d+(?:\.\d+)*\.)',                    # 1.2.
        r'^([A-Z][A-Z\s]{10,})',                  # DEFINITIONS, TERM AND TERMINATION
    ]

    DEFAULT_CONFIG = {
        "target_chunk_tokens": 50000,
        "max_chunk_tokens": 60000,
        "overlap_tokens": 2000,
        "min_chunk_tokens": 5000,
        "prompt_overhead_tokens": 5000,
    }

    def __init__(
        self,
        token_estimator: TokenEstimator,
        config: Optional[dict] = None
    ):
        """
        Initialize chunker.

        Args:
            token_estimator: TokenEstimator instance for counting tokens
            config: Optional configuration overrides
        """
        self.estimator = token_estimator
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._compiled_patterns = [
            re.compile(p, re.MULTILINE | re.IGNORECASE)
            for p in self.SECTION_PATTERNS
        ]

    def chunk_contract(self, text: str) -> List[TextChunk]:
        """
        Split contract text into chunks.

        Args:
            text: Full contract text

        Returns:
            List of TextChunk objects with metadata
        """
        total_tokens = self.estimator.estimate_tokens(text)
        target = self.config["target_chunk_tokens"]

        # If text fits in one chunk, return as-is
        if total_tokens <= target:
            logger.info(f"Contract fits in single chunk ({total_tokens} tokens)")
            return [TextChunk(
                text=text,
                metadata=ChunkMetadata(
                    chunk_index=0,
                    total_chunks=1,
                    start_section=None,
                    end_section=None,
                    has_overlap_before=False,
                    has_overlap_after=False,
                    estimated_tokens=total_tokens
                )
            )]

        logger.info(f"Chunking contract: {total_tokens} tokens into ~{total_tokens // target + 1} chunks")

        # Detect section boundaries
        sections = self._detect_sections(text)

        if sections:
            # Section-aware chunking
            chunks = self._chunk_by_sections(text, sections)
        else:
            # Fallback: paragraph-based chunking
            logger.warning("No section markers detected, using paragraph-based chunking")
            chunks = self._chunk_by_paragraphs(text)

        return chunks

    def _detect_sections(self, text: str) -> List[Tuple[int, str, str]]:
        """
        Detect section boundaries in text.

        Returns:
            List of (position, section_marker, section_title) tuples
        """
        sections = []
        lines = text.split('\n')
        position = 0

        for line in lines:
            stripped = line.strip()
            for pattern in self._compiled_patterns:
                match = pattern.match(stripped)
                if match:
                    sections.append((position, match.group(1), stripped))
                    break
            position += len(line) + 1  # +1 for newline

        logger.debug(f"Detected {len(sections)} section markers")
        return sections

    def _chunk_by_sections(
        self,
        text: str,
        sections: List[Tuple[int, str, str]]
    ) -> List[TextChunk]:
        """
        Create chunks based on section boundaries.

        Groups consecutive sections until target token limit is reached.
        """
        chunks = []
        target = self.config["target_chunk_tokens"]
        overlap = self.config["overlap_tokens"]
        overlap_chars = overlap * 4  # Approximate chars for overlap

        current_start = 0
        current_sections = []

        for i, (pos, marker, title) in enumerate(sections):
            # Get end position (next section or end of text)
            next_pos = sections[i + 1][0] if i + 1 < len(sections) else len(text)

            # Check if adding this section exceeds limit
            current_text = text[current_start:next_pos]
            current_tokens = self.estimator.estimate_tokens(current_text)

            if current_tokens > target and current_sections:
                # Finalize current chunk
                chunk_end = pos
                chunk_text = text[current_start:chunk_end]

                # Add overlap from next section
                overlap_end = min(chunk_end + overlap_chars, len(text))
                chunk_text_with_overlap = text[current_start:overlap_end]

                chunks.append(self._create_chunk(
                    text=chunk_text_with_overlap,
                    chunk_index=len(chunks),
                    start_section=current_sections[0][1] if current_sections else None,
                    end_section=current_sections[-1][1] if current_sections else None,
                    has_overlap_before=len(chunks) > 0,
                    has_overlap_after=True
                ))

                # Start new chunk with overlap from previous
                overlap_start = max(current_start, chunk_end - overlap_chars)
                current_start = overlap_start
                current_sections = []

            current_sections.append((pos, marker, title))

        # Add final chunk
        if current_start < len(text):
            final_text = text[current_start:]
            chunks.append(self._create_chunk(
                text=final_text,
                chunk_index=len(chunks),
                start_section=current_sections[0][1] if current_sections else None,
                end_section=current_sections[-1][1] if current_sections else None,
                has_overlap_before=len(chunks) > 0,
                has_overlap_after=False
            ))

        # Update total_chunks in all metadata
        for chunk in chunks:
            chunk.metadata.total_chunks = len(chunks)

        return chunks

    def _chunk_by_paragraphs(self, text: str) -> List[TextChunk]:
        """
        Fallback chunking by paragraphs when no sections detected.
        """
        chunks = []
        paragraphs = text.split('\n\n')
        target = self.config["target_chunk_tokens"]
        overlap = self.config["overlap_tokens"]

        current_paragraphs = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self.estimator.estimate_tokens(para)

            if current_tokens + para_tokens > target and current_paragraphs:
                # Create chunk
                chunk_text = '\n\n'.join(current_paragraphs)
                chunks.append(self._create_chunk(
                    text=chunk_text,
                    chunk_index=len(chunks),
                    start_section=None,
                    end_section=None,
                    has_overlap_before=len(chunks) > 0,
                    has_overlap_after=True
                ))

                # Keep last few paragraphs for overlap
                overlap_paras = []
                overlap_tokens = 0
                for p in reversed(current_paragraphs):
                    p_tokens = self.estimator.estimate_tokens(p)
                    if overlap_tokens + p_tokens > overlap:
                        break
                    overlap_paras.insert(0, p)
                    overlap_tokens += p_tokens

                current_paragraphs = overlap_paras
                current_tokens = overlap_tokens

            current_paragraphs.append(para)
            current_tokens += para_tokens

        # Final chunk
        if current_paragraphs:
            chunk_text = '\n\n'.join(current_paragraphs)
            chunks.append(self._create_chunk(
                text=chunk_text,
                chunk_index=len(chunks),
                start_section=None,
                end_section=None,
                has_overlap_before=len(chunks) > 0,
                has_overlap_after=False
            ))

        for chunk in chunks:
            chunk.metadata.total_chunks = len(chunks)

        return chunks

    def _create_chunk(
        self,
        text: str,
        chunk_index: int,
        start_section: Optional[str],
        end_section: Optional[str],
        has_overlap_before: bool,
        has_overlap_after: bool
    ) -> TextChunk:
        """Create a TextChunk with computed metadata."""
        return TextChunk(
            text=text,
            metadata=ChunkMetadata(
                chunk_index=chunk_index,
                total_chunks=0,  # Updated later
                start_section=start_section,
                end_section=end_section,
                has_overlap_before=has_overlap_before,
                has_overlap_after=has_overlap_after,
                estimated_tokens=self.estimator.estimate_tokens(text)
            )
        )
