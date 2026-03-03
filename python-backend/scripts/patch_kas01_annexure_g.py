"""
One-time patch: Add Annexure G fields to KAS01 AVAILABILITY clause (id=337).

Source: CBE - KAS01_Kasapreko SSA Amendment Stamped_20170531 (Solar Africa).pdf
        Annexure G: Energy Output Calculation (page 39)

Fields added to normalized_payload:
  - available_energy_method: irradiance_interval_adjusted
  - irradiance_threshold_wm2: 100
  - interval_minutes: 15
  - calculation_method: E_Available(x) = (E_hist / Intervals) * (Irr(x) / Irr_hist)
  - monthly_production_formula: E_month = sum(E_metered(i)) + sum(E_Available(x))
  - excused_events: updated to include system_event, curtailed_operation

Also fixes threshold_unit: contract says "355 days", not percent.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.database import get_db_connection, init_connection_pool

CLAUSE_ID = 337
PROJECT_ID = 53
TARIFF_ID = 11  # GH-KAS01 Main Tariff

ANNEXURE_G_FIELDS = {
    "available_energy_method": "irradiance_interval_adjusted",
    "irradiance_threshold_wm2": 100,
    "interval_minutes": 15,
    "calculation_method": (
        "Actual Monthly Production: E_month = sum(E_metered(i)) + sum(E_Available(x)). "
        "Available Energy per 15-min interval: E_Available(x) = (E_hist / Intervals) * (Irr(x) / Irr_hist). "
        "E_hist = energy metered prior month during Normal Operation (irradiance > 100 W/m2). "
        "Intervals = count of 15-min intervals under Normal Operation prior month (irradiance > 100 W/m2). "
        "Irr_hist = avg in-plane irradiance prior month Normal Operation (> 100 W/m2). "
        "Irr(x) = in-plane irradiance averaged over 15-min interval x."
    ),
    "monthly_production_formula": "E_month = sum(E_metered(i)) + sum(E_Available(x))",
    "available_energy_formula": "E_Available(x) = (E_hist / Intervals) * (Irr(x) / Irr_hist)",
    "excused_events": [
        "force_majeure",
        "grid_curtailment",
        "scheduled_maintenance",
        "system_event",
        "curtailed_operation",
    ],
    # Fix: contract says 355 days, threshold_unit should be "days" not "percent"
    "threshold_unit": "days",
}


TARIFF_LP_FIELDS = {
    "available_energy_method": "irradiance_interval_adjusted",
    "irradiance_threshold_wm2": 100,
    "interval_minutes": 15,
    "excused_events": [
        "Customer acts or omissions causing curtailment",
        "Force Majeure events",
        "System Events",
        "Curtailed Operation",
        "Scheduled maintenance",
    ],
    "monthly_production_formula": "E_month = sum(E_metered(i)) + sum(E_Available(x))",
    "available_energy_formula": "E_Available(x) = (E_hist / Intervals) × (Irr(x) / Irr_hist)",
    "available_energy_variables": [
        {
            "symbol": "E_Available(x)",
            "definition": "Available Energy (kWh) for 15-minute interval x",
            "unit": "kWh",
        },
        {
            "symbol": "E_hist",
            "definition": "Energy measured by the billing meter for the previous calendar month during periods of Normal Operation where irradiance as measured by the onsite pyranometer is greater than 100 W/m²",
            "unit": "kWh",
        },
        {
            "symbol": "Intervals",
            "definition": "Total number of 15-minute intervals under Normal Operation during the previous calendar month where irradiance as measured by the onsite pyranometer is greater than 100 W/m²",
            "unit": None,
        },
        {
            "symbol": "Irr_hist",
            "definition": "Average in-plane irradiance measured for the previous calendar month during Normal Operation (where irradiance > 100 W/m²)",
            "unit": "kW/m²",
        },
        {
            "symbol": "Irr(x)",
            "definition": "In-plane irradiance measured by the onsite reference pyranometer and averaged over 15-minute interval x",
            "unit": "kW/m²",
        },
    ],
}


def main():
    init_connection_pool()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Verify clause exists
            cur.execute(
                "SELECT id, name, normalized_payload FROM clause WHERE id = %s AND project_id = %s",
                (CLAUSE_ID, PROJECT_ID),
            )
            row = cur.fetchone()
            if not row:
                print(f"ERROR: Clause {CLAUSE_ID} not found for project {PROJECT_ID}")
                return

            print(f"Found clause: {row['name']}")
            print(f"Current payload: {json.dumps(row['normalized_payload'], indent=2)}")

            # Merge: preserve existing keys, add/overwrite with Annexure G fields
            cur.execute(
                """
                UPDATE clause
                SET normalized_payload = COALESCE(normalized_payload, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s AND project_id = %s
                RETURNING id, normalized_payload
                """,
                (json.dumps(ANNEXURE_G_FIELDS), CLAUSE_ID, PROJECT_ID),
            )
            result = cur.fetchone()
            conn.commit()

            print(f"\nUpdated clause {result['id']}")
            print(f"New payload: {json.dumps(result['normalized_payload'], indent=2)}")

            # --- Step 2: Update tariff logic_parameters ---
            print(f"\n--- Updating tariff {TARIFF_ID} logic_parameters ---")

            cur.execute(
                "SELECT id, name, logic_parameters FROM clause_tariff WHERE id = %s",
                (TARIFF_ID,),
            )
            tariff_row = cur.fetchone()
            if not tariff_row:
                print(f"ERROR: Tariff {TARIFF_ID} not found")
                return

            print(f"Found tariff: {tariff_row['name']}")
            existing_lp = tariff_row["logic_parameters"] or {}
            ae_keys = [k for k in existing_lp if k.startswith("available_energy") or k in ("irradiance_threshold_wm2", "interval_minutes", "excused_events", "monthly_production_formula")]
            print(f"Existing Annexure G keys in LP: {ae_keys or '(none)'}")

            cur.execute(
                """
                UPDATE clause_tariff
                SET logic_parameters = COALESCE(logic_parameters, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (json.dumps(TARIFF_LP_FIELDS), TARIFF_ID),
            )
            tariff_result = cur.fetchone()
            conn.commit()

            print(f"Updated tariff {tariff_result['id']} with Annexure G logic_parameters")
            for k, v in TARIFF_LP_FIELDS.items():
                if k != "available_energy_variables":
                    print(f"  {k}: {v}")
                else:
                    print(f"  {k}: [{len(v)} variable definitions]")


if __name__ == "__main__":
    main()
