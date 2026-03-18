"""
Phase 1 — Section Isolator for Step 11P.

Scans OCR text (from LlamaParse) and isolates pricing-relevant sections
by heading pattern matching. Reduces ~60 pages of contract text to ~10-15
pages of pricing-relevant content for focused Claude extraction.
"""

import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("step11p.section_isolator")

# OCR cache directory (shared with step8 pattern)
REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "reports" / "cbe-population"
OCR_CACHE_DIR = REPORT_DIR / "step11p_ocr_cache"


# =============================================================================
# Section Patterns
# =============================================================================

# Each tuple: (section_type, compiled_regex, priority)
# Higher priority sections are more likely to contain pricing data.
# Patterns match section/annexure headings in OCR text.

SECTION_PATTERNS: List[Tuple[str, re.Pattern, int]] = [
    # Part I / Project Terms — OY definition, key dates, capacity
    ("project_terms", re.compile(
        r"(?:^|\n)\s*(?:Part\s+I[:\s]|Project\s+Terms\s+and\s+Conditions)",
        re.IGNORECASE,
    ), 5),

    # Pricing Annexure — base rates, escalation, floor/ceiling
    ("pricing_annexure", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s*[-–—]?\s*"
        r"(?:Pricing|Payment|Tariff|Energy\s+(?:Charges?|Fees?|Rates?))",
        re.IGNORECASE,
    ), 10),

    # Energy Output — guaranteed kWh per year, degradation
    ("energy_output", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s*[-–—]?\s*"
        r"(?:Expected\s+Energy|Energy\s+Output|Guaranteed\s+(?:Energy|Generation))",
        re.IGNORECASE,
    ), 9),

    # Energy Calculation — available/deemed energy formulas
    ("energy_calculation", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s*[-–—]?\s*"
        r"(?:Energy\s+(?:Output\s+)?Calculation|Deemed\s+Energy|Available\s+Energy)",
        re.IGNORECASE,
    ), 8),

    # Required Energy Output — performance thresholds
    ("required_energy", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s*[-–—]?\s*"
        r"(?:Required\s+Energy|Minimum\s+(?:Energy|Generation|Output))",
        re.IGNORECASE,
    ), 7),

    # Performance Guarantee articles
    ("performance_guarantee", re.compile(
        r"(?:^|\n)\s*(?:Article|Section|Clause)\s+\d+[\.\s]*[-–—:]?\s*"
        r"(?:Performance\s+Guarantee|Generation\s+Guarantee|Energy\s+Guarantee)",
        re.IGNORECASE,
    ), 8),

    # Liquidated Damages articles
    ("liquidated_damages", re.compile(
        r"(?:^|\n)\s*(?:Article|Section|Clause)\s+\d+[\.\s]*[-–—:]?\s*"
        r"(?:Liquidated\s+Damages|Shortfall\s+(?:Payment|Penalty)|Performance\s+(?:Shortfall|Penalty))",
        re.IGNORECASE,
    ), 7),

    # Deemed/Available Energy articles
    ("deemed_energy", re.compile(
        r"(?:^|\n)\s*(?:Article|Section|Clause)\s+\d+[\.\s]*[-–—:]?\s*"
        r"(?:Available\s+Energy|Deemed\s+(?:Energy|Generation)|Energy\s+Accounting)",
        re.IGNORECASE,
    ), 8),

    # CPI/Indexation annexure
    ("cpi_indexation", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s*[-–—]?\s*"
        r"(?:Indexation|CPI|Consumer\s+Price|Price\s+(?:Adjustment|Escalation))",
        re.IGNORECASE,
    ), 9),

    # Definitions article
    ("definitions", re.compile(
        r"(?:^|\n)\s*(?:Article|Section|Clause)\s+1[\.\s]*[-–—:]?\s*"
        r"(?:Definitions|Interpretation)",
        re.IGNORECASE,
    ), 4),

    # Pricing/Payment articles (not in annexure)
    ("pricing_article", re.compile(
        r"(?:^|\n)\s*(?:Article|Section|Clause)\s+\d+[\.\s]*[-–—:]?\s*"
        r"(?:Pricing|Payment|Tariff|Billing|Invoice|Energy\s+(?:Charges?|Price|Rate))",
        re.IGNORECASE,
    ), 7),

    # Generic annexure headers (lettered) — catch-all for Annexure C, D, E, etc.
    ("generic_annexure", re.compile(
        r"(?:^|\n)\s*(?:Annexure|Annex|Schedule|Appendix)\s+([A-Z]|\d+)\b",
        re.IGNORECASE,
    ), 2),
]

# Pattern to detect the start of a new major section (used to find section boundaries)
SECTION_BOUNDARY = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:Article|Section|Clause)\s+\d+[\.\s]*[-–—:]|"
    r"(?:Annexure|Annex|Schedule|Appendix)\s+[-–—]?\s*[A-Z\d]|"
    r"Part\s+(?:I{1,3}|IV|V|[1-5])\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class IsolatedSection:
    """A section extracted from the OCR text."""
    section_type: str
    heading: str
    start_pos: int
    end_pos: int
    text: str
    priority: int
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass
class PricingSectionBundle:
    """Concatenated pricing-relevant sections with metadata."""
    combined_text: str
    sections: List[IsolatedSection] = field(default_factory=list)
    total_chars: int = 0
    original_chars: int = 0
    reduction_pct: float = 0.0

    def __post_init__(self):
        self.total_chars = len(self.combined_text)
        if self.original_chars > 0:
            self.reduction_pct = round(
                (1 - self.total_chars / self.original_chars) * 100, 1
            )


# =============================================================================
# OCR Helpers
# =============================================================================

def get_ocr_text(
    file_bytes: bytes,
    filename: str,
    use_cache: bool = True,
) -> str:
    """
    Get OCR text for a PDF, using disk cache if available.

    Checks step11p cache first, then step8 cache (shared OCR), then runs fresh.
    """
    cache_key = hashlib.sha256(filename.encode()).hexdigest()

    # Check step11p cache
    cache_path = OCR_CACHE_DIR / f"{cache_key}.md"
    if use_cache and cache_path.exists():
        log.info(f"  OCR cache hit (step11p): {filename}")
        return cache_path.read_text()

    # Check step8 cache (may have already been OCR'd for invoice calibration)
    step8_cache = REPORT_DIR / "step8_ocr_cache" / f"{cache_key}.md"
    if use_cache and step8_cache.exists():
        log.info(f"  OCR cache hit (step8): {filename}")
        return step8_cache.read_text()

    # Also check step11 extraction_metadata for cached OCR
    # (step11 stores OCR text in contract.extraction_metadata.ocr_text)
    # This is handled by the orchestrator, not here.

    # Run fresh OCR via LlamaParse
    log.info(f"  Running LlamaParse OCR for: {filename}")
    text = _run_llamaparse(file_bytes, filename)

    # Cache result
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text)
    log.info(f"  OCR complete: {len(text)} chars, cached → {cache_key}.md")

    return text


def _run_llamaparse(file_bytes: bytes, filename: str) -> str:
    """Run LlamaParse OCR on PDF bytes."""
    from llama_parse import LlamaParse

    parser = LlamaParse(
        result_type="markdown",
        verbose=False,
    )

    # LlamaParse requires a file path
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        documents = parser.load_data(str(tmp_path))
        text = "\n\n".join(doc.text for doc in documents)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if not text.strip():
        raise ValueError(f"LlamaParse returned empty text for {filename}")

    return text


# =============================================================================
# Core: Section Isolation
# =============================================================================

def isolate_pricing_sections(
    ocr_text: str,
    min_priority: int = 3,
) -> PricingSectionBundle:
    """
    Scan OCR text and extract pricing-relevant sections.

    Args:
        ocr_text: Full contract OCR text.
        min_priority: Minimum pattern priority to include (default 3, skips
                      generic annexures and low-signal definitions).

    Returns:
        PricingSectionBundle with concatenated pricing text and section metadata.
    """
    if not ocr_text.strip():
        return PricingSectionBundle(combined_text="", original_chars=0)

    # Find all section heading matches
    matches: List[Tuple[int, str, str, int]] = []  # (pos, section_type, heading_text, priority)

    for section_type, pattern, priority in SECTION_PATTERNS:
        if priority < min_priority:
            continue
        for m in pattern.finditer(ocr_text):
            heading = m.group(0).strip()
            matches.append((m.start(), section_type, heading, priority))

    if not matches:
        log.info("  No pricing sections found — returning full text")
        return PricingSectionBundle(
            combined_text=ocr_text,
            original_chars=len(ocr_text),
        )

    # Sort by position in document
    matches.sort(key=lambda x: x[0])

    # De-duplicate overlapping matches (keep highest priority)
    deduped: List[Tuple[int, str, str, int]] = []
    for pos, stype, heading, prio in matches:
        # Skip if within 200 chars of a higher-priority match
        if deduped and abs(pos - deduped[-1][0]) < 200:
            if prio > deduped[-1][3]:
                deduped[-1] = (pos, stype, heading, prio)
            continue
        deduped.append((pos, stype, heading, prio))

    # Find all section boundaries to determine where each section ends
    all_boundaries = sorted(set(m.start() for m in SECTION_BOUNDARY.finditer(ocr_text)))

    # Extract section text
    sections: List[IsolatedSection] = []

    for pos, stype, heading, prio in deduped:
        # Find the end of this section (next boundary after this one)
        end_pos = len(ocr_text)
        for b in all_boundaries:
            if b > pos + len(heading) + 50:  # skip boundaries within the heading itself
                end_pos = b
                break

        section_text = ocr_text[pos:end_pos].strip()

        # Skip very short sections (likely false positives)
        if len(section_text) < 100:
            continue

        sections.append(IsolatedSection(
            section_type=stype,
            heading=heading,
            start_pos=pos,
            end_pos=end_pos,
            text=section_text,
            priority=prio,
        ))

    if not sections:
        log.info("  No substantial pricing sections found — returning full text")
        return PricingSectionBundle(
            combined_text=ocr_text,
            original_chars=len(ocr_text),
        )

    # Sort by document order and combine
    sections.sort(key=lambda s: s.start_pos)

    # Combine with section markers
    parts = []
    for s in sections:
        parts.append(f"\n{'='*60}")
        parts.append(f"[SECTION: {s.section_type.upper()} | {s.heading.strip()}]")
        parts.append(f"{'='*60}\n")
        parts.append(s.text)

    combined = "\n".join(parts)

    bundle = PricingSectionBundle(
        combined_text=combined,
        sections=sections,
        original_chars=len(ocr_text),
    )

    section_types = [s.section_type for s in sections]
    log.info(
        f"  Isolated {len(sections)} sections: {section_types} "
        f"({bundle.total_chars:,} chars from {bundle.original_chars:,}, "
        f"{bundle.reduction_pct}% reduction)"
    )

    return bundle


def get_section_types_found(bundle: PricingSectionBundle) -> List[str]:
    """Return unique section types found in the bundle."""
    return list(dict.fromkeys(s.section_type for s in bundle.sections))
