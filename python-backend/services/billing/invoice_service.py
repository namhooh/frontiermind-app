"""
Invoice Generation Service.

Extracts core invoice generation logic from api/billing.py generate_expected_invoice
handler into a reusable service. The API handler becomes a thin wrapper.

Writes atomically to expected_invoice_header and expected_invoice_line_item.
Supports versioning: if a current invoice exists, it's superseded.
"""

import json
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_FLOOR, ROUND_CEILING, InvalidOperation
from typing import Any, Dict, Optional

from db.database import get_db_connection

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-2 lookup from full country name
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "ghana": "GH", "kenya": "KE", "nigeria": "NG", "south africa": "ZA",
    "egypt": "EG", "madagascar": "MG", "sierra leone": "SL", "somalia": "SO",
    "mozambique": "MZ", "zimbabwe": "ZW", "drc": "CD", "rwanda": "RW",
}

_ROUNDING_MODES: dict[str, str] = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
}


def _country_to_code(country_name: str | None) -> str | None:
    if not country_name:
        return None
    return _COUNTRY_NAME_TO_CODE.get(country_name.strip().lower())


def _to_decimal(val: Any) -> Decimal:
    if val is None:
        return Decimal('0')
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _round_d(val: Decimal, precision: int = 2, mode: str = 'ROUND_HALF_UP') -> Decimal:
    rounding = _ROUNDING_MODES.get(mode)
    if rounding is None:
        rounding = ROUND_HALF_UP
    return val.quantize(Decimal(10) ** -precision, rounding=rounding)


def _resolve_basis(
    config: dict,
    energy_subtotal: Decimal,
    levies_total: Decimal,
    subtotal_after_levies: Optional[Decimal] = None,
) -> Decimal:
    applies_to = config.get("applies_to", {})
    base = applies_to.get("base", "energy_subtotal")
    if base == "energy_subtotal":
        return energy_subtotal
    elif base == "subtotal_after_levies":
        return subtotal_after_levies if subtotal_after_levies is not None else (energy_subtotal + levies_total)
    return energy_subtotal


def _resolve_effective_rates(
    cur, clause_tariff_ids: list[int], billing_month: date
) -> dict[int, tuple[Decimal | None, Decimal | None]]:
    """Batch-resolve effective rates for a single billing month.

    Returns {ct_id: (billing_ccy_rate, hard_ccy_rate)} using fallback chain:
    monthly rate → annual rate → base_rate from clause_tariff.
    """
    result: dict[int, tuple[Decimal | None, Decimal | None]] = {}
    if not clause_tariff_ids:
        return result

    ids = list(clause_tariff_ids)

    # 1) Monthly rates
    cur.execute("""
        SELECT clause_tariff_id, effective_rate_billing_ccy, effective_rate_hard_ccy
        FROM tariff_rate
        WHERE clause_tariff_id = ANY(%(ids)s)
          AND billing_month = %(bm)s
          AND rate_granularity = 'monthly'
          AND calc_status IN ('computed', 'approved')
    """, {"ids": ids, "bm": billing_month})
    for rr in cur.fetchall():
        if rr["effective_rate_billing_ccy"] is not None:
            hard = Decimal(str(rr["effective_rate_hard_ccy"])) if rr["effective_rate_hard_ccy"] is not None else None
            result[rr["clause_tariff_id"]] = (Decimal(str(rr["effective_rate_billing_ccy"])), hard)

    # 2) Annual fallback
    missing_ids = [ct_id for ct_id in ids if ct_id not in result]
    if missing_ids:
        cur.execute("""
            SELECT DISTINCT ON (clause_tariff_id)
                   clause_tariff_id, effective_rate_billing_ccy, effective_rate_hard_ccy
            FROM tariff_rate
            WHERE clause_tariff_id = ANY(%(ids)s)
              AND rate_granularity = 'annual'
              AND period_start <= %(bm)s
              AND (period_end IS NULL OR period_end >= %(bm)s)
              AND calc_status IN ('computed', 'approved')
            ORDER BY clause_tariff_id, period_start DESC
        """, {"ids": missing_ids, "bm": billing_month})
        for rr in cur.fetchall():
            if rr["effective_rate_billing_ccy"] is not None:
                hard = Decimal(str(rr["effective_rate_hard_ccy"])) if rr["effective_rate_hard_ccy"] is not None else None
                result[rr["clause_tariff_id"]] = (Decimal(str(rr["effective_rate_billing_ccy"])), hard)

    # 3) Base rate fallback
    still_missing = [ct_id for ct_id in ids if ct_id not in result]
    if still_missing:
        cur.execute("""
            SELECT id, base_rate FROM clause_tariff WHERE id = ANY(%(ids)s)
        """, {"ids": still_missing})
        for rr in cur.fetchall():
            if rr["base_rate"] is not None:
                result[rr["id"]] = (Decimal(str(rr["base_rate"])), None)

    return result


class InvoiceService:
    """Generate expected invoices from rates + meter data + tax rules."""

    def generate(
        self,
        project_id: int,
        billing_month: str,
        invoice_direction: str = "payable",
        idempotency_key: Optional[str] = None,
        conn=None,
    ) -> Dict[str, Any]:
        """Generate expected invoice for a project/month.

        Args:
            project_id: Project ID
            billing_month: YYYY-MM format
            invoice_direction: 'payable' or 'receivable'
            idempotency_key: Optional deduplication key
            conn: Optional DB connection (for transaction sharing)

        Returns dict with header_id, amounts, etc.
        """
        parts = billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)

        if conn is not None:
            return self._generate_with_conn(conn, project_id, bm_date, billing_month, invoice_direction, idempotency_key)

        with get_db_connection() as conn:
            return self._generate_with_conn(conn, project_id, bm_date, billing_month, invoice_direction, idempotency_key)

    def _generate_with_conn(
        self,
        conn,
        project_id: int,
        bm_date: date,
        billing_month: str,
        invoice_direction: str,
        idempotency_key: Optional[str],
    ) -> Dict[str, Any]:
        """Core invoice generation logic with an already-open connection."""
        try:
            with conn.cursor() as cur:
                # 1. Resolve project, org, contract, billing_period
                cur.execute("""
                    SELECT p.id, p.organization_id, p.country,
                           c.id AS contract_id
                    FROM project p
                    JOIN contract c ON c.project_id = p.id
                      AND c.parent_contract_id IS NULL
                    WHERE p.id = %(pid)s
                    LIMIT 1
                """, {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    return {"success": False, "error": "Project or contract not found"}
                org_id = proj["organization_id"]
                contract_id = proj["contract_id"]
                country_code = _country_to_code(proj.get("country"))

                cur.execute("""
                    SELECT id FROM billing_period
                    WHERE start_date <= %(bm)s AND end_date >= %(bm)s
                    LIMIT 1
                """, {"bm": bm_date})
                bp_row = cur.fetchone()
                if not bp_row:
                    return {"success": False, "error": f"No billing_period for {billing_month}"}
                billing_period_id = bp_row["id"]

                # 2. Get contract lines + clause_tariff
                cur.execute("""
                    SELECT cl.id, cl.contract_line_number, cl.product_desc,
                           cl.energy_category::text AS energy_category,
                           cl.meter_id, cl.clause_tariff_id,
                           m.name AS meter_name
                    FROM contract_line cl
                    LEFT JOIN meter m ON m.id = cl.meter_id
                    WHERE cl.contract_id = %(cid)s AND cl.is_active = true
                      AND cl.parent_contract_line_id IS NULL
                    ORDER BY cl.contract_line_number
                """, {"cid": contract_id})
                contract_lines = cur.fetchall()
                if not contract_lines:
                    return {"success": False, "error": "No active contract lines found"}

                # Project-level fallback tariff
                cur.execute("""
                    SELECT ct.id, ct.base_rate, ct.currency_id, ct.logic_parameters,
                           cur.code AS currency_code
                    FROM clause_tariff ct
                    JOIN currency cur ON cur.id = ct.currency_id
                    WHERE ct.project_id = %(pid)s AND ct.is_current = true
                    LIMIT 1
                """, {"pid": project_id})
                project_tariff = cur.fetchone()
                if not project_tariff:
                    return {"success": False, "error": "No current clause_tariff for project"}

                currency_code = project_tariff["currency_code"]
                currency_id = project_tariff["currency_id"]

                # 3. Resolve tariff rates per contract_line
                tariff_ids = set()
                for cl in contract_lines:
                    ct_id = cl.get("clause_tariff_id") or project_tariff["id"]
                    tariff_ids.add(ct_id)

                resolved = _resolve_effective_rates(cur, list(tariff_ids), bm_date)
                rate_by_tariff: dict[int, Decimal] = {
                    ct_id: pair[0] for ct_id, pair in resolved.items() if pair[0] is not None
                }

                # 4. Get meter_aggregate data
                meter_ids = [cl["meter_id"] for cl in contract_lines if cl["meter_id"]]
                agg_by_cl: dict[int, dict] = {}

                if meter_ids:
                    cur.execute("""
                        SELECT ma.id AS meter_aggregate_id,
                               ma.contract_line_id, ma.meter_id,
                               COALESCE(ma.energy_kwh, ma.total_production, 0) AS metered_kwh,
                               COALESCE(ma.available_energy_kwh, 0) AS available_kwh,
                               m.name AS meter_name
                        FROM meter_aggregate ma
                        JOIN meter m ON m.id = ma.meter_id
                        WHERE ma.meter_id = ANY(%(mids)s)
                          AND ma.billing_period_id = %(bp)s
                    """, {"mids": meter_ids, "bp": billing_period_id})
                    for row in cur.fetchall():
                        cl_id = row["contract_line_id"]
                        if cl_id:
                            agg_by_cl[cl_id] = row

                # Meterless contract lines
                meterless_cl_ids = [cl["id"] for cl in contract_lines if not cl["meter_id"]]
                if meterless_cl_ids:
                    cur.execute("""
                        SELECT ma.id AS meter_aggregate_id,
                               ma.contract_line_id, ma.meter_id,
                               COALESCE(ma.energy_kwh, ma.total_production, 0) AS metered_kwh,
                               COALESCE(ma.available_energy_kwh, 0) AS available_kwh,
                               NULL AS meter_name
                        FROM meter_aggregate ma
                        WHERE ma.contract_line_id = ANY(%(cl_ids)s)
                          AND ma.billing_period_id = %(bp)s
                    """, {"cl_ids": meterless_cl_ids, "bp": billing_period_id})
                    for row in cur.fetchall():
                        cl_id = row["contract_line_id"]
                        if cl_id:
                            agg_by_cl[cl_id] = row

                # 5. Resolve billing taxes config
                logic_params = project_tariff.get("logic_parameters") or {}
                tax_config = logic_params.get("billing_taxes")

                if not tax_config:
                    tax_rule_sql = """
                        SELECT btr.rules
                        FROM billing_tax_rule btr
                        WHERE btr.organization_id = %(oid)s
                          AND btr.is_active = true
                          AND btr.effective_start_date <= %(bm)s
                          AND (btr.effective_end_date IS NULL OR btr.effective_end_date >= %(bm)s)
                    """
                    tax_rule_params: dict[str, Any] = {"oid": org_id, "bm": bm_date}
                    if country_code:
                        tax_rule_sql += "  AND btr.country_code = %(cc)s\n"
                        tax_rule_params["cc"] = country_code
                    tax_rule_sql += "ORDER BY btr.effective_start_date DESC\nLIMIT 1"
                    cur.execute(tax_rule_sql, tax_rule_params)
                    tax_rule = cur.fetchone()
                    if tax_rule:
                        tax_config = tax_rule["rules"]

                if not tax_config:
                    return {"success": False, "error": "No billing tax config found"}

                rounding_precision = tax_config.get("rounding_precision", 2)
                rounding_mode = tax_config.get("rounding_mode", "ROUND_HALF_UP")
                avail_mode = tax_config.get("available_energy_line_mode", "single")

                # Round rates to invoice precision
                invoice_rate_precision = tax_config.get("invoice_rate_precision", 4)
                invoice_rate_rounding = tax_config.get("invoice_rate_rounding_mode", rounding_mode)
                rate_rounding = _ROUNDING_MODES.get(invoice_rate_rounding)
                if rate_rounding is None:
                    rate_rounding = ROUND_HALF_UP
                for ct_id in rate_by_tariff:
                    rate_by_tariff[ct_id] = rate_by_tariff[ct_id].quantize(
                        Decimal(10) ** -invoice_rate_precision, rounding=rate_rounding
                    )

                # 6. Resolve line item type IDs
                cur.execute("SELECT id, code FROM invoice_line_item_type")
                type_map: dict[str, int] = {r["code"]: r["id"] for r in cur.fetchall()}

                # 7. Compute energy line items
                line_items: list[dict] = []
                sort_counter = 1

                # Available energy
                total_available_kwh = Decimal('0')
                for cl in contract_lines:
                    if cl["energy_category"] == 'available':
                        agg = agg_by_cl.get(cl["id"])
                        if agg:
                            total_available_kwh += _to_decimal(agg["available_kwh"])

                if avail_mode == "single" and total_available_kwh > 0:
                    ct_id = contract_lines[0].get("clause_tariff_id") or project_tariff["id"]
                    rate = rate_by_tariff.get(ct_id, Decimal('0'))
                    line_total = _round_d(total_available_kwh * rate, rounding_precision, rounding_mode)
                    line_items.append({
                        "type_code": "AVAILABLE_ENERGY", "type_id": type_map.get("AVAILABLE_ENERGY"),
                        "component_code": None, "description": "Available Energy",
                        "quantity": total_available_kwh, "unit_price": rate,
                        "basis_amount": None, "rate_pct": None,
                        "line_total_amount": line_total, "amount_sign": 1,
                        "sort_order": sort_counter, "contract_line_id": None,
                        "clause_tariff_id": ct_id, "meter_aggregate_id": None, "meter_name": None,
                    })
                    sort_counter += 1
                elif avail_mode == "per_meter":
                    for cl in contract_lines:
                        if cl["energy_category"] != 'available':
                            continue
                        agg = agg_by_cl.get(cl["id"])
                        if not agg:
                            continue
                        avail_kwh = _to_decimal(agg["available_kwh"])
                        if avail_kwh <= 0:
                            continue
                        ct_id = cl.get("clause_tariff_id") or project_tariff["id"]
                        rate = rate_by_tariff.get(ct_id, Decimal('0'))
                        line_total = _round_d(avail_kwh * rate, rounding_precision, rounding_mode)
                        desc = cl.get("product_desc") or agg.get("meter_name") or f"Meter {cl['meter_id']}"
                        line_items.append({
                            "type_code": "AVAILABLE_ENERGY", "type_id": type_map.get("AVAILABLE_ENERGY"),
                            "component_code": None, "description": f"Available - {desc}",
                            "quantity": avail_kwh, "unit_price": rate,
                            "basis_amount": None, "rate_pct": None,
                            "line_total_amount": line_total, "amount_sign": 1,
                            "sort_order": sort_counter, "contract_line_id": cl["id"],
                            "clause_tariff_id": ct_id, "meter_aggregate_id": agg.get("meter_aggregate_id"),
                            "meter_name": agg.get("meter_name"),
                        })
                        sort_counter += 1

                # Metered energy
                for cl in contract_lines:
                    if cl["energy_category"] != 'metered':
                        continue
                    agg = agg_by_cl.get(cl["id"])
                    if not agg:
                        continue
                    metered_kwh = _to_decimal(agg["metered_kwh"])
                    if metered_kwh <= 0:
                        continue
                    ct_id = cl.get("clause_tariff_id") or project_tariff["id"]
                    rate = rate_by_tariff.get(ct_id, Decimal('0'))
                    line_total = _round_d(metered_kwh * rate, rounding_precision, rounding_mode)
                    desc = cl.get("product_desc") or agg.get("meter_name") or f"Meter {cl['meter_id']}"
                    line_items.append({
                        "type_code": "ENERGY", "type_id": type_map.get("ENERGY"),
                        "component_code": None, "description": f"Metered - {desc}",
                        "quantity": metered_kwh, "unit_price": rate,
                        "basis_amount": None, "rate_pct": None,
                        "line_total_amount": line_total, "amount_sign": 1,
                        "sort_order": sort_counter, "contract_line_id": cl["id"],
                        "clause_tariff_id": ct_id, "meter_aggregate_id": agg.get("meter_aggregate_id"),
                        "meter_name": agg.get("meter_name"),
                    })
                    sort_counter += 1

                if not line_items:
                    return {
                        "success": False,
                        "error": "No energy data found for this billing period",
                        "blocked_by": "meter_aggregate",
                    }

                # 8. Energy subtotal
                energy_subtotal = sum(li["line_total_amount"] for li in line_items)

                # 9. Tax chain
                levies = tax_config.get("levies", [])
                vat_config = tax_config.get("vat")
                withholdings = tax_config.get("withholdings", [])

                levies_total = Decimal('0')
                for levy in levies:
                    basis = _resolve_basis(levy, energy_subtotal, levies_total)
                    rate_pct = _to_decimal(levy.get("rate", 0))
                    levy_amount = _round_d(basis * rate_pct, rounding_precision, rounding_mode)
                    levies_total += levy_amount
                    line_items.append({
                        "type_code": "LEVY", "type_id": type_map.get("LEVY"),
                        "component_code": levy["code"],
                        "description": f"{levy['name']} ({float(rate_pct)*100:.1f}%)",
                        "quantity": None, "unit_price": None,
                        "basis_amount": basis, "rate_pct": rate_pct,
                        "line_total_amount": levy_amount, "amount_sign": 1,
                        "sort_order": levy.get("sort_order", 10),
                        "contract_line_id": None, "clause_tariff_id": None,
                        "meter_aggregate_id": None, "meter_name": None,
                    })

                subtotal_after_levies = energy_subtotal + levies_total

                vat_amount = Decimal('0')
                if vat_config:
                    vat_basis = _resolve_basis(vat_config, energy_subtotal, levies_total, subtotal_after_levies)
                    vat_rate = _to_decimal(vat_config.get("rate", 0))
                    vat_amount = _round_d(vat_basis * vat_rate, rounding_precision, rounding_mode)
                    line_items.append({
                        "type_code": "TAX", "type_id": type_map.get("TAX"),
                        "component_code": vat_config.get("code", "VAT"),
                        "description": f"{vat_config.get('name', 'VAT')} ({float(vat_rate)*100:.0f}%)",
                        "quantity": None, "unit_price": None,
                        "basis_amount": vat_basis, "rate_pct": vat_rate,
                        "line_total_amount": vat_amount, "amount_sign": 1,
                        "sort_order": vat_config.get("sort_order", 20),
                        "contract_line_id": None, "clause_tariff_id": None,
                        "meter_aggregate_id": None, "meter_name": None,
                    })

                invoice_total = subtotal_after_levies + vat_amount

                withholdings_total = Decimal('0')
                for wh in withholdings:
                    wh_basis = _resolve_basis(wh, energy_subtotal, levies_total, subtotal_after_levies)
                    wh_rate = _to_decimal(wh.get("rate", 0))
                    wh_amount = _round_d(wh_basis * wh_rate, rounding_precision, rounding_mode)
                    wh_signed = -wh_amount
                    withholdings_total += wh_amount
                    line_items.append({
                        "type_code": "WITHHOLDING", "type_id": type_map.get("WITHHOLDING"),
                        "component_code": wh["code"],
                        "description": f"{wh['name']} ({float(wh_rate)*100:.0f}%)",
                        "quantity": None, "unit_price": None,
                        "basis_amount": wh_basis, "rate_pct": wh_rate,
                        "line_total_amount": wh_signed, "amount_sign": -1,
                        "sort_order": wh.get("sort_order", 30),
                        "contract_line_id": None, "clause_tariff_id": None,
                        "meter_aggregate_id": None, "meter_name": None,
                    })

                net_due = invoice_total - withholdings_total

                # 10. Source metadata
                source_metadata = {
                    "generator_version": "1.0.0",
                    "rounding_policy": {"mode": rounding_mode, "precision": rounding_precision},
                    "rates_full_precision": {str(ct_id): str(rate) for ct_id, rate in rate_by_tariff.items()},
                    "calculation_steps": {
                        "energy_subtotal": str(energy_subtotal),
                        "levies_total": str(levies_total),
                        "subtotal_after_levies": str(subtotal_after_levies),
                        "vat_amount": str(vat_amount),
                        "invoice_total": str(invoice_total),
                        "withholdings_total": str(withholdings_total),
                        "net_due": str(net_due),
                    },
                    "billing_taxes_snapshot": tax_config,
                }

                # 11. Counterparty + direction
                cur.execute("SELECT counterparty_id FROM contract WHERE id = %(cid)s", {"cid": contract_id})
                contract_info = cur.fetchone()
                counterparty_id = contract_info["counterparty_id"] if contract_info else None

                if invoice_direction not in ("payable", "receivable"):
                    return {"success": False, "error": "invoice_direction must be 'payable' or 'receivable'"}

                # 12. Idempotency + versioning
                if idempotency_key:
                    cur.execute("""
                        SELECT id FROM expected_invoice_header
                        WHERE idempotency_key = %(key)s
                    """, {"key": idempotency_key})
                    if cur.fetchone():
                        return {"success": False, "error": f"Invoice already generated with idempotency_key={idempotency_key}"}

                new_version = 1
                cur.execute("""
                    SELECT id, version_no FROM expected_invoice_header
                    WHERE project_id = %(pid)s AND billing_period_id = %(bp)s
                      AND invoice_direction = %(dir)s AND is_current = true
                """, {"pid": project_id, "bp": billing_period_id, "dir": invoice_direction})
                existing = cur.fetchone()
                if existing:
                    new_version = existing["version_no"] + 1
                    cur.execute("UPDATE expected_invoice_header SET is_current = false WHERE id = %(id)s", {"id": existing["id"]})

                # 13. Write header
                cur.execute("""
                    INSERT INTO expected_invoice_header (
                        project_id, contract_id, billing_period_id,
                        counterparty_id, currency_id,
                        invoice_direction, total_amount,
                        version_no, is_current, generated_at,
                        idempotency_key, source_metadata
                    ) VALUES (
                        %(pid)s, %(cid)s, %(bp)s, %(cp)s, %(cur)s,
                        %(dir)s, %(total)s, %(ver)s, true, NOW(),
                        %(ikey)s, %(meta)s
                    ) RETURNING id
                """, {
                    "pid": project_id, "cid": contract_id, "bp": billing_period_id,
                    "cp": counterparty_id, "cur": currency_id,
                    "dir": invoice_direction, "total": net_due,
                    "ver": new_version, "ikey": idempotency_key,
                    "meta": json.dumps(source_metadata, default=str),
                })
                header_id = cur.fetchone()["id"]

                # 14. Write line items
                for li in line_items:
                    cur.execute("""
                        INSERT INTO expected_invoice_line_item (
                            expected_invoice_header_id, invoice_line_item_type_id,
                            component_code, description,
                            quantity, line_unit_price, basis_amount, rate_pct,
                            line_total_amount, amount_sign, sort_order,
                            contract_line_id, clause_tariff_id, meter_aggregate_id
                        ) VALUES (
                            %(hid)s, %(type_id)s, %(comp)s, %(desc)s,
                            %(qty)s, %(price)s, %(basis)s, %(rate)s,
                            %(total)s, %(sign)s, %(sort)s,
                            %(cl_id)s, %(ct_id)s, %(ma_id)s
                        )
                    """, {
                        "hid": header_id, "type_id": li["type_id"],
                        "comp": li["component_code"], "desc": li["description"],
                        "qty": li["quantity"], "price": li["unit_price"],
                        "basis": li["basis_amount"], "rate": li["rate_pct"],
                        "total": li["line_total_amount"], "sign": li["amount_sign"],
                        "sort": li["sort_order"], "cl_id": li["contract_line_id"],
                        "ct_id": li["clause_tariff_id"], "ma_id": li["meter_aggregate_id"],
                    })

                return {
                    "success": True,
                    "header_id": header_id,
                    "version_no": new_version,
                    "billing_month": billing_month,
                    "energy_subtotal": float(energy_subtotal),
                    "levies_total": float(levies_total),
                    "subtotal_after_levies": float(subtotal_after_levies),
                    "vat_amount": float(vat_amount),
                    "invoice_total": float(invoice_total),
                    "withholdings_total": float(withholdings_total),
                    "net_due": float(net_due),
                    "line_count": len(line_items),
                    "currency_code": currency_code,
                }

        except Exception as e:
            logger.error(f"Invoice generation failed for project {project_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
