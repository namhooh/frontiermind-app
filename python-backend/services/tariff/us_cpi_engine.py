"""
US CPI Indexation Engine.

Computes effective rates for US_CPI escalation tariffs where the rate is
adjusted annually by the Consumer Price Index (CUUR0000SA0).

Two sub-types:
- base_rate: effective_rate = base_rate × (current_cpi / base_cpi)
- floor_ceiling: escalates USD floor/ceiling bounds by CPI factor;
  effective_rate = escalated_floor (conservative lower bound for annual summary)
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection

logger = logging.getLogger(__name__)

CPI_INDEX_CODE = "CUUR0000SA0"
QUANTIZE_4 = Decimal("0.0001")


class USCPIEngine:
    """Generate tariff_rate rows for US_CPI escalation tariffs."""

    def generate(
        self,
        project_id: int,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Main entry point. For each current clause_tariff with US_CPI escalation,
        compute annual rows for all operating years.

        Returns {"tariffs_processed": M, "periods_generated": N, "details": [...]}.
        """
        tariffs = self._fetch_tariffs(project_id)
        if not tariffs:
            logger.info(f"No US_CPI tariffs found for project {project_id}")
            return {"tariffs_processed": 0, "periods_generated": 0, "details": []}

        total_periods = 0
        details: List[Dict[str, Any]] = []

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    for t in tariffs:
                        n, detail = self._process_tariff(cur, t, force_refresh)
                        total_periods += n
                        details.append(detail)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        logger.info(
            f"CPI rate generation complete: {len(tariffs)} tariffs, "
            f"{total_periods} periods for project {project_id}"
        )
        return {
            "tariffs_processed": len(tariffs),
            "periods_generated": total_periods,
            "details": details,
        }

    def _fetch_tariffs(self, project_id: int) -> List[Dict[str, Any]]:
        """Fetch clause_tariff rows with US_CPI escalation type."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ct.id, ct.base_rate, ct.valid_from, ct.currency_id,
                           ct.logic_parameters, ct.organization_id, ct.project_id,
                           esc.code AS escalation_type_code,
                           c.contract_term_years,
                           p.cod_date
                    FROM clause_tariff ct
                    JOIN contract c ON ct.contract_id = c.id
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    JOIN project p ON p.id = ct.project_id
                    WHERE ct.project_id = %s
                      AND ct.is_current = true
                      AND esc.code = 'US_CPI'
                    """,
                    (project_id,),
                )
                return [dict(row) for row in cur.fetchall()]

    def _resolve_cpi_base(
        self, tariff: Dict[str, Any], cur
    ) -> Tuple[date, Decimal]:
        """
        Resolve CPI base date and value from logic_parameters.
        Falls back to COD month - 1 lookup in price_index if not set.
        """
        lp = tariff["logic_parameters"] or {}
        org_id = tariff["organization_id"]

        if lp.get("cpi_base_date") and lp.get("cpi_base_value"):
            return (
                date.fromisoformat(lp["cpi_base_date"]),
                Decimal(str(lp["cpi_base_value"])),
            )

        # Derive from COD - 1 month
        cod = tariff.get("cod_date")
        if not cod:
            raise ValueError(
                f"clause_tariff {tariff['id']}: no cpi_base_date in logic_parameters "
                f"and no cod_date on project"
            )
        if hasattr(cod, "date"):
            cod = cod.date()

        # COD month - 1
        if cod.month == 1:
            base_date = date(cod.year - 1, 12, 1)
        else:
            base_date = date(cod.year, cod.month - 1, 1)

        cpi_value = self._fetch_cpi_value(base_date, org_id, cur)
        if cpi_value is None:
            raise ValueError(
                f"clause_tariff {tariff['id']}: CPI not found for base date {base_date}"
            )
        return base_date, cpi_value

    def _fetch_cpi_value(
        self, reference_date: date, org_id: Optional[int], cur
    ) -> Optional[Decimal]:
        """Look up CPI index value for a given month.

        Falls back across organization_id: try exact match first, then org_id=1
        (platform-level), then any org.
        """
        candidates = [org_id] if org_id else []
        if org_id != 1:
            candidates.append(1)  # platform-level fallback

        for oid in candidates:
            cur.execute(
                """
                SELECT index_value FROM price_index
                WHERE index_code = %s AND reference_date = %s AND organization_id = %s
                """,
                (CPI_INDEX_CODE, reference_date, oid),
            )
            row = cur.fetchone()
            if row:
                return Decimal(str(row["index_value"]))
        return None

    def _get_cpi_for_oy(
        self,
        oy_year_num: int,
        cpi_base_date: date,
        org_id: int,
        cur,
    ) -> Tuple[date, Optional[Decimal], str]:
        """
        Get CPI value for an operating year.
        CPI reference month = base month anniversary: cpi_base_date + (N-1) years.

        Returns (cpi_date, cpi_value, status) where status is
        'computed' or 'pending'.
        """
        # Year 1 uses base CPI (handled by caller), Year N uses base month + (N-1) years
        cpi_date = _add_years(cpi_base_date, oy_year_num - 1)

        cpi_value = self._fetch_cpi_value(cpi_date, org_id, cur)
        if cpi_value is None:
            return cpi_date, None, "pending"
        return cpi_date, cpi_value, "computed"

    def _process_tariff(
        self, cur, tariff: Dict[str, Any], force_refresh: bool
    ) -> Tuple[int, Dict[str, Any]]:
        """Process a single US_CPI tariff. Returns (rows_inserted, detail_dict)."""
        ct_id = tariff["id"]
        lp = tariff["logic_parameters"] or {}
        subtype = lp.get("cpi_escalation_subtype", "base_rate")

        cpi_base_date, cpi_base_value = self._resolve_cpi_base(tariff, cur)

        if subtype == "floor_ceiling":
            return self._process_floor_ceiling_tariff(
                cur, tariff, cpi_base_date, cpi_base_value, force_refresh
            )
        else:
            return self._process_base_rate_tariff(
                cur, tariff, cpi_base_date, cpi_base_value, force_refresh
            )

    def _process_base_rate_tariff(
        self,
        cur,
        tariff: Dict[str, Any],
        cpi_base_date: date,
        cpi_base_value: Decimal,
        force_refresh: bool,
    ) -> Tuple[int, Dict[str, Any]]:
        """Generate annual tariff_rate rows for CPI base_rate subtype."""
        ct_id = tariff["id"]
        base_rate = Decimal(str(tariff["base_rate"]))
        currency_id = tariff["currency_id"]
        org_id = tariff["organization_id"]
        term_years = tariff["contract_term_years"] or 1
        valid_from = tariff["valid_from"]
        lp = tariff["logic_parameters"] or {}

        if hasattr(valid_from, "date"):
            valid_from = valid_from.date()

        oy_start_date = date.fromisoformat(lp["oy_start_date"]) if lp.get("oy_start_date") else valid_from
        if not oy_start_date:
            raise ValueError(f"clause_tariff {ct_id}: no valid_from or oy_start_date")

        today = date.today()

        # Clear is_current on existing annual rows
        cur.execute(
            """
            UPDATE tariff_rate SET is_current = false
            WHERE clause_tariff_id = %s AND rate_granularity = 'annual' AND is_current = true
            """,
            (ct_id,),
        )

        inserted = 0
        year_details = []

        for year in range(1, term_years + 1):
            p_start = _add_years(oy_start_date, year - 1)
            if year < term_years:
                p_end = _add_years(oy_start_date, year) - timedelta(days=1)
            else:
                p_end = None

            is_current = p_start <= today and (p_end is None or today <= p_end)

            if year == 1:
                # Year 1: no escalation
                effective_rate = base_rate
                calc_status = "computed"
                calc_detail = {
                    "source": "us_cpi_v1",
                    "subtype": "base_rate",
                    "base_rate": float(base_rate),
                    "formula": "Year 1: no CPI escalation",
                }
                basis = "Year 1: original contractual base rate"
            else:
                cpi_date, cpi_value, status = self._get_cpi_for_oy(
                    year, cpi_base_date, org_id, cur
                )
                if cpi_value is not None:
                    cpi_factor = (cpi_value / cpi_base_value).quantize(
                        QUANTIZE_4, rounding=ROUND_HALF_UP
                    )
                    effective_rate = (base_rate * cpi_factor).quantize(
                        QUANTIZE_4, rounding=ROUND_HALF_UP
                    )
                    calc_status = status
                else:
                    # CPI not yet available — use base_rate as provisional
                    cpi_factor = Decimal("1")
                    effective_rate = base_rate
                    calc_status = "pending"
                    cpi_value = None

                calc_detail = {
                    "source": "us_cpi_v1",
                    "subtype": "base_rate",
                    "base_rate": float(base_rate),
                    "base_cpi_date": str(cpi_base_date),
                    "base_cpi_value": float(cpi_base_value),
                    "current_cpi_date": str(cpi_date),
                    "current_cpi_value": float(cpi_value) if cpi_value else None,
                    "cpi_factor": float(cpi_factor),
                    "formula": "base_rate × (current_cpi / base_cpi)",
                }
                basis = (
                    f"Year {year}: {base_rate} × ({cpi_value or '?'} / {cpi_base_value}) "
                    f"= {effective_rate}"
                )

            year_details.append({
                "year": year,
                "effective_rate": float(effective_rate),
                "calc_status": calc_status,
            })

            cur.execute(
                """
                INSERT INTO tariff_rate (
                    clause_tariff_id, contract_year, rate_granularity,
                    period_start, period_end,
                    hard_currency_id, local_currency_id, billing_currency_id,
                    effective_rate_contract_ccy, effective_rate_hard_ccy,
                    effective_rate_local_ccy, effective_rate_billing_ccy,
                    effective_rate_contract_role,
                    calc_detail,
                    rate_binding, formula_version,
                    calc_status, calculation_basis, is_current
                ) VALUES (
                    %s, %s, 'annual',
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    'hard',
                    %s::jsonb,
                    'fixed', 'us_cpi_v1',
                    %s, %s, %s
                )
                ON CONFLICT (clause_tariff_id, contract_year)
                    WHERE rate_granularity = 'annual'
                DO UPDATE SET
                    effective_rate_contract_ccy = EXCLUDED.effective_rate_contract_ccy,
                    effective_rate_hard_ccy = EXCLUDED.effective_rate_hard_ccy,
                    effective_rate_local_ccy = EXCLUDED.effective_rate_local_ccy,
                    effective_rate_billing_ccy = EXCLUDED.effective_rate_billing_ccy,
                    calc_detail = EXCLUDED.calc_detail,
                    calc_status = EXCLUDED.calc_status,
                    calculation_basis = EXCLUDED.calculation_basis,
                    is_current = EXCLUDED.is_current,
                    period_start = EXCLUDED.period_start,
                    period_end = EXCLUDED.period_end,
                    updated_at = NOW()
                """,
                (
                    ct_id, year,
                    p_start, p_end,
                    currency_id, currency_id, currency_id,
                    effective_rate, effective_rate, effective_rate, effective_rate,
                    json.dumps(calc_detail),
                    calc_status, basis, is_current,
                ),
            )
            inserted += cur.rowcount

        detail = {
            "clause_tariff_id": ct_id,
            "subtype": "base_rate",
            "years_generated": len(year_details),
            "year_details": year_details,
        }
        return inserted, detail

    def _process_floor_ceiling_tariff(
        self,
        cur,
        tariff: Dict[str, Any],
        cpi_base_date: date,
        cpi_base_value: Decimal,
        force_refresh: bool,
    ) -> Tuple[int, Dict[str, Any]]:
        """Generate annual tariff_rate rows for CPI floor_ceiling subtype."""
        ct_id = tariff["id"]
        currency_id = tariff["currency_id"]
        org_id = tariff["organization_id"]
        term_years = tariff["contract_term_years"] or 1
        valid_from = tariff["valid_from"]
        lp = tariff["logic_parameters"] or {}

        if hasattr(valid_from, "date"):
            valid_from = valid_from.date()

        oy_start_date = date.fromisoformat(lp["oy_start_date"]) if lp.get("oy_start_date") else valid_from
        if not oy_start_date:
            raise ValueError(f"clause_tariff {ct_id}: no valid_from or oy_start_date")

        floor_rate = Decimal(str(lp.get("floor_rate", 0)))
        ceiling_rate = Decimal(str(lp.get("ceiling_rate", 0)))

        today = date.today()

        # Clear is_current on existing annual rows
        cur.execute(
            """
            UPDATE tariff_rate SET is_current = false
            WHERE clause_tariff_id = %s AND rate_granularity = 'annual' AND is_current = true
            """,
            (ct_id,),
        )

        inserted = 0
        year_details = []
        latest_escalated_floor = None
        latest_escalated_ceiling = None

        for year in range(1, term_years + 1):
            p_start = _add_years(oy_start_date, year - 1)
            if year < term_years:
                p_end = _add_years(oy_start_date, year) - timedelta(days=1)
            else:
                p_end = None

            is_current = p_start <= today and (p_end is None or today <= p_end)

            if year == 1:
                escalated_floor = floor_rate
                escalated_ceiling = ceiling_rate
                effective_rate = escalated_floor  # conservative lower bound
                calc_status = "computed"
                calc_detail = {
                    "source": "us_cpi_v1",
                    "subtype": "floor_ceiling",
                    "base_floor_usd": float(floor_rate),
                    "base_ceiling_usd": float(ceiling_rate),
                    "escalated_floor_usd": float(escalated_floor),
                    "escalated_ceiling_usd": float(escalated_ceiling),
                    "formula": "Year 1: no CPI escalation on floor/ceiling",
                }
                basis = "Year 1: original contractual floor/ceiling"
            else:
                cpi_date, cpi_value, status = self._get_cpi_for_oy(
                    year, cpi_base_date, org_id, cur
                )
                if cpi_value is not None:
                    cpi_factor = (cpi_value / cpi_base_value).quantize(
                        QUANTIZE_4, rounding=ROUND_HALF_UP
                    )
                    escalated_floor = (floor_rate * cpi_factor).quantize(
                        QUANTIZE_4, rounding=ROUND_HALF_UP
                    )
                    escalated_ceiling = (ceiling_rate * cpi_factor).quantize(
                        QUANTIZE_4, rounding=ROUND_HALF_UP
                    )
                    calc_status = status
                else:
                    cpi_factor = Decimal("1")
                    escalated_floor = floor_rate
                    escalated_ceiling = ceiling_rate
                    calc_status = "pending"
                    cpi_value = None

                effective_rate = escalated_floor  # conservative lower bound

                calc_detail = {
                    "source": "us_cpi_v1",
                    "subtype": "floor_ceiling",
                    "base_floor_usd": float(floor_rate),
                    "base_ceiling_usd": float(ceiling_rate),
                    "base_cpi_date": str(cpi_base_date),
                    "base_cpi_value": float(cpi_base_value),
                    "current_cpi_date": str(cpi_date),
                    "current_cpi_value": float(cpi_value) if cpi_value else None,
                    "cpi_factor": float(cpi_factor),
                    "escalated_floor_usd": float(escalated_floor),
                    "escalated_ceiling_usd": float(escalated_ceiling),
                    "formula": "floor/ceiling × (current_cpi / base_cpi)",
                }
                basis = (
                    f"Year {year}: floor {floor_rate}→{escalated_floor}, "
                    f"ceiling {ceiling_rate}→{escalated_ceiling} "
                    f"(CPI factor {cpi_factor})"
                )

            if is_current:
                latest_escalated_floor = escalated_floor
                latest_escalated_ceiling = escalated_ceiling

            year_details.append({
                "year": year,
                "escalated_floor": float(escalated_floor),
                "escalated_ceiling": float(escalated_ceiling),
                "effective_rate": float(effective_rate),
                "calc_status": calc_status,
            })

            cur.execute(
                """
                INSERT INTO tariff_rate (
                    clause_tariff_id, contract_year, rate_granularity,
                    period_start, period_end,
                    hard_currency_id, local_currency_id, billing_currency_id,
                    effective_rate_contract_ccy, effective_rate_hard_ccy,
                    effective_rate_local_ccy, effective_rate_billing_ccy,
                    effective_rate_contract_role,
                    calc_detail,
                    rate_binding, formula_version,
                    calc_status, calculation_basis, is_current
                ) VALUES (
                    %s, %s, 'annual',
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    'hard',
                    %s::jsonb,
                    'fixed', 'us_cpi_v1',
                    %s, %s, %s
                )
                ON CONFLICT (clause_tariff_id, contract_year)
                    WHERE rate_granularity = 'annual'
                DO UPDATE SET
                    effective_rate_contract_ccy = EXCLUDED.effective_rate_contract_ccy,
                    effective_rate_hard_ccy = EXCLUDED.effective_rate_hard_ccy,
                    effective_rate_local_ccy = EXCLUDED.effective_rate_local_ccy,
                    effective_rate_billing_ccy = EXCLUDED.effective_rate_billing_ccy,
                    calc_detail = EXCLUDED.calc_detail,
                    calc_status = EXCLUDED.calc_status,
                    calculation_basis = EXCLUDED.calculation_basis,
                    is_current = EXCLUDED.is_current,
                    period_start = EXCLUDED.period_start,
                    period_end = EXCLUDED.period_end,
                    updated_at = NOW()
                """,
                (
                    ct_id, year,
                    p_start, p_end,
                    currency_id, currency_id, currency_id,
                    effective_rate, effective_rate, effective_rate, effective_rate,
                    json.dumps(calc_detail),
                    calc_status, basis, is_current,
                ),
            )
            inserted += cur.rowcount

        # Write escalated floor/ceiling to logic_parameters for rebased engine integration
        if latest_escalated_floor is not None:
            cur.execute(
                """
                UPDATE clause_tariff
                SET logic_parameters = logic_parameters
                    || %s::jsonb
                WHERE id = %s
                """,
                (
                    json.dumps({
                        "cpi_escalated_floor": float(latest_escalated_floor),
                        "cpi_escalated_ceiling": float(latest_escalated_ceiling),
                    }),
                    ct_id,
                ),
            )

        detail = {
            "clause_tariff_id": ct_id,
            "subtype": "floor_ceiling",
            "years_generated": len(year_details),
            "year_details": year_details,
        }
        return inserted, detail


def _add_years(d: date, years: int) -> date:
    """Add N years to a date, handling Feb 29 → Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
