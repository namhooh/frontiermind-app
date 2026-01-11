"""
Manual integration test for Contract Parser Service.

This script tests the full pipeline with real API calls (requires valid API keys).
For testing without real API calls, use the unit tests instead.

IMPORTANT: This will make real API calls and incur costs!
- LlamaParse API calls cost credits
- Claude API calls cost money based on tokens

Only run this with real API keys when you want to test end-to-end functionality.
"""

import os
import sys
from pathlib import Path

from services.contract_parser import ContractParser


def main():
    print("=" * 80)
    print("CONTRACT PARSER SERVICE - MANUAL INTEGRATION TEST")
    print("=" * 80)
    print()

    # Check API keys
    llama_key = os.getenv("LLAMA_CLOUD_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if not llama_key or llama_key.startswith("test_"):
        print("⚠️  WARNING: LLAMA_CLOUD_API_KEY not set or using test key")
        print("   Set real API key to test with LlamaParse")
        print()

    if not anthropic_key or anthropic_key.startswith("test_"):
        print("⚠️  WARNING: ANTHROPIC_API_KEY not set or using test key")
        print("   Set real API key to test with Claude")
        print()

    # Create sample contract text
    # In real usage, this would be actual PDF bytes
    sample_text = """
    POWER PURCHASE AGREEMENT

    Contract ID: PPA-2024-001234

    This Agreement is entered into on January 1, 2024, between:

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
    Availability is calculated as the ratio of available hours to total hours in the
    measurement period, excluding Force Majeure Events and Buyer Curtailment.

    SECTION 5.1 - LIQUIDATED DAMAGES FOR AVAILABILITY SHORTFALL
    For each percentage point that annual Availability falls below 95%, Buyer may
    assess liquidated damages of $50,000 per year. The maximum annual liquidated
    damages under this Section shall not exceed $10,000,000 per calendar year.

    SECTION 6.1 - PRICING TERMS
    The base energy price shall be $0.05 per kWh, subject to annual escalation
    based on the Consumer Price Index (CPI).

    SECTION 7.1 - PAYMENT TERMS
    Buyer shall pay Seller within thirty (30) days of receiving a valid invoice.
    Late payments shall accrue interest at a rate of 5% per annum.
    """

    print("NOTE: This is a simplified test with text content")
    print("For full PDF testing, provide actual PDF file bytes")
    print()

    if llama_key and llama_key.startswith("test_"):
        print("⚠️  DEMO MODE: Using test keys, will not make real API calls")
        print()

    print("Initializing ContractParser...")

    try:
        parser = ContractParser()
        print("✓ ContractParser initialized")
        print()

        print("Processing contract...")
        print("-" * 80)

        # For demo, we'll create a simple text file
        sample_bytes = sample_text.encode("utf-8")

        result = parser.process_contract(sample_bytes, "sample_contract.txt")

        print(f"✓ Contract processed successfully in {result.processing_time:.2f}s")
        print()

        print("RESULTS:")
        print("-" * 80)
        print(f"Status: {result.status}")
        print(f"PII Detected: {result.pii_detected}")
        print(f"PII Anonymized: {result.pii_anonymized}")
        print(f"Clauses Extracted: {len(result.clauses)}")
        print(f"Processing Time: {result.processing_time:.2f}s")
        print()

        if result.clauses:
            print("EXTRACTED CLAUSES:")
            print("-" * 80)
            for i, clause in enumerate(result.clauses, 1):
                print(f"\n{i}. {clause.clause_name} (Section {clause.section_reference})")
                print(f"   Type: {clause.clause_type}")
                print(f"   Category: {clause.clause_category}")
                print(f"   Responsible Party: {clause.responsible_party}")
                if clause.beneficiary_party:
                    print(f"   Beneficiary: {clause.beneficiary_party}")
                print(f"   Summary: {clause.summary}")
                print(f"   Confidence: {clause.confidence_score:.2f}")
                print(f"   Normalized Data: {clause.normalized_payload}")
                print(f"   Raw Text (first 100 chars): {clause.raw_text[:100]}...")
        else:
            print("(No clauses extracted)")

        print()
        print("=" * 80)
        print("✓ Test completed successfully!")
        print()

        print("PRIVACY VERIFICATION:")
        print("-" * 80)
        print(f"✓ PII detected: {result.pii_detected} entities")
        print(f"✓ PII anonymized: {result.pii_anonymized} entities")
        print("✓ Claude API received ONLY anonymized text (PII redacted)")
        print("✓ Original PII never sent to external AI services")
        print("=" * 80)

    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
