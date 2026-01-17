"""
End-to-End Test for Contract Processing Pipeline

This script tests the complete workflow:
1. PDF upload
2. LlamaParse document parsing (OCR)
3. Presidio PII detection and anonymization
4. Claude clause extraction
5. Database storage

Usage:
    python test_end_to_end.py <path_to_pdf_file>

Example:
    python test_end_to_end.py tests/fixtures/sample_contract.pdf
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from services.contract_parser import ContractParser
from db.database import init_connection_pool, health_check
from db.contract_repository import ContractRepository


def verify_environment():
    """Verify all required environment variables are set."""
    print("\n" + "="*60)
    print("ENVIRONMENT VERIFICATION")
    print("="*60)

    required_vars = {
        'LLAMA_CLOUD_API_KEY': 'LlamaParse API',
        'ANTHROPIC_API_KEY': 'Claude API',
        'DATABASE_URL': 'Database Connection',
        'ENCRYPTION_KEY': 'PII Encryption'
    }

    all_set = True
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value and not value.startswith('test_key') and not value.startswith('your_'):
            print(f"✓ {description:25} : Set")
        else:
            print(f"✗ {description:25} : Missing or placeholder")
            all_set = False

    if not all_set:
        print("\n❌ Error: Please set all required API keys in .env file")
        print("See .env.example for instructions")
        return False

    print("\n✅ All environment variables configured")
    return True


def verify_database():
    """Verify database connection."""
    print("\n" + "="*60)
    print("DATABASE VERIFICATION")
    print("="*60)

    try:
        init_connection_pool(min_connections=1, max_connections=2)
        if health_check():
            print("✅ Database connection successful")
            return True
        else:
            print("❌ Database health check failed")
            return False
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return False


def test_in_memory_mode(file_path: str):
    """Test contract processing in-memory mode (no database)."""
    print("\n" + "="*60)
    print("TEST 1: IN-MEMORY MODE (No Database)")
    print("="*60)

    try:
        # Read file
        with open(file_path, 'rb') as f:
            file_bytes = f.read()

        print(f"\n📄 Processing file: {Path(file_path).name}")
        print(f"   File size: {len(file_bytes):,} bytes")

        # Initialize parser (no database)
        parser = ContractParser(use_database=False)

        # Process contract
        print("\n🔄 Pipeline steps:")
        print("   1. LlamaParse: Extracting text from PDF...")
        print("   2. Presidio: Detecting PII entities...")
        print("   3. Presidio: Anonymizing PII...")
        print("   4. Claude: Extracting contract clauses...")

        result = parser.process_contract(file_bytes, Path(file_path).name)

        # Display results
        print("\n" + "="*60)
        print("RESULTS (In-Memory)")
        print("="*60)
        print(f"✅ Success!")
        print(f"   Processing time: {result.processing_time:.2f} seconds")
        print(f"   PII detected: {result.pii_detected}")
        print(f"   PII anonymized: {result.pii_anonymized}")
        print(f"   Clauses extracted: {len(result.clauses)}")

        if result.clauses:
            print("\n📋 Extracted Clauses:")
            for i, clause in enumerate(result.clauses, 1):
                print(f"\n   Clause {i}: {clause.clause_name}")
                print(f"   - Type: {clause.clause_type}")
                print(f"   - Beneficiary: {clause.beneficiary_party}")
                print(f"   - Confidence: {clause.confidence_score:.2f}")
                print(f"   - Summary: {clause.summary}")

        # Export results to JSON for inspection/download
        try:
            from utils.export_utils import export_contract_result_to_json
            export_path = export_contract_result_to_json(
                result=result,
                filename=Path(file_path).name,
                include_pii=False  # Set to True if PII mappings needed (WARNING: sensitive data)
            )
            print(f"\n📄 Results exported to JSON:")
            print(f"   {export_path}")
            print(f"   You can access this file via:")
            print(f"   - VS Code: File Explorer → python-backend/exports/ → Download")
            print(f"   - Terminal: cat {export_path}")
            print(f"   - Finder: Open /Users/namho/frontiermind-app/python-backend/exports/")
        except Exception as e:
            print(f"\n⚠️  Warning: Could not export results to JSON: {e}")

        return True

    except Exception as e:
        print(f"\n❌ Error in in-memory processing: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_mode(file_path: str):
    """Test contract processing with database storage."""
    print("\n" + "="*60)
    print("TEST 2: DATABASE MODE (Full Pipeline + Storage)")
    print("="*60)

    try:
        # Read file
        with open(file_path, 'rb') as f:
            file_bytes = f.read()

        print(f"\n📄 Processing file: {Path(file_path).name}")
        print(f"   File size: {len(file_bytes):,} bytes")

        # Initialize repository and parser
        repository = ContractRepository()
        parser = ContractParser(use_database=True)

        # Create contract record
        print("\n📝 Creating contract record in database...")
        contract_id = repository.store_contract(
            name=Path(file_path).name,
            file_location=f"/uploads/{Path(file_path).name}",
            description="End-to-end test contract"
        )
        print(f"   Contract ID: {contract_id}")

        # Process and store
        print("\n🔄 Pipeline steps:")
        print("   1. Update status to 'processing'")
        print("   2. LlamaParse: Extract text from PDF")
        print("   3. Presidio: Detect PII entities")
        print("   4. Presidio: Anonymize PII")
        print("   5. Store encrypted PII mapping")
        print("   6. Claude: Extract contract clauses")
        print("   7. Store clauses in database")
        print("   8. Update status to 'completed'")

        result = parser.process_and_store_contract(
            contract_id=contract_id,
            file_bytes=file_bytes,
            filename=Path(file_path).name
        )

        # Display results
        print("\n" + "="*60)
        print("RESULTS (Database Mode)")
        print("="*60)
        print(f"✅ Success!")
        print(f"   Contract ID: {result.contract_id}")
        print(f"   Processing time: {result.processing_time:.2f} seconds")
        print(f"   PII detected: {result.pii_detected}")
        print(f"   PII anonymized: {result.pii_anonymized}")
        print(f"   Clauses extracted: {len(result.clauses)}")

        # Verify database storage
        print("\n🔍 Verifying database storage...")
        contract = repository.get_contract(contract_id)
        print(f"   ✓ Contract record retrieved")
        print(f"   ✓ Parsing status: {contract['parsing_status']}")
        print(f"   ✓ PII count in DB: {contract['pii_detected_count']}")
        print(f"   ✓ Clauses count in DB: {contract['clauses_extracted_count']}")

        clauses = repository.get_clauses(contract_id)
        print(f"   ✓ Retrieved {len(clauses)} clauses from database")

        pii_mapping = repository.get_pii_mapping(contract_id)
        if pii_mapping:
            print(f"   ✓ PII mapping retrieved and decrypted")

        if clauses:
            print("\n📋 Stored Clauses:")
            for clause in clauses:
                print(f"\n   Clause: {clause['name']}")
                print(f"   - Summary: {clause['summary']}")
                print(f"   - Beneficiary: {clause['beneficiary_party']}")
                if clause['confidence_score']:
                    print(f"   - Confidence: {float(clause['confidence_score']):.2f}")

        return True

    except Exception as e:
        print(f"\n❌ Error in database processing: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test execution."""
    print("\n" + "="*60)
    print("CONTRACT PROCESSING END-TO-END TEST")
    print("="*60)

    # Check command line arguments
    if len(sys.argv) < 2:
        print("\n❌ Error: No PDF file provided")
        print("\nUsage:")
        print("    python test_end_to_end.py <path_to_pdf_file>")
        print("\nExample:")
        print("    python test_end_to_end.py tests/fixtures/sample_contract.pdf")
        sys.exit(1)

    file_path = sys.argv[1]

    # Verify file exists
    if not Path(file_path).exists():
        print(f"\n❌ Error: File not found: {file_path}")
        sys.exit(1)

    if not file_path.lower().endswith('.pdf'):
        print(f"\n❌ Error: File must be a PDF: {file_path}")
        sys.exit(1)

    # Step 1: Verify environment
    if not verify_environment():
        sys.exit(1)

    # Step 2: Verify database
    db_available = verify_database()

    # Step 3: Run tests
    print("\n" + "="*60)
    print("RUNNING TESTS")
    print("="*60)

    # Test 1: In-memory mode
    test1_passed = test_in_memory_mode(file_path)

    # Test 2: Database mode (if available)
    test2_passed = False
    if db_available:
        test2_passed = test_database_mode(file_path)
    else:
        print("\n⚠️  Skipping database mode test (database not available)")

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Test 1 - In-Memory Mode: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    if db_available:
        print(f"Test 2 - Database Mode:  {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    else:
        print(f"Test 2 - Database Mode:  ⏭️  SKIPPED")

    if test1_passed and (test2_passed or not db_available):
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
