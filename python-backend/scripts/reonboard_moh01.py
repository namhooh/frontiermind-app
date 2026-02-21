"""
Re-onboard MOH01 with the updated parser to populate all new pricing fields.

Usage:
    cd python-backend
    python scripts/reonboard_moh01.py [--parse-only]
"""

import json
import logging
import os
import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reonboard_moh01")

from dotenv import load_dotenv
load_dotenv()

from services.onboarding.excel_parser import ExcelParser
from services.onboarding.normalizer import extract_billing_product_code

TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "CBE_data_extracts" / "AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx"

ORGANIZATION_ID = 1
EXTERNAL_PROJECT_ID = "MOH01"
EXTERNAL_CONTRACT_ID = "GH-MOH01-PPA-001"


def parse_only():
    """Parse the Excel file and show all extracted fields, highlighting new ones."""
    logger.info(f"Parsing: {TEMPLATE_PATH}")
    excel_bytes = TEMPLATE_PATH.read_bytes()
    parser = ExcelParser()
    data = parser.parse(excel_bytes, TEMPLATE_PATH.name)

    print("\n" + "=" * 70)
    print("EXCEL PARSER OUTPUT — ALL FIELDS")
    print("=" * 70)

    # Project info
    print("\n--- Project Info ---")
    for f in ["external_project_id", "external_contract_id", "project_name", "country",
              "sage_id", "cod_date", "installed_dc_capacity_kwp", "installed_ac_capacity_kw",
              "installation_location_url"]:
        print(f"  {f}: {getattr(data, f, None)}")

    # Customer info
    print("\n--- Customer Info ---")
    for f in ["customer_name", "registered_name", "registration_number", "tax_pin",
              "registered_address", "customer_email", "customer_country"]:
        print(f"  {f}: {getattr(data, f, None)}")

    # Contract info
    print("\n--- Contract Info ---")
    for f in ["contract_name", "contract_type_code", "contract_term_years", "effective_date",
              "end_date", "interconnection_voltage_kv", "payment_security_required",
              "payment_security_details", "agreed_fx_rate_source"]:
        print(f"  {f}: {getattr(data, f, None)}")

    # NEW: Contract flags
    print("\n--- Contract Flags (NEW) ---")
    for f in ["ppa_confirmed_uploaded", "has_amendments"]:
        v = getattr(data, f, None)
        marker = " ✓ EXTRACTED" if v is not None else " ✗ not found"
        print(f"  {f}: {v}{marker}")

    # Tariff info
    print("\n--- Tariff Info ---")
    for f in ["contract_service_type", "energy_sale_type", "escalation_type",
              "billing_currency", "market_ref_currency", "base_rate", "unit",
              "discount_pct", "floor_rate", "ceiling_rate", "escalation_value",
              "grp_method", "payment_terms"]:
        print(f"  {f}: {getattr(data, f, None)}")

    # NEW: Multi-value service types
    print("\n--- Multi-Value Service Types (NEW) ---")
    st = data.contract_service_types
    marker = f" ✓ {len(st)} types" if st else " ✗ none"
    print(f"  contract_service_types: {st}{marker}")

    # NEW: Additional rate fields
    print("\n--- Additional Rate Fields (NEW) ---")
    for f in ["equipment_rental_rate", "bess_fee", "loan_repayment_value"]:
        v = getattr(data, f, None)
        marker = " ✓ EXTRACTED" if v is not None else " (empty — expected for Energy Sales-only)"
        print(f"  {f}: {v}{marker}")

    # NEW: Escalation detail fields
    print("\n--- Escalation Detail Fields (NEW) ---")
    for f in ["billing_frequency", "escalation_frequency", "escalation_start_date",
              "tariff_components_to_adjust"]:
        v = getattr(data, f, None)
        marker = " ✓ EXTRACTED" if v is not None else " ✗ not found"
        print(f"  {f}: {v}{marker}")

    # Billing products
    print("\n--- Billing Products ---")
    print(f"  product_to_be_billed (raw): {data.product_to_be_billed}")
    print(f"  product_to_be_billed_list: {data.product_to_be_billed_list}")
    marker = f" ✓ {len(data.product_to_be_billed_list)} products" if len(data.product_to_be_billed_list) > 1 else " (single product)"
    print(f"  Multi-value extraction:{marker}")

    # Collections
    print(f"\n--- Collections ---")
    print(f"  contacts: {len(data.contacts)}")
    print(f"  meters: {len(data.meters)}")
    print(f"  assets: {len(data.assets)}")
    print(f"  forecasts: {len(data.forecasts)}")

    print("\n" + "=" * 70)
    return data


def _pre_cleanup():
    """Fix contract external_contract_id and clear stale billing products."""
    from db.database import get_db_connection
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Fix empty external_contract_id so upsert matches existing contract
            cur.execute(
                "UPDATE contract SET external_contract_id = %s WHERE project_id = (SELECT id FROM project WHERE external_project_id = %s AND organization_id = %s) AND (external_contract_id IS NULL OR external_contract_id = '')",
                (EXTERNAL_CONTRACT_ID, EXTERNAL_PROJECT_ID, ORGANIZATION_ID),
            )
            updated = cur.rowcount
            if updated:
                print(f"  Fixed contract.external_contract_id → '{EXTERNAL_CONTRACT_ID}' ({updated} row)")

            # Clear old billing products to avoid duplicate primary assertion failure
            cur.execute(
                """DELETE FROM contract_billing_product WHERE contract_id IN (
                    SELECT c.id FROM contract c
                    JOIN project p ON c.project_id = p.id
                    WHERE p.external_project_id = %s AND p.organization_id = %s
                )""",
                (EXTERNAL_PROJECT_ID, ORGANIZATION_ID),
            )
            deleted = cur.rowcount
            if deleted:
                print(f"  Cleared {deleted} old billing products (will be re-inserted)")
        conn.commit()


def full_onboard():
    """Run the full preview + commit cycle."""
    from db.database import init_connection_pool
    from models.onboarding import OnboardingOverrides
    from services.onboarding.onboarding_service import OnboardingService

    init_connection_pool()

    # Pre-cleanup: fix data issues that would cause upsert conflicts
    print("\n--- Pre-cleanup ---")
    _pre_cleanup()

    service = OnboardingService()

    excel_bytes = TEMPLATE_PATH.read_bytes()
    overrides = OnboardingOverrides(
        external_project_id=EXTERNAL_PROJECT_ID,
        external_contract_id=EXTERNAL_CONTRACT_ID,
    )

    # Phase A: Preview
    logger.info("Running preview...")
    preview = service.preview(
        organization_id=ORGANIZATION_ID,
        overrides=overrides,
        excel_bytes=excel_bytes,
        excel_filename=TEMPLATE_PATH.name,
    )

    print("\n" + "=" * 70)
    print("PREVIEW RESULT")
    print("=" * 70)
    print(f"  Preview ID: {preview.preview_id}")
    print(f"  Discrepancies: {len(preview.discrepancy_report.discrepancies)}")
    for d in preview.discrepancy_report.discrepancies:
        print(f"    [{d.severity}] {d.field}: {d.explanation}")
    print(f"  Counts: {preview.counts}")

    # Show tariff lines
    tariff_lines = preview.parsed_data.get("tariff_lines", [])
    print(f"\n  Tariff lines: {len(tariff_lines)}")
    for tl in tariff_lines:
        print(f"    - {tl['tariff_group_key']}: type={tl.get('tariff_type_code')}, rate={tl.get('base_rate')}")
        lpe = tl.get("logic_parameters_extra", {})
        if lpe:
            new_keys = ["billing_frequency", "escalation_frequency", "escalation_start_date", "tariff_components_to_adjust"]
            new_params = {k: v for k, v in lpe.items() if k in new_keys}
            if new_params:
                print(f"      NEW escalation params: {new_params}")

    # Show new contract fields
    print(f"\n  payment_terms: {preview.parsed_data.get('payment_terms')}")
    print(f"  ppa_confirmed_uploaded: {preview.parsed_data.get('ppa_confirmed_uploaded')}")
    print(f"  has_amendments: {preview.parsed_data.get('has_amendments')}")
    print(f"  billing_products: {preview.parsed_data.get('billing_products')}")

    # Phase B: Commit
    logger.info("Running commit...")
    result = service.commit(
        organization_id=ORGANIZATION_ID,
        preview_id=preview.preview_id,
        overrides={},
    )

    print("\n" + "=" * 70)
    print("COMMIT RESULT")
    print("=" * 70)
    print(f"  Success: {result.success}")
    print(f"  Project ID: {result.project_id}")
    print(f"  Contract ID: {result.contract_id}")
    print(f"  Warnings: {result.warnings}")
    print(f"  Counts: {result.counts}")
    print("=" * 70)

    return result


if __name__ == "__main__":
    parse_only_flag = "--parse-only" in sys.argv

    data = parse_only()

    if not parse_only_flag:
        print("\n\nProceeding to full onboarding (preview + commit)...")
        full_onboard()
    else:
        print("\n(Parse-only mode — skipping preview/commit)")
