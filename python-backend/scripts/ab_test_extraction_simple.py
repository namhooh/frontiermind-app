#!/usr/bin/env python3
"""
Simplified A/B Test: Compare old vs new extraction configurations.

Uses a small sample contract text directly to avoid LlamaParse timeouts.
Tests just the clause extraction pipeline differences.
"""

import os
import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from services.prompts import build_extraction_prompt, build_chunk_extraction_prompt
from services.prompts.discovery_prompt import build_chunk_discovery_prompt
from services.prompts.categorization_prompt import build_categorization_prompt
from services.prompts.targeted_extraction_prompt import (
    build_targeted_extraction_prompt,
    TARGETED_CATEGORIES,
    get_missing_categories,
)
from services.prompts.validation_prompt import build_validation_prompt, parse_validation_response
from services.contract_parser import TOKEN_BUDGETS

# Sample PPA contract text (representative clauses)
SAMPLE_CONTRACT = """
POWER PURCHASE AGREEMENT

Between: Solar Energy Corp. ("Seller")
And: City of Springfield Electric Utility ("Buyer")

Effective Date: January 1, 2024
Term: 25 years from Commercial Operation Date

ARTICLE 1 - DEFINITIONS

1.1 "Availability" means the percentage of time during each Contract Year that the Facility
is capable of delivering Energy to the Delivery Point.

1.2 "Commercial Operation Date" or "COD" means the date on which the Facility achieves
Commercial Operation as certified by the Independent Engineer.

1.3 "Guaranteed Capacity" means 50 MW AC measured at the Delivery Point.

ARTICLE 2 - CONDITIONS PRECEDENT

2.1 Conditions Precedent to Buyer's Obligations. The obligations of Buyer under this Agreement
shall be subject to the satisfaction of the following conditions precedent on or before the
Target COD:
(a) Seller shall have obtained all required Permits;
(b) Seller shall have delivered the Performance Security;
(c) The Facility shall have achieved Mechanical Completion;
(d) Seller shall have obtained all required interconnection approvals from the Transmission Provider.

2.2 Conditions Precedent to Seller's Obligations. The obligations of Seller under this Agreement
shall be subject to Buyer providing the Site Lease in form and substance acceptable to Seller.

ARTICLE 3 - ENERGY DELIVERY AND PRICING

3.1 Contract Price. Buyer shall pay Seller for all Energy delivered to the Delivery Point at
the Contract Price of $45.00 per MWh for the first Contract Year, subject to annual escalation.

3.2 Price Escalation. The Contract Price shall escalate annually by 2.0% beginning on the
first anniversary of the Commercial Operation Date.

3.3 Minimum Purchase Obligation. Buyer agrees to purchase, or pay for if not taken, a minimum
of 80% of the Expected Annual Energy Output in each Contract Year ("Take-or-Pay Obligation").

ARTICLE 4 - PERFORMANCE GUARANTEES

4.1 Availability Guarantee. Seller guarantees that the Facility shall achieve an annual
Availability of at least 95% ("Guaranteed Availability").

4.2 Performance Ratio Guarantee. Seller guarantees that the Facility shall achieve a minimum
Performance Ratio of 80% during each Contract Year.

4.3 Degradation. The parties acknowledge that the Facility output may degrade over time.
Seller guarantees that annual degradation shall not exceed 0.5% per year.

ARTICLE 5 - LIQUIDATED DAMAGES

5.1 Availability Shortfall Damages. If the Facility's annual Availability falls below the
Guaranteed Availability, Seller shall pay Buyer liquidated damages equal to $50,000 per
percentage point below 95%, up to a maximum of $500,000 per Contract Year.

5.2 Delay Damages. If Commercial Operation is not achieved by the Target COD, Seller shall
pay Buyer delay liquidated damages of $10,000 per day, up to a maximum of 180 days.

5.3 Performance Shortfall Damages. For each percentage point that the actual Performance Ratio
falls below the guaranteed 80%, Seller shall pay Buyer $25,000 per Contract Year.

ARTICLE 6 - SECURITY

6.1 Performance Security. Prior to the commencement of construction, Seller shall deliver
to Buyer a letter of credit in the amount of $2,500,000 from a bank with a credit rating of
at least A- from S&P or equivalent.

6.2 Release of Security. The Performance Security shall be reduced by 50% upon achievement
of COD and fully released after the second anniversary of COD, provided no Events of Default
have occurred.

ARTICLE 7 - DEFAULT AND TERMINATION

7.1 Events of Default by Seller.
(a) Failure to achieve COD within 180 days of the Target COD;
(b) Failure to maintain the Performance Security as required;
(c) Material breach of any representation, warranty, or covenant;
(d) Bankruptcy or insolvency of Seller.

7.2 Events of Default by Buyer.
(a) Failure to make undisputed payments within 30 days of the due date;
(b) Material breach of any representation, warranty, or covenant;
(c) Bankruptcy or insolvency of Buyer.

7.3 Cure Period. The non-defaulting Party shall provide written notice of any Event of Default.
The defaulting Party shall have 30 days to cure (or 60 days if the cure requires more time
and diligent efforts are being made).

7.4 Termination Rights. Upon the occurrence of an Event of Default that is not cured within
the applicable cure period, the non-defaulting Party may terminate this Agreement.

ARTICLE 8 - FORCE MAJEURE

8.1 Definition. "Force Majeure" means any event beyond the reasonable control of a Party,
including acts of God, war, terrorism, strikes, natural disasters, and changes in law.

8.2 Effect of Force Majeure. A Party's performance shall be excused to the extent prevented
by Force Majeure, provided that the affected Party gives prompt notice and uses commercially
reasonable efforts to mitigate the effects.

ARTICLE 9 - MAINTENANCE

9.1 O&M Obligations. Seller shall operate and maintain the Facility in accordance with
Prudent Utility Practices and manufacturer recommendations.

9.2 Scheduled Maintenance. Seller shall schedule major maintenance during periods of low
solar irradiance and provide Buyer at least 30 days advance notice.

9.3 Unscheduled Outages. Seller shall notify Buyer within 24 hours of any unscheduled outage
and provide regular updates on restoration efforts.

ARTICLE 10 - COMPLIANCE

10.1 Environmental Compliance. Seller shall comply with all applicable environmental laws
and maintain all required environmental permits.

10.2 Regulatory Approvals. Each Party shall obtain and maintain all regulatory approvals
necessary for the performance of its obligations under this Agreement.

ARTICLE 11 - PAYMENT TERMS

11.1 Invoicing. Seller shall invoice Buyer monthly for all Energy delivered during the
preceding month, with payment due within 30 days of invoice receipt.

11.2 Late Payment Interest. Any amounts not paid when due shall bear interest at the prime
rate plus 2% per annum.

ARTICLE 12 - GENERAL PROVISIONS

12.1 Governing Law. This Agreement shall be governed by the laws of the State of Illinois.

12.2 Dispute Resolution. Any dispute shall be resolved through binding arbitration under
AAA Commercial Arbitration Rules.

12.3 Assignment. Neither Party may assign this Agreement without the prior written consent
of the other Party, except to an Affiliate or in connection with a merger or acquisition.

12.4 Confidentiality. Each Party shall maintain the confidentiality of this Agreement and
all confidential information received from the other Party.

12.5 Notices. All notices shall be in writing and sent to the addresses specified in Exhibit A.
"""


def call_claude_with_streaming(client: Anthropic, system: str, user: str, max_tokens: int, retries: int = 2):
    """Call Claude with streaming to avoid timeout issues."""
    for attempt in range(retries + 1):
        try:
            full_response = ""
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
            return full_response
        except Exception as e:
            if attempt < retries:
                print(f"    Retry {attempt + 1}/{retries} after error: {type(e).__name__}")
                time.sleep(2)
            else:
                raise


def extract_clauses_single_pass(client: Anthropic, text: str):
    """Single-pass extraction (old method)."""
    prompts = build_chunk_extraction_prompt(
        contract_text=text,
        chunk_index=0,
        total_chunks=1,
        include_examples=False
    )

    response_text = call_claude_with_streaming(
        client,
        prompts['system'],
        prompts['user'],
        TOKEN_BUDGETS["main_extraction"]
    )

    return parse_extraction_response(response_text)


def extract_clauses_two_pass(client: Anthropic, text: str):
    """Two-pass extraction: discovery then categorization."""
    # Pass 1: Discovery
    prompts = build_chunk_discovery_prompt(
        contract_text=text,
        chunk_index=0,
        total_chunks=1,
        contract_type_hint="PPA"
    )

    response_text = call_claude_with_streaming(
        client,
        prompts['system'],
        prompts['user'],
        TOKEN_BUDGETS["discovery"]
    )

    discovered = parse_discovery_response(response_text)
    print(f"  Discovery phase found {len(discovered)} raw clauses")

    if not discovered:
        return []

    # Pass 2: Categorization
    prompts = build_categorization_prompt(
        discovered_clauses=discovered,
        include_examples=True
    )

    response_text = call_claude_with_streaming(
        client,
        prompts['system'],
        prompts['user'],
        TOKEN_BUDGETS["categorization"]
    )

    return parse_categorization_response(response_text)


def run_targeted_extraction(client: Anthropic, text: str, existing_clauses: list, categories: list):
    """Run targeted extraction for specific categories."""
    new_clauses = []

    for category in categories:
        if category not in TARGETED_CATEGORIES:
            continue

        prompts = build_targeted_extraction_prompt(
            contract_text=text,
            target_category=category,
            existing_clauses=existing_clauses
        )

        response_text = call_claude_with_streaming(
            client,
            prompts['system'],
            prompts['user'],
            TOKEN_BUDGETS["targeted"]
        )

        found = parse_targeted_response(response_text, category)
        if found:
            print(f"    Targeted: Found {len(found)} {category} clause(s)")
            new_clauses.extend(found)

    return new_clauses


def run_validation_pass(client: Anthropic, text: str, existing_clauses: list):
    """Run validation pass to catch missed clauses."""
    prompts = build_validation_prompt(
        contract_text=text,
        extracted_clauses=existing_clauses
    )

    response_text = call_claude_with_streaming(
        client,
        prompts['system'],
        prompts['user'],
        TOKEN_BUDGETS["validation"]
    )

    missed, summary = parse_validation_response(response_text)
    return missed, summary


def parse_extraction_response(text: str) -> list:
    """Parse single-pass extraction response."""
    import json
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
        return data.get("clauses", [])
    except:
        return []


def parse_discovery_response(text: str) -> list:
    """Parse discovery phase response."""
    import json
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
        return data.get("discovered_clauses", [])
    except:
        return []


def parse_categorization_response(text: str) -> list:
    """Parse categorization phase response."""
    import json
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end == -1:
            end = len(text)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end == -1:
            end = len(text)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
        return data.get("categorized_clauses", [])
    except:
        return []


def parse_targeted_response(text: str, category: str) -> list:
    """Parse targeted extraction response."""
    import json
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
        clauses = data.get("found_clauses", [])
        # Ensure category is set
        for c in clauses:
            c['category'] = category
        return clauses
    except:
        return []


def get_stats(clauses: list) -> dict:
    """Calculate extraction statistics."""
    categories = defaultdict(int)
    total_payload_fields = 0

    for c in clauses:
        cat = c.get('category') or c.get('clause_category') or 'UNIDENTIFIED'
        categories[cat] += 1

        payload = c.get('normalized_payload', {})
        if payload:
            total_payload_fields += sum(1 for v in payload.values() if v is not None and v != "" and v != [])

    return {
        'total_clauses': len(clauses),
        'categories': dict(categories),
        'unique_categories': len(categories),
        'avg_payload_fields': total_payload_fields / len(clauses) if clauses else 0,
        'unidentified': categories.get('UNIDENTIFIED', 0),
    }


def main():
    import json

    print("=" * 80)
    print("A/B TEST: OLD vs NEW EXTRACTION CONFIGURATION")
    print("=" * 80)
    print(f"\nSample contract: {len(SAMPLE_CONTRACT)} characters")

    client = Anthropic()

    # ========== CONFIG A: OLD (single-pass, no targeted, no validation) ==========
    print("\n" + "=" * 60)
    print("CONFIG A: OLD (single-pass only)")
    print("=" * 60)

    start_a = time.time()
    clauses_a = extract_clauses_single_pass(client, SAMPLE_CONTRACT)
    time_a = time.time() - start_a

    stats_a = get_stats(clauses_a)
    print(f"  Extracted {stats_a['total_clauses']} clauses in {time_a:.1f}s")
    print(f"  Categories: {stats_a['unique_categories']}")
    print(f"  Avg payload fields: {stats_a['avg_payload_fields']:.1f}")

    # ========== CONFIG B: NEW (two-pass + targeted + validation) ==========
    print("\n" + "=" * 60)
    print("CONFIG B: NEW (two-pass + targeted + validation)")
    print("=" * 60)

    start_b = time.time()

    # Two-pass extraction
    print("  Phase 1: Two-pass extraction...")
    clauses_b = extract_clauses_two_pass(client, SAMPLE_CONTRACT)
    print(f"  Two-pass found {len(clauses_b)} clauses")

    # Get current categories
    current_cats = set(c.get('category') or c.get('clause_category') for c in clauses_b)
    current_cats.discard(None)
    current_cats.discard('UNIDENTIFIED')

    # Targeted extraction for missing categories
    print("  Phase 2: Targeted extraction...")
    missing_cats = get_missing_categories(list(current_cats))
    if missing_cats:
        print(f"    Missing categories: {missing_cats}")
        targeted_clauses = run_targeted_extraction(client, SAMPLE_CONTRACT, clauses_b, missing_cats)
        clauses_b.extend(targeted_clauses)
        print(f"    Added {len(targeted_clauses)} clauses from targeted extraction")

    # Validation pass
    print("  Phase 3: Validation pass...")
    missed, summary = run_validation_pass(client, SAMPLE_CONTRACT, clauses_b)
    if missed:
        clauses_b.extend(missed)
        print(f"    Validation found {len(missed)} missed clauses")
    else:
        print(f"    Validation: no additional clauses found")
    if summary.get('confidence_complete'):
        print(f"    Confidence complete: {summary['confidence_complete']:.0%}")

    time_b = time.time() - start_b

    stats_b = get_stats(clauses_b)
    print(f"\n  Total: {stats_b['total_clauses']} clauses in {time_b:.1f}s")
    print(f"  Categories: {stats_b['unique_categories']}")
    print(f"  Avg payload fields: {stats_b['avg_payload_fields']:.1f}")

    # ========== COMPARISON ==========
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    print(f"\n{'Metric':<35} {'Config A':<15} {'Config B':<15} {'Delta':<15}")
    print("-" * 80)

    delta_clauses = stats_b['total_clauses'] - stats_a['total_clauses']
    delta_cats = stats_b['unique_categories'] - stats_a['unique_categories']
    delta_payload = stats_b['avg_payload_fields'] - stats_a['avg_payload_fields']
    delta_time = time_b - time_a

    print(f"{'Total Clauses':<35} {stats_a['total_clauses']:<15} {stats_b['total_clauses']:<15} {delta_clauses:+d}")
    print(f"{'Unique Categories':<35} {stats_a['unique_categories']:<15} {stats_b['unique_categories']:<15} {delta_cats:+d}")
    print(f"{'Avg Payload Fields':<35} {stats_a['avg_payload_fields']:<15.1f} {stats_b['avg_payload_fields']:<15.1f} {delta_payload:+.1f}")
    print(f"{'Unidentified Clauses':<35} {stats_a['unidentified']:<15} {stats_b['unidentified']:<15} {stats_b['unidentified'] - stats_a['unidentified']:+d}")
    print(f"{'Processing Time (sec)':<35} {time_a:<15.1f} {time_b:<15.1f} {delta_time:+.1f}")

    # Category breakdown
    print("\n" + "-" * 80)
    print("CATEGORY BREAKDOWN")
    print("-" * 80)

    all_cats = sorted(set(list(stats_a['categories'].keys()) + list(stats_b['categories'].keys())))

    print(f"\n{'Category':<30} {'Config A':<10} {'Config B':<10} {'Delta':<10}")
    print("-" * 60)

    for cat in all_cats:
        count_a = stats_a['categories'].get(cat, 0)
        count_b = stats_b['categories'].get(cat, 0)
        delta = count_b - count_a
        print(f"{cat:<30} {count_a:<10} {count_b:<10} {delta:+d}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if delta_clauses > 0:
        pct = (delta_clauses / stats_a['total_clauses'] * 100) if stats_a['total_clauses'] > 0 else 0
        print(f"✓ Config B found {delta_clauses} MORE clauses ({pct:.0f}% improvement)")
    elif delta_clauses < 0:
        print(f"✗ Config B found {abs(delta_clauses)} FEWER clauses")
    else:
        print(f"= Same number of clauses")

    if delta_cats > 0:
        print(f"✓ Config B covers {delta_cats} MORE categories")

    if delta_payload > 0.5:
        print(f"✓ Config B has {delta_payload:.1f} MORE avg payload fields per clause")

    print(f"⏱ Config B took {delta_time:.1f} additional seconds (more thorough)")

    # Save comprehensive results to JSON
    output_path = Path(__file__).parent.parent / "test_data" / "ab_test_full_results.json"
    results = {
        "test_info": {
            "contract_length": len(SAMPLE_CONTRACT),
            "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "config_a": {
            "name": "Old (single-pass only)",
            "settings": {
                "extraction_mode": "single_pass",
                "enable_targeted": False,
                "enable_validation": False,
            },
            "stats": stats_a,
            "processing_time_sec": time_a,
            "clauses": clauses_a,
        },
        "config_b": {
            "name": "New (two-pass + targeted + validation)",
            "settings": {
                "extraction_mode": "two_pass",
                "enable_targeted": True,
                "enable_validation": True,
            },
            "stats": stats_b,
            "processing_time_sec": time_b,
            "clauses": clauses_b,
        },
        "comparison": {
            "clause_delta": delta_clauses,
            "category_delta": delta_cats,
            "payload_delta": round(delta_payload, 2),
            "time_delta": round(delta_time, 1),
        }
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n📁 Full results saved to: {output_path}")


if __name__ == "__main__":
    main()
