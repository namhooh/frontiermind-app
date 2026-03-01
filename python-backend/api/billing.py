"""
Monthly Billing API Endpoints

Assembles billing data per month: actual generation, forecasts, variance,
and per-product billing amounts computed as kWh × effective_rate.

Invoice generation endpoint writes to expected_invoice_* tables with
full tax/levy/withholding calculations.
"""

import io
import json
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile, File, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.database import get_db_connection, init_connection_pool
from services.audit_service import log_business_event

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-2 lookup from full country name (case-insensitive)
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "ghana": "GH",
    "kenya": "KE",
    "nigeria": "NG",
    "south africa": "ZA",
    "egypt": "EG",
    "madagascar": "MG",
    "sierra leone": "SL",
    "somalia": "SO",
    "mozambique": "MZ",
    "zimbabwe": "ZW",
    "drc": "CD",
    "rwanda": "RW",
}


def _country_to_code(country_name: str | None) -> str | None:
    """Map a full country name (e.g. 'Ghana') to its ISO 2-letter code."""
    if not country_name:
        return None
    return _COUNTRY_NAME_TO_CODE.get(country_name.strip().lower())

router = APIRouter(
    prefix="/api",
    tags=["billing"],
    responses={500: {"description": "Internal server error"}},
)

try:
    init_connection_pool()
    USE_DATABASE = True
except Exception as e:
    logger.error(f"Billing API: Database not available - {e}")
    USE_DATABASE = False


# ============================================================================
# Response / Request Models
# ============================================================================

class ProductColumn(BaseModel):
    billing_product_id: int
    product_code: str
    product_name: str
    clause_tariff_id: Optional[int] = None
    tariff_name: Optional[str] = None
    is_metered: bool = True  # False for fixed-fee products
    energy_category: Optional[str] = None  # 'metered', 'available', 'test', etc.


class MonthlyBillingRow(BaseModel):
    billing_month: str  # YYYY-MM-DD
    billing_period_id: Optional[int] = None
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None
    variance_kwh: Optional[float] = None
    variance_pct: Optional[float] = None
    product_amounts: dict[str, Optional[float]] = {}  # product_code -> amount (billing ccy)
    product_rates: dict[str, Optional[float]] = {}    # product_code -> rate used (billing ccy)
    product_amounts_hard_ccy: dict[str, Optional[float]] = {}  # product_code -> amount (hard ccy)
    product_rates_hard_ccy: dict[str, Optional[float]] = {}    # product_code -> rate used (hard ccy)
    total_billing_amount: Optional[float] = None
    total_billing_amount_hard_ccy: Optional[float] = None


class MonthlyBillingResponse(BaseModel):
    success: bool = True
    rows: List[MonthlyBillingRow] = []
    products: List[ProductColumn] = []
    currency_code: Optional[str] = None
    hard_currency_code: Optional[str] = None
    degradation_pct: Optional[float] = None
    cod_date: Optional[str] = None  # ISO date string from project.cod_date
    summary: dict[str, Any] = {}


class ManualEntryRequest(BaseModel):
    billing_month: str = Field(..., description="YYYY-MM format")
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None
    meter_id: Optional[int] = Field(None, description="Specific meter ID (falls back to first project meter)")


class ImportResponse(BaseModel):
    success: bool = True
    imported_rows: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Meter Billing Models
# ---------------------------------------------------------------------------

class MeterInfo(BaseModel):
    meter_id: int
    meter_name: Optional[str] = None
    contract_line_number: Optional[int] = None
    energy_category: Optional[str] = None
    product_desc: Optional[str] = None


class MeterReadingDetail(BaseModel):
    meter_id: int
    meter_name: Optional[str] = None
    opening_reading: Optional[float] = None
    closing_reading: Optional[float] = None
    metered_kwh: Optional[float] = None
    available_kwh: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    rate_hard_ccy: Optional[float] = None
    amount_hard_ccy: Optional[float] = None


class MeterBillingMonth(BaseModel):
    billing_month: str
    meter_readings: List[MeterReadingDetail] = []
    total_metered_kwh: Optional[float] = None
    total_available_kwh: Optional[float] = None
    total_energy_kwh: Optional[float] = None
    total_amount: Optional[float] = None
    expected_invoice: Optional['ExpectedInvoiceSummary'] = None


class MeterBillingResponse(BaseModel):
    success: bool = True
    meters: List[MeterInfo] = []
    months: List[MeterBillingMonth] = []
    currency_code: Optional[str] = None
    hard_currency_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Expected Invoice Models
# ---------------------------------------------------------------------------

class ExpectedInvoiceLineItem(BaseModel):
    line_item_type_code: str           # ENERGY, AVAILABLE_ENERGY, LEVY, TAX, WITHHOLDING
    component_code: Optional[str] = None  # NHIL, GETFUND, etc.
    description: str = ""
    quantity: Optional[float] = None          # energy lines
    unit_price: Optional[float] = None        # energy lines
    basis_amount: Optional[float] = None      # tax lines
    rate_pct: Optional[float] = None          # tax lines
    line_total_amount: float = 0              # always signed
    amount_sign: int = 1
    sort_order: int = 0
    meter_name: Optional[str] = None


class ExpectedInvoiceSummary(BaseModel):
    """All section totals derived from line_items at read time."""
    header_id: int
    version_no: int = 1
    energy_subtotal: float = 0       # SUM(line_total) WHERE type IN (ENERGY, AVAILABLE_ENERGY)
    levies_total: float = 0          # SUM(line_total) WHERE type = LEVY
    subtotal_after_levies: float = 0 # energy_subtotal + levies_total
    vat_amount: float = 0            # line_total WHERE type = TAX
    invoice_total: float = 0         # subtotal_after_levies + vat_amount
    withholdings_total: float = 0    # SUM(|line_total|) WHERE type = WITHHOLDING
    net_due: float = 0               # SUM(all line_total) = header.total_amount
    line_items: List[ExpectedInvoiceLineItem] = []


class GenerateInvoiceRequest(BaseModel):
    billing_month: str = Field(..., description="YYYY-MM format")
    idempotency_key: Optional[str] = None
    invoice_direction: Optional[str] = Field("payable", description="'payable' or 'receivable'")


# Fixed-fee product codes (flat per month, not kWh-based)
FIXED_FEE_PRODUCT_CODES = {
    "EQUIPMENT_RENTAL_LEASE",
    "BESS_LEASE",
    "LOAN",
    "EQUIPMENT_LEASE",
    "BESS",
}


def _decimal_to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _to_decimal(val: Any) -> Decimal:
    """Convert to Decimal, defaulting to 0."""
    if val is None:
        return Decimal('0')
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _round_d(val: Decimal, precision: int = 2, mode: str = 'ROUND_HALF_UP') -> Decimal:
    """Round a Decimal with the specified mode."""
    rounding = ROUND_HALF_UP  # only mode we support currently
    return val.quantize(Decimal(10) ** -precision, rounding=rounding)


# ============================================================================
# POST /projects/{project_id}/billing/generate-expected-invoice
# ============================================================================

@router.post(
    "/projects/{project_id}/billing/generate-expected-invoice",
    response_model=dict,
    summary="Generate expected invoice for a billing month",
)
async def generate_expected_invoice(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: int = Path(..., description="Project ID"),
    body: GenerateInvoiceRequest = ...,
) -> dict:
    """Generate expected invoice from meter_aggregate + tariff_rate + tax config.

    Writes atomically to expected_invoice_header and expected_invoice_line_item.
    Supports versioning: if a current invoice exists, it's superseded.
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    # Parse billing_month
    try:
        parts = body.billing_month.split("-")
        bm_year, bm_month = int(parts[0]), int(parts[1])
        bm_date = date(bm_year, bm_month, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="billing_month must be YYYY-MM")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # ----------------------------------------------------------
                # 1. Resolve project, org, contract, billing_period
                # ----------------------------------------------------------
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
                    raise HTTPException(status_code=404, detail="Project or contract not found")
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
                    raise HTTPException(status_code=404, detail=f"No billing_period for {body.billing_month}")
                billing_period_id = bp_row["id"]

                # ----------------------------------------------------------
                # 2. Get contract lines + clause_tariff
                # ----------------------------------------------------------
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
                    raise HTTPException(status_code=404, detail="No active contract lines found")

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
                    raise HTTPException(status_code=404, detail="No current clause_tariff for project")

                currency_code = project_tariff["currency_code"]
                currency_id = project_tariff["currency_id"]

                # ----------------------------------------------------------
                # 3. Resolve tariff rates per contract_line
                # ----------------------------------------------------------
                # Collect all clause_tariff_ids we need rates for
                tariff_ids = set()
                for cl in contract_lines:
                    ct_id = cl.get("clause_tariff_id") or project_tariff["id"]
                    tariff_ids.add(ct_id)

                # Get monthly rates for the billing month
                rate_by_tariff: dict[int, Decimal] = {}
                if tariff_ids:
                    cur.execute("""
                        SELECT clause_tariff_id, effective_rate_billing_ccy
                        FROM tariff_rate
                        WHERE clause_tariff_id = ANY(%(ids)s)
                          AND billing_month = %(bm)s
                          AND rate_granularity = 'monthly'
                          AND calc_status IN ('computed', 'approved')
                    """, {"ids": list(tariff_ids), "bm": bm_date})
                    for rr in cur.fetchall():
                        if rr["effective_rate_billing_ccy"] is not None:
                            rate_by_tariff[rr["clause_tariff_id"]] = Decimal(str(rr["effective_rate_billing_ccy"]))

                    # Fallback: annual rates
                    for ct_id in tariff_ids:
                        if ct_id not in rate_by_tariff:
                            cur.execute("""
                                SELECT effective_rate_billing_ccy
                                FROM tariff_rate
                                WHERE clause_tariff_id = %(ct_id)s
                                  AND rate_granularity = 'annual'
                                  AND period_start <= %(bm)s
                                  AND (period_end IS NULL OR period_end >= %(bm)s)
                                  AND calc_status IN ('computed', 'approved')
                                ORDER BY period_start DESC
                                LIMIT 1
                            """, {"ct_id": ct_id, "bm": bm_date})
                            ar = cur.fetchone()
                            if ar and ar["effective_rate_billing_ccy"]:
                                rate_by_tariff[ct_id] = Decimal(str(ar["effective_rate_billing_ccy"]))

                    # Last fallback: base_rate from clause_tariff
                    for ct_id in tariff_ids:
                        if ct_id not in rate_by_tariff:
                            cur.execute("SELECT base_rate FROM clause_tariff WHERE id = %(id)s", {"id": ct_id})
                            br = cur.fetchone()
                            if br and br["base_rate"]:
                                rate_by_tariff[ct_id] = Decimal(str(br["base_rate"]))

                # ----------------------------------------------------------
                # 4. Get meter_aggregate data for this billing period
                # ----------------------------------------------------------
                meter_ids = [cl["meter_id"] for cl in contract_lines if cl["meter_id"]]
                agg_by_cl: dict[int, dict] = {}  # contract_line_id → aggregate row

                if meter_ids:
                    cur.execute("""
                        SELECT ma.contract_line_id, ma.meter_id,
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

                # Also pick up meterless contract lines (e.g. test energy)
                meterless_cl_ids = [cl["id"] for cl in contract_lines if not cl["meter_id"]]
                if meterless_cl_ids:
                    cur.execute("""
                        SELECT ma.contract_line_id, ma.meter_id,
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

                # ----------------------------------------------------------
                # 5. Resolve billing taxes config
                # ----------------------------------------------------------
                logic_params = project_tariff.get("logic_parameters") or {}
                tax_config = logic_params.get("billing_taxes")

                if not tax_config:
                    # Fallback: billing_tax_rule by org + country
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
                    raise HTTPException(
                        status_code=422,
                        detail="No billing tax config found (checked clause_tariff.logic_parameters and billing_tax_rule)"
                    )

                rounding_precision = tax_config.get("rounding_precision", 2)
                rounding_mode = tax_config.get("rounding_mode", "ROUND_HALF_UP")
                avail_mode = tax_config.get("available_energy_line_mode", "single")

                # Round rates to invoice precision (default 4dp) to match
                # CBE billing system which truncates effective rates before
                # multiplying by kWh quantities.
                invoice_rate_precision = tax_config.get("invoice_rate_precision", 4)
                for ct_id in rate_by_tariff:
                    rate_by_tariff[ct_id] = rate_by_tariff[ct_id].quantize(
                        Decimal(10) ** -invoice_rate_precision, rounding=ROUND_HALF_UP
                    )

                # ----------------------------------------------------------
                # 6. Resolve line item type IDs
                # ----------------------------------------------------------
                cur.execute("SELECT id, code FROM invoice_line_item_type")
                type_map: dict[str, int] = {r["code"]: r["id"] for r in cur.fetchall()}

                # ----------------------------------------------------------
                # 7. Compute energy line items
                # ----------------------------------------------------------
                line_items: list[dict] = []
                sort_counter = 1

                # Available energy line(s)
                total_available_kwh = Decimal('0')
                for cl in contract_lines:
                    if cl["energy_category"] == 'available':
                        agg = agg_by_cl.get(cl["id"])
                        if agg:
                            total_available_kwh += _to_decimal(agg["available_kwh"])

                if avail_mode == "single" and total_available_kwh > 0:
                    ct_id = contract_lines[0].get("clause_tariff_id") or project_tariff["id"]
                    rate = rate_by_tariff.get(ct_id, Decimal('0'))
                    line_total = _round_d(total_available_kwh * rate, rounding_precision)
                    line_items.append({
                        "type_code": "AVAILABLE_ENERGY",
                        "type_id": type_map.get("AVAILABLE_ENERGY"),
                        "component_code": None,
                        "description": "Available Energy",
                        "quantity": total_available_kwh,
                        "unit_price": rate,
                        "basis_amount": None,
                        "rate_pct": None,
                        "line_total_amount": line_total,
                        "amount_sign": 1,
                        "sort_order": sort_counter,
                        "contract_line_id": None,
                        "meter_name": None,
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
                        line_total = _round_d(avail_kwh * rate, rounding_precision)

                        desc = cl.get("product_desc") or agg.get("meter_name") or f"Meter {cl['meter_id']}"
                        line_items.append({
                            "type_code": "AVAILABLE_ENERGY",
                            "type_id": type_map.get("AVAILABLE_ENERGY"),
                            "component_code": None,
                            "description": f"Available - {desc}",
                            "quantity": avail_kwh,
                            "unit_price": rate,
                            "basis_amount": None,
                            "rate_pct": None,
                            "line_total_amount": line_total,
                            "amount_sign": 1,
                            "sort_order": sort_counter,
                            "contract_line_id": cl["id"],
                            "meter_name": agg.get("meter_name"),
                        })
                        sort_counter += 1

                # Metered energy lines
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
                    line_total = _round_d(metered_kwh * rate, rounding_precision)

                    desc = cl.get("product_desc") or agg.get("meter_name") or f"Meter {cl['meter_id']}"
                    line_items.append({
                        "type_code": "ENERGY",
                        "type_id": type_map.get("ENERGY"),
                        "component_code": None,
                        "description": f"Metered - {desc}",
                        "quantity": metered_kwh,
                        "unit_price": rate,
                        "basis_amount": None,
                        "rate_pct": None,
                        "line_total_amount": line_total,
                        "amount_sign": 1,
                        "sort_order": sort_counter,
                        "contract_line_id": cl["id"],
                        "meter_name": agg.get("meter_name"),
                    })
                    sort_counter += 1

                if not line_items:
                    raise HTTPException(
                        status_code=422,
                        detail="No energy data found for this billing period. Ensure meter_aggregate has data."
                    )

                # ----------------------------------------------------------
                # 8. Compute energy subtotal
                # ----------------------------------------------------------
                energy_subtotal = sum(li["line_total_amount"] for li in line_items)

                # ----------------------------------------------------------
                # 9. Compute tax chain with deterministic rounding
                # ----------------------------------------------------------
                levies = tax_config.get("levies", [])
                vat_config = tax_config.get("vat")
                withholdings = tax_config.get("withholdings", [])

                levies_total = Decimal('0')
                for levy in levies:
                    basis = _resolve_basis(levy, energy_subtotal, levies_total)
                    rate_pct = _to_decimal(levy.get("rate", 0))
                    levy_amount = _round_d(basis * rate_pct, rounding_precision)
                    levies_total += levy_amount

                    line_items.append({
                        "type_code": "LEVY",
                        "type_id": type_map.get("LEVY"),
                        "component_code": levy["code"],
                        "description": f"{levy['name']} ({float(rate_pct)*100:.1f}%)",
                        "quantity": None,
                        "unit_price": None,
                        "basis_amount": basis,
                        "rate_pct": rate_pct,
                        "line_total_amount": levy_amount,
                        "amount_sign": 1,
                        "sort_order": levy.get("sort_order", 10),
                        "contract_line_id": None,
                        "meter_name": None,
                    })

                subtotal_after_levies = energy_subtotal + levies_total

                # VAT
                vat_amount = Decimal('0')
                if vat_config:
                    vat_basis = _resolve_basis(vat_config, energy_subtotal, levies_total, subtotal_after_levies)
                    vat_rate = _to_decimal(vat_config.get("rate", 0))
                    vat_amount = _round_d(vat_basis * vat_rate, rounding_precision)

                    line_items.append({
                        "type_code": "TAX",
                        "type_id": type_map.get("TAX"),
                        "component_code": vat_config.get("code", "VAT"),
                        "description": f"{vat_config.get('name', 'VAT')} ({float(vat_rate)*100:.0f}%)",
                        "quantity": None,
                        "unit_price": None,
                        "basis_amount": vat_basis,
                        "rate_pct": vat_rate,
                        "line_total_amount": vat_amount,
                        "amount_sign": 1,
                        "sort_order": vat_config.get("sort_order", 20),
                        "contract_line_id": None,
                        "meter_name": None,
                    })

                invoice_total = subtotal_after_levies + vat_amount

                # Withholdings (negative amounts)
                withholdings_total = Decimal('0')
                for wh in withholdings:
                    wh_basis = _resolve_basis(wh, energy_subtotal, levies_total, subtotal_after_levies)
                    wh_rate = _to_decimal(wh.get("rate", 0))
                    wh_amount = _round_d(wh_basis * wh_rate, rounding_precision)
                    wh_signed = -wh_amount  # store as negative
                    withholdings_total += wh_amount

                    line_items.append({
                        "type_code": "WITHHOLDING",
                        "type_id": type_map.get("WITHHOLDING"),
                        "component_code": wh["code"],
                        "description": f"{wh['name']} ({float(wh_rate)*100:.0f}%)",
                        "quantity": None,
                        "unit_price": None,
                        "basis_amount": wh_basis,
                        "rate_pct": wh_rate,
                        "line_total_amount": wh_signed,
                        "amount_sign": -1,
                        "sort_order": wh.get("sort_order", 30),
                        "contract_line_id": None,
                        "meter_name": None,
                    })

                net_due = invoice_total - withholdings_total

                # ----------------------------------------------------------
                # 10. Build source_metadata audit trail
                # ----------------------------------------------------------
                source_metadata = {
                    "generator_version": "1.0.0",
                    "rounding_policy": {
                        "mode": rounding_mode,
                        "precision": rounding_precision,
                    },
                    "rates_full_precision": {
                        str(ct_id): str(rate)
                        for ct_id, rate in rate_by_tariff.items()
                    },
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

                # ----------------------------------------------------------
                # 11. Resolve counterparty + invoice direction
                # ----------------------------------------------------------
                cur.execute("""
                    SELECT counterparty_id
                    FROM contract WHERE id = %(cid)s
                """, {"cid": contract_id})
                contract_info = cur.fetchone()
                counterparty_id = contract_info["counterparty_id"] if contract_info else None
                invoice_direction = body.invoice_direction or "payable"
                if invoice_direction not in ("payable", "receivable"):
                    raise HTTPException(status_code=400, detail="invoice_direction must be 'payable' or 'receivable'")

                # ----------------------------------------------------------
                # 12. Idempotency + versioning
                # ----------------------------------------------------------
                if body.idempotency_key:
                    cur.execute("""
                        SELECT id FROM expected_invoice_header
                        WHERE idempotency_key = %(key)s
                    """, {"key": body.idempotency_key})
                    if cur.fetchone():
                        raise HTTPException(
                            status_code=409,
                            detail=f"Invoice already generated with idempotency_key={body.idempotency_key}"
                        )

                # Supersede existing current invoice
                new_version = 1
                cur.execute("""
                    SELECT id, version_no FROM expected_invoice_header
                    WHERE project_id = %(pid)s
                      AND billing_period_id = %(bp)s
                      AND invoice_direction = %(dir)s
                      AND is_current = true
                """, {"pid": project_id, "bp": billing_period_id, "dir": invoice_direction})
                existing = cur.fetchone()
                if existing:
                    new_version = existing["version_no"] + 1
                    cur.execute("""
                        UPDATE expected_invoice_header
                        SET is_current = false
                        WHERE id = %(id)s
                    """, {"id": existing["id"]})

                # ----------------------------------------------------------
                # 13. Write header
                # ----------------------------------------------------------
                cur.execute("""
                    INSERT INTO expected_invoice_header (
                        project_id, contract_id, billing_period_id,
                        counterparty_id, currency_id,
                        invoice_direction, total_amount,
                        version_no, is_current, generated_at,
                        idempotency_key, source_metadata
                    ) VALUES (
                        %(pid)s, %(cid)s, %(bp)s,
                        %(cp)s, %(cur)s,
                        %(dir)s, %(total)s,
                        %(ver)s, true, NOW(),
                        %(ikey)s, %(meta)s
                    )
                    RETURNING id
                """, {
                    "pid": project_id,
                    "cid": contract_id,
                    "bp": billing_period_id,
                    "cp": counterparty_id,
                    "cur": currency_id,
                    "dir": invoice_direction,
                    "total": float(net_due),
                    "ver": new_version,
                    "ikey": body.idempotency_key,
                    "meta": json.dumps(source_metadata, default=str),
                })
                header_id = cur.fetchone()["id"]

                # ----------------------------------------------------------
                # 14. Write line items
                # ----------------------------------------------------------
                for li in line_items:
                    cur.execute("""
                        INSERT INTO expected_invoice_line_item (
                            expected_invoice_header_id,
                            invoice_line_item_type_id,
                            component_code,
                            description,
                            quantity, line_unit_price,
                            basis_amount, rate_pct,
                            line_total_amount, amount_sign,
                            sort_order, contract_line_id
                        ) VALUES (
                            %(hid)s, %(type_id)s, %(comp)s, %(desc)s,
                            %(qty)s, %(price)s,
                            %(basis)s, %(rate)s,
                            %(total)s, %(sign)s,
                            %(sort)s, %(cl_id)s
                        )
                    """, {
                        "hid": header_id,
                        "type_id": li["type_id"],
                        "comp": li["component_code"],
                        "desc": li["description"],
                        "qty": float(li["quantity"]) if li["quantity"] is not None else None,
                        "price": float(li["unit_price"]) if li["unit_price"] is not None else None,
                        "basis": float(li["basis_amount"]) if li["basis_amount"] is not None else None,
                        "rate": float(li["rate_pct"]) if li["rate_pct"] is not None else None,
                        "total": float(li["line_total_amount"]),
                        "sign": li["amount_sign"],
                        "sort": li["sort_order"],
                        "cl_id": li["contract_line_id"],
                    })

                result = {
                    "success": True,
                    "header_id": header_id,
                    "version_no": new_version,
                    "billing_month": body.billing_month,
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

                log_business_event(
                    background_tasks, request,
                    action="CREATE",
                    resource_type="expected_invoice",
                    resource_id=str(header_id),
                    organization_id=org_id,
                    compliance_relevant=True,
                    details={"project_id": project_id, "billing_month": body.billing_month, "version": new_version},
                )

                return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating expected invoice for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_basis(
    config: dict,
    energy_subtotal: Decimal,
    levies_total: Decimal,
    subtotal_after_levies: Optional[Decimal] = None,
) -> Decimal:
    """Resolve basis_amount from the applies_to config."""
    applies_to = config.get("applies_to", {})
    base = applies_to.get("base", "energy_subtotal")
    if base == "energy_subtotal":
        return energy_subtotal
    elif base == "subtotal_after_levies":
        return subtotal_after_levies if subtotal_after_levies is not None else (energy_subtotal + levies_total)
    return energy_subtotal


# ============================================================================
# GET /projects/{project_id}/monthly-billing
# ============================================================================

@router.get(
    "/projects/{project_id}/monthly-billing",
    response_model=MonthlyBillingResponse,
    summary="Get monthly billing data",
)
async def get_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
) -> MonthlyBillingResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1) Get project's billing products with their tariff linkage
                cur.execute("""
                    SELECT
                        cbp.billing_product_id,
                        bp.code  AS product_code,
                        bp.name  AS product_name,
                        ct.id    AS clause_tariff_id,
                        ct.name  AS tariff_name,
                        ct.base_rate,
                        (SELECT cl2.energy_category::text
                         FROM contract_line cl2
                         WHERE cl2.billing_product_id = cbp.billing_product_id
                           AND cl2.contract_id = c.id AND cl2.is_active = true
                         LIMIT 1) AS energy_category
                    FROM contract_billing_product cbp
                    JOIN billing_product bp ON bp.id = cbp.billing_product_id
                    JOIN contract c ON c.id = cbp.contract_id
                    LEFT JOIN clause_tariff ct
                        ON ct.contract_id = c.id
                       AND ct.is_current = true
                    WHERE c.project_id = %(pid)s
                    ORDER BY cbp.is_primary DESC, bp.code
                """, {"pid": project_id})
                product_rows = cur.fetchall()

                # Build product columns
                products: list[ProductColumn] = []
                seen_codes: set[str] = set()
                for pr in product_rows:
                    code = pr["product_code"]
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    is_metered = code not in FIXED_FEE_PRODUCT_CODES
                    products.append(ProductColumn(
                        billing_product_id=pr["billing_product_id"],
                        product_code=code,
                        product_name=pr["product_name"] or code,
                        clause_tariff_id=pr["clause_tariff_id"],
                        tariff_name=pr["tariff_name"],
                        is_metered=is_metered,
                        energy_category=pr.get("energy_category"),
                    ))

                # 2) Get currency from first tariff (billing + hard currency)
                cur.execute("""
                    SELECT COALESCE(bcur.code, cur.code) AS code,
                           hcur.code AS hard_currency_code,
                           ct.logic_parameters->>'degradation_pct' AS degradation_pct
                    FROM clause_tariff ct
                    JOIN currency cur ON cur.id = ct.currency_id
                    LEFT JOIN tariff_rate tr2 ON tr2.clause_tariff_id = ct.id
                    LEFT JOIN currency bcur ON bcur.id = tr2.billing_currency_id
                    LEFT JOIN currency hcur ON hcur.id = tr2.hard_currency_id
                    WHERE ct.project_id = %(pid)s AND ct.is_current = true
                    ORDER BY tr2.billing_currency_id IS NOT NULL DESC
                    LIMIT 1
                """, {"pid": project_id})
                currency_row = cur.fetchone()
                currency_code = currency_row["code"] if currency_row else None
                hard_currency_code = currency_row["hard_currency_code"] if currency_row else None
                degradation_pct = float(currency_row["degradation_pct"]) if currency_row and currency_row["degradation_pct"] else None

                # 2b) Get project COD date
                cur.execute("SELECT cod_date FROM project WHERE id = %(pid)s", {"pid": project_id})
                proj_row = cur.fetchone()
                cod_date_str = proj_row["cod_date"].isoformat() if proj_row and proj_row["cod_date"] else None

                # 3) Main billing data query
                cur.execute("""
                    WITH project_meters AS (
                        SELECT id FROM meter WHERE project_id = %(pid)s
                    ),
                    -- Get all distinct billing months from meter_aggregate and forecasts
                    all_months AS (
                        SELECT DISTINCT date_trunc('month', ma.period_start)::date AS billing_month
                        FROM meter_aggregate ma
                        LEFT JOIN contract_line cl ON cl.id = ma.contract_line_id
                        LEFT JOIN contract c ON c.id = cl.contract_id
                        WHERE (ma.meter_id IN (SELECT id FROM project_meters)
                               OR (c.project_id = %(pid)s AND ma.contract_line_id IS NOT NULL))
                          AND ma.period_start IS NOT NULL
                        UNION
                        SELECT DISTINCT forecast_month AS billing_month
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                    ),
                    -- Aggregate actuals per month (metered + available only; excludes test energy)
                    monthly_actuals AS (
                        SELECT
                            date_trunc('month', ma.period_start)::date AS billing_month,
                            ma.billing_period_id,
                            SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS metered_kwh,
                            SUM(COALESCE(ma.available_energy_kwh, 0)) AS available_kwh
                        FROM meter_aggregate ma
                        LEFT JOIN contract_line cl ON cl.id = ma.contract_line_id
                        LEFT JOIN contract c ON c.id = cl.contract_id
                        WHERE (ma.meter_id IN (SELECT id FROM project_meters)
                               OR (c.project_id = %(pid)s AND ma.contract_line_id IS NOT NULL))
                          AND ma.period_start IS NOT NULL
                          AND (cl.energy_category IS DISTINCT FROM 'test')
                        GROUP BY 1, 2
                    ),
                    -- Get forecasts per month
                    monthly_forecasts AS (
                        SELECT
                            forecast_month AS billing_month,
                            SUM(forecast_energy_kwh) AS forecast_kwh
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                        GROUP BY forecast_month
                    )
                    SELECT
                        am.billing_month,
                        act.billing_period_id,
                        COALESCE(act.metered_kwh, 0) + COALESCE(act.available_kwh, 0) AS actual_kwh,
                        fc.forecast_kwh
                    FROM all_months am
                    LEFT JOIN monthly_actuals act ON act.billing_month = am.billing_month
                    LEFT JOIN monthly_forecasts fc ON fc.billing_month = am.billing_month
                    ORDER BY am.billing_month DESC
                """, {"pid": project_id})
                month_rows = cur.fetchall()

                # 3b) Per-product kWh actuals
                cur.execute("""
                    SELECT date_trunc('month', ma.period_start)::date AS billing_month,
                           cl.billing_product_id,
                           SUM(CASE WHEN cl.energy_category = 'available'
                               THEN COALESCE(ma.available_energy_kwh, 0)
                               ELSE COALESCE(ma.energy_kwh, ma.total_production, 0) END) AS product_kwh
                    FROM meter_aggregate ma
                    JOIN contract_line cl ON cl.id = ma.contract_line_id
                    JOIN contract c ON c.id = cl.contract_id
                    WHERE c.project_id = %(pid)s AND ma.period_start IS NOT NULL
                    GROUP BY 1, 2
                """, {"pid": project_id})
                per_product_map: dict[tuple, float] = {}
                for ppr in cur.fetchall():
                    key = (ppr["billing_month"].strftime("%Y-%m-%d") if isinstance(ppr["billing_month"], date) else str(ppr["billing_month"]),
                           ppr["billing_product_id"])
                    per_product_map[key] = _decimal_to_float(ppr["product_kwh"])

                # Months that have per-product meter_aggregate data; the
                # actual*rate fallback is only used for months WITHOUT any
                # per-product breakdown (legacy/manual rows).
                months_with_product_data: set[str] = {bm for (bm, _) in per_product_map}

                # 4) Build rate lookup: for each product, get rates per month
                rate_map: dict[str, dict[str, float]] = {}
                rate_map_hard: dict[str, dict[str, float]] = {}
                base_rate_map: dict[str, float] = {}

                for p in products:
                    ct_id = p.clause_tariff_id
                    if ct_id is None:
                        continue

                    for pr in product_rows:
                        if pr["product_code"] == p.product_code and pr["base_rate"] is not None:
                            base_rate_map[p.product_code] = float(pr["base_rate"])
                            break

                    cur.execute("""
                        SELECT tr.billing_month, tr.effective_rate_billing_ccy,
                               tr.effective_rate_hard_ccy,
                               tr.rate_granularity::text AS rate_granularity,
                               tr.period_start, tr.period_end,
                               tr.calc_status::text AS calc_status
                        FROM tariff_rate tr
                        WHERE tr.clause_tariff_id = %(ct_id)s
                          AND tr.calc_status IN ('computed', 'approved')
                        ORDER BY tr.rate_granularity = 'annual' ASC, tr.billing_month
                    """, {"ct_id": ct_id})
                    rate_rows = cur.fetchall()

                    month_rate_dict: dict[str, float] = {}
                    month_rate_hard_dict: dict[str, float] = {}
                    annual_rates = []
                    for nr in rate_rows:
                        if nr["rate_granularity"] == "monthly" and nr["effective_rate_billing_ccy"] is not None:
                            m_str = nr["billing_month"].strftime("%Y-%m-%d") if isinstance(nr["billing_month"], date) else str(nr["billing_month"])
                            month_rate_dict[m_str] = float(nr["effective_rate_billing_ccy"])
                            if nr["effective_rate_hard_ccy"] is not None:
                                month_rate_hard_dict[m_str] = float(nr["effective_rate_hard_ccy"])
                        elif nr["rate_granularity"] == "annual":
                            annual_rates.append({
                                "period_start": nr["period_start"],
                                "period_end": nr["period_end"],
                                "effective_tariff": float(nr["effective_rate_billing_ccy"]) if nr["effective_rate_billing_ccy"] else None,
                                "final_effective_tariff": float(nr["effective_rate_billing_ccy"]) if nr["effective_rate_billing_ccy"] else None,
                                "effective_tariff_hard_ccy": float(nr["effective_rate_hard_ccy"]) if nr["effective_rate_hard_ccy"] else None,
                            })

                    rate_map[p.product_code] = month_rate_dict
                    rate_map_hard[p.product_code] = month_rate_hard_dict
                    p.__dict__['_annual_rates'] = annual_rates

                # 5) Assemble rows
                rows: list[MonthlyBillingRow] = []
                totals = {
                    "actual_kwh": 0.0,
                    "forecast_kwh": 0.0,
                    "total_billing": 0.0,
                    "total_billing_hard": 0.0,
                }

                for mr in month_rows:
                    bm = mr["billing_month"]
                    bm_str = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)
                    actual = _decimal_to_float(mr["actual_kwh"])
                    forecast = _decimal_to_float(mr["forecast_kwh"])

                    variance_kwh = None
                    variance_pct = None
                    if actual is not None and forecast is not None and forecast != 0:
                        variance_kwh = actual - forecast
                        variance_pct = (variance_kwh / forecast) * 100

                    product_amounts: dict[str, Optional[float]] = {}
                    product_rates_out: dict[str, Optional[float]] = {}
                    product_amounts_hard: dict[str, Optional[float]] = {}
                    product_rates_hard_out: dict[str, Optional[float]] = {}
                    row_total = 0.0
                    row_total_hard = 0.0

                    for p in products:
                        rate: Optional[float] = None
                        rate_hard: Optional[float] = None

                        monthly_dict = rate_map.get(p.product_code, {})
                        monthly_hard_dict = rate_map_hard.get(p.product_code, {})
                        if bm_str in monthly_dict:
                            rate = monthly_dict[bm_str]
                        if bm_str in monthly_hard_dict:
                            rate_hard = monthly_hard_dict[bm_str]

                        if rate is None and p.clause_tariff_id is not None:
                            annual_rates = p.__dict__.get('_annual_rates', [])
                            for ar in annual_rates:
                                ps = ar["period_start"]
                                pe = ar["period_end"]
                                if ps and ps <= bm and (pe is None or bm <= pe):
                                    rate = _decimal_to_float(ar["final_effective_tariff"]) or _decimal_to_float(ar["effective_tariff"])
                                    if rate_hard is None:
                                        rate_hard = _decimal_to_float(ar.get("effective_tariff_hard_ccy"))
                                    break

                        if rate is None:
                            rate = base_rate_map.get(p.product_code)

                        product_rates_out[p.product_code] = rate
                        product_rates_hard_out[p.product_code] = rate_hard

                        amount: Optional[float] = None
                        amount_hard: Optional[float] = None

                        # Look up per-product kWh for this month
                        product_kwh = per_product_map.get((bm_str, p.billing_product_id))

                        if rate is not None:
                            if p.is_metered:
                                if product_kwh is not None:
                                    amount = product_kwh * rate
                                elif bm_str not in months_with_product_data and actual is not None:
                                    amount = actual * rate  # fallback only for months without per-product data
                            else:
                                amount = rate
                        if rate_hard is not None:
                            if p.is_metered:
                                if product_kwh is not None:
                                    amount_hard = product_kwh * rate_hard
                                elif bm_str not in months_with_product_data and actual is not None:
                                    amount_hard = actual * rate_hard  # fallback only for months without per-product data
                            else:
                                amount_hard = rate_hard

                        product_amounts[p.product_code] = amount
                        product_amounts_hard[p.product_code] = amount_hard
                        if amount is not None:
                            row_total += amount
                        if amount_hard is not None:
                            row_total_hard += amount_hard

                    if actual is not None:
                        totals["actual_kwh"] += actual
                    if forecast is not None:
                        totals["forecast_kwh"] += forecast
                    totals["total_billing"] += row_total
                    totals["total_billing_hard"] += row_total_hard

                    rows.append(MonthlyBillingRow(
                        billing_month=bm_str,
                        billing_period_id=mr.get("billing_period_id"),
                        actual_kwh=actual,
                        forecast_kwh=forecast,
                        variance_kwh=variance_kwh,
                        variance_pct=variance_pct,
                        product_amounts=product_amounts,
                        product_rates=product_rates_out,
                        product_amounts_hard_ccy=product_amounts_hard,
                        product_rates_hard_ccy=product_rates_hard_out,
                        total_billing_amount=row_total if row_total > 0 else None,
                        total_billing_amount_hard_ccy=row_total_hard if row_total_hard > 0 else None,
                    ))

                return MonthlyBillingResponse(
                    success=True,
                    rows=rows,
                    products=products,
                    currency_code=currency_code,
                    hard_currency_code=hard_currency_code,
                    degradation_pct=degradation_pct,
                    cod_date=cod_date_str,
                    summary=totals,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching monthly billing for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/monthly-billing/manual
# ============================================================================

@router.post(
    "/projects/{project_id}/monthly-billing/manual",
    response_model=ImportResponse,
    summary="Add/update a single month of billing data",
)
async def add_manual_entry(
    project_id: int = Path(..., description="Project ID"),
    body: ManualEntryRequest = ...,
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        parts = body.billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)
    except Exception:
        raise HTTPException(status_code=400, detail="billing_month must be YYYY-MM or YYYY-MM-DD")

    if body.actual_kwh is None and body.forecast_kwh is None:
        raise HTTPException(status_code=400, detail="At least one of actual_kwh or forecast_kwh required")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT organization_id FROM project WHERE id = %(pid)s", {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")
                org_id = proj["organization_id"]

                count = 0

                if body.actual_kwh is not None:
                    cur.execute("""
                        SELECT id FROM billing_period
                        WHERE start_date <= %(bm)s AND end_date >= %(bm)s
                        LIMIT 1
                    """, {"bm": bm_date})
                    bp_row = cur.fetchone()
                    bp_id = bp_row["id"] if bp_row else None

                    if body.meter_id:
                        meter_id = body.meter_id
                    else:
                        cur.execute("SELECT id FROM meter WHERE project_id = %(pid)s LIMIT 1", {"pid": project_id})
                        meter_row = cur.fetchone()
                        if not meter_row:
                            raise HTTPException(status_code=400, detail="No meter found for project")
                        meter_id = meter_row["id"]

                    cur.execute("""
                        SELECT id FROM meter_aggregate
                        WHERE meter_id = %(mid)s
                          AND date_trunc('month', period_start) = %(bm)s
                        LIMIT 1
                    """, {"mid": meter_id, "bm": bm_date})
                    existing = cur.fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE meter_aggregate
                            SET energy_kwh = %(kwh)s, total_production = %(kwh)s
                            WHERE id = %(id)s
                        """, {"kwh": body.actual_kwh, "id": existing["id"]})
                    else:
                        period_end = date(bm_date.year, bm_date.month + 1, 1) if bm_date.month < 12 else date(bm_date.year + 1, 1, 1)
                        cur.execute("""
                            INSERT INTO meter_aggregate (
                                meter_id, billing_period_id, organization_id,
                                period_start, period_end, energy_kwh, total_production, unit
                            ) VALUES (
                                %(mid)s, %(bpid)s, %(oid)s,
                                %(ps)s, %(pe)s, %(kwh)s, %(kwh)s, 'kWh'
                            )
                        """, {
                            "mid": meter_id, "bpid": bp_id, "oid": org_id,
                            "ps": bm_date, "pe": period_end, "kwh": body.actual_kwh,
                        })
                    count += 1

                if body.forecast_kwh is not None:
                    cur.execute("""
                        SELECT id FROM production_forecast
                        WHERE project_id = %(pid)s AND forecast_month = %(bm)s
                        LIMIT 1
                    """, {"pid": project_id, "bm": bm_date})
                    existing_fc = cur.fetchone()

                    if existing_fc:
                        cur.execute("""
                            UPDATE production_forecast
                            SET forecast_energy_kwh = %(kwh)s, updated_at = NOW()
                            WHERE id = %(id)s
                        """, {"kwh": body.forecast_kwh, "id": existing_fc["id"]})
                    else:
                        cur.execute("""
                            INSERT INTO production_forecast (
                                project_id, organization_id, forecast_month,
                                forecast_energy_kwh, forecast_source
                            ) VALUES (%(pid)s, %(oid)s, %(bm)s, %(kwh)s, 'manual_entry')
                        """, {"pid": project_id, "oid": org_id, "bm": bm_date, "kwh": body.forecast_kwh})
                    count += 1

                return ImportResponse(success=True, imported_rows=count, message=f"Saved {bm_date.strftime('%Y-%m')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving manual billing entry: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/monthly-billing/import
# ============================================================================

@router.post(
    "/projects/{project_id}/monthly-billing/import",
    response_model=ImportResponse,
    summary="Import billing data from CSV/Excel",
)
async def import_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
    file: UploadFile = File(...),
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files accepted")

    try:
        import pandas as pd

        content = await file.read()

        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        if "billing_month" not in df.columns:
            raise HTTPException(status_code=400, detail="Missing required column: billing_month")

        imported = 0
        errors = []

        for _, row in df.iterrows():
            try:
                bm_raw = str(row["billing_month"]).strip()
                try:
                    bm_date = pd.to_datetime(bm_raw).date().replace(day=1)
                except Exception:
                    parts = bm_raw.split("-")
                    bm_date = date(int(parts[0]), int(parts[1]), 1)

                actual = float(row["actual_kwh"]) if "actual_kwh" in df.columns and pd.notna(row.get("actual_kwh")) else None
                forecast = float(row["forecast_kwh"]) if "forecast_kwh" in df.columns and pd.notna(row.get("forecast_kwh")) else None
                mid = int(row["meter_id"]) if "meter_id" in df.columns and pd.notna(row.get("meter_id")) else None

                if actual is None and forecast is None:
                    continue

                entry = ManualEntryRequest(
                    billing_month=bm_date.strftime("%Y-%m"),
                    actual_kwh=actual,
                    forecast_kwh=forecast,
                    meter_id=mid,
                )
                await add_manual_entry(project_id, entry)
                imported += 1

            except HTTPException:
                raise
            except Exception as ex:
                errors.append(f"Row {_ + 1}: {ex}")

        msg = f"Imported {imported} rows"
        if errors:
            msg += f" ({len(errors)} errors)"

        return ImportResponse(success=True, imported_rows=imported, message=msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing billing data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /projects/{project_id}/monthly-billing/export
# ============================================================================

@router.get(
    "/projects/{project_id}/monthly-billing/export",
    summary="Export monthly billing data as Excel",
)
async def export_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
):
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        import pandas as pd

        billing_data = await get_monthly_billing(project_id)

        rows_data = []
        for row in billing_data.rows:
            rd: dict[str, Any] = {
                "Billing Month": row.billing_month,
                "Actual Generation (kWh)": row.actual_kwh,
                "Forecast (kWh)": row.forecast_kwh,
                "Variance (kWh)": row.variance_kwh,
                "Variance (%)": row.variance_pct,
            }
            for p in billing_data.products:
                rd[f"{p.product_name} Rate"] = row.product_rates.get(p.product_code)
                rd[f"{p.product_name} Amount"] = row.product_amounts.get(p.product_code)
            rd["Total Billing Amount"] = row.total_billing_amount
            rows_data.append(rd)

        df = pd.DataFrame(rows_data)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Monthly Billing")
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=monthly_billing_project_{project_id}.xlsx"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting billing data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /projects/{project_id}/meter-billing
# ============================================================================

def _read_expected_invoice(cur, project_id: int, billing_period_id: int, invoice_direction: str = "payable") -> Optional[ExpectedInvoiceSummary]:
    """Read persisted expected invoice and derive section totals from line items."""
    cur.execute("""
        SELECT eih.id, eih.version_no, eih.total_amount
        FROM expected_invoice_header eih
        WHERE eih.project_id = %(pid)s
          AND eih.billing_period_id = %(bp)s
          AND eih.invoice_direction = %(dir)s
          AND eih.is_current = true
        LIMIT 1
    """, {"pid": project_id, "bp": billing_period_id, "dir": invoice_direction})
    header = cur.fetchone()
    if not header:
        return None

    cur.execute("""
        SELECT eil.*, ilit.code AS type_code, m.name AS meter_name
        FROM expected_invoice_line_item eil
        JOIN invoice_line_item_type ilit ON ilit.id = eil.invoice_line_item_type_id
        LEFT JOIN contract_line cl ON cl.id = eil.contract_line_id
        LEFT JOIN meter m ON m.id = cl.meter_id
        WHERE eil.expected_invoice_header_id = %(hid)s
        ORDER BY eil.sort_order, eil.id
    """, {"hid": header["id"]})

    line_items = []
    energy_subtotal = 0.0
    levies_total = 0.0
    vat_amount = 0.0
    withholdings_total = 0.0

    for row in cur.fetchall():
        tc = row["type_code"]
        lt = _decimal_to_float(row["line_total_amount"]) or 0.0

        if tc in ("ENERGY", "AVAILABLE_ENERGY"):
            energy_subtotal += lt
        elif tc == "LEVY":
            levies_total += lt
        elif tc == "TAX":
            vat_amount += lt
        elif tc == "WITHHOLDING":
            withholdings_total += abs(lt)

        line_items.append(ExpectedInvoiceLineItem(
            line_item_type_code=tc,
            component_code=row.get("component_code"),
            description=row.get("description") or "",
            quantity=_decimal_to_float(row.get("quantity")),
            unit_price=_decimal_to_float(row.get("line_unit_price")),
            basis_amount=_decimal_to_float(row.get("basis_amount")),
            rate_pct=_decimal_to_float(row.get("rate_pct")),
            line_total_amount=lt,
            amount_sign=row.get("amount_sign", 1),
            sort_order=row.get("sort_order", 0),
            meter_name=row.get("meter_name"),
        ))

    subtotal_after_levies = energy_subtotal + levies_total
    invoice_total = subtotal_after_levies + vat_amount
    net_due = sum(li.line_total_amount for li in line_items)

    return ExpectedInvoiceSummary(
        header_id=header["id"],
        version_no=header["version_no"],
        energy_subtotal=round(energy_subtotal, 2),
        levies_total=round(levies_total, 2),
        subtotal_after_levies=round(subtotal_after_levies, 2),
        vat_amount=round(vat_amount, 2),
        invoice_total=round(invoice_total, 2),
        withholdings_total=round(withholdings_total, 2),
        net_due=round(net_due, 2),
        line_items=line_items,
    )


@router.get(
    "/projects/{project_id}/meter-billing",
    response_model=MeterBillingResponse,
    summary="Get per-meter billing breakdown",
)
async def get_meter_billing(
    project_id: int = Path(..., description="Project ID"),
) -> MeterBillingResponse:
    """Per-meter billing breakdown with metered + available energy per meter.
    Includes expected_invoice data when available."""
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1) Get contract lines for this project's contract
                cur.execute("""
                    SELECT cl.id AS cl_id, cl.contract_line_number, cl.product_desc,
                           cl.energy_category::text AS energy_category,
                           cl.meter_id, m.name AS meter_name,
                           cl.external_line_id
                    FROM contract_line cl
                    JOIN contract c ON c.id = cl.contract_id
                    LEFT JOIN meter m ON m.id = cl.meter_id
                    WHERE c.project_id = %(pid)s AND cl.is_active = true
                      AND cl.parent_contract_line_id IS NULL
                    ORDER BY cl.contract_line_number
                """, {"pid": project_id})
                cl_rows = cur.fetchall()

                meters_info: list[MeterInfo] = []
                seen_meters: set[int] = set()
                for cl in cl_rows:
                    mid = cl["meter_id"]
                    if mid and mid not in seen_meters:
                        seen_meters.add(mid)
                        meters_info.append(MeterInfo(
                            meter_id=mid,
                            meter_name=cl["meter_name"],
                            contract_line_number=cl["contract_line_number"],
                            energy_category=cl["energy_category"],
                            product_desc=cl["product_desc"],
                        ))

                if not meters_info:
                    cur.execute("""
                        SELECT id, name FROM meter WHERE project_id = %(pid)s ORDER BY id
                    """, {"pid": project_id})
                    for m in cur.fetchall():
                        meters_info.append(MeterInfo(
                            meter_id=m["id"],
                            meter_name=m["name"],
                        ))

                # 2) Get currency (billing + hard)
                cur.execute("""
                    SELECT COALESCE(bcur.code, cur.code) AS code,
                           hcur.code AS hard_currency_code
                    FROM clause_tariff ct
                    JOIN currency cur ON cur.id = ct.currency_id
                    LEFT JOIN tariff_rate tr2 ON tr2.clause_tariff_id = ct.id
                    LEFT JOIN currency bcur ON bcur.id = tr2.billing_currency_id
                    LEFT JOIN currency hcur ON hcur.id = tr2.hard_currency_id
                    WHERE ct.project_id = %(pid)s AND ct.is_current = true
                    ORDER BY tr2.billing_currency_id IS NOT NULL DESC
                    LIMIT 1
                """, {"pid": project_id})
                cc = cur.fetchone()
                currency_code = cc["code"] if cc else None
                hard_currency_code = cc["hard_currency_code"] if cc else None

                # 3) Build per-meter rate resolvers
                meter_tariff_map: dict[int, int] = {}
                for cl in cl_rows:
                    mid = cl["meter_id"]
                    if mid:
                        ext_id = cl.get("external_line_id") if "external_line_id" in (cl.keys() if hasattr(cl, 'keys') else []) else None
                        if ext_id:
                            cur.execute("""
                                SELECT id FROM clause_tariff
                                WHERE tariff_group_key = %(ext_id)s
                                  AND is_current = true AND is_active = true
                                LIMIT 1
                            """, {"ext_id": ext_id})
                            ct_row = cur.fetchone()
                            if ct_row:
                                meter_tariff_map[mid] = ct_row["id"]

                if not meter_tariff_map and cl_rows:
                    cur.execute("""
                        SELECT cl.meter_id, ct.id AS clause_tariff_id
                        FROM contract_line cl
                        JOIN clause_tariff ct
                            ON ct.tariff_group_key = cl.external_line_id
                           AND ct.is_current = true AND ct.is_active = true
                        JOIN contract c ON c.id = cl.contract_id
                        WHERE c.project_id = %(pid)s AND cl.is_active = true
                          AND cl.meter_id IS NOT NULL AND cl.external_line_id IS NOT NULL
                    """, {"pid": project_id})
                    for row in cur.fetchall():
                        meter_tariff_map[row["meter_id"]] = row["clause_tariff_id"]

                cur.execute("""
                    SELECT ct.id AS clause_tariff_id, ct.base_rate
                    FROM clause_tariff ct
                    WHERE ct.project_id = %(pid)s AND ct.is_current = true
                    LIMIT 1
                """, {"pid": project_id})
                tariff_row = cur.fetchone()
                fallback_ct_id = tariff_row["clause_tariff_id"] if tariff_row else None
                fallback_base_rate = float(tariff_row["base_rate"]) if tariff_row and tariff_row["base_rate"] else None

                all_ct_ids = set(meter_tariff_map.values())
                if fallback_ct_id:
                    all_ct_ids.add(fallback_ct_id)

                rate_data_by_ct: dict[int, dict] = {}
                for ct_id in all_ct_ids:
                    cur.execute("SELECT base_rate FROM clause_tariff WHERE id = %(ct_id)s", {"ct_id": ct_id})
                    ct_info = cur.fetchone()
                    br = float(ct_info["base_rate"]) if ct_info and ct_info["base_rate"] else None

                    cur.execute("""
                        SELECT tr.billing_month, tr.effective_rate_billing_ccy,
                               tr.effective_rate_hard_ccy,
                               tr.rate_granularity::text AS rate_granularity,
                               tr.period_start, tr.period_end
                        FROM tariff_rate tr
                        WHERE tr.clause_tariff_id = %(ct_id)s
                          AND tr.calc_status IN ('computed', 'approved')
                        ORDER BY tr.rate_granularity = 'annual' ASC, tr.billing_month
                    """, {"ct_id": ct_id})
                    monthly: dict[str, float] = {}
                    monthly_hard: dict[str, float] = {}
                    annual: list[dict] = []
                    for rr in cur.fetchall():
                        if rr["rate_granularity"] == "monthly" and rr["effective_rate_billing_ccy"] is not None:
                            m_str = rr["billing_month"].strftime("%Y-%m-%d") if isinstance(rr["billing_month"], date) else str(rr["billing_month"])
                            monthly[m_str] = float(rr["effective_rate_billing_ccy"])
                            if rr["effective_rate_hard_ccy"] is not None:
                                monthly_hard[m_str] = float(rr["effective_rate_hard_ccy"])
                        elif rr["rate_granularity"] == "annual":
                            annual.append({
                                "period_start": rr["period_start"],
                                "period_end": rr["period_end"],
                                "rate": float(rr["effective_rate_billing_ccy"]) if rr["effective_rate_billing_ccy"] else None,
                                "rate_hard_ccy": float(rr["effective_rate_hard_ccy"]) if rr["effective_rate_hard_ccy"] else None,
                            })
                    rate_data_by_ct[ct_id] = {"monthly": monthly, "monthly_hard": monthly_hard, "annual": annual, "base": br}

                def resolve_rate_for_meter(meter_id: int, bm: date) -> tuple[Optional[float], Optional[float]]:
                    """Returns (billing_ccy_rate, hard_ccy_rate)."""
                    ct_id = meter_tariff_map.get(meter_id, fallback_ct_id)
                    if ct_id is None:
                        return fallback_base_rate, None
                    rd = rate_data_by_ct.get(ct_id)
                    if rd is None:
                        return fallback_base_rate, None
                    bm_str = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)
                    if bm_str in rd["monthly"]:
                        return rd["monthly"][bm_str], rd.get("monthly_hard", {}).get(bm_str)
                    for ar in rd["annual"]:
                        ps, pe = ar["period_start"], ar["period_end"]
                        if ps and ps <= bm and (pe is None or bm <= pe):
                            return ar["rate"], ar.get("rate_hard_ccy")
                    return rd["base"], None

                # 4) Get per-meter aggregates grouped by month
                meter_ids = [m.meter_id for m in meters_info]
                if not meter_ids:
                    return MeterBillingResponse(success=True, currency_code=currency_code)

                cur.execute("""
                    SELECT
                        date_trunc('month', ma.period_start)::date AS billing_month,
                        ma.meter_id,
                        m.name AS meter_name,
                        MAX(CASE WHEN COALESCE(ma.energy_kwh, ma.total_production, 0) > 0
                                 THEN ma.opening_reading END) AS opening_reading,
                        MAX(CASE WHEN COALESCE(ma.energy_kwh, ma.total_production, 0) > 0
                                 THEN ma.closing_reading END) AS closing_reading,
                        SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS metered_kwh,
                        SUM(COALESCE(ma.available_energy_kwh, 0)) AS available_kwh,
                        MAX(ma.billing_period_id) AS billing_period_id
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE ma.meter_id = ANY(%(mids)s)
                      AND ma.period_start IS NOT NULL
                    GROUP BY date_trunc('month', ma.period_start)::date, ma.meter_id, m.name
                    ORDER BY date_trunc('month', ma.period_start)::date DESC, ma.meter_id
                """, {"mids": meter_ids})
                agg_rows = cur.fetchall()

                # Group by month
                from collections import defaultdict
                month_data: dict[str, list] = defaultdict(list)
                month_bp_map: dict[str, int] = {}  # billing_month → billing_period_id
                for ar in agg_rows:
                    bm = ar["billing_month"]
                    bm_str = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)
                    month_data[bm_str].append(ar)
                    if ar.get("billing_period_id"):
                        month_bp_map[bm_str] = ar["billing_period_id"]

                # 5) Assemble months with expected_invoice when available
                months: list[MeterBillingMonth] = []
                for bm_str in sorted(month_data.keys(), reverse=True):
                    readings_raw = month_data[bm_str]
                    bm = datetime.strptime(bm_str, "%Y-%m-%d").date()

                    readings: list[MeterReadingDetail] = []
                    total_metered = 0.0
                    total_available = 0.0
                    total_amount = 0.0

                    for rr in readings_raw:
                        metered = _decimal_to_float(rr["metered_kwh"]) or 0.0
                        available = _decimal_to_float(rr["available_kwh"]) or 0.0
                        rate, rate_hard = resolve_rate_for_meter(rr["meter_id"], bm)
                        amount = (metered + available) * rate if rate else None
                        amount_hard = (metered + available) * rate_hard if rate_hard else None

                        total_metered += metered
                        total_available += available
                        if amount is not None:
                            total_amount += amount

                        readings.append(MeterReadingDetail(
                            meter_id=rr["meter_id"],
                            meter_name=rr["meter_name"],
                            opening_reading=_decimal_to_float(rr["opening_reading"]),
                            closing_reading=_decimal_to_float(rr["closing_reading"]),
                            metered_kwh=metered,
                            available_kwh=available if available > 0 else None,
                            rate=rate,
                            amount=round(amount, 2) if amount is not None else None,
                            rate_hard_ccy=rate_hard,
                            amount_hard_ccy=round(amount_hard, 2) if amount_hard is not None else None,
                        ))

                    # Try to read persisted expected_invoice
                    expected_invoice = None
                    bp_id = month_bp_map.get(bm_str)
                    if bp_id:
                        expected_invoice = _read_expected_invoice(cur, project_id, bp_id)

                    months.append(MeterBillingMonth(
                        billing_month=bm_str,
                        meter_readings=readings,
                        total_metered_kwh=round(total_metered, 2),
                        total_available_kwh=round(total_available, 2) if total_available > 0 else None,
                        total_energy_kwh=round(total_metered + total_available, 2),
                        total_amount=round(total_amount, 2) if total_amount > 0 else None,
                        expected_invoice=expected_invoice,
                    ))

                return MeterBillingResponse(
                    success=True,
                    meters=meters_info,
                    months=months,
                    currency_code=currency_code,
                    hard_currency_code=hard_currency_code,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching meter billing for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
