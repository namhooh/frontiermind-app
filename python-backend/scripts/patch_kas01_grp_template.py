"""
One-time patch: Populate KAS01 tariff (id=11) with missing GRP template fields.

Uses MOH01 (tariff id=2) as the canonical GRP template. Adds fields that are
present in MOH01 but missing in KAS01, with KAS01-specific values extracted
from the contract PDF.

Source: CBE - KAS01_Kasapreko SSA Amendment Stamped_20170531 (Solar Africa).pdf

Fields added to clause_tariff.logic_parameters:
  - pricing_formula_text: From Part I pricing table and notes
  - shortfall_formula_type: "price_differential" (Section 3.3)
  - shortfall_formula_cap: No explicit cap in contract
  - shortfall_formula_variables: 5 variables from Section 3.3
  - degradation_pct: 0.004 (derived from Annexure D: 577→574.69 MWh)
  - escalation_start_date: 2018-09-30 (COD Sep 2017 + 1 year)
  - grp_verification_deadline_days: 30 (Part I: "one month prior")
  - billing_taxes: Ghana tax structure (same jurisdiction as MOH01)
  - annual_specific_yield: 1443 (577 MWh / 400 kWp)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.database import get_db_connection, init_connection_pool

TARIFF_ID = 11  # GH-KAS01 Main Tariff

GRP_TEMPLATE_FIELDS = {
    "pricing_formula_text": (
        "Payment = (1 − Fixed Solar Discount) × Energy Output × Current Grid Tariff\n\n"
        "subject to Floor:\n"
        "Payment ≥ Energy Output × Floor Solar Tariff (USD × FX Rate)\n\n"
        "Floor Solar Tariff escalates at 2.5% per annum from Operating Year 2\n"
        "All Demand Charge savings excluded from tariff-setting mechanism\n"
        "All Payments exclusive of Taxes"
    ),
    "shortfall_formula_type": "price_differential",
    "shortfall_formula_cap": "No explicit monetary cap stated in contract. Shortfall payment applies for each day below 355-day Availability Guarantee.",
    "shortfall_formula_variables": [
        {
            "symbol": "SP",
            "definition": "Shortfall Payment owed by Developer to Customer",
        },
        {
            "symbol": "P_Solar",
            "unit": "GHS/kWh",
            "definition": "Discounted Solar Tariff for the relevant Operating Year",
        },
        {
            "symbol": "P_Grid",
            "unit": "GHS/kWh",
            "definition": "Current Grid Tariff for the relevant Operating Year",
        },
        {
            "symbol": "E_daily_avg",
            "unit": "kWh",
            "definition": "Average daily production, defined as the daily fraction of the annual expected energy output (Annexure D) for the given Operating Year",
        },
        {
            "symbol": "Days_Shortfall",
            "unit": "days",
            "definition": "Number of days of shortfall in availability below the 355-day Availability Guarantee",
        },
    ],
    "degradation_pct": 0.004,
    "escalation_start_date": "2018-09-30",
    "grp_verification_deadline_days": 30,
    "billing_taxes": {
        "vat": {
            "code": "VAT",
            "name": "VAT",
            "rate": 0.15,
            "applies_to": {"base": "subtotal_after_levies"},
            "sort_order": 20,
        },
        "levies": [
            {
                "code": "NHIL",
                "name": "NHIL",
                "rate": 0.025,
                "applies_to": {"base": "energy_subtotal"},
                "sort_order": 10,
            },
            {
                "code": "GETFUND",
                "name": "GETFund",
                "rate": 0.025,
                "applies_to": {"base": "energy_subtotal"},
                "sort_order": 11,
            },
            {
                "code": "COVID",
                "name": "COVID Levy",
                "rate": 0.01,
                "applies_to": {"base": "energy_subtotal"},
                "sort_order": 12,
            },
        ],
        "withholdings": [
            {
                "code": "WHT",
                "name": "Withholding Tax",
                "rate": 0.03,
                "applies_to": {"base": "energy_subtotal"},
                "sort_order": 30,
            },
            {
                "code": "WHVAT",
                "name": "Withholding VAT",
                "rate": 0.07,
                "applies_to": {"base": "subtotal_after_levies"},
                "sort_order": 31,
            },
        ],
        "rounding_mode": "ROUND_HALF_UP",
        "effective_from": "2025-01-01",
        "rounding_precision": 2,
        "invoice_rate_precision": 4,
        "available_energy_line_mode": "per_meter",
    },
    "annual_specific_yield": 1443,
}


def main():
    init_connection_pool()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Verify tariff exists and show current state
            cur.execute(
                "SELECT id, name, logic_parameters FROM clause_tariff WHERE id = %s",
                (TARIFF_ID,),
            )
            row = cur.fetchone()
            if not row:
                print(f"ERROR: Tariff {TARIFF_ID} not found")
                return

            print(f"Found tariff: {row['name']}")
            existing_lp = row["logic_parameters"] or {}

            # Show which keys will be added vs already exist
            for k in GRP_TEMPLATE_FIELDS:
                status = "EXISTS (will overwrite)" if k in existing_lp else "NEW"
                print(f"  {k}: {status}")

            # Merge into logic_parameters
            cur.execute(
                """
                UPDATE clause_tariff
                SET logic_parameters = COALESCE(logic_parameters, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (json.dumps(GRP_TEMPLATE_FIELDS), TARIFF_ID),
            )
            result = cur.fetchone()
            conn.commit()

            print(f"\nUpdated tariff {result['id']} with GRP template fields:")
            for k, v in GRP_TEMPLATE_FIELDS.items():
                if isinstance(v, (list, dict)):
                    if isinstance(v, list):
                        print(f"  {k}: [{len(v)} items]")
                    else:
                        print(f"  {k}: {{...}}")
                else:
                    print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
