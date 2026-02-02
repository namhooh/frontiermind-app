"""
PII Detection Service using Microsoft Presidio.

PRIVACY-FIRST DESIGN:
This service MUST be called BEFORE sending contract text to external APIs
(LlamaParse, Claude API) to prevent PII exposure.

The service detects and anonymizes personally identifiable information (PII)
locally using Microsoft Presidio, ensuring sensitive data never leaves the system
until it's been properly redacted.

Configuration is loaded from config/pii_config.yaml. If the config file is
missing, hardcoded defaults are used as a fallback.
"""

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
from typing import List, Dict, Any, Optional, Set, Tuple
import logging
import os
import re

import yaml

from models.contract import PIIEntity, AnonymizedResult


# Configure logging
logger = logging.getLogger(__name__)

# Default config used when pii_config.yaml is missing
_DEFAULT_CONFIG: Dict[str, Any] = {
    "detection": {
        "language": "en",
        "min_confidence_threshold": 0.4,
    },
    "person_entity_denylist": [
        "Managed Site",
        "Site Acceptance",
        "Allocation Target",
        "Technical Site",
        "Commercial Operation",
        "Force Majeure",
        "Effective Date",
        "Guaranteed Capacity",
        "Commercial Operation Date",
        "Site Acceptance Test",
        "Force Majeure Event",
        "Project Site",
        "Generation Site",
        "Facility Site",
        "Construction Site",
        "Solar Site",
        "Wind Site",
        "Battery Site",
        "Substation Site",
        "Interconnection Site",
        "Delivery Site",
        "Metering Site",
        "Sierra Leone",
        "Freetown",
        "Ivory Coast",
        "Burkina Faso",
        "Sri Lanka",
        "Costa Rica",
        "Puerto Rico",
        "El Salvador",
        "Trinidad",
        "Tobago",
    ],
    "person_entity_deny_patterns": [
        r"\b\w+\s+(?:Date|Period|Test|Agreement|Certificate|Obligation|Requirement|Warranty|Guarantee|Condition|Termination|Payment|Schedule|Appendix|Annex|Notice|Amount|Dispute|Damages|Report|Site)\b",
        r"\b(?:\w+\s+){2,4}(?:Event|Capacity|Price|Rate|Fee|Charge|Limit|Factor|Index|Ratio)\b",
        r"\b[A-Z][a-z]+\s+of\s+[A-Z][a-z]+\b",
    ],
    "standard_entities": [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON",
        "US_SSN",
        "CREDIT_CARD",
        "ORGANIZATION",
    ],
    "custom_recognizers": [
        {
            "name": "contract_id",
            "entity_type": "CONTRACT_ID",
            "patterns": [
                {
                    "name": "contract_id_pattern",
                    "regex": r"PPA-\d{4}-\d{6}",
                    "score": 0.9,
                }
            ],
        },
        {
            "name": "street_address",
            "entity_type": "STREET_ADDRESS",
            "patterns": [
                {
                    "name": "numbered_street",
                    "regex": r"(?:No\.?\s*)?\d{1,6}[A-Za-z]?\s+[A-Za-z][A-Za-z\.\s]{0,30}\b(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Road|Rd|Court|Ct|Place|Pl|Way|Circle|Cir|Terrace|Ter|Trail|Trl|Parkway|Pkwy|Highway|Hwy|Loop|Square|Sq)\.?\b",
                    "score": 0.85,
                },
                {
                    "name": "no_prefix_street",
                    "regex": r"No\.?\s*\d{1,6}[A-Za-z]?\s*,\s*[A-Za-z][A-Za-z\.\s]{0,30}\b(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Road|Rd|Court|Ct|Place|Pl|Way|Circle|Cir|Terrace|Ter|Trail|Trl|Parkway|Pkwy|Highway|Hwy|Loop|Square|Sq)\.?\b",
                    "score": 0.85,
                },
                {
                    "name": "po_box",
                    "regex": r"P\.?\s?O\.?\s*Box\s+\d+",
                    "score": 0.9,
                },
            ],
        },
    ],
    "anonymization": {
        "operators": {
            "EMAIL_ADDRESS": {"strategy": "replace", "placeholder": "<EMAIL_REDACTED>"},
            "PHONE_NUMBER": {"strategy": "replace", "placeholder": "<PHONE_REDACTED>"},
            "PERSON": {"strategy": "replace", "placeholder": "<NAME_REDACTED>"},
            "US_SSN": {"strategy": "redact"},
            "CREDIT_CARD": {"strategy": "redact"},
            "CONTRACT_ID": {"strategy": "replace", "placeholder": "<CONTRACT_ID_REDACTED>"},
            "STREET_ADDRESS": {"strategy": "replace", "placeholder": "<ADDRESS_REDACTED>"},
            "ORGANIZATION": {"strategy": "keep"},
        }
    },
    "file_validation": {
        "max_file_size_mb": 10,
        "allowed_extensions": [".pdf", ".docx"],
    },
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load PII configuration from YAML file.

    Falls back to hardcoded defaults if the file is missing or invalid.

    Args:
        config_path: Optional explicit path to config file. If None, looks
            for config/pii_config.yaml relative to python-backend/.

    Returns:
        Configuration dictionary.
    """
    if config_path is None:
        # Resolve relative to this file: services/ -> python-backend/ -> config/
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config", "pii_config.yaml")

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded PII config from {config_path}")
        return config
    except FileNotFoundError:
        logger.warning(f"PII config not found at {config_path}, using defaults")
        return _DEFAULT_CONFIG
    except Exception as e:
        logger.warning(f"Failed to load PII config ({e}), using defaults")
        return _DEFAULT_CONFIG


class PIIDetectionError(Exception):
    """Raised when PII detection fails."""
    pass


class PIIAnonymizationError(Exception):
    """Raised when PII anonymization fails."""
    pass


class PIIDetector:
    """
    PII detection and anonymization service.

    Uses Microsoft Presidio to detect and anonymize personally identifiable
    information in contract text. Supports standard PII types (email, phone,
    SSN, etc.) plus custom patterns like CONTRACT_ID.

    Configuration is loaded from config/pii_config.yaml. If the file is not
    found, hardcoded defaults are used.

    Example usage:
        detector = PIIDetector()
        entities = detector.detect(contract_text)
        result = detector.anonymize(contract_text, entities)
        # result.anonymized_text is safe to send to external APIs
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize Presidio analyzer and anonymizer engines.

        Sets up the engines and registers custom recognizers for
        energy contract-specific patterns.

        Args:
            config_path: Optional path to pii_config.yaml. If None, uses
                the default location (config/pii_config.yaml).
        """
        try:
            logger.info("Initializing PIIDetector with Presidio engines")

            # Load configuration
            self._config = load_config(config_path)

            # Derive settings from config
            self.SUPPORTED_ENTITIES = self._config.get(
                "standard_entities", _DEFAULT_CONFIG["standard_entities"]
            )

            detection_cfg = self._config.get("detection", {})
            self._language = detection_cfg.get("language", "en")
            self._min_confidence = detection_cfg.get("min_confidence_threshold", 0.4)

            # Load person-entity denylist (case-insensitive)
            raw_denylist = self._config.get(
                "person_entity_denylist",
                _DEFAULT_CONFIG.get("person_entity_denylist", []),
            )
            self._person_denylist: set = {term.lower() for term in raw_denylist}

            # Compile person-entity deny patterns (regex, case-insensitive)
            raw_patterns = self._config.get(
                "person_entity_deny_patterns",
                _DEFAULT_CONFIG.get("person_entity_deny_patterns", []),
            )
            self._person_deny_patterns = [
                re.compile(p, re.IGNORECASE) for p in raw_patterns
            ]

            # Compile PII-section heading patterns
            raw_pii_sections = self._config.get("pii_sections", [])
            self._pii_section_patterns = [
                re.compile(p, re.IGNORECASE) for p in raw_pii_sections
            ]

            # Compile definitions-section patterns
            defs_cfg = self._config.get("definitions_section", {})
            heading_pat = defs_cfg.get("heading_pattern", "")
            self._defs_heading_pattern = (
                re.compile(heading_pat, re.IGNORECASE) if heading_pat else None
            )
            self._defs_term_patterns = [
                re.compile(p, re.IGNORECASE)
                for p in defs_cfg.get("term_patterns", [])
            ]

            # Section-restricted entity types
            self._section_restricted_entities: set = set(
                self._config.get("section_restricted_entities", [])
            )

            # Name context triggers — second-pass filter for PERSON in PII sections
            name_ctx_cfg = self._config.get("name_context_triggers", {})
            self._name_context_enabled = name_ctx_cfg.get("enabled", False)
            self._name_context_lookbehind = name_ctx_cfg.get("lookbehind_chars", 300)
            self._name_context_patterns = [
                re.compile(p) for p in name_ctx_cfg.get("patterns", [])
            ]

            # Major heading pattern used to find section boundaries
            self._major_heading_re = re.compile(
                r'(?:^|\n)\s*(?:ARTICLE\s+[\dIVXLCDM]+[.:]?\s+\w|[A-Z][A-Z ]{3,}(?:\n|$)|\d+\.\s+[A-Z])',
                re.MULTILINE,
            )

            # Stricter heading pattern for end-of-definitions detection.
            # Only matches ARTICLE headings and numbered section headings,
            # not arbitrary all-caps text within the DEFINITIONS section.
            self._article_heading_re = re.compile(
                r'(?:^|\n)\s*(?:ARTICLE\s+[\dIVXLCDM]+[.:]?\s+\w|\d+\.\s+[A-Z])',
                re.MULTILINE,
            )

            # Initialize Presidio engines
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()

            # Add custom recognizers from config
            self._register_custom_recognizers()

            logger.info("PIIDetector initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PIIDetector: {str(e)}")
            raise PIIDetectionError(f"Initialization failed: {str(e)}") from e

    def _register_custom_recognizers(self):
        """
        Register custom recognizers from configuration.

        Reads the custom_recognizers list from pii_config.yaml and registers
        each as a Presidio PatternRecognizer.
        """
        custom_recognizers = self._config.get(
            "custom_recognizers", _DEFAULT_CONFIG["custom_recognizers"]
        )

        for recognizer_def in custom_recognizers:
            entity_type = recognizer_def["entity_type"]
            patterns = []

            for pat_def in recognizer_def.get("patterns", []):
                patterns.append(
                    Pattern(
                        name=pat_def["name"],
                        regex=pat_def["regex"],
                        score=pat_def.get("score", 0.5),
                    )
                )

            recognizer = PatternRecognizer(
                supported_entity=entity_type,
                patterns=patterns,
            )

            self.analyzer.registry.add_recognizer(recognizer)
            logger.info(f"Registered custom {entity_type} recognizer")

    def _build_operators(self) -> Dict[str, OperatorConfig]:
        """
        Build Presidio OperatorConfig dict from configuration.

        Returns:
            Dictionary mapping entity type to OperatorConfig.
        """
        anon_cfg = self._config.get("anonymization", {}).get(
            "operators", _DEFAULT_CONFIG["anonymization"]["operators"]
        )

        operators: Dict[str, OperatorConfig] = {}

        for entity_type, op_def in anon_cfg.items():
            strategy = op_def.get("strategy", "replace")

            if strategy == "keep":
                # Skip — entity will be filtered out before anonymization
                continue
            elif strategy == "redact":
                operators[entity_type] = OperatorConfig("redact", {})
            else:
                placeholder = op_def.get("placeholder", f"<{entity_type}_REDACTED>")
                operators[entity_type] = OperatorConfig(
                    "replace", {"new_value": placeholder}
                )

        return operators

    def _get_keep_entities(self) -> set:
        """Return entity types configured with strategy 'keep'."""
        anon_cfg = self._config.get("anonymization", {}).get(
            "operators", _DEFAULT_CONFIG["anonymization"]["operators"]
        )
        return {
            entity_type
            for entity_type, op_def in anon_cfg.items()
            if op_def.get("strategy") == "keep"
        }

    def _is_person_denylist_match(self, entity_text: str) -> bool:
        """Return True if *entity_text* matches the person-entity denylist (case-insensitive)."""
        return entity_text.strip().lower() in self._person_denylist

    def _is_person_deny_pattern_match(self, entity_text: str) -> bool:
        """Return True if *entity_text* matches a person-entity deny pattern.

        Checks two conditions:
        1. ALL-CAPS text (3+ chars) — section headers like "DEFINITIONS".
        2. Regex patterns from ``person_entity_deny_patterns`` config.
        """
        text = entity_text.strip()
        # ALL-CAPS structural filter (3+ chars)
        if len(text) >= 3 and text == text.upper():
            return True
        # Regex pattern filter
        for pattern in self._person_deny_patterns:
            if pattern.search(text):
                return True
        return False

    def _extract_definition_terms(self, text: str) -> Set[str]:
        """Extract defined terms from the contract's DEFINITIONS section.

        Scans for a DEFINITIONS heading, then extracts quoted terms followed by
        defining verbs (e.g. ``"Withdrawal Notice" means ...``).  Returns a set
        of term strings (original case) to be used as a per-contract dynamic
        denylist for PERSON entities.
        """
        if not self._defs_heading_pattern or not self._defs_term_patterns:
            return set()

        heading_match = self._defs_heading_pattern.search(text)
        if not heading_match:
            return set()

        section_start = heading_match.end()

        # Find the end of the definitions section using a stricter heading
        # pattern (ARTICLE / numbered section) to avoid truncating on
        # sub-headings within DEFINITIONS that happen to be all-caps.
        next_heading = self._article_heading_re.search(text, section_start + 1)
        section_end = next_heading.start() if next_heading else len(text)

        section_text = text[section_start:section_end]

        terms: Set[str] = set()
        for pattern in self._defs_term_patterns:
            for m in pattern.finditer(section_text):
                term = m.group(1).strip()
                if term:
                    terms.add(term)

        if terms:
            logger.debug(f"Extracted {len(terms)} definition terms: {terms}")

        return terms

    def _parse_pii_sections(self, text: str) -> List[Tuple[int, int]]:
        """Identify character ranges of PII-heavy sections.

        Each PII section starts at the matched heading and extends to the next
        major heading (or end of document).  Returns a list of ``(start, end)``
        character offset tuples.
        """
        if not self._pii_section_patterns:
            return []

        ranges: List[Tuple[int, int]] = []

        for pattern in self._pii_section_patterns:
            for m in pattern.finditer(text):
                section_start = m.start()
                # Find next major heading after this match
                next_heading = self._major_heading_re.search(text, m.end() + 1)
                section_end = next_heading.start() if next_heading else len(text)
                ranges.append((section_start, section_end))

        # Add pre-heading text (contract preamble) as a PII section.
        # Text before the first ARTICLE / numbered section heading often
        # contains party names and addresses (e.g., "POWER PURCHASE AGREEMENT\n
        # Between John Smith and...").  We use the stricter article heading
        # pattern so that document titles (ALL-CAPS lines) don't prematurely
        # end the preamble range.
        first_article = self._article_heading_re.search(text)
        if first_article and first_article.start() > 0:
            ranges.append((0, first_article.start()))

        # Sort and merge overlapping ranges
        if ranges:
            ranges.sort()
            merged: List[Tuple[int, int]] = [ranges[0]]
            for start, end in ranges[1:]:
                if start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            ranges = merged

        return ranges

    @staticmethod
    def _is_in_pii_section(start: int, end: int, pii_ranges: List[Tuple[int, int]]) -> bool:
        """Check if an entity span falls within any PII-heavy section range."""
        for range_start, range_end in pii_ranges:
            if start >= range_start and end <= range_end:
                return True
        return False

    def _has_name_context(self, text: str, entity_start: int) -> bool:
        """Check if a PERSON entity appears near a contextual trigger.

        Searches the text within ``lookbehind_chars`` before the entity start
        position for any configured trigger pattern (e.g., ``Name:``,
        ``Attention:``, ``By:``, ``between``).

        Returns ``True`` if a trigger is found (the entity is likely a real
        name) or if no patterns are configured (safe default).
        """
        if not self._name_context_patterns:
            return True  # safe default: no patterns → keep entity

        window_start = max(0, entity_start - self._name_context_lookbehind)
        window = text[window_start:entity_start]

        for pattern in self._name_context_patterns:
            if pattern.search(window):
                return True
        return False

    @staticmethod
    def _resolve_overlaps(results: List[RecognizerResult], text: str) -> List[RecognizerResult]:
        """Deduplicate / resolve overlapping entities.

        Rules applied in order:
        1. Discard entities where ``start >= end``.
        2. Discard entities whose matched text is whitespace-only.
        3. For overlapping spans, keep the entity produced by a custom
           PatternRecognizer (``recognition_metadata`` contains
           ``recognizer_name``).  If both are custom or both NER, keep
           the one with the higher confidence score.
        """
        # Step 1 & 2: filter degenerate / whitespace-only entities
        valid: List[RecognizerResult] = []
        for r in results:
            if r.start >= r.end:
                continue
            matched = text[r.start:r.end]
            if not matched.strip():
                continue
            valid.append(r)

        if not valid:
            return valid

        # Sort by start position, then by descending span length for tie-breaking
        valid.sort(key=lambda r: (r.start, -(r.end - r.start)))

        def _is_custom(r: RecognizerResult) -> bool:
            meta = getattr(r, "recognition_metadata", None) or {}
            name = meta.get("recognizer_name", "")
            # Presidio NER recognizer is "SpacyRecognizer" or "StanzaRecognizer"
            return bool(name) and "Recognizer" not in name

        kept: List[RecognizerResult] = []
        for r in valid:
            overlap = False
            for i, existing in enumerate(kept):
                # Check overlap
                if r.start < existing.end and r.end > existing.start:
                    overlap = True
                    # Decide which to keep
                    r_custom = _is_custom(r)
                    ex_custom = _is_custom(existing)
                    if r_custom and not ex_custom:
                        kept[i] = r  # replace with custom
                    elif not r_custom and ex_custom:
                        pass  # keep existing custom
                    elif r.score > existing.score:
                        kept[i] = r
                    # else keep existing
                    break
            if not overlap:
                kept.append(r)

        return kept

    def detect(self, text: str) -> List[PIIEntity]:
        """
        Detect PII entities in text.

        Analyzes the provided text for personally identifiable information
        using Presidio's NLP-based detection. Detects standard PII types
        (email, phone, names, SSN, credit cards) plus custom patterns.

        Args:
            text: Contract text to analyze for PII

        Returns:
            List of detected PII entities with positions and confidence scores

        Raises:
            PIIDetectionError: If detection fails

        Example:
            entities = detector.detect("Contact john.doe@example.com")
            # Returns: [PIIEntity(entity_type='EMAIL_ADDRESS', ...)]
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to detect()")
            return []

        try:
            logger.info(f"Detecting PII in text (length: {len(text)} characters)")

            # --- Mechanism 1: Extract definition terms (dynamic denylist) ---
            definition_terms = self._extract_definition_terms(text)
            dynamic_denylist = self._person_denylist | {t.lower() for t in definition_terms}
            # Keep a separate set of lowercased definition terms for substring matching
            definition_terms_lower = {t.lower() for t in definition_terms}

            # --- Mechanism 2: Parse PII-heavy section boundaries ---
            pii_ranges = self._parse_pii_sections(text)

            # Add custom energy-specific entities to detection
            custom_entities = [
                r["entity_type"]
                for r in self._config.get(
                    "custom_recognizers", _DEFAULT_CONFIG["custom_recognizers"]
                )
            ]
            entities_to_detect = self.SUPPORTED_ENTITIES + custom_entities

            # Run Presidio analyzer
            results: List[RecognizerResult] = self.analyzer.analyze(
                text=text,
                language=self._language,
                entities=entities_to_detect
            )

            # Filter to minimum confidence threshold to reduce false positives
            results = [r for r in results if r.score >= self._min_confidence]

            # Resolve overlapping / degenerate entities
            results = self._resolve_overlaps(results, text)

            # Filter out person-entity denylist and deny-pattern matches
            # (uses dynamic denylist which includes extracted definition terms)
            def _is_person_excluded(r: RecognizerResult) -> bool:
                entity_text = text[r.start:r.end].strip().lower()
                # Exact match against static denylist + definition terms
                if entity_text in dynamic_denylist:
                    return True
                # Substring match: if the entity text is a contiguous
                # substring of any definition term, also exclude it.
                # This handles partial NER matches (e.g., spaCy detects
                # "Withdrawal" instead of full "Withdrawal Notice").
                if definition_terms_lower and any(
                    entity_text in dt for dt in definition_terms_lower
                ):
                    return True
                # Regex structural patterns
                if self._is_person_deny_pattern_match(text[r.start:r.end]):
                    return True
                return False

            results = [
                r for r in results
                if not (r.entity_type == "PERSON" and _is_person_excluded(r))
            ]

            # Section-restriction filter: suppress NER-based entities outside
            # PII-heavy sections.  If no PII sections were found, fall back to
            # redacting everything (safe default).
            if pii_ranges and self._section_restricted_entities:
                results = [
                    r for r in results
                    if r.entity_type not in self._section_restricted_entities
                    or self._is_in_pii_section(r.start, r.end, pii_ranges)
                ]

            # Context trigger filter: within PII sections, PERSON entities must
            # appear near a contextual trigger (e.g., "Name:", "Attention:", "By:")
            # to be kept.  This narrows detection from "anywhere in NOTICES" to
            # "near name-related lines within NOTICES."
            if self._name_context_enabled and self._name_context_patterns:
                results = [
                    r for r in results
                    if r.entity_type != "PERSON"
                    or not pii_ranges  # safe default: no sections found → skip context check
                    or self._has_name_context(text, r.start)
                ]

            # Debug logging for ADDRESS entities to trace recognizer source
            for r in results:
                if r.entity_type == "STREET_ADDRESS":
                    meta = getattr(r, "recognition_metadata", None) or {}
                    recognizer_name = meta.get("recognizer_name", "unknown")
                    logger.debug(
                        f"ADDRESS entity: '{text[r.start:r.end]}' "
                        f"(score={r.score}, recognizer={recognizer_name}, "
                        f"span={r.start}-{r.end})"
                    )

            # Convert Presidio results to our Pydantic model
            pii_entities = [
                PIIEntity(
                    entity_type=result.entity_type,
                    start=result.start,
                    end=result.end,
                    score=result.score,
                    text=text[result.start:result.end]
                )
                for result in results
            ]

            logger.info(f"Detected {len(pii_entities)} PII entities")

            # Log entity types found (for debugging)
            if pii_entities:
                entity_types = {e.entity_type for e in pii_entities}
                logger.debug(f"Entity types found: {', '.join(entity_types)}")

            return pii_entities

        except Exception as e:
            logger.error(f"PII detection failed: {str(e)}")
            raise PIIDetectionError(f"Failed to detect PII: {str(e)}") from e

    def anonymize(self, text: str, entities: List[PIIEntity]) -> AnonymizedResult:
        """
        Anonymize detected PII in text.

        Replaces PII entities with placeholders like <EMAIL_REDACTED>,
        <PHONE_REDACTED>, etc. Organizations are kept for context.

        Args:
            text: Original contract text
            entities: List of PII entities from detect()

        Returns:
            AnonymizedResult containing:
            - anonymized_text: Text with PII replaced
            - pii_count: Number of entities anonymized
            - entities_found: Original entities
            - mapping: Placeholder -> original value mapping

        Raises:
            PIIAnonymizationError: If anonymization fails

        Example:
            result = detector.anonymize(text, entities)
            # result.anonymized_text: "Contact <EMAIL_REDACTED>"
            # result.mapping: {"<EMAIL_ADDRESS_8_28>": "john@example.com"}
        """
        if not text:
            logger.warning("Empty text provided to anonymize()")
            return AnonymizedResult(
                anonymized_text="",
                pii_count=0,
                entities_found=[],
                mapping={}
            )

        if not entities:
            logger.info("No PII entities to anonymize")
            return AnonymizedResult(
                anonymized_text=text,
                pii_count=0,
                entities_found=[],
                mapping={}
            )

        try:
            logger.info(f"Anonymizing {len(entities)} PII entities")

            # Filter out entities with "keep" strategy (e.g., ORGANIZATION)
            keep_entities = self._get_keep_entities()
            entities_to_anonymize = [
                e for e in entities if e.entity_type not in keep_entities
            ]

            if not entities_to_anonymize:
                logger.info("All entities have 'keep' strategy, keeping text unchanged")
                return AnonymizedResult(
                    anonymized_text=text,
                    pii_count=0,
                    entities_found=entities,
                    mapping={}
                )

            # Build operators from config
            operators = self._build_operators()

            # Convert PIIEntity to PresidioResult format
            presidio_results = [
                RecognizerResult(
                    entity_type=e.entity_type,
                    start=e.start,
                    end=e.end,
                    score=e.score
                )
                for e in entities_to_anonymize
            ]

            # Run anonymization
            anonymized_result = self.anonymizer.anonymize(
                text=text,
                analyzer_results=presidio_results,
                operators=operators
            )

            # Create mapping for re-identification
            mapping = self.create_mapping(entities_to_anonymize, text)

            result = AnonymizedResult(
                anonymized_text=anonymized_result.text,
                pii_count=len(entities_to_anonymize),
                entities_found=entities,
                mapping=mapping
            )

            logger.info(
                f"Anonymization complete. Anonymized {result.pii_count} entities, "
                f"created {len(mapping)} mappings"
            )

            return result

        except Exception as e:
            logger.error(f"PII anonymization failed: {str(e)}")
            raise PIIAnonymizationError(f"Failed to anonymize PII: {str(e)}") from e

    def create_mapping(
        self, entities: List[PIIEntity], original_text: str
    ) -> Dict[str, str]:
        """
        Create mapping of placeholders to original PII values.

        This mapping allows potential re-identification of PII for authorized
        users. MUST be stored separately in the contract_pii_mapping table
        with encryption.

        Args:
            entities: List of detected PII entities
            original_text: Original contract text (before anonymization)

        Returns:
            Dictionary mapping unique placeholders to original PII values

        Example:
            mapping = {
                "<EMAIL_ADDRESS_42_65>": "john.smith@example.com",
                "<PHONE_NUMBER_70_82>": "555-123-4567"
            }
        """
        mapping = {}

        for entity in entities:
            # Create unique placeholder based on entity type and position
            placeholder = f"<{entity.entity_type}_{entity.start}_{entity.end}>"

            # Extract original value from text
            original_value = original_text[entity.start:entity.end]

            mapping[placeholder] = original_value

        logger.debug(f"Created {len(mapping)} PII mappings")

        return mapping
