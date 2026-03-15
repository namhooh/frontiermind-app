"""
Monthly Billing API Endpoints

Assembles billing data per month: actual generation, forecasts, variance,
and per-product billing amounts computed as kWh × effective_rate.

Invoice generation endpoint writes to expected_invoice_* tables with
full tax/levy/withholding calculations.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_FLOOR, ROUND_CEILING, InvalidOperation
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile, File, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.database import get_db_connection, init_connection_pool
from services.audit_service import log_business_event
from models.billing_cycle import GenerateTariffRatesRequest, RunCycleRequest

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
    expected_invoice: Optional[ExpectedInvoiceSummary] = None


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
    amount_metered: Optional[float] = None
    amount_available: Optional[float] = None
    rate_hard_ccy: Optional[float] = None
    amount_hard_ccy: Optional[float] = None


class MeterBillingMonth(BaseModel):
    billing_month: str
    meter_readings: List[MeterReadingDetail] = []
    total_metered_kwh: Optional[float] = None
    total_available_kwh: Optional[float] = None
    total_energy_kwh: Optional[float] = None
    total_amount: Optional[float] = None
    total_amount_hard_ccy: Optional[float] = None
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
    net_due_hard_ccy: Optional[float] = None  # net_due converted via FX rate
    fx_rate: Optional[float] = None           # billing_ccy / hard_ccy (e.g. GHS/USD)
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


_ROUNDING_MODES: dict[str, str] = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
}


def _round_d(val: Decimal, precision: int = 2, mode: str = 'ROUND_HALF_UP') -> Decimal:
    """Round a Decimal with the specified mode."""
    rounding = _ROUNDING_MODES.get(mode)
    if rounding is None:
        logger.warning(f"Unknown rounding mode '{mode}', falling back to ROUND_HALF_UP")
        rounding = ROUND_HALF_UP
    return val.quantize(Decimal(10) ** -precision, rounding=rounding)


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

    # 1) Monthly rates (batch)
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

    # 2) Annual fallback (batch — pick best matching annual rate per tariff)
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

    # 3) Base rate fallback (batch)
    still_missing = [ct_id for ct_id in ids if ct_id not in result]
    if still_missing:
        cur.execute("""
            SELECT id, base_rate FROM clause_tariff WHERE id = ANY(%(ids)s)
        """, {"ids": still_missing})
        for rr in cur.fetchall():
            if rr["base_rate"] is not None:
                result[rr["id"]] = (Decimal(str(rr["base_rate"])), None)

    return result


def _get_project_currencies(cur, project_id: int) -> tuple[str | None, str | None, float | None]:
    """Get billing and hard currency codes + degradation_pct for a project.

    Returns (billing_currency_code, hard_currency_code, degradation_pct).
    """
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
    row = cur.fetchone()
    if not row:
        return None, None, None
    degradation = float(row["degradation_pct"]) if row["degradation_pct"] else None
    return row["code"], row["hard_currency_code"], degradation


def _load_rate_data(cur, ct_id: int) -> dict:
    """Load all rate data (monthly + annual) for a clause_tariff.

    Returns dict with keys: monthly, monthly_hard, annual, base.
    Used by monthly-billing and meter-billing rate lookups.
    """
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
    return {"monthly": monthly, "monthly_hard": monthly_hard, "annual": annual, "base": br}


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

    Delegates to InvoiceService for the actual computation.
    Writes atomically to expected_invoice_header and expected_invoice_line_item.
    Supports versioning: if a current invoice exists, it's superseded.
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    # Validate billing_month format
    try:
        parts = body.billing_month.split("-")
        int(parts[0]), int(parts[1])
    except Exception:
        raise HTTPException(status_code=400, detail="billing_month must be YYYY-MM")

    from services.billing.invoice_service import InvoiceService
    svc = InvoiceService()

    try:
        result = svc.generate(
            project_id=project_id,
            billing_month=body.billing_month,
            invoice_direction=body.invoice_direction or "payable",
            idempotency_key=body.idempotency_key,
        )

        if not result.get("success"):
            error = result.get("error", "Invoice generation failed")
            # Map service errors to appropriate HTTP status codes
            if "not found" in error.lower():
                raise HTTPException(status_code=404, detail=error)
            elif "already generated" in error.lower():
                raise HTTPException(status_code=409, detail=error)
            elif "no billing tax" in error.lower() or "no energy data" in error.lower():
                raise HTTPException(status_code=422, detail=error)
            else:
                raise HTTPException(status_code=422, detail=error)

        log_business_event(
            background_tasks, request,
            action="CREATE",
            resource_type="expected_invoice",
            resource_id=str(result.get("header_id")),
            organization_id=None,  # resolved inside service
            compliance_relevant=True,
            details={"project_id": project_id, "billing_month": body.billing_month, "version": result.get("version_no")},
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
# POST /projects/{project_id}/billing/generate-tariff-rates
# ============================================================================

@router.post(
    "/projects/{project_id}/billing/generate-tariff-rates",
    response_model=dict,
    summary="Generate tariff rates for a billing month",
)
async def generate_tariff_rates(
    project_id: int = Path(..., description="Project ID"),
    body: "GenerateTariffRatesRequest" = ...,
) -> dict:
    """Generate tariff rates from clause_tariff + FX + MRP.

    Dispatches to appropriate generator based on escalation type:
    - Deterministic → RatePeriodGenerator
    - Floating → RebasedMarketPriceEngine (requires FX + MRP)
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    from models.billing_cycle import GenerateTariffRatesRequest as _GTR
    if not isinstance(body, _GTR):
        body = _GTR(**body.dict() if hasattr(body, 'dict') else body)

    from services.billing.tariff_rate_service import TariffRateService
    svc = TariffRateService()

    try:
        result = svc.generate(
            project_id=project_id,
            billing_month=body.billing_month,
            operating_year=body.operating_year,
            force_refresh=body.force_refresh,
        )
        if not result.get("success"):
            raise HTTPException(status_code=422, detail=result.get("error", "Tariff rate generation failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating tariff rates for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/billing/run-cycle
# ============================================================================

@router.post(
    "/projects/{project_id}/billing/run-cycle",
    response_model=dict,
    summary="Run full billing cycle for a billing month",
)
async def run_billing_cycle(
    project_id: int = Path(..., description="Project ID"),
    body: "RunCycleRequest" = ...,
) -> dict:
    """Run the full monthly billing cycle as a dependency graph.

    Layer 1: Verify inputs (FX, MRP conditional, meter data)
    Layer 2: Compute (tariff rates + plant performance in parallel branches)
    Layer 3: Generate expected invoice
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    from models.billing_cycle import RunCycleRequest as _RCR
    if not isinstance(body, _RCR):
        body = _RCR(**body.dict() if hasattr(body, 'dict') else body)

    from services.billing.billing_cycle_orchestrator import BillingCycleOrchestrator
    orchestrator = BillingCycleOrchestrator()

    try:
        result = orchestrator.run_cycle(
            project_id=project_id,
            billing_month=body.billing_month,
            force_refresh=body.force_refresh,
            invoice_direction=body.invoice_direction,
        )
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error running billing cycle for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Guard against double-counted kWh when both a meter_id=NULL row (from
# migration 049) and a real-meter row exist for the same contract_line/month.
_METER_AGG_DEDUP = """
    AND NOT (
        ma.meter_id IS NULL
        AND ma.contract_line_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM meter_aggregate ma2
            WHERE ma2.contract_line_id = ma.contract_line_id
              AND date_trunc('month', ma2.period_start) = date_trunc('month', ma.period_start)
              AND ma2.meter_id IS NOT NULL
        )
    )
"""

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
                currency_code, hard_currency_code, degradation_pct = _get_project_currencies(cur, project_id)

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
                    """ + _METER_AGG_DEDUP + """
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
                    """ + _METER_AGG_DEDUP + """
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

                    rd = _load_rate_data(cur, ct_id)
                    rate_map[p.product_code] = rd["monthly"]
                    rate_map_hard[p.product_code] = rd["monthly_hard"]
                    # Map annual rates to the legacy shape expected by downstream
                    p.__dict__['_annual_rates'] = [
                        {
                            "period_start": ar["period_start"],
                            "period_end": ar["period_end"],
                            "effective_tariff": ar["rate"],
                            "final_effective_tariff": ar["rate"],
                            "effective_tariff_hard_ccy": ar.get("rate_hard_ccy"),
                        }
                        for ar in rd["annual"]
                    ]

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
                                # No fallback: without per-product kWh, leave amount as None
                                # to avoid duplicating total actual across every metered product
                            else:
                                amount = rate
                        if rate_hard is not None:
                            if p.is_metered:
                                if product_kwh is not None:
                                    amount_hard = product_kwh * rate_hard
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

                    # Load expected invoice if billing_period_id exists
                    exp_inv = None
                    bp_id = mr.get("billing_period_id")
                    if bp_id is not None:
                        exp_inv = _read_expected_invoice(cur, project_id, bp_id)

                    rows.append(MonthlyBillingRow(
                        billing_month=bm_str,
                        billing_period_id=bp_id,
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
                        expected_invoice=exp_inv,
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

def _read_expected_invoice(cur, project_id: int, billing_period_id: int, invoice_direction: str = "payable", fx_rate: Optional[float] = None) -> Optional[ExpectedInvoiceSummary]:
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

    net_due_hard = None
    if fx_rate and fx_rate > 0:
        net_due_hard = round(net_due / fx_rate, 2)

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
        net_due_hard_ccy=net_due_hard,
        fx_rate=fx_rate,
        line_items=line_items,
    )


@router.get(
    "/projects/{project_id}/meter-billing",
    response_model=MeterBillingResponse,
    summary="Get per-meter billing breakdown",
)
async def get_meter_billing(
    project_id: int = Path(..., description="Project ID"),
    invoice_direction: str = Query("payable", description="Invoice direction: 'payable' or 'receivable'"),
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
                currency_code, hard_currency_code, _ = _get_project_currencies(cur, project_id)

                # 3) Build per-meter rate resolvers
                # Key by (meter_id, energy_category) so metered/available
                # can have different tariffs for the same meter
                meter_tariff_map: dict[int, int] = {}  # meter_id → ct_id (legacy compat)
                meter_cat_tariff_map: dict[tuple[int, str], int] = {}  # (meter_id, energy_category) → ct_id
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
                                cat = cl.get("energy_category") or "metered"
                                meter_cat_tariff_map[(mid, cat)] = ct_row["id"]

                if not meter_tariff_map and cl_rows:
                    cur.execute("""
                        SELECT cl.meter_id, cl.energy_category::text AS energy_category,
                               ct.id AS clause_tariff_id
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
                        cat = row.get("energy_category") or "metered"
                        meter_cat_tariff_map[(row["meter_id"], cat)] = row["clause_tariff_id"]

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
                    rate_data_by_ct[ct_id] = _load_rate_data(cur, ct_id)

                def resolve_rate_for_meter(meter_id: int, bm: date, energy_category: str | None = None) -> tuple[Optional[float], Optional[float]]:
                    """Returns (billing_ccy_rate, hard_ccy_rate).

                    If energy_category is provided, tries (meter_id, energy_category)
                    key first for per-category pricing, then falls back to meter-level.
                    """
                    ct_id = None
                    if energy_category:
                        ct_id = meter_cat_tariff_map.get((meter_id, energy_category))
                    if ct_id is None:
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
                    total_amount_hard = 0.0
                    month_fx_rate: Optional[float] = None

                    for rr in readings_raw:
                        metered = _decimal_to_float(rr["metered_kwh"]) or 0.0
                        available = _decimal_to_float(rr["available_kwh"]) or 0.0

                        # Resolve rates per energy category for this meter
                        rate_m, rate_m_hard = resolve_rate_for_meter(rr["meter_id"], bm, "metered")
                        rate_a, rate_a_hard = resolve_rate_for_meter(rr["meter_id"], bm, "available")

                        # Compute per-category amounts
                        amt_metered = metered * rate_m if rate_m else None
                        amt_available = available * rate_a if rate_a and available > 0 else None

                        # Total amount = sum of per-category amounts
                        amount = None
                        if amt_metered is not None or amt_available is not None:
                            amount = (amt_metered or 0.0) + (amt_available or 0.0)
                        amount_hard = None
                        amt_m_hard = metered * rate_m_hard if rate_m_hard else None
                        amt_a_hard = available * rate_a_hard if rate_a_hard and available > 0 else None
                        if amt_m_hard is not None or amt_a_hard is not None:
                            amount_hard = (amt_m_hard or 0.0) + (amt_a_hard or 0.0)

                        # Use metered rate as the display rate (backward compat)
                        rate = rate_m
                        rate_hard = rate_m_hard

                        # Derive FX rate from billing/hard rate pair
                        if month_fx_rate is None and rate and rate_hard and rate_hard > 0:
                            month_fx_rate = rate / rate_hard

                        total_metered += metered
                        total_available += available
                        if amount is not None:
                            total_amount += amount
                        if amount_hard is not None:
                            total_amount_hard += amount_hard

                        readings.append(MeterReadingDetail(
                            meter_id=rr["meter_id"],
                            meter_name=rr["meter_name"],
                            opening_reading=_decimal_to_float(rr["opening_reading"]),
                            closing_reading=_decimal_to_float(rr["closing_reading"]),
                            metered_kwh=metered,
                            available_kwh=available if available > 0 else None,
                            rate=rate,
                            amount=round(amount, 2) if amount is not None else None,
                            amount_metered=round(amt_metered, 2) if amt_metered is not None else None,
                            amount_available=round(amt_available, 2) if amt_available is not None else None,
                            rate_hard_ccy=rate_hard,
                            amount_hard_ccy=round(amount_hard, 2) if amount_hard is not None else None,
                        ))

                    # Try to read persisted expected_invoice (pass FX rate for hard_ccy conversion)
                    expected_invoice = None
                    bp_id = month_bp_map.get(bm_str)
                    if bp_id:
                        expected_invoice = _read_expected_invoice(cur, project_id, bp_id, invoice_direction=invoice_direction, fx_rate=month_fx_rate)

                    months.append(MeterBillingMonth(
                        billing_month=bm_str,
                        meter_readings=readings,
                        total_metered_kwh=round(total_metered, 2),
                        total_available_kwh=round(total_available, 2) if total_available > 0 else None,
                        total_energy_kwh=round(total_metered + total_available, 2),
                        total_amount=round(total_amount, 2) if total_amount > 0 else None,
                        total_amount_hard_ccy=round(total_amount_hard, 2) if total_amount_hard > 0 else None,
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
