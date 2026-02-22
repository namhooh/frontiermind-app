"""
Rebased Market Price Engine.

Computes effective rates for REBASED_MARKET_PRICE tariffs where the rate is
rebased annually to the Grid Reference Price (GRP) from utility invoices.

The formula is dispatched via `formula_type` in logic_parameters — different
projects can use different formula implementations. Floor/ceiling are re-evaluated
monthly because USD→GHS conversion uses that month's FX rate.

GHS is the system of record: GRP is in GHS, floor/ceiling are converted from USD
to GHS at the monthly FX rate. USD billing amounts are derived from the GHS rate.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from db.database import get_db_connection
from services.calculations.grid_reference_price import calculate_grp

logger = logging.getLogger(__name__)


# =============================================================================
# Formula Registry
# =============================================================================

def _formula_grid_discount_bounded(
    grp_local: Decimal,
    discount_pct: Decimal,
    floor_local: Decimal,
    ceiling_local: Decimal,
) -> tuple[Decimal, str]:
    """
    effective = MAX(floor, MIN(GRP × (1 - discount), ceiling))

    Returns (effective_rate, rate_binding).
    """
    discounted = grp_local * (1 - discount_pct)

    if discounted <= floor_local:
        return floor_local, "floor"
    elif discounted >= ceiling_local:
        return ceiling_local, "ceiling"
    else:
        return discounted, "discounted"


FORMULA_REGISTRY = {
    "GRID_DISCOUNT_BOUNDED": _formula_grid_discount_bounded,
}


# =============================================================================
# Component Escalation
# =============================================================================

def _escalate_component(
    base_value: Decimal,
    operating_year: int,
    escalation_rules: List[dict],
    component_name: str,
) -> Decimal:
    """
    Escalate a component (e.g. floor/ceiling) based on escalation_rules from
    logic_parameters.

    Each rule: {"component": str, "escalation_type": str, "escalation_value": float, "start_year": int}
    - FIXED = compound percentage per year
    - ABSOLUTE = flat amount added per year
    - NONE = no escalation
    """
    rule = None
    for r in escalation_rules:
        if r.get("component") == component_name:
            rule = r
            break

    if rule is None:
        return base_value

    # Support both canonical keys (escalation_type/escalation_value) and
    # legacy keys (type/value) found in existing DB data
    esc_type = rule.get("escalation_type") or rule.get("type", "NONE")
    if esc_type == "NONE":
        return base_value

    start_year = rule.get("start_year", 2)
    if operating_year < start_year:
        return base_value

    esc_value = Decimal(str(rule.get("escalation_value") or rule.get("value", 0)))
    years_escalated = operating_year - start_year

    if esc_type == "FIXED":
        # Compound percentage: base × (1 + pct)^years
        multiplier = (1 + esc_value) ** years_escalated
        return (base_value * multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    if esc_type == "ABSOLUTE":
        # Flat amount per year
        return base_value + esc_value * years_escalated

    return base_value


# =============================================================================
# Engine
# =============================================================================

class RebasedMarketPriceEngine:
    """Calculate and store rebased market price tariff rates."""

    def calculate_and_store(
        self,
        project_id: int,
        operating_year: int,
        grp_per_kwh: Optional[float] = None,
        invoice_line_items: Optional[List[dict]] = None,
        monthly_fx_rates: Optional[List[Dict[str, Any]]] = None,
        verification_status: str = "pending",
    ) -> dict:
        """
        Calculate rebased rate for a project/year and write to DB.

        Args:
            project_id: Project ID
            operating_year: Contract operating year (>= 2)
            grp_per_kwh: Pre-calculated GRP in local currency/kWh. If None,
                         calculated from invoice_line_items.
            invoice_line_items: Utility invoice line items for GRP calculation.
            monthly_fx_rates: List of {billing_month: date, fx_rate: float, rate_date: date}.
                              One per billing month in the contract year (1-12).
            verification_status: Status for the reference_price row.

        Returns:
            Dict with annual summary + monthly breakdowns + inserted IDs.
        """
        if not monthly_fx_rates:
            raise ValueError("monthly_fx_rates is required (1-12 entries)")

        # 1. Fetch clause_tariff
        tariff = self._fetch_tariff(project_id)
        lp = tariff["logic_parameters"] or {}

        # 2. Validate logic_parameters
        self._validate_logic_parameters(lp)

        formula_type = lp["formula_type"]
        discount_pct = Decimal(str(lp["discount_pct"]))
        base_floor = Decimal(str(lp["floor_rate"]))
        base_ceiling = Decimal(str(lp["ceiling_rate"]))
        escalation_rules = lp.get("escalation_rules", [])

        # 3. Calculate or use provided GRP
        grp_local: Optional[Decimal] = None
        grp_totals: Dict[str, Any] = {}

        if grp_per_kwh is not None:
            grp_local = Decimal(str(grp_per_kwh))
        elif invoice_line_items:
            grp_local = calculate_grp(lp, invoice_line_items)
            if grp_local is None:
                raise ValueError("GRP calculation returned None — insufficient invoice data")
            # Capture totals for reference_price
            total_charges = sum(
                Decimal(str(item.get("line_total_amount", 0) or 0))
                for item in invoice_line_items
                if item.get("invoice_line_item_type_code") == "VARIABLE_ENERGY"
            )
            total_kwh = sum(
                Decimal(str(item.get("quantity", 0) or 0))
                for item in invoice_line_items
                if item.get("invoice_line_item_type_code") == "VARIABLE_ENERGY"
            )
            grp_totals = {
                "total_variable_charges": total_charges,
                "total_kwh_invoiced": total_kwh,
            }
        else:
            raise ValueError("Either grp_per_kwh or invoice_line_items must be provided")

        # 4. Escalate floor/ceiling
        escalated_floor = _escalate_component(base_floor, operating_year, escalation_rules, "min_solar_price")
        escalated_ceiling = _escalate_component(base_ceiling, operating_year, escalation_rules, "max_solar_price")

        # 5. Calculate discounted GRP (constant for the year — GRP and discount don't vary monthly)
        discounted_grp = grp_local * (1 - discount_pct)

        # 6. For each billing month: convert floor/ceiling USD→GHS, apply formula
        monthly_results = []
        formula_fn = FORMULA_REGISTRY[formula_type]

        for fx_entry in sorted(monthly_fx_rates, key=lambda x: x["billing_month"]):
            billing_month = fx_entry["billing_month"]
            if isinstance(billing_month, str):
                billing_month = date.fromisoformat(billing_month)
            fx_rate = Decimal(str(fx_entry["fx_rate"]))
            rate_date = fx_entry["rate_date"]
            if isinstance(rate_date, str):
                rate_date = date.fromisoformat(rate_date)

            floor_ghs = (escalated_floor * fx_rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            ceiling_ghs = (escalated_ceiling * fx_rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

            effective_rate, rate_binding = formula_fn(
                grp_local=grp_local,
                discount_pct=discount_pct,
                floor_local=floor_ghs,
                ceiling_local=ceiling_ghs,
            )

            effective_rate = effective_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

            basis = (
                f"GRP={grp_local}, disc={discount_pct}, "
                f"floor_usd={escalated_floor}→GHS={floor_ghs} (FX={fx_rate}), "
                f"ceil_usd={escalated_ceiling}→GHS={ceiling_ghs}, "
                f"binding={rate_binding}"
            )

            monthly_results.append({
                "billing_month": billing_month,
                "fx_rate": fx_rate,
                "rate_date": rate_date,
                "floor_local": floor_ghs,
                "ceiling_local": ceiling_ghs,
                "discounted_grp_local": discounted_grp.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                "effective_tariff_local": effective_rate,
                "rate_binding": rate_binding,
                "calculation_basis": basis,
            })

        # 7. Determine representative annual rate + final effective tariff
        # Representative annual rate = discounted GRP (before floor/ceiling — the annual anchor)
        representative_rate = discounted_grp.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        # Final effective tariff = latest monthly effective rate
        latest_month = monthly_results[-1]
        final_effective_tariff = latest_month["effective_tariff_local"]

        annual_basis = (
            f"REBASED_MARKET_PRICE Y{operating_year}: "
            f"GRP={grp_local}/kWh, discount={discount_pct}, "
            f"floor_usd={escalated_floor}, ceiling_usd={escalated_ceiling}, "
            f"formula={formula_type}, months={len(monthly_results)}"
        )

        # 8. Write to DB in a single transaction
        result = self._write_to_db(
            tariff=tariff,
            operating_year=operating_year,
            grp_local=grp_local,
            grp_totals=grp_totals,
            verification_status=verification_status,
            representative_rate=representative_rate,
            final_effective_tariff=final_effective_tariff,
            annual_basis=annual_basis,
            monthly_results=monthly_results,
        )

        logger.info(
            f"Rebased rate calculated for project {project_id} year {operating_year}: "
            f"GRP={grp_local}, final_effective_tariff={final_effective_tariff}, "
            f"months={len(monthly_results)}"
        )

        return {
            "success": True,
            "project_id": project_id,
            "operating_year": operating_year,
            "grp_per_kwh": float(grp_local),
            "discount_pct": float(discount_pct),
            "escalated_floor_usd": float(escalated_floor),
            "escalated_ceiling_usd": float(escalated_ceiling),
            "representative_annual_rate": float(representative_rate),
            "final_effective_tariff": float(final_effective_tariff),
            "final_effective_tariff_source": "monthly",
            "formula_type": formula_type,
            "monthly_breakdown": [
                {
                    "billing_month": str(m["billing_month"]),
                    "fx_rate": float(m["fx_rate"]),
                    "floor_ghs": float(m["floor_local"]),
                    "ceiling_ghs": float(m["ceiling_local"]),
                    "discounted_grp_ghs": float(m["discounted_grp_local"]),
                    "effective_tariff_ghs": float(m["effective_tariff_local"]),
                    "rate_binding": m["rate_binding"],
                }
                for m in monthly_results
            ],
            **result,
        }

    # =========================================================================
    # Private methods
    # =========================================================================

    def _fetch_tariff(self, project_id: int) -> dict:
        """Fetch the REBASED_MARKET_PRICE clause_tariff for a project."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ct.id, ct.base_rate, ct.valid_from, ct.currency_id,
                           ct.logic_parameters, ct.organization_id, ct.project_id,
                           esc.code AS escalation_type_code,
                           c.contract_term_years
                    FROM clause_tariff ct
                    JOIN contract c ON ct.contract_id = c.id
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s
                      AND ct.is_current = true
                      AND esc.code = 'REBASED_MARKET_PRICE'
                    """,
                    (project_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(
                        f"No REBASED_MARKET_PRICE tariff found for project {project_id}"
                    )
                return dict(row)

    def _validate_logic_parameters(self, lp: dict) -> None:
        """Validate required keys in logic_parameters."""
        required = ["formula_type", "discount_pct", "floor_rate", "ceiling_rate"]
        missing = [k for k in required if k not in lp]
        if missing:
            raise ValueError(f"logic_parameters missing required keys: {missing}")

        formula_type = lp["formula_type"]
        if formula_type not in FORMULA_REGISTRY:
            raise ValueError(
                f"Unknown formula_type: {formula_type}. "
                f"Available: {list(FORMULA_REGISTRY.keys())}"
            )

    def _write_to_db(
        self,
        tariff: dict,
        operating_year: int,
        grp_local: Decimal,
        grp_totals: dict,
        verification_status: str,
        representative_rate: Decimal,
        final_effective_tariff: Decimal,
        annual_basis: str,
        monthly_results: List[dict],
    ) -> dict:
        """Write results to exchange_rate, reference_price, tariff_annual_rate, tariff_monthly_rate."""
        ct_id = tariff["id"]
        org_id = tariff["organization_id"]
        currency_id = tariff["currency_id"]
        project_id = tariff["project_id"]
        valid_from = tariff["valid_from"]

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    # Get currency_id for GHS (for FX rates)
                    cur.execute(
                        "SELECT id FROM currency WHERE code = 'GHS'"
                    )
                    ghs_row = cur.fetchone()
                    ghs_currency_id = ghs_row["id"] if ghs_row else None

                    # --- a. exchange_rate: 1 row per month ---
                    fx_id_map = {}  # billing_month -> exchange_rate.id
                    for m in monthly_results:
                        cur.execute(
                            """
                            INSERT INTO exchange_rate
                                (organization_id, currency_id, rate_date, rate, source)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (organization_id, currency_id, rate_date)
                            DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
                            RETURNING id
                            """,
                            (
                                org_id,
                                ghs_currency_id,
                                m["rate_date"],
                                m["fx_rate"],
                                "rebased_market_price_engine",
                            ),
                        )
                        fx_id_map[m["billing_month"]] = cur.fetchone()["id"]

                    # --- b. reference_price: annual GRP observation ---
                    # Derive period_start/end from valid_from + operating_year
                    if hasattr(valid_from, "date"):
                        valid_from = valid_from.date()

                    period_start = _add_years(valid_from, operating_year - 1)
                    period_end = _add_years(valid_from, operating_year) - timedelta(days=1)

                    cur.execute(
                        """
                        INSERT INTO reference_price
                            (project_id, organization_id, operating_year, period_start,
                             period_end, calculated_grp_per_kwh, currency_id,
                             total_variable_charges, total_kwh_invoiced,
                             verification_status, observation_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'annual')
                        ON CONFLICT (project_id, operating_year)
                            WHERE observation_type = 'annual'
                        DO UPDATE SET
                            calculated_grp_per_kwh = EXCLUDED.calculated_grp_per_kwh,
                            period_start = EXCLUDED.period_start,
                            period_end = EXCLUDED.period_end,
                            total_variable_charges = EXCLUDED.total_variable_charges,
                            total_kwh_invoiced = EXCLUDED.total_kwh_invoiced,
                            verification_status = EXCLUDED.verification_status,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (
                            project_id,
                            org_id,
                            operating_year,
                            period_start,
                            period_end,
                            grp_local,
                            ghs_currency_id,
                            grp_totals.get("total_variable_charges"),
                            grp_totals.get("total_kwh_invoiced"),
                            verification_status,
                        ),
                    )
                    ref_price_id = cur.fetchone()["id"]

                    # --- c. tariff_annual_rate: annual anchor row ---
                    # Clear is_current on existing rows
                    cur.execute(
                        "UPDATE tariff_annual_rate SET is_current = false WHERE clause_tariff_id = %s AND is_current = true",
                        (ct_id,),
                    )

                    cur.execute(
                        """
                        INSERT INTO tariff_annual_rate
                            (clause_tariff_id, contract_year, period_start, period_end,
                             effective_tariff, currency_id, calculation_basis, is_current,
                             final_effective_tariff, final_effective_tariff_source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, 'monthly')
                        ON CONFLICT (clause_tariff_id, contract_year)
                        DO UPDATE SET
                            effective_tariff = EXCLUDED.effective_tariff,
                            calculation_basis = EXCLUDED.calculation_basis,
                            is_current = true,
                            final_effective_tariff = EXCLUDED.final_effective_tariff,
                            final_effective_tariff_source = EXCLUDED.final_effective_tariff_source
                        RETURNING id
                        """,
                        (
                            ct_id,
                            operating_year,
                            period_start,
                            period_end,
                            representative_rate,
                            currency_id,
                            annual_basis,
                            final_effective_tariff,
                        ),
                    )
                    annual_rate_id = cur.fetchone()["id"]

                    # Ensure only this row is current
                    cur.execute(
                        """
                        UPDATE tariff_annual_rate
                        SET is_current = false
                        WHERE clause_tariff_id = %s AND id != %s AND is_current = true
                        """,
                        (ct_id, annual_rate_id),
                    )

                    # --- d. tariff_monthly_rate: up to 12 rows ---
                    # Clear is_current on existing monthly rows for this annual rate
                    cur.execute(
                        "UPDATE tariff_monthly_rate SET is_current = false WHERE tariff_annual_rate_id = %s AND is_current = true",
                        (annual_rate_id,),
                    )

                    monthly_ids = []
                    latest_month_date = max(m["billing_month"] for m in monthly_results)

                    for m in monthly_results:
                        is_current = (m["billing_month"] == latest_month_date)

                        cur.execute(
                            """
                            INSERT INTO tariff_monthly_rate
                                (tariff_annual_rate_id, exchange_rate_id, billing_month,
                                 floor_local, ceiling_local, discounted_grp_local,
                                 effective_tariff_local, rate_binding, calculation_basis,
                                 is_current)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (tariff_annual_rate_id, billing_month)
                            DO UPDATE SET
                                exchange_rate_id = EXCLUDED.exchange_rate_id,
                                floor_local = EXCLUDED.floor_local,
                                ceiling_local = EXCLUDED.ceiling_local,
                                discounted_grp_local = EXCLUDED.discounted_grp_local,
                                effective_tariff_local = EXCLUDED.effective_tariff_local,
                                rate_binding = EXCLUDED.rate_binding,
                                calculation_basis = EXCLUDED.calculation_basis,
                                is_current = EXCLUDED.is_current
                            RETURNING id
                            """,
                            (
                                annual_rate_id,
                                fx_id_map[m["billing_month"]],
                                m["billing_month"],
                                m["floor_local"],
                                m["ceiling_local"],
                                m["discounted_grp_local"],
                                m["effective_tariff_local"],
                                m["rate_binding"],
                                m["calculation_basis"],
                                is_current,
                            ),
                        )
                        monthly_ids.append(cur.fetchone()["id"])

                conn.commit()

                return {
                    "reference_price_id": ref_price_id,
                    "tariff_annual_rate_id": annual_rate_id,
                    "tariff_monthly_rate_ids": monthly_ids,
                    "exchange_rate_ids": list(fx_id_map.values()),
                }

            except Exception:
                conn.rollback()
                raise


def _add_years(d: date, years: int) -> date:
    """Add N years to a date, handling Feb 29 → Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
