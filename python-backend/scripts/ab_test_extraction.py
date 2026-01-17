#!/usr/bin/env python3
"""
A/B Test: Compare old vs new extraction configurations.

Runs extraction on the same contract with:
- Config A (Old): single_pass, no validation, limited targeted (2 categories)
- Config B (New): two_pass, validation enabled, all targeted (13 categories)

Compares clause counts, category coverage, and payload completeness.
"""

import os
import sys
import json
import time
from pathlib import Path
from collections import defaultdict

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.contract_parser import ContractParser


def count_payload_fields(clauses):
    """Count average non-null fields in normalized_payload."""
    if not clauses:
        return 0

    total_fields = 0
    for clause in clauses:
        payload = clause.normalized_payload or {}
        # Count non-null, non-empty fields
        non_empty = sum(1 for v in payload.values() if v is not None and v != "" and v != [])
        total_fields += non_empty

    return total_fields / len(clauses) if clauses else 0


def get_category_distribution(clauses):
    """Get clause count by category."""
    dist = defaultdict(int)
    for clause in clauses:
        cat = clause.category or clause.clause_category or "UNIDENTIFIED"
        dist[cat] += 1
    return dict(dist)


def run_extraction(pdf_path: str, config_name: str, **kwargs):
    """Run extraction with given configuration."""
    print(f"\n{'='*60}")
    print(f"Running Config {config_name}")
    print(f"Settings: {kwargs}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        parser = ContractParser(**kwargs)

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        result = parser.process_contract(pdf_bytes, Path(pdf_path).name)

        elapsed = time.time() - start_time

        return {
            'config': config_name,
            'status': result.status,
            'clause_count': len(result.clauses),
            'clauses': result.clauses,
            'categories': get_category_distribution(result.clauses),
            'category_count': len(set(c.category or c.clause_category for c in result.clauses if c.category or c.clause_category)),
            'avg_payload_fields': count_payload_fields(result.clauses),
            'unidentified_count': sum(1 for c in result.clauses if (c.category or c.clause_category) == "UNIDENTIFIED"),
            'elapsed_seconds': elapsed,
            'pii_detected': result.pii_detected,
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            'config': config_name,
            'status': 'error',
            'error': str(e),
            'elapsed_seconds': elapsed,
        }


def print_comparison(result_a, result_b):
    """Print side-by-side comparison."""
    print("\n")
    print("=" * 80)
    print("A/B TEST RESULTS COMPARISON")
    print("=" * 80)

    if result_a.get('status') == 'error':
        print(f"\nConfig A ERROR: {result_a.get('error')}")
        return
    if result_b.get('status') == 'error':
        print(f"\nConfig B ERROR: {result_b.get('error')}")
        return

    # Summary table
    print(f"\n{'Metric':<35} {'Config A (Old)':<20} {'Config B (New)':<20} {'Delta':<15}")
    print("-" * 90)

    metrics = [
        ('Total Clauses', 'clause_count'),
        ('Categories Found', 'category_count'),
        ('Avg Payload Fields', 'avg_payload_fields'),
        ('Unidentified Clauses', 'unidentified_count'),
        ('Processing Time (sec)', 'elapsed_seconds'),
        ('PII Entities Detected', 'pii_detected'),
    ]

    for label, key in metrics:
        val_a = result_a.get(key, 0)
        val_b = result_b.get(key, 0)

        if isinstance(val_a, float):
            delta = val_b - val_a
            delta_str = f"{delta:+.2f}" if delta != 0 else "0"
            print(f"{label:<35} {val_a:<20.2f} {val_b:<20.2f} {delta_str:<15}")
        else:
            delta = val_b - val_a
            delta_str = f"{delta:+d}" if delta != 0 else "0"
            print(f"{label:<35} {val_a:<20} {val_b:<20} {delta_str:<15}")

    # Category breakdown
    print("\n" + "-" * 90)
    print("CATEGORY BREAKDOWN")
    print("-" * 90)

    all_categories = sorted(set(list(result_a.get('categories', {}).keys()) +
                               list(result_b.get('categories', {}).keys())))

    print(f"\n{'Category':<30} {'Config A':<15} {'Config B':<15} {'Delta':<10}")
    print("-" * 70)

    for cat in all_categories:
        count_a = result_a.get('categories', {}).get(cat, 0)
        count_b = result_b.get('categories', {}).get(cat, 0)
        delta = count_b - count_a
        delta_str = f"{delta:+d}" if delta != 0 else "0"
        print(f"{cat:<30} {count_a:<15} {count_b:<15} {delta_str:<10}")

    # New clauses found
    print("\n" + "-" * 90)
    print("NEW CLAUSES IN CONFIG B (not in Config A)")
    print("-" * 90)

    # Get clause names from both
    names_a = set(c.clause_name for c in result_a.get('clauses', []))
    clauses_b = result_b.get('clauses', [])

    new_clauses = [c for c in clauses_b if c.clause_name not in names_a]

    if new_clauses:
        for c in new_clauses[:20]:  # Show first 20
            cat = c.category or c.clause_category or "UNIDENTIFIED"
            section = c.section_reference or "N/A"
            print(f"  + [{cat}] {c.clause_name} (Section: {section})")
        if len(new_clauses) > 20:
            print(f"  ... and {len(new_clauses) - 20} more")
    else:
        print("  No new clauses found")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    clause_delta = result_b['clause_count'] - result_a['clause_count']
    category_delta = result_b['category_count'] - result_a['category_count']
    payload_delta = result_b['avg_payload_fields'] - result_a['avg_payload_fields']

    if clause_delta > 0:
        print(f"✓ Config B found {clause_delta} MORE clauses ({clause_delta/result_a['clause_count']*100:.1f}% improvement)")
    elif clause_delta < 0:
        print(f"✗ Config B found {abs(clause_delta)} FEWER clauses")
    else:
        print(f"= Same number of clauses")

    if category_delta > 0:
        print(f"✓ Config B covers {category_delta} MORE categories")
    elif category_delta < 0:
        print(f"✗ Config B covers {abs(category_delta)} FEWER categories")
    else:
        print(f"= Same category coverage")

    if payload_delta > 0.5:
        print(f"✓ Config B has {payload_delta:.1f} MORE avg payload fields per clause")
    elif payload_delta < -0.5:
        print(f"✗ Config B has {abs(payload_delta):.1f} FEWER avg payload fields")
    else:
        print(f"= Similar payload completeness")

    time_delta = result_b['elapsed_seconds'] - result_a['elapsed_seconds']
    print(f"⏱ Config B took {time_delta:+.1f} seconds compared to Config A")


def main():
    # Check for test PDF
    test_pdf = Path(__file__).parent.parent / "test_data" / "City Fort Collins_Power_Purchase_AgreementPPA).pdf"

    if not test_pdf.exists():
        print(f"ERROR: Test PDF not found at {test_pdf}")
        print("Please provide a sample contract PDF.")
        sys.exit(1)

    print(f"Using test contract: {test_pdf.name}")
    print(f"File size: {test_pdf.stat().st_size / 1024:.1f} KB")

    # Config A: Old settings (simulating pre-update behavior)
    result_a = run_extraction(
        str(test_pdf),
        config_name="A (Old)",
        extraction_mode="single_pass",
        enable_targeted=False,  # Only 2 categories before
        enable_validation=False,
    )

    # Config B: New settings
    result_b = run_extraction(
        str(test_pdf),
        config_name="B (New)",
        extraction_mode="two_pass",
        enable_targeted=True,  # All 13 categories now
        enable_validation=True,
    )

    # Print comparison
    print_comparison(result_a, result_b)

    # Save detailed results
    output_path = Path(__file__).parent.parent / "test_data" / "ab_test_results.json"

    # Convert clauses to dicts for JSON serialization
    def serialize_result(result):
        r = dict(result)
        if 'clauses' in r:
            r['clauses'] = [c.model_dump() for c in r['clauses']]
        return r

    with open(output_path, 'w') as f:
        json.dump({
            'config_a': serialize_result(result_a),
            'config_b': serialize_result(result_b),
        }, f, indent=2, default=str)

    print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
