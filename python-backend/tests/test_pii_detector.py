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

    # Should detect: 2 emails, 1+ phones, 1 contract ID (SSN/credit card detection varies by Presidio version)
    assert len(entities) >= 3, f"Expected at least 3 entities, found {len(entities)}"

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


def test_minimum_confidence_threshold(pii_detector):
    """Test that low-confidence detections are filtered out."""
    text = "The system operates at full capacity during peak hours."
    entities = pii_detector.detect(text)

    # All returned entities should have score >= 0.4
    for entity in entities:
        assert entity.score >= 0.4, (
            f"Entity '{entity.text}' ({entity.entity_type}) has score {entity.score} < 0.4"
        )


# --- Regression tests for reported false positive issues ---


def test_regression_address_not_garbled(pii_detector):
    """Regression: address text should not produce garbled output.

    Previously, overlapping CAPACITY/PROJECT_NAME/PRICE recognizers would
    match parts of address text and produce garbled anonymized output.
    Now only the street-level portion is redacted; city/state are kept.
    """
    text = "The facility is located at 123 Main Street, Springfield, IL 62701."
    entities = pii_detector.detect(text)
    result = pii_detector.anonymize(text, entities)

    # The output should be coherent — no garbled fragments
    # Check that the sentence structure is preserved (starts correctly, ends correctly)
    assert result.anonymized_text.startswith("The facility is located at")
    # Should not contain fragments of redaction tags jammed together
    assert "<CAPACITY_REDACTED>" not in result.anonymized_text
    assert "<PRICE_REDACTED>" not in result.anonymized_text
    assert "<PROJECT_NAME_REDACTED>" not in result.anonymized_text
    # City and state should be preserved for geographic context
    assert "Springfield" in result.anonymized_text, "City name should not be redacted"


def test_regression_allocation_target_not_redacted(pii_detector):
    """Regression: 'Allocation Target' and 'Site' should not be redacted.

    The PROJECT_NAME recognizer's broad regex previously matched terms like
    'Site: Allocation Target' as a project name.
    """
    text = "The Allocation Target for Site A is 500 MWh per year."
    entities = pii_detector.detect(text)
    result = pii_detector.anonymize(text, entities)

    assert "Allocation Target" in result.anonymized_text, (
        "Business term 'Allocation Target' should not be redacted"
    )
    assert "<PROJECT_NAME_REDACTED>" not in result.anonymized_text


def test_regression_technical_site_survey_not_redacted(pii_detector):
    """Regression: 'Technical Site Survey' should not be redacted.

    The PROJECT_NAME recognizer previously matched 'Site: Technical Site Survey'
    or similar patterns as a project name.
    """
    text = "A Technical Site Survey shall be completed prior to Commercial Operation Date."
    entities = pii_detector.detect(text)
    result = pii_detector.anonymize(text, entities)

    assert "Technical Site Survey" in result.anonymized_text, (
        "Business term 'Technical Site Survey' should not be redacted"
    )
    assert "<PROJECT_NAME_REDACTED>" not in result.anonymized_text


def test_business_data_not_redacted(pii_detector):
    """Test that energy business data (capacity, price) is NOT redacted."""
    text = (
        "The SunValley Solar Farm has a capacity of 150 MW and sells power "
        "at $45/MWh under contract PPA-2024-001234."
    )
    entities = pii_detector.detect(text)
    result = pii_detector.anonymize(text, entities)

    # Business data should remain in the output
    assert "150 MW" in result.anonymized_text, "Capacity should not be redacted"
    assert "$45/MWh" in result.anonymized_text, "Price should not be redacted"
    # Contract ID is still a unique identifier and should be redacted
    assert "PPA-2024-001234" not in result.anonymized_text, "Contract ID should be redacted"


def test_street_address_detection(pii_detector):
    """Test that STREET_ADDRESS entities are detected for street-level PII.

    Only street-level details (house number, street name, PO box) should be
    redacted. City and country names are kept for context.
    """
    text = "John Smith resides at 742 Evergreen Terrace, Springfield, Illinois 62704."
    entities = pii_detector.detect(text)

    # Should detect STREET_ADDRESS via custom regex recognizer
    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, f"Expected at least 1 STREET_ADDRESS, found {len(street_entities)}"

    result = pii_detector.anonymize(text, entities)
    assert "<ADDRESS_REDACTED>" in result.anonymized_text

    # City and state should NOT be redacted — they provide geographic context
    assert "Springfield" in result.anonymized_text, "City name should not be redacted"
    assert "Illinois" in result.anonymized_text, "State name should not be redacted"


def test_po_box_detection(pii_detector):
    """Test that PO Box addresses are detected as STREET_ADDRESS."""
    text = "Send correspondence to P.O. Box 4521 or PO Box 100."
    entities = pii_detector.detect(text)

    po_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(po_entities) >= 2, f"Expected at least 2 PO Box matches, found {len(po_entities)}"

    result = pii_detector.anonymize(text, entities)
    assert "P.O. Box 4521" not in result.anonymized_text, "PO Box should be redacted"
    assert "PO Box 100" not in result.anonymized_text, "PO Box should be redacted"


def test_city_country_not_redacted(pii_detector):
    """Test that city and country names are NOT redacted."""
    text = "The solar farm is located in Austin, Texas, United States."
    entities = pii_detector.detect(text)
    result = pii_detector.anonymize(text, entities)

    assert "Austin" in result.anonymized_text, "City name should not be redacted"
    assert "Texas" in result.anonymized_text, "State name should not be redacted"
    assert "United States" in result.anonymized_text, "Country name should not be redacted"


# --- Person-entity denylist tests ---


def test_managed_site_not_redacted_as_person(pii_detector):
    """'a Managed Site' must not be flagged as PERSON."""
    text = "The Seller shall operate a Managed Site in accordance with the agreement."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert "Managed Site" not in person_texts, (
        f"'Managed Site' was incorrectly flagged as PERSON: {person_texts}"
    )


def test_sierra_leone_not_redacted_as_person(pii_detector):
    """Country name 'Sierra Leone' must not be flagged as PERSON."""
    text = "The project is located in Sierra Leone, West Africa."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert "Sierra Leone" not in person_texts, (
        f"'Sierra Leone' was incorrectly flagged as PERSON: {person_texts}"
    )


def test_freetown_not_redacted_as_person(pii_detector):
    """City name 'Freetown' must not be flagged as PERSON."""
    text = "The office is in Freetown, the capital of Sierra Leone."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert "Freetown" not in person_texts, (
        f"'Freetown' was incorrectly flagged as PERSON: {person_texts}"
    )


# --- Overlap resolution tests ---


def test_overlapping_entities_resolved(pii_detector):
    """No two returned entities should have overlapping character spans."""
    text = (
        "Contact John Smith at john.smith@sunvalley.com, "
        "located at 123 Main Street, Springfield, IL."
    )
    entities = pii_detector.detect(text)

    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            overlaps = a.start < b.end and b.start < a.end
            assert not overlaps, (
                f"Overlapping entities: [{a.entity_type}] "
                f"({a.start}-{a.end} '{a.text}') and [{b.entity_type}] "
                f"({b.start}-{b.end} '{b.text}')"
            )


def test_whitespace_only_entities_filtered(pii_detector):
    """Entities whose matched text is whitespace-only must be discarded."""
    entities = pii_detector.detect("   \n\t  Some normal text here.")

    for entity in entities:
        assert entity.text.strip(), (
            f"Whitespace-only entity returned: [{entity.entity_type}] "
            f"({entity.start}-{entity.end})"
        )


# --- No-prefix street address tests ---


def test_no_prefix_address_detected(pii_detector):
    """'No.7 Wilkinson Road' should be detected as STREET_ADDRESS."""
    text = "The site is at No.7 Wilkinson Road, Freetown."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for 'No.7 Wilkinson Road', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )
    matched_texts = " ".join(e.text for e in street_entities)
    assert "Wilkinson Road" in matched_texts


def test_no_space_prefix_address_detected(pii_detector):
    """'No 5 Siaka Stevens Street' should be detected as STREET_ADDRESS."""
    text = "Send mail to No 5 Siaka Stevens Street, Freetown."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for 'No 5 Siaka Stevens Street', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )
    matched_texts = " ".join(e.text for e in street_entities)
    assert "Siaka Stevens Street" in matched_texts


def test_standard_address_still_detected(pii_detector):
    """Regression: '123 Main Street' must still be detected after regex update."""
    text = "The office is at 123 Main Street."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for '123 Main Street', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


def test_denylist_does_not_affect_real_names(pii_detector):
    """Real person names must still be detected despite denylist."""
    text = "The agreement was signed by John Smith and Jane Doe."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    assert len(person_entities) >= 1, (
        f"Expected at least 1 PERSON entity for real names, got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


# --- Alphanumeric house number tests ---


def test_alphanumeric_house_number_detected(pii_detector):
    """'No. 37A Wilkinson Road' should be detected as STREET_ADDRESS."""
    text = "The office is at No. 37A Wilkinson Road, Freetown."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for 'No. 37A Wilkinson Road', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )
    matched_texts = " ".join(e.text for e in street_entities)
    assert "37A" in matched_texts or "Wilkinson Road" in matched_texts


def test_alphanumeric_house_number_no_prefix(pii_detector):
    """'42B Oak Avenue' should be detected as STREET_ADDRESS."""
    text = "Deliveries go to 42B Oak Avenue."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for '42B Oak Avenue', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


def test_pure_numeric_address_still_works(pii_detector):
    """Regression: '456 Elm Drive' must still be detected after regex update."""
    text = "The warehouse is at 456 Elm Drive."
    entities = pii_detector.detect(text)

    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS for '456 Elm Drive', got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


# --- Person deny pattern tests ---


def test_commercial_operation_date_not_person(pii_detector):
    """'Commercial Operation Date' must not be flagged as PERSON."""
    text = "The Commercial Operation Date shall be no later than December 31, 2025."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Commercial Operation Date" not in pt, (
            f"'Commercial Operation Date' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_site_acceptance_test_not_person(pii_detector):
    """'Site Acceptance Test' must not be flagged as PERSON."""
    text = "The Site Acceptance Test must be completed within 30 days."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Site Acceptance Test" not in pt, (
            f"'Site Acceptance Test' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_effective_date_not_person(pii_detector):
    """'Effective Date' must not be flagged as PERSON."""
    text = "This Agreement shall commence on the Effective Date."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Effective Date" not in pt, (
            f"'Effective Date' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_force_majeure_event_not_person(pii_detector):
    """'Force Majeure Event' must not be flagged as PERSON."""
    text = "In the event of a Force Majeure Event, the obligations shall be suspended."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Force Majeure Event" not in pt, (
            f"'Force Majeure Event' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_guaranteed_capacity_not_person(pii_detector):
    """'Guaranteed Capacity' must not be flagged as PERSON."""
    text = "The Guaranteed Capacity of the facility is 150 MW."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Guaranteed Capacity" not in pt, (
            f"'Guaranteed Capacity' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_all_caps_section_header_not_person(pii_detector):
    """ALL-CAPS section headers like 'DEFINITIONS' must not be flagged as PERSON."""
    text = "DEFINITIONS\nThe following terms shall have the meanings set forth below."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "DEFINITIONS" not in pt, (
            f"'DEFINITIONS' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_deny_patterns_do_not_filter_real_names(pii_detector):
    """Real names like 'John Smith' and 'Sarah Johnson' must still be detected."""
    text = "The contract was signed by John Smith and Sarah Johnson."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    assert len(person_entities) >= 1, (
        f"Expected at least 1 PERSON entity for real names, got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


def test_deny_patterns_with_of_phrase(pii_detector):
    """'Certificate of Acceptance' must not be flagged as PERSON."""
    text = "The Certificate of Acceptance shall be issued upon completion."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Certificate of Acceptance" not in pt, (
            f"'Certificate of Acceptance' was incorrectly flagged as PERSON: {person_texts}"
        )


# --- Definition-term extraction tests ---


def test_definition_terms_extracted(pii_detector):
    """Terms defined in a DEFINITIONS section should be extracted."""
    text = (
        'ARTICLE I: DEFINITIONS\n'
        '"Withdrawal Notice" means a written notice issued by the Buyer.\n'
        '"Disputed Amount" has the meaning set forth in Section 5.2.\n'
        '"Gang" refers to a group of workers assigned to a task.\n'
        '\nARTICLE II: OBLIGATIONS\n'
        'The Seller shall comply with all obligations.'
    )
    terms = pii_detector._extract_definition_terms(text)
    assert "Withdrawal Notice" in terms
    assert "Disputed Amount" in terms
    assert "Gang" in terms


def test_defined_term_not_redacted_as_person(pii_detector):
    """A term defined in DEFINITIONS must not be flagged as PERSON."""
    text = (
        'DEFINITIONS\n'
        '"Withdrawal Notice" means a written notice from the Buyer.\n'
        '\nOBLIGATIONS\n'
        'The Seller shall issue a Withdrawal Notice within 30 days.'
    )
    entities = pii_detector.detect(text)
    person_texts = [e.text for e in entities if e.entity_type == "PERSON"]
    for pt in person_texts:
        assert "Withdrawal Notice" not in pt, (
            f"Defined term 'Withdrawal Notice' was flagged as PERSON: {person_texts}"
        )


def test_defined_term_disputed_amount_not_person(pii_detector):
    """'Disputed Amount' defined in DEFINITIONS must not be flagged as PERSON."""
    text = (
        'DEFINITIONS\n'
        '"Disputed Amount" means any amount contested by either Party.\n'
        '\nPAYMENT TERMS\n'
        'The Disputed Amount shall be resolved within 60 days.'
    )
    entities = pii_detector.detect(text)
    person_texts = [e.text for e in entities if e.entity_type == "PERSON"]
    for pt in person_texts:
        assert "Disputed Amount" not in pt, (
            f"Defined term 'Disputed Amount' was flagged as PERSON: {person_texts}"
        )


def test_definition_extraction_no_definitions_section(pii_detector):
    """Text without a DEFINITIONS section should return empty set, no crash."""
    text = "This contract has no definitions section. The Seller shall comply."
    terms = pii_detector._extract_definition_terms(text)
    assert terms == set()


# --- Section-restricted redaction tests ---


def test_person_in_notices_section_redacted(pii_detector):
    """A real person name in a NOTICES section near a context trigger should be redacted."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'If to Buyer:\n'
        'All notices shall be sent to John Smith at the following address.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("John Smith" in pt for pt in person_texts), (
        f"Expected 'John Smith' in NOTICES to be detected as PERSON, got: {person_texts}"
    )


def test_person_in_body_section_not_redacted(pii_detector):
    """Contract terms in the operative body should not be flagged as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The Seller shall issue a Withdrawal Notice within 30 days.\n'
        '\nNOTICES\n'
        'All notices shall be sent to the address below.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Withdrawal Notice" not in pt, (
            f"'Withdrawal Notice' in body was flagged as PERSON: {person_texts}"
        )


def test_address_in_notices_section_redacted(pii_detector):
    """A street address in a NOTICES section should be redacted."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'Send all correspondence to 123 Main Street, Springfield, IL 62701.\n'
    )
    entities = pii_detector.detect(text)
    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    assert len(street_entities) >= 1, (
        f"Expected STREET_ADDRESS in NOTICES section, got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


def test_address_in_body_section_not_redacted(pii_detector):
    """A street address in the operative body should be suppressed."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility is located at 456 Elm Drive, Springfield, IL.\n'
        '\nNOTICES\n'
        'All notices shall be sent to the address below.\n'
    )
    entities = pii_detector.detect(text)
    street_entities = [e for e in entities if e.entity_type == "STREET_ADDRESS"]
    # The address is in the body (TERMS AND CONDITIONS), not in NOTICES,
    # so it should be suppressed by section restriction
    street_texts = [e.text for e in street_entities]
    assert not any("456 Elm Drive" in t for t in street_texts), (
        f"Street address in body section should be suppressed: {street_texts}"
    )


def test_email_in_body_still_redacted(pii_detector):
    """Emails in the operative body should still be redacted (not section-restricted)."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'Contact support@example.com for technical issues.\n'
        '\nNOTICES\n'
        'All notices shall be sent to the address below.\n'
    )
    entities = pii_detector.detect(text)
    email_entities = [e for e in entities if e.entity_type == "EMAIL_ADDRESS"]
    assert len(email_entities) >= 1, (
        f"Expected EMAIL_ADDRESS in body to still be detected, got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


def test_phone_in_body_still_redacted(pii_detector):
    """Phone numbers in the operative body should still be redacted (not section-restricted)."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'Call 555-123-4567 for emergencies.\n'
        '\nNOTICES\n'
        'All notices shall be sent to the address below.\n'
    )
    entities = pii_detector.detect(text)
    phone_entities = [e for e in entities if e.entity_type == "PHONE_NUMBER"]
    assert len(phone_entities) >= 1, (
        f"Expected PHONE_NUMBER in body to still be detected, got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


# --- Safety / regression tests ---


def test_real_name_in_preamble_still_redacted(pii_detector):
    """A real person name in RECITALS should still be redacted."""
    text = (
        'RECITALS\n'
        'WHEREAS, John Smith ("the Seller") and Jane Doe ("the Buyer") agree.\n'
        '\nARTICLE I: DEFINITIONS\n'
        'The following terms apply.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("John Smith" in pt or "Jane Doe" in pt for pt in person_texts), (
        f"Expected real names in RECITALS to be detected as PERSON, got: {person_texts}"
    )


def test_section_restriction_with_no_sections_found(pii_detector):
    """When no PII sections are found, fall back to redacting everything (safe default)."""
    text = "The agreement was signed by John Smith and Jane Doe."
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    assert len(person_entities) >= 1, (
        f"Expected PERSON entities when no PII sections found (safe default), got: "
        f"{[(e.entity_type, e.text) for e in entities]}"
    )


# --- Pre-heading text (preamble) tests ---


def test_person_in_preamble_before_first_heading_redacted(pii_detector):
    """A person name before any section heading should be redacted.

    Contract preambles (text before the first heading) often contain party
    names and addresses. The pre-heading range (0, first_heading_start) must
    be treated as a PII section so NER entities there are not suppressed.
    """
    text = (
        'POWER PURCHASE AGREEMENT\n'
        'Between John Smith and SunValley Solar LLC\n'
        '\nARTICLE I: DEFINITIONS\n'
        'The following terms apply.\n'
        '\nARTICLE II: OBLIGATIONS\n'
        'The Seller shall comply.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("John Smith" in pt for pt in person_texts), (
        f"Expected 'John Smith' in preamble to be detected as PERSON, got: {person_texts}"
    )


# --- Curly-quote definition term tests ---


def test_definition_terms_with_curly_quotes(pii_detector):
    """Curly-quoted defined terms (\u201c...\u201d) should be extracted."""
    text = (
        'ARTICLE I: DEFINITIONS\n'
        '\u201cWithdrawal Notice\u201d means a written notice issued by the Buyer.\n'
        '\u201cDisputed Amount\u201d has the meaning set forth in Section 5.2.\n'
        '\nARTICLE II: OBLIGATIONS\n'
        'The Seller shall comply.\n'
    )
    terms = pii_detector._extract_definition_terms(text)
    assert "Withdrawal Notice" in terms, (
        f"Expected 'Withdrawal Notice' from curly-quote pattern, got: {terms}"
    )
    assert "Disputed Amount" in terms, (
        f"Expected 'Disputed Amount' from curly-quote pattern, got: {terms}"
    )


# --- Partial definition term matching tests ---


def test_partial_definition_term_not_person(pii_detector):
    """If 'Withdrawal Notice' is defined, partial match 'Withdrawal' should not be PERSON.

    spaCy may detect only a substring of a defined term. The substring containment
    check should exclude it from PERSON results.
    """
    text = (
        'DEFINITIONS\n'
        '"Withdrawal Notice" means a written notice from the Buyer.\n'
        '"Disputed Amount" has the meaning set forth in Section 5.2.\n'
        '\nOBLIGATIONS\n'
        'The Seller shall issue a Withdrawal within 30 days.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Withdrawal" not in pt, (
            f"Partial defined term 'Withdrawal' was flagged as PERSON: {person_texts}"
        )


# --- DEFINITIONS section real name tests ---


def test_definitions_section_real_name_not_redacted(pii_detector):
    """A real person name inside DEFINITIONS section should NOT be redacted.

    DEFINITIONS is no longer a PII section — definition terms are handled by
    the denylist extraction.  Having DEFINITIONS as a PII section creates
    false positives for contract terms.

    NOTE: The contract must contain at least one PII section (e.g., NOTICES)
    so that section restriction activates. Without any PII sections, the safe
    default (redact everything) applies.
    """
    text = (
        'ARTICLE I: DEFINITIONS\n'
        '"Project Manager" means John Smith or his designated representative.\n'
        '"Facility" means the solar generation facility.\n'
        '\nARTICLE II: OBLIGATIONS\n'
        'The Seller shall comply.\n'
        '\nNOTICES\n'
        'All notices shall be sent to the address below.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert not any("John Smith" in pt for pt in person_texts), (
        f"'John Smith' in DEFINITIONS should NOT be detected (not a PII section), got: {person_texts}"
    )


# --- Context trigger tests ---


def test_contract_term_in_notices_not_redacted(pii_detector):
    """Contract terms in NOTICES without a nearby context trigger should NOT be flagged as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'The Site Acceptance Test schedule is attached.\n'
        'The Project Site location is described in Exhibit A.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Site Acceptance Test" not in pt, (
            f"'Site Acceptance Test' in NOTICES (no trigger) was flagged as PERSON: {person_texts}"
        )
        assert "Project Site" not in pt, (
            f"'Project Site' in NOTICES (no trigger) was flagged as PERSON: {person_texts}"
        )


def test_real_name_near_attention_trigger_redacted(pii_detector):
    """A real name near 'Attention:' in NOTICES should be detected as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'Attention: John Smith\n'
        '123 Main Street, Springfield, IL 62701\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("John Smith" in pt for pt in person_texts), (
        f"Expected 'John Smith' near 'Attention:' to be detected as PERSON, got: {person_texts}"
    )


def test_real_name_near_name_colon_trigger_redacted(pii_detector):
    """A real name near 'Name:' should be detected as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'Name: Jane Doe\n'
        'Email: jane@example.com\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("Jane Doe" in pt for pt in person_texts), (
        f"Expected 'Jane Doe' near 'Name:' to be detected as PERSON, got: {person_texts}"
    )


def test_real_name_near_by_in_signature_redacted(pii_detector):
    """A real name near 'By:' in a signature block should be detected as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nIN WITNESS WHEREOF\n'
        'By: Michael Johnson\n'
        'Title: Vice President\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("Michael Johnson" in pt for pt in person_texts), (
        f"Expected 'Michael Johnson' near 'By:' to be detected as PERSON, got: {person_texts}"
    )


def test_real_name_with_title_prefix_redacted(pii_detector):
    """A name with a title prefix (Dr.) in a SCHEDULE should be detected as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nSCHEDULE A\n'
        'Technical advisor: Dr. Robert Chen\n'
        'Report frequency: monthly\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("Robert Chen" in pt for pt in person_texts), (
        f"Expected 'Dr. Robert Chen' in SCHEDULE to be detected as PERSON, got: {person_texts}"
    )


def test_name_in_preamble_near_between_redacted(pii_detector):
    """A real name near 'between' in the preamble should be detected as PERSON."""
    text = (
        'POWER PURCHASE AGREEMENT\n'
        'This Agreement is entered into between John Smith and SunValley Solar LLC.\n'
        '\nARTICLE I: DEFINITIONS\n'
        'The following terms apply.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("John Smith" in pt for pt in person_texts), (
        f"Expected 'John Smith' near 'between' in preamble to be detected as PERSON, got: {person_texts}"
    )


def test_if_to_seller_trigger_works(pii_detector):
    """A real name near 'If to Seller:' should be detected as PERSON."""
    text = (
        'ARTICLE 10: TERMS AND CONDITIONS\n'
        'The facility shall operate continuously.\n'
        '\nNOTICES\n'
        'If to Seller:\n'
        'Sarah Williams\n'
        'SunValley Solar LLC\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    assert any("Sarah Williams" in pt for pt in person_texts), (
        f"Expected 'Sarah Williams' near 'If to Seller:' to be detected as PERSON, got: {person_texts}"
    )


# --- Site-associated term tests ---


def test_project_site_not_redacted_as_person(pii_detector):
    """'Project Site' must not be flagged as PERSON."""
    text = "The Project Site is located in the northern region of the country."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Project Site" not in pt, (
            f"'Project Site' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_generation_site_not_redacted_as_person(pii_detector):
    """'Generation Site' must not be flagged as PERSON."""
    text = "The Generation Site shall be maintained according to the specifications."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Generation Site" not in pt, (
            f"'Generation Site' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_facility_site_not_redacted_as_person(pii_detector):
    """'Facility Site' must not be flagged as PERSON."""
    text = "Access to the Facility Site requires prior authorization."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Facility Site" not in pt, (
            f"'Facility Site' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_construction_site_not_redacted_as_person(pii_detector):
    """'Construction Site' must not be flagged as PERSON."""
    text = "The Construction Site shall be cleared by the Seller before handover."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Construction Site" not in pt, (
            f"'Construction Site' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_interconnection_site_not_redacted_as_person(pii_detector):
    """'Interconnection Site' must not be flagged as PERSON."""
    text = "The Interconnection Site is located adjacent to the substation."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Interconnection Site" not in pt, (
            f"'Interconnection Site' was incorrectly flagged as PERSON: {person_texts}"
        )


def test_deny_pattern_catches_novel_site_term(pii_detector):
    """A novel 'X Site' term not in the static denylist should still be caught by deny patterns."""
    text = "The Monitoring Site is equipped with advanced sensors."
    entities = pii_detector.detect(text)

    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Monitoring Site" not in pt, (
            f"'Monitoring Site' (not in static denylist) was flagged as PERSON: {person_texts}"
        )


def test_definition_terms_exclude_site_terms(pii_detector):
    """Defined site terms in DEFINITIONS should be excluded from PERSON detection."""
    text = (
        'DEFINITIONS\n'
        '"Project Site" means the location where the Facility is situated.\n'
        '"Delivery Site" means the point of interconnection.\n'
        '\nOBLIGATIONS\n'
        'The Seller shall maintain the Project Site and Delivery Site.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Project Site" not in pt, (
            f"Defined term 'Project Site' was flagged as PERSON: {person_texts}"
        )
        assert "Delivery Site" not in pt, (
            f"Defined term 'Delivery Site' was flagged as PERSON: {person_texts}"
        )


def test_definitions_section_terms_not_redacted(pii_detector):
    """Contract terms in DEFINITIONS should NOT be flagged as PERSON.

    DEFINITIONS is no longer a PII section, so NER entities there are suppressed.
    """
    text = (
        'ARTICLE I: DEFINITIONS\n'
        '"Project Site" means the location where the Facility is situated.\n'
        '"Generation Site" means the area designated for power generation.\n'
        '\nARTICLE II: OBLIGATIONS\n'
        'The Seller shall comply.\n'
    )
    entities = pii_detector.detect(text)
    person_entities = [e for e in entities if e.entity_type == "PERSON"]
    person_texts = [e.text for e in person_entities]
    for pt in person_texts:
        assert "Project Site" not in pt, (
            f"'Project Site' in DEFINITIONS was flagged as PERSON: {person_texts}"
        )
        assert "Generation Site" not in pt, (
            f"'Generation Site' in DEFINITIONS was flagged as PERSON: {person_texts}"
        )
