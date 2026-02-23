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

import json
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

            disc_pct_display = int(discount_pct * 100) if discount_pct * 100 == int(discount_pct * 100) else float(discount_pct * 100)
            basis = (
                f"GRP per kWh less {disc_pct_display}% solar discount, "
                f"bounded by floor/ceiling (USD→local at monthly FX rate), "
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

        disc_pct_display = int(discount_pct * 100) if discount_pct * 100 == int(discount_pct * 100) else float(discount_pct * 100)
        annual_basis = (
            f"GRP per kWh less {disc_pct_display}% solar discount, "
            f"bounded by floor/ceiling (USD), converted at monthly FX rate"
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
            discount_pct=discount_pct,
            escalated_floor=escalated_floor,
            escalated_ceiling=escalated_ceiling,
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
                           ct.market_ref_currency_id,
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
        discount_pct: Decimal,
        escalated_floor: Decimal,
        escalated_ceiling: Decimal,
    ) -> dict:
        """Write results to exchange_rate, reference_price, and tariff_rate."""
        ct_id = tariff["id"]
        org_id = tariff["organization_id"]
        currency_id = tariff["currency_id"]
        project_id = tariff["project_id"]
        valid_from = tariff["valid_from"]

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    # Get currency IDs — resolve from clause_tariff metadata
                    cur.execute("SELECT id FROM currency WHERE code = 'USD'")
                    usd_row = cur.fetchone()
                    usd_currency_id = usd_row["id"] if usd_row else None

                    # hard = clause_tariff.currency_id (USD — contract/billing currency)
                    hard_ccy_from_tariff = currency_id
                    # local = market_ref_currency (GHS — local market currency where GRP is denominated)
                    local_ccy_from_tariff = tariff.get("market_ref_currency_id") or currency_id

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
                                local_ccy_from_tariff,
                                m["rate_date"],
                                m["fx_rate"],
                                "rebased_market_price_engine",
                            ),
                        )
                        fx_id_map[m["billing_month"]] = cur.fetchone()["id"]

                    # --- b. reference_price: annual GRP observation ---
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
                            local_ccy_from_tariff,
                            grp_totals.get("total_variable_charges"),
                            grp_totals.get("total_kwh_invoiced"),
                            verification_status,
                        ),
                    )
                    ref_price_id = cur.fetchone()["id"]

                    latest_month_date = max(m["billing_month"] for m in monthly_results)

                    # =============================================================
                    # c. tariff_rate: unified table
                    # =============================================================

                    # Currency FKs: hard=clause_tariff.currency_id (USD), local=market_ref (GHS), billing=local (GHS)
                    hard_ccy_id = hard_ccy_from_tariff
                    local_ccy_id = local_ccy_from_tariff
                    billing_ccy_id = local_ccy_from_tariff  # billing in local currency (GHS)

                    # --- c1. Annual row in tariff_rate ---
                    # For annual: representative_rate is discounted GRP in local ccy
                    # Convert to hard ccy using a reference FX rate (use latest month's rate)
                    latest_fx = monthly_results[-1]["fx_rate"]
                    annual_hard = (representative_rate / latest_fx).quantize(
                        Decimal("0.00000001"), rounding=ROUND_HALF_UP
                    ) if latest_fx else None

                    # Clear is_current on existing annual tariff_rate rows
                    cur.execute(
                        """
                        UPDATE tariff_rate SET is_current = false
                        WHERE clause_tariff_id = %s AND rate_granularity = 'annual' AND is_current = true
                        """,
                        (ct_id,),
                    )

                    cur.execute(
                        """
                        INSERT INTO tariff_rate (
                            clause_tariff_id, contract_year, rate_granularity,
                            period_start, period_end,
                            hard_currency_id, local_currency_id, billing_currency_id,
                            fx_rate_hard_id, fx_rate_local_id,
                            effective_rate_contract_ccy, effective_rate_hard_ccy,
                            effective_rate_local_ccy, effective_rate_billing_ccy,
                            effective_rate_contract_role,
                            calc_detail,
                            rate_binding,
                            reference_price_id, discount_pct_applied, formula_version,
                            calc_status, calculation_basis, is_current
                        ) VALUES (
                            %s, %s, 'annual',
                            %s, %s,
                            %s, %s, %s,
                            NULL, %s,
                            %s, %s, %s, %s,
                            'local',
                            NULL,
                            'fixed',
                            %s, %s, 'rebased_v1',
                            'computed', %s, true
                        )
                        ON CONFLICT (clause_tariff_id, contract_year)
                            WHERE rate_granularity = 'annual'
                        DO UPDATE SET
                            effective_rate_contract_ccy = EXCLUDED.effective_rate_contract_ccy,
                            effective_rate_hard_ccy = EXCLUDED.effective_rate_hard_ccy,
                            effective_rate_local_ccy = EXCLUDED.effective_rate_local_ccy,
                            effective_rate_billing_ccy = EXCLUDED.effective_rate_billing_ccy,
                            fx_rate_local_id = EXCLUDED.fx_rate_local_id,
                            reference_price_id = EXCLUDED.reference_price_id,
                            discount_pct_applied = EXCLUDED.discount_pct_applied,
                            calc_status = 'computed',
                            calculation_basis = EXCLUDED.calculation_basis,
                            is_current = true,
                            updated_at = NOW()
                        """,
                        (
                            ct_id, operating_year,
                            period_start, period_end,
                            hard_ccy_id, local_ccy_id, billing_ccy_id,
                            fx_id_map[latest_month_date],  # fx_rate_local_id = latest month's FX
                            representative_rate,   # contract_ccy = local
                            annual_hard,           # hard_ccy
                            representative_rate,   # local_ccy
                            representative_rate,   # billing_ccy = local
                            ref_price_id, discount_pct,
                            annual_basis,
                        ),
                    )

                    # Ensure only this annual row is current
                    cur.execute(
                        """
                        UPDATE tariff_rate SET is_current = false
                        WHERE clause_tariff_id = %s AND rate_granularity = 'annual'
                          AND contract_year != %s AND is_current = true
                        """,
                        (ct_id, operating_year),
                    )

                    # --- c2. Monthly rows in tariff_rate ---
                    # Clear is_current on existing monthly tariff_rate rows
                    cur.execute(
                        """
                        UPDATE tariff_rate SET is_current = false
                        WHERE clause_tariff_id = %s AND rate_granularity = 'monthly' AND is_current = true
                        """,
                        (ct_id,),
                    )

                    new_monthly_ids = []
                    for m in monthly_results:
                        is_current = (m["billing_month"] == latest_month_date)
                        fx_rate = m["fx_rate"]
                        fx_local_id = fx_id_map[m["billing_month"]]

                        # Look up monthly reference_price if it exists, else fall back to annual
                        cur.execute("""
                            SELECT id FROM reference_price
                            WHERE project_id = %s AND observation_type = 'monthly'
                              AND period_start = %s
                            LIMIT 1
                        """, (project_id, m["billing_month"]))
                        monthly_ref_row = cur.fetchone()
                        monthly_ref_id = monthly_ref_row["id"] if monthly_ref_row else ref_price_id

                        # Compute hard-currency values
                        eff_hard = (m["effective_tariff_local"] / fx_rate).quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ) if fx_rate else None

                        # Build calc_detail JSONB
                        floor_hard = (m["floor_local"] / fx_rate).quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ) if fx_rate else None
                        ceiling_hard = (m["ceiling_local"] / fx_rate).quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ) if fx_rate else None
                        disc_hard = (m["discounted_grp_local"] / fx_rate).quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ) if fx_rate else None

                        calc_detail = json.dumps({
                            "floor": {
                                "contract_ccy": float(floor_hard) if floor_hard else None,
                                "hard_ccy": float(floor_hard) if floor_hard else None,
                                "local_ccy": float(m["floor_local"]),
                                "billing_ccy": float(m["floor_local"]),
                                "contract_role": "hard",
                            },
                            "ceiling": {
                                "contract_ccy": float(ceiling_hard) if ceiling_hard else None,
                                "hard_ccy": float(ceiling_hard) if ceiling_hard else None,
                                "local_ccy": float(m["ceiling_local"]),
                                "billing_ccy": float(m["ceiling_local"]),
                                "contract_role": "hard",
                            },
                            "discounted_base": {
                                "contract_ccy": float(m["discounted_grp_local"]),
                                "hard_ccy": float(disc_hard) if disc_hard else None,
                                "local_ccy": float(m["discounted_grp_local"]),
                                "billing_ccy": float(m["discounted_grp_local"]),
                                "contract_role": "local",
                            },
                            "grp_per_kwh": float(grp_local),
                            "discount_pct": float(discount_pct),
                            "escalated_floor_usd": float(escalated_floor),
                            "escalated_ceiling_usd": float(escalated_ceiling),
                            "fx_rate": float(fx_rate),
                            "formula": "MAX(floor_local, MIN(discounted_base_local, ceiling_local))",
                        })

                        month_end = (m["billing_month"].replace(day=28) + timedelta(days=4))
                        month_end = month_end.replace(day=1) - timedelta(days=1)

                        cur.execute(
                            """
                            INSERT INTO tariff_rate (
                                clause_tariff_id, contract_year, rate_granularity,
                                billing_month, period_start, period_end,
                                hard_currency_id, local_currency_id, billing_currency_id,
                                fx_rate_hard_id, fx_rate_local_id,
                                effective_rate_contract_ccy, effective_rate_hard_ccy,
                                effective_rate_local_ccy, effective_rate_billing_ccy,
                                effective_rate_contract_role,
                                calc_detail,
                                rate_binding,
                                reference_price_id, discount_pct_applied, formula_version,
                                calc_status, calculation_basis, is_current
                            ) VALUES (
                                %s, %s, 'monthly',
                                %s, %s, %s,
                                %s, %s, %s,
                                NULL, %s,
                                %s, %s, %s, %s,
                                'local',
                                %s::jsonb,
                                %s,
                                %s, %s, 'rebased_v1',
                                'computed', %s, %s
                            )
                            ON CONFLICT (clause_tariff_id, billing_month)
                                WHERE rate_granularity = 'monthly'
                            DO UPDATE SET
                                fx_rate_local_id = EXCLUDED.fx_rate_local_id,
                                effective_rate_contract_ccy = EXCLUDED.effective_rate_contract_ccy,
                                effective_rate_hard_ccy = EXCLUDED.effective_rate_hard_ccy,
                                effective_rate_local_ccy = EXCLUDED.effective_rate_local_ccy,
                                effective_rate_billing_ccy = EXCLUDED.effective_rate_billing_ccy,
                                calc_detail = EXCLUDED.calc_detail,
                                rate_binding = EXCLUDED.rate_binding,
                                reference_price_id = EXCLUDED.reference_price_id,
                                discount_pct_applied = EXCLUDED.discount_pct_applied,
                                calc_status = 'computed',
                                calculation_basis = EXCLUDED.calculation_basis,
                                is_current = EXCLUDED.is_current,
                                updated_at = NOW()
                            RETURNING id
                            """,
                            (
                                ct_id, operating_year,
                                m["billing_month"], m["billing_month"], month_end,
                                hard_ccy_id, local_ccy_id, billing_ccy_id,
                                fx_local_id,
                                m["effective_tariff_local"],  # contract_ccy = local
                                eff_hard,                     # hard_ccy
                                m["effective_tariff_local"],  # local_ccy
                                m["effective_tariff_local"],  # billing_ccy = local
                                calc_detail,
                                m["rate_binding"],
                                monthly_ref_id, discount_pct,
                                m["calculation_basis"], is_current,
                            ),
                        )
                        new_monthly_ids.append(cur.fetchone()["id"])

                conn.commit()

                return {
                    "reference_price_id": ref_price_id,
                    "tariff_rate_monthly_ids": new_monthly_ids,
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
