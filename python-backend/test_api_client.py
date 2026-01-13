"""
Simple API Client for Testing Contract Processing

This script makes it easy to test the FastAPI endpoints without curl.

Prerequisites:
1. Start the FastAPI server: uvicorn main:app --reload
2. Have a PDF contract ready

Usage:
    python test_api_client.py <path_to_pdf>

Example:
    python test_api_client.py test_data/sample_contract.pdf
"""

import sys
import httpx
import json
from pathlib import Path
from typing import Optional


class ContractAPIClient:
    """Client for testing contract processing API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=300.0)  # 5 minute timeout for processing

    def health_check(self) -> dict:
        """Check API health."""
        print("\n🏥 Checking API health...")
        response = self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        data = response.json()
        print(f"   Status: {data.get('status')}")
        print(f"   Database: {data.get('database')}")
        return data

    def upload_and_parse(self, file_path: str) -> dict:
        """Upload and parse a contract PDF."""
        print(f"\n📤 Uploading contract: {Path(file_path).name}")

        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "application/pdf")}

            print("   ⏳ Processing (this may take 10-60 seconds)...")
            print("      1. LlamaParse: Extracting text...")
            print("      2. Presidio: Detecting & anonymizing PII...")
            print("      3. Claude: Extracting clauses...")
            print("      4. Database: Storing results...")

            response = self.client.post(
                f"{self.base_url}/api/contracts/parse",
                files=files
            )

        if response.status_code != 200:
            print(f"\n❌ Error: {response.status_code}")
            print(response.text)
            response.raise_for_status()

        result = response.json()

        print(f"\n✅ Success!")
        print(f"   Contract ID: {result['contract_id']}")
        print(f"   Processing time: {result['processing_time']:.2f}s")
        print(f"   PII detected: {result['pii_detected']}")
        print(f"   PII anonymized: {result['pii_anonymized']}")
        print(f"   Clauses extracted: {result['clauses_extracted']}")

        return result

    def get_contract(self, contract_id: int) -> dict:
        """Get contract metadata by ID."""
        print(f"\n📄 Retrieving contract {contract_id}...")

        response = self.client.get(f"{self.base_url}/api/contracts/{contract_id}")

        if response.status_code == 404:
            print(f"   ❌ Contract {contract_id} not found")
            return None

        response.raise_for_status()
        result = response.json()

        contract = result['contract']
        print(f"   ✓ Name: {contract['name']}")
        print(f"   ✓ Status: {contract['parsing_status']}")
        print(f"   ✓ PII detected: {contract['pii_detected_count']}")
        print(f"   ✓ Clauses extracted: {contract['clauses_extracted_count']}")
        print(f"   ✓ Processing time: {contract.get('processing_time_seconds', 'N/A')}s")

        return contract

    def get_clauses(self, contract_id: int, min_confidence: Optional[float] = None) -> list:
        """Get clauses for a contract."""
        print(f"\n📋 Retrieving clauses for contract {contract_id}...")

        url = f"{self.base_url}/api/contracts/{contract_id}/clauses"
        if min_confidence:
            url += f"?min_confidence={min_confidence}"
            print(f"   (filtering by confidence >= {min_confidence})")

        response = self.client.get(url)

        if response.status_code == 404:
            print(f"   ❌ Contract {contract_id} not found")
            return []

        response.raise_for_status()
        result = response.json()

        clauses = result['clauses']
        print(f"   ✓ Retrieved {len(clauses)} clauses")

        return clauses

    def display_clauses(self, clauses: list):
        """Display clause details."""
        if not clauses:
            print("\n   No clauses to display")
            return

        print("\n📋 Clause Details:")
        print("=" * 80)

        for i, clause in enumerate(clauses, 1):
            print(f"\n{i}. {clause['name']}")
            print(f"   Summary: {clause['summary']}")
            print(f"   Beneficiary: {clause['beneficiary_party']}")
            if clause.get('confidence_score'):
                conf = float(clause['confidence_score'])
                emoji = "🟢" if conf >= 0.8 else "🟡" if conf >= 0.6 else "🔴"
                print(f"   Confidence: {emoji} {conf:.2f}")
            print(f"   Text: {clause['raw_text'][:100]}...")

    def close(self):
        """Close HTTP client."""
        self.client.close()


def main():
    """Main test execution."""
    print("=" * 80)
    print("CONTRACT PROCESSING API CLIENT")
    print("=" * 80)

    # Check arguments
    if len(sys.argv) < 2:
        print("\n❌ Error: No PDF file provided")
        print("\nUsage:")
        print("    python test_api_client.py <path_to_pdf>")
        print("\nExample:")
        print("    python test_api_client.py test_data/sample_contract.pdf")
        print("\nNote: Make sure the API server is running:")
        print("    uvicorn main:app --reload")
        sys.exit(1)

    file_path = sys.argv[1]

    # Verify file exists
    if not Path(file_path).exists():
        print(f"\n❌ Error: File not found: {file_path}")
        sys.exit(1)

    if not file_path.lower().endswith('.pdf'):
        print(f"\n❌ Error: File must be a PDF: {file_path}")
        sys.exit(1)

    # Initialize client
    client = ContractAPIClient()

    try:
        # Step 1: Health check
        health = client.health_check()

        if health.get('status') != 'healthy':
            print("\n❌ API is not healthy. Is the server running?")
            print("   Start with: uvicorn main:app --reload")
            sys.exit(1)

        # Step 2: Upload and parse contract
        result = client.upload_and_parse(file_path)
        contract_id = result['contract_id']

        # Step 3: Display extracted clauses
        if result.get('clauses'):
            print("\n📋 Clauses from API response:")
            print("=" * 80)
            for i, clause in enumerate(result['clauses'], 1):
                print(f"\n{i}. {clause['clause_name']}")
                print(f"   Type: {clause['clause_type']}")
                print(f"   Summary: {clause['summary']}")
                print(f"   Beneficiary: {clause['beneficiary_party']}")
                print(f"   Confidence: {clause['confidence_score']:.2f}")

        # Step 4: Verify by retrieving from database
        if contract_id > 0:  # contract_id = 0 means in-memory mode
            print("\n" + "=" * 80)
            print("VERIFICATION: Retrieving from Database")
            print("=" * 80)

            contract = client.get_contract(contract_id)

            clauses = client.get_clauses(contract_id)
            client.display_clauses(clauses)

            # Show high-confidence clauses only
            print("\n" + "=" * 80)
            print("HIGH-CONFIDENCE CLAUSES (>= 0.8)")
            print("=" * 80)
            high_conf_clauses = client.get_clauses(contract_id, min_confidence=0.8)
            client.display_clauses(high_conf_clauses)

        else:
            print("\n⚠️  Database storage not available (running in in-memory mode)")

        # Success!
        print("\n" + "=" * 80)
        print("✅ TEST COMPLETE")
        print("=" * 80)
        print(f"\nContract processed successfully!")
        print(f"   Contract ID: {contract_id}")
        print(f"   Clauses: {result['clauses_extracted']}")
        print(f"   PII anonymized: {result['pii_anonymized']}")
        print(f"\nView full API docs: http://localhost:8000/docs")

    except httpx.ConnectError:
        print("\n❌ Error: Cannot connect to API server")
        print("\nMake sure the server is running:")
        print("    cd python-backend")
        print("    uvicorn main:app --reload")
        sys.exit(1)

    except httpx.HTTPStatusError as e:
        print(f"\n❌ HTTP Error: {e.response.status_code}")
        print(e.response.text)
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        client.close()


if __name__ == "__main__":
    main()
