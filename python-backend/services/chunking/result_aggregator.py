"""
Aggregates and deduplicates clause extraction results from multiple chunks.

Handles:
- Deduplication of clauses appearing in overlapping regions
- Merging extraction_summary from multiple chunks
- Preserving section references and audit trails
"""

import re
import logging
from typing import List, Dict, Tuple
from collections import defaultdict

from models.contract import ExtractedClause, ExtractionSummary

logger = logging.getLogger(__name__)


class ResultAggregator:
    """
    Aggregates extraction results from multiple chunks.

    Deduplication Strategy:
    1. Match by section_reference (exact match = definite duplicate)
    2. Match by clause_name similarity + raw_text overlap (fuzzy match)
    3. Keep clause with higher extraction_confidence when duplicates found
    4. Never deduplicate clauses with different categories
    """

    # Default similarity threshold (increased from 0.85 to reduce false positives)
    SIMILARITY_THRESHOLD = 0.90

    # Per-category thresholds - some categories commonly have multiple distinct clauses
    CATEGORY_THRESHOLDS = {
        "LIQUIDATED_DAMAGES": 0.95,  # Multiple LD types are common (delay, performance, availability)
        "DEFAULT": 0.95,              # Multiple default events are distinct
        "CONDITIONS_PRECEDENT": 0.95, # Multiple CPs are common
        "COMPLIANCE": 0.92,           # Multiple compliance provisions
        "GENERAL": 0.85,              # Boilerplate can be similar
    }

    def aggregate_results(
        self,
        chunk_results: List[Tuple[List[ExtractedClause], ExtractionSummary]],
        chunk_metadata: List[dict] = None
    ) -> Tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Aggregate results from multiple chunk extractions.

        Args:
            chunk_results: List of (clauses, summary) tuples from each chunk
            chunk_metadata: Optional metadata for each chunk (for overlap detection)

        Returns:
            Tuple of (deduplicated clauses, merged summary)
        """
        if not chunk_results:
            return [], ExtractionSummary()

        all_clauses = []
        all_summaries = []

        for clauses, summary in chunk_results:
            all_clauses.extend(clauses)
            all_summaries.append(summary)

        # Deduplicate clauses
        unique_clauses = self._deduplicate_clauses(all_clauses)

        # Merge summaries
        merged_summary = self._merge_summaries(all_summaries, unique_clauses)

        # Renumber clause IDs sequentially
        for i, clause in enumerate(unique_clauses):
            clause.clause_id = f"clause_{i+1:03d}"

        logger.info(
            f"Aggregation complete: {len(all_clauses)} total -> "
            f"{len(unique_clauses)} unique clauses"
        )

        return unique_clauses, merged_summary

    def _deduplicate_clauses(
        self,
        clauses: List[ExtractedClause]
    ) -> List[ExtractedClause]:
        """
        Remove duplicate clauses, keeping highest confidence version.

        Matching criteria:
        1. Exact section_reference match
        2. Fuzzy clause_name + raw_text similarity
        """
        if not clauses:
            return []

        # Group by section_reference first
        by_section: Dict[str, List[ExtractedClause]] = defaultdict(list)
        no_section: List[ExtractedClause] = []

        for clause in clauses:
            if clause.section_reference:
                by_section[clause.section_reference].append(clause)
            else:
                no_section.append(clause)

        unique = []

        # Process clauses with section references
        for section_ref, group in by_section.items():
            if len(group) == 1:
                unique.append(group[0])
            else:
                # Multiple clauses with same section - deduplicate
                best = self._select_best_clause(group)
                unique.append(best)
                logger.debug(
                    f"Deduplicated {len(group)} clauses for section {section_ref}"
                )

        # Process clauses without section references (use fuzzy matching)
        for clause in no_section:
            if not self._is_duplicate(clause, unique):
                unique.append(clause)

        # Sort by section reference
        unique.sort(key=lambda c: self._section_sort_key(c.section_reference))

        return unique

    def _select_best_clause(
        self,
        clauses: List[ExtractedClause]
    ) -> ExtractedClause:
        """Select the best clause from duplicates based on confidence."""
        return max(
            clauses,
            key=lambda c: (
                c.extraction_confidence or c.confidence_score or 0,
                len(c.raw_text or "")  # Prefer longer raw_text as tiebreaker
            )
        )

    def _is_duplicate(
        self,
        clause: ExtractedClause,
        existing: List[ExtractedClause]
    ) -> bool:
        """Check if clause is a duplicate of any in existing list."""
        # Get the appropriate threshold for this clause's category
        threshold = self._get_threshold_for_category(clause.category)

        for existing_clause in existing:
            similarity = self._calculate_similarity(clause, existing_clause)
            if similarity >= threshold:
                logger.debug(
                    f"Fuzzy duplicate detected: '{clause.clause_name}' ~ "
                    f"'{existing_clause.clause_name}' (similarity={similarity:.2f}, threshold={threshold})"
                )
                return True
        return False

    def _get_threshold_for_category(self, category: str) -> float:
        """Get the deduplication threshold for a specific category."""
        if category and category in self.CATEGORY_THRESHOLDS:
            return self.CATEGORY_THRESHOLDS[category]
        return self.SIMILARITY_THRESHOLD

    def _calculate_similarity(
        self,
        a: ExtractedClause,
        b: ExtractedClause
    ) -> float:
        """
        Calculate similarity between two clauses.

        IMPORTANT: Clauses with different categories are NEVER considered duplicates.
        This prevents loss of distinct clause types (e.g., multiple LD types).
        """
        # Never deduplicate clauses with different categories
        if a.category and b.category and a.category != b.category:
            return 0.0  # Different categories = never duplicate

        # Name similarity
        name_sim = self._text_similarity(
            a.clause_name or "",
            b.clause_name or ""
        )

        # Raw text overlap (compare first 500 chars)
        text_sim = self._text_similarity(
            (a.raw_text or "")[:500],
            (b.raw_text or "")[:500]
        )

        # Category match bonus (only applies when categories are the same or missing)
        category_match = 0.1 if a.category == b.category else 0

        return (name_sim * 0.3) + (text_sim * 0.6) + category_match

    def _text_similarity(self, a: str, b: str) -> float:
        """Simple Jaccard similarity on words."""
        if not a or not b:
            return 0.0

        words_a = set(a.lower().split())
        words_b = set(b.lower().split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union)

    def _section_sort_key(self, section_ref: str) -> Tuple:
        """Generate sort key for section references."""
        if not section_ref:
            return (999,)  # Put unsorted at end

        # Extract numbers from section reference
        numbers = re.findall(r'\d+', section_ref)

        if numbers:
            return tuple(int(n) for n in numbers)
        return (998, section_ref)  # Alpha sections near end

    def _merge_summaries(
        self,
        summaries: List[ExtractionSummary],
        unique_clauses: List[ExtractedClause]
    ) -> ExtractionSummary:
        """Merge extraction summaries from multiple chunks."""
        if not summaries:
            return ExtractionSummary()

        # Use first detected contract type
        contract_type = None
        for s in summaries:
            if s.contract_type_detected:
                contract_type = s.contract_type_detected
                break

        # Recalculate clauses_by_category from unique clauses
        clauses_by_category: Dict[str, int] = defaultdict(int)
        unidentified_count = 0
        confidence_sum = 0.0
        confidence_count = 0

        for clause in unique_clauses:
            category = clause.category or "UNIDENTIFIED"
            clauses_by_category[category] += 1

            if category == "UNIDENTIFIED":
                unidentified_count += 1

            conf = clause.extraction_confidence or clause.confidence_score
            if conf is not None:
                confidence_sum += conf
                confidence_count += 1

        # Collect all warnings
        all_warnings = []
        seen_warnings = set()
        for s in summaries:
            for w in (s.extraction_warnings or []):
                if w not in seen_warnings:
                    all_warnings.append(w)
                    seen_warnings.add(w)

        # Detect if template (any chunk detected template)
        is_template = any(s.is_template for s in summaries)

        return ExtractionSummary(
            contract_type_detected=contract_type,
            total_clauses_extracted=len(unique_clauses),
            clauses_by_category=dict(clauses_by_category),
            unidentified_count=unidentified_count,
            average_confidence=confidence_sum / confidence_count if confidence_count > 0 else None,
            extraction_warnings=all_warnings,
            is_template=is_template,
        )
