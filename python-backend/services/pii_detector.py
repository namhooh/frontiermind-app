"""
PII Detection Service using Microsoft Presidio.

PRIVACY-FIRST DESIGN:
This service MUST be called BEFORE sending contract text to external APIs
(LlamaParse, Claude API) to prevent PII exposure.

The service detects and anonymizes personally identifiable information (PII)
locally using Microsoft Presidio, ensuring sensitive data never leaves the system
until it's been properly redacted.
"""

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
from typing import List, Dict
import logging

from models.contract import PIIEntity, AnonymizedResult


# Configure logging
logger = logging.getLogger(__name__)


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

    Example usage:
        detector = PIIDetector()
        entities = detector.detect(contract_text)
        result = detector.anonymize(contract_text, entities)
        # result.anonymized_text is safe to send to external APIs
    """

    # Supported PII entity types
    SUPPORTED_ENTITIES = [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON",
        "US_SSN",
        "CREDIT_CARD",
        "ORGANIZATION",  # Keep for context but don't anonymize
    ]

    def __init__(self):
        """
        Initialize Presidio analyzer and anonymizer engines.

        Sets up the engines and registers custom recognizers for
        energy contract-specific patterns.
        """
        try:
            logger.info("Initializing PIIDetector with Presidio engines")

            # Initialize Presidio engines
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()

            # Add custom CONTRACT_ID recognizer
            self._register_custom_recognizers()

            logger.info("PIIDetector initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PIIDetector: {str(e)}")
            raise PIIDetectionError(f"Initialization failed: {str(e)}") from e

    def _register_custom_recognizers(self):
        """
        Register custom recognizers for energy contract-specific patterns.

        Adds recognizers for:
        - CONTRACT_ID: Pattern PPA-YYYY-NNNNNN (e.g., PPA-2024-001234)
        """
        # CONTRACT_ID pattern: PPA-YYYY-NNNNNN
        contract_id_pattern = Pattern(
            name="contract_id_pattern",
            regex=r'PPA-\d{4}-\d{6}',
            score=0.9  # High confidence for exact pattern match
        )

        contract_id_recognizer = PatternRecognizer(
            supported_entity="CONTRACT_ID",
            patterns=[contract_id_pattern]
        )

        # Register the custom recognizer
        self.analyzer.registry.add_recognizer(contract_id_recognizer)

        logger.info("Registered custom CONTRACT_ID recognizer")

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

            # Add CONTRACT_ID to supported entities
            entities_to_detect = self.SUPPORTED_ENTITIES + ["CONTRACT_ID"]

            # Run Presidio analyzer
            results: List[RecognizerResult] = self.analyzer.analyze(
                text=text,
                language='en',
                entities=entities_to_detect
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

            # Filter out ORGANIZATION entities (keep for context)
            entities_to_anonymize = [
                e for e in entities if e.entity_type != "ORGANIZATION"
            ]

            if not entities_to_anonymize:
                logger.info("All entities are ORGANIZATION type, keeping text unchanged")
                return AnonymizedResult(
                    anonymized_text=text,
                    pii_count=0,
                    entities_found=entities,
                    mapping={}
                )

            # Define anonymization operators
            operators = {
                "EMAIL_ADDRESS": OperatorConfig(
                    "replace", {"new_value": "<EMAIL_REDACTED>"}
                ),
                "PHONE_NUMBER": OperatorConfig(
                    "replace", {"new_value": "<PHONE_REDACTED>"}
                ),
                "PERSON": OperatorConfig(
                    "replace", {"new_value": "<NAME_REDACTED>"}
                ),
                "US_SSN": OperatorConfig("redact", {}),
                "CREDIT_CARD": OperatorConfig("redact", {}),
                "CONTRACT_ID": OperatorConfig(
                    "replace", {"new_value": "<CONTRACT_ID_REDACTED>"}
                ),
            }

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
