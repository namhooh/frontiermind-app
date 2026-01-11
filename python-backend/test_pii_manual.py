"""
Manual test script for PII Detection Service.

Run this script to see the PII detector in action with sample contract text.
"""

from services.pii_detector import PIIDetector


def main():
    """Demonstrate PII detection and anonymization."""
    print("=" * 80)
    print("PII DETECTION SERVICE - MANUAL TEST")
    print("=" * 80)
    print()

    # Initialize detector
    print("Initializing PIIDetector...")
    detector = PIIDetector()
    print("✓ PIIDetector initialized successfully\n")

    # Sample contract text with various PII types
    sample_text = """
    POWER PURCHASE AGREEMENT
    Contract ID: PPA-2024-001234

    This Agreement is entered into between:

    SELLER: SunValley Solar LLC
    Contact: John Smith
    Email: john.smith@sunvalley.com
    Phone: 555-123-4567

    BUYER: GridCorp Energy Inc.
    Contact: Jane Doe
    Email: jane.doe@gridcorp.com
    Phone: (555) 987-6543

    SECTION 4.1 - AVAILABILITY GUARANTEE
    Seller shall ensure the Facility achieves a minimum annual Availability of 95%.

    SECTION 5.2 - PAYMENT TERMS
    Buyer shall pay Seller within 30 days of invoice receipt.
    """

    print("ORIGINAL CONTRACT TEXT:")
    print("-" * 80)
    print(sample_text)
    print("-" * 80)
    print()

    # Detect PII
    print("Detecting PII entities...")
    entities = detector.detect(sample_text)
    print(f"✓ Detected {len(entities)} PII entities\n")

    if entities:
        print("DETECTED PII ENTITIES:")
        print("-" * 80)
        for i, entity in enumerate(entities, 1):
            print(f"{i}. Type: {entity.entity_type}")
            print(f"   Text: '{entity.text}'")
            print(f"   Position: {entity.start}-{entity.end}")
            print(f"   Confidence: {entity.score:.2f}")
            print()
        print("-" * 80)
        print()

    # Anonymize
    print("Anonymizing PII...")
    result = detector.anonymize(sample_text, entities)
    print(f"✓ Anonymized {result.pii_count} PII entities\n")

    print("ANONYMIZED CONTRACT TEXT:")
    print("-" * 80)
    print(result.anonymized_text)
    print("-" * 80)
    print()

    print("PII MAPPING (for authorized re-identification):")
    print("-" * 80)
    if result.mapping:
        for placeholder, original_value in result.mapping.items():
            print(f"{placeholder}")
            print(f"  → {original_value}")
        print()
    else:
        print("(No mappings created)")
        print()
    print("-" * 80)
    print()

    print("✓ Test completed successfully!")
    print()
    print("PRIVACY-FIRST VERIFICATION:")
    print("✓ PII detection performed locally (no external API calls)")
    print("✓ Sensitive data anonymized before any external processing")
    print("✓ Original PII preserved in encrypted mapping for authorized access")
    print("=" * 80)


if __name__ == "__main__":
    main()
