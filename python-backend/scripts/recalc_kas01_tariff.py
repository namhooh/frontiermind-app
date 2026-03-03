#!/usr/bin/env python3
"""
Recalculate KAS01 tariff using RebasedMarketPriceEngine.

1. Updates clause_tariff logic_parameters to engine-compatible format
   (PO Summary values: MRP=1.554, Discount=19.2%, Floor=0.0874 USD, Ceiling=0.3 USD)
2. Sets valid_from to initial Phase I COD (2018-10-03)
3. Runs the engine with available GHS FX rates for Year 8 (Oct 2025 – Oct 2026)

Usage:
    cd python-backend
    python scripts/recalc_kas01_tariff.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import get_db_connection, init_connection_pool, close_connection_pool
from services.tariff.rebased_market_price_engine import RebasedMarketPriceEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("recalc_kas01")

# ─── PO Summary values (KAS01 = GH 22010 Kasapreko Phase 1) ─────────────
PO_SUMMARY = {
    "mrp_ghs_kwh": 1.554,          # MRP (Grid/Fixed) = GRP
    "discount_pct": 0.192,          # 19.2%
    "solar_tariff_ghs": 1.255632,   # = MRP * (1 - discount)
    "floor_usd": 0.0874,            # Min Tariff (USD)
    "ceiling_usd": 0.3,             # Max Tariff (USD) — from cross-exam data
    "floor_escalation_pct": 0.025,  # Indexation 2.5%
}

PROJECT_ID = 53
CLAUSE_TARIFF_ID = 11
COD_DATE = date(2018, 10, 3)  # Phase I initial COD

# Year 8 = Oct 2025 – Oct 2026 (current period, we're in Mar 2026)
# Counting from initial COD: Year 1 = Oct 2018-Oct 2019, ..., Year 8 = Oct 2025-Oct 2026
OPERATING_YEAR = 8


def update_clause_tariff():
    """Update clause_tariff with engine-compatible logic_parameters."""
    new_lp = {
        # Engine-required keys
        "formula_type": "GRID_DISCOUNT_BOUNDED",
        "grp_method": "utility_variable_charges_tou",
        "discount_pct": PO_SUMMARY["discount_pct"],
        "floor_rate": PO_SUMMARY["floor_usd"],
        "ceiling_rate": PO_SUMMARY["ceiling_usd"],
        # Escalation rules (MOH01 pattern)
        "escalation_rules": [
            {
                "type": "FIXED",
                "value": PO_SUMMARY["floor_escalation_pct"],
                "component": "min_solar_price",
                "start_year": 2,
            },
            {
                "type": "NONE",
                "component": "max_solar_price",
            },
        ],
        # Preserve provenance
        "pricing_model": "discount_based",
        "recalculation_frequency": "annual",
        "po_summary_mrp_ghs": PO_SUMMARY["mrp_ghs_kwh"],
        "po_summary_solar_tariff_ghs": PO_SUMMARY["solar_tariff_ghs"],
    }

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE clause_tariff
                SET base_rate = %s,
                    logic_parameters = %s,
                    market_ref_currency_id = 5,
                    valid_from = %s
                WHERE id = %s
                RETURNING id, base_rate, valid_from
                """,
                (
                    PO_SUMMARY["solar_tariff_ghs"],
                    json.dumps(new_lp),
                    COD_DATE,
                    CLAUSE_TARIFF_ID,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            logger.info(f"Updated clause_tariff {row['id']}: base_rate={row['base_rate']}, valid_from={row['valid_from']}")
    return new_lp


def fetch_fx_rates():
    """Fetch GHS exchange rates that fall in Year 8 (Oct 2025 – Oct 2026)."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT er.rate, er.rate_date
                FROM exchange_rate er
                JOIN currency c ON c.id = er.currency_id
                WHERE c.code = 'GHS'
                  AND er.rate_date >= '2025-10-01'
                  AND er.rate_date < '2026-10-01'
                ORDER BY er.rate_date
            """)
            rows = cur.fetchall()

    monthly_fx = []
    for r in rows:
        rd = r["rate_date"]
        if hasattr(rd, "date"):
            rd = rd.date()
        monthly_fx.append({
            "billing_month": rd.replace(day=1),
            "fx_rate": float(r["rate"]),
            "rate_date": rd,
        })

    logger.info(f"Found {len(monthly_fx)} GHS FX rates for Year 8")
    for m in monthly_fx:
        logger.info(f"  {m['billing_month']}: FX={m['fx_rate']}")
    return monthly_fx


def main():
    init_connection_pool(min_connections=1, max_connections=3)

    try:
        # Step 1: Update logic_parameters + valid_from
        logger.info("Step 1: Updating clause_tariff logic_parameters + valid_from...")
        update_clause_tariff()

        # Step 1b: Update project.cod_date to initial Phase I COD
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE project SET cod_date = %s WHERE id = %s RETURNING id, cod_date",
                    (COD_DATE, PROJECT_ID),
                )
                row = cur.fetchone()
                conn.commit()
                logger.info(f"Updated project {row['id']}: cod_date={row['cod_date']}")

        # Step 2: Delete existing tariff_rate rows
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tariff_rate WHERE clause_tariff_id = %s",
                    (CLAUSE_TARIFF_ID,),
                )
                deleted = cur.rowcount
                conn.commit()
                logger.info(f"Cleared {deleted} existing tariff_rate rows")

        # Step 3: Fetch FX rates
        logger.info("Step 2: Fetching GHS exchange rates...")
        monthly_fx = fetch_fx_rates()

        if not monthly_fx:
            logger.error("No FX rates available for Year 8. Cannot calculate.")
            return

        # Step 4: Run the engine
        logger.info("Step 3: Running RebasedMarketPriceEngine...")
        engine = RebasedMarketPriceEngine()
        result = engine.calculate_and_store(
            project_id=PROJECT_ID,
            operating_year=OPERATING_YEAR,
            grp_per_kwh=PO_SUMMARY["mrp_ghs_kwh"],
            monthly_fx_rates=monthly_fx,
            verification_status="pending",
        )

        # Print results
        logger.info("=" * 60)
        logger.info("CALCULATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  GRP (MRP):              {result['grp_per_kwh']:.6f} GHS/kWh")
        logger.info(f"  Discount:               {result['discount_pct']*100:.1f}%")
        logger.info(f"  Solar Tariff (annual):   {result['representative_annual_rate']:.6f} GHS/kWh")
        logger.info(f"  Floor (USD, escalated):  {result['escalated_floor_usd']:.6f}")
        logger.info(f"  Ceiling (USD, escalated):{result['escalated_ceiling_usd']:.6f}")
        logger.info(f"  Final effective tariff:  {result['final_effective_tariff']:.6f} GHS/kWh")
        logger.info("")
        logger.info("  Monthly breakdown:")
        for m in result["monthly_breakdown"]:
            logger.info(
                f"    {m['billing_month']}: "
                f"FX={m['fx_rate']:.2f}  "
                f"floor={m['floor_ghs']:.6f}  "
                f"ceiling={m['ceiling_ghs']:.6f}  "
                f"effective={m['effective_tariff_ghs']:.6f}  "
                f"binding={m['rate_binding']}"
            )

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
