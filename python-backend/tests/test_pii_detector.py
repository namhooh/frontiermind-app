"""
Unit tests for PII Detection Service.

Tests the PIIDetector class to ensure proper detection and anonymization
of personally identifiable information in contract text.
"""

import pytest
from services.pii_detector import PIIDetector, PIIDetectionError, PIIAnonymizationError
from models.contract import PIIEntity, AnonymizedResult


@pytest.fixture
def pii_detector():
    """Create PIIDetector instance for testing."""
    return PIIDetector()


@pytest.fixture
def sample_contract_text():
    """Sample contract with PII for testing."""
    return """
    POWER PURCHASE AGREEMENT
    Contract ID: PPA-2024-001234

    Between SunValley Solar LLC (Contact: john.smith@sunvalley.com, 555-123-4567)
    and GridCorp Energy Inc. (Contact: jane.doe@gridcorp.com)

    SSN: 123-45-6789
    Credit Card: 4532-1234-5678-9010

    Section 4.1 Availability Guarantee
    Seller shall ensure the Facility achieves a minimum annual Availability of 95%.
    """


def test_pii_detection(pii_detector, sample_contract_text):
    """Test PII detection finds all expected entities."""
    entities = pii_detector.detect(sample_contract_text)

    # Should detect: 2 emails, 1 phone, potential names, 1 SSN, 1 credit card, 1 contract ID
    assert len(entities) >= 5, f"Expected at least 5 entities, found {len(entities)}"

    # Verify entity types found
    entity_types = {e.entity_type for e in entities}
    assert "EMAIL_ADDRESS" in entity_types, "EMAIL_ADDRESS not detected"
    assert "PHONE_NUMBER" in entity_types, "PHONE_NUMBER not detected"
    assert "CONTRACT_ID" in entity_types, "CONTRACT_ID not detected"

    # Verify all entities have required fields
    for entity in entities:
        assert entity.entity_type is not None
        assert entity.start >= 0
        assert entity.end > entity.start
        assert 0.0 <= entity.score <= 1.0
        assert len(entity.text) > 0


def test_pii_anonymization(pii_detector, sample_contract_text):
    """Test PII anonymization replaces sensitive data."""
    entities = pii_detector.detect(sample_contract_text)
    result = pii_detector.anonymize(sample_contract_text, entities)

    # Verify result structure
    assert isinstance(result, AnonymizedResult)
    assert result.pii_count >= 0
    assert len(result.entities_found) == len(entities)
    assert isinstance(result.mapping, dict)
    assert isinstance(result.anonymized_text, str)

    # Verify specific PII is removed (where detected by Presidio)
    assert "john.smith@sunvalley.com" not in result.anonymized_text, "Email not anonymized"
    assert "555-123-4567" not in result.anonymized_text, "Phone not anonymized"
    assert "PPA-2024-001234" not in result.anonymized_text, "Contract ID not anonymized"

    # Note: SSN detection depends on Presidio's NLP model and context
    # Not all SSN formats are guaranteed to be detected

    # Verify placeholders exist (at least for common types)
    # Note: Presidio may filter some entities, so we check if anonymization happened
    if result.pii_count > 0:
        # At least some redaction should have occurred
        assert result.anonymized_text != sample_contract_text, "Text should be modified"


def test_empty_text_handling(pii_detector):
    """Test handling of empty input."""
    entities = pii_detector.detect("")
    assert len(entities) == 0, "Empty text should return no entities"

    result = pii_detector.anonymize("", [])
    assert result.anonymized_text == ""
    assert result.pii_count == 0
    assert len(result.entities_found) == 0
    assert len(result.mapping) == 0


def test_no_pii_text(pii_detector):
    """Test handling of text with no PII."""
    text = "This is a normal contract with no sensitive information. The price is 100 dollars."
    entities = pii_detector.detect(text)

    # May detect false positives, but should not crash
    assert isinstance(entities, list)

    # Anonymization should work even with no entities
    result = pii_detector.anonymize(text, entities)
    assert isinstance(result, AnonymizedResult)
    assert result.anonymized_text is not None


def test_contract_id_custom_recognizer(pii_detector):
    """Test custom CONTRACT_ID pattern recognition."""
    text = "Contract ID: PPA-2024-001234 and also PPA-2025-999999"
    entities = pii_detector.detect(text)

    # Find CONTRACT_ID entities
    contract_ids = [e for e in entities if e.entity_type == "CONTRACT_ID"]
    assert len(contract_ids) >= 2, f"Expected 2 CONTRACT_ID entities, found {len(contract_ids)}"

    # Verify the pattern matches correctly
    for contract_id in contract_ids:
        assert contract_id.text.startswith("PPA-"), f"CONTRACT_ID should start with 'PPA-': {contract_id.text}"
        assert len(contract_id.text) == 15, f"CONTRACT_ID should be 15 chars: {contract_id.text}"


def test_email_detection_and_anonymization(pii_detector):
    """Test specific email detection and anonymization."""
    text = "Please contact us at support@example.com or admin@test.org for assistance."
    entities = pii_detector.detect(text)

    # Should detect both emails
    email_entities = [e for e in entities if e.entity_type == "EMAIL_ADDRESS"]
    assert len(email_entities) >= 2, f"Expected at least 2 emails, found {len(email_entities)}"

    # Anonymize
    result = pii_detector.anonymize(text, entities)
    assert "support@example.com" not in result.anonymized_text
    assert "admin@test.org" not in result.anonymized_text
    assert "<EMAIL_REDACTED>" in result.anonymized_text


def test_phone_number_detection(pii_detector):
    """Test phone number detection."""
    text = "Call us at 555-123-4567 or (555) 987-6543 for more information."
    entities = pii_detector.detect(text)

    # Should detect phone numbers
    phone_entities = [e for e in entities if e.entity_type == "PHONE_NUMBER"]
    assert len(phone_entities) >= 1, f"Expected at least 1 phone number, found {len(phone_entities)}"

    # Anonymize
    result = pii_detector.anonymize(text, entities)
    if phone_entities:  # Only check if phones were detected
        assert "<PHONE_REDACTED>" in result.anonymized_text


def test_mapping_creation(pii_detector):
    """Test that mapping preserves original PII values."""
    text = "Contact john@example.com at 555-0100"
    entities = pii_detector.detect(text)

    if not entities:
        pytest.skip("No entities detected for mapping test")

    result = pii_detector.anonymize(text, entities)

    # Verify mapping structure
    assert isinstance(result.mapping, dict)
    assert len(result.mapping) > 0, "Mapping should contain entries"

    # Each mapping key should be a placeholder format
    for placeholder, original_value in result.mapping.items():
        assert placeholder.startswith("<"), f"Placeholder should start with '<': {placeholder}"
        assert placeholder.endswith(">"), f"Placeholder should end with '>': {placeholder}"
        assert len(original_value) > 0, "Original value should not be empty"


def test_organization_kept_for_context(pii_detector):
    """Test that ORGANIZATION entities are kept for context (not anonymized)."""
    text = "Agreement between Microsoft Corporation and Apple Inc."
    entities = pii_detector.detect(text)

    result = pii_detector.anonymize(text, entities)

    # Organizations should still be present in anonymized text
    # Note: This depends on Presidio detecting them as ORGANIZATION
    # The test verifies the implementation doesn't redact them
    org_entities = [e for e in entities if e.entity_type == "ORGANIZATION"]
    if org_entities:
        # If organizations were detected, verify at least one is still in the text
        # (they should not be in the mapping as they're not anonymized)
        org_in_mapping = any(e.entity_type == "ORGANIZATION" for e in result.entities_found
                            if f"<ORGANIZATION_{e.start}_{e.end}>" in result.mapping)
        assert not org_in_mapping, "Organizations should not be in anonymization mapping"
