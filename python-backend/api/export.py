"""
Export API Endpoints

GET endpoints for external clients (e.g. SAGE via Snowflake) to pull
invoice data from FrontierMind. Uses the same API key auth as ingestion.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from middleware.rate_limiter import limiter
from middleware.api_key_auth import require_api_key
from db.database import get_db_connection, init_connection_pool
from models.export import (
    ExportExpectedInvoice,
    ExportExpectedInvoiceLineItem,
    ExportExpectedInvoiceResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/export",
    tags=["export"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden – missing scope"},
        500: {"description": "Internal server error"},
    },
)


def _authorize_scope(auth: dict, required_scope: str) -> None:
    """Check that the API key's allowed_scopes permit the requested scope."""
    allowed = auth.get("allowed_scopes")
    if allowed is None:
        return
    if required_scope not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key does not have the '{required_scope}' scope. Allowed: {allowed}",
        )


def _dec_to_str(val) -> Optional[str]:
    """Convert a Decimal/float/int to string for JSON precision safety."""
    if val is None:
        return None
    return str(val)


@router.get(
    "/expected-invoices",
    response_model=ExportExpectedInvoiceResponse,
    summary="Export expected invoices for SAGE/ERP integration",
)
@limiter.limit("20/minute")
async def export_expected_invoices(
    request: Request,
    billing_month: Optional[str] = Query(None, description="Filter by billing month (YYYY-MM)"),
    sage_id: Optional[str] = Query(None, description="Filter by project sage_id"),
    invoice_direction: Optional[str] = Query(None, description="'payable' or 'receivable'"),
    include_superseded: bool = Query(False, description="Include non-current versions"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    auth: dict = Depends(require_api_key),
):
    """
    Return expected invoices with nested line items.

    Organization is derived from the API key — no org parameter needed.
    Amounts are returned as strings to avoid floating-point precision loss.
    Only current (latest) invoice versions are returned by default.
    """
    _authorize_scope(auth, "invoice_export")
    organization_id = auth["organization_id"]

    init_connection_pool()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # ---------------------------------------------------------
                # 1. Build WHERE clause
                # ---------------------------------------------------------
                conditions = [
                    "p.organization_id = %(org_id)s",
                ]
                params: dict = {"org_id": organization_id}

                if not include_superseded:
                    conditions.append("h.is_current = true")

                if billing_month:
                    conditions.append("bp.name = %(billing_month)s")
                    params["billing_month"] = billing_month

                if sage_id:
                    conditions.append("p.sage_id = %(sage_id)s")
                    params["sage_id"] = sage_id

                if invoice_direction:
                    if invoice_direction not in ("payable", "receivable"):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="invoice_direction must be 'payable' or 'receivable'",
                        )
                    conditions.append("h.invoice_direction = %(invoice_direction)s")
                    params["invoice_direction"] = invoice_direction

                where_clause = " AND ".join(conditions)

                # ---------------------------------------------------------
                # 2. Count total matching headers
                # ---------------------------------------------------------
                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM expected_invoice_header h
                    JOIN project p ON p.id = h.project_id
                    JOIN billing_period bp ON bp.id = h.billing_period_id
                    WHERE {where_clause}
                    """,
                    params,
                )
                total = cur.fetchone()["count"]

                if total == 0:
                    return ExportExpectedInvoiceResponse(
                        items=[], total=0, page=page, page_size=page_size
                    )

                # ---------------------------------------------------------
                # 3. Fetch paginated headers
                # ---------------------------------------------------------
                offset = (page - 1) * page_size
                params["limit"] = page_size
                params["offset"] = offset

                cur.execute(
                    f"""
                    SELECT
                        h.id,
                        h.project_id,
                        p.name AS project_name,
                        p.sage_id,
                        h.contract_id,
                        h.billing_period_id,
                        bp.name AS billing_month,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        h.counterparty_id,
                        cp.name AS counterparty_name,
                        cu.code AS currency_code,
                        h.invoice_direction::TEXT,
                        h.total_amount,
                        h.version_no,
                        h.is_current,
                        h.generated_at,
                        h.created_at
                    FROM expected_invoice_header h
                    JOIN project p ON p.id = h.project_id
                    JOIN billing_period bp ON bp.id = h.billing_period_id
                    LEFT JOIN counterparty cp ON cp.id = h.counterparty_id
                    LEFT JOIN currency cu ON cu.id = h.currency_id
                    WHERE {where_clause}
                    ORDER BY bp.start_date DESC, p.sage_id, h.version_no DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    params,
                )

                headers = cur.fetchall()

                header_ids = [h["id"] for h in headers]

                # ---------------------------------------------------------
                # 4. Batch-fetch line items for all headers on this page
                # ---------------------------------------------------------
                cur.execute(
                    """
                    SELECT
                        li.id,
                        li.expected_invoice_header_id,
                        lit.code AS line_item_type_code,
                        lit.name AS line_item_type_name,
                        li.component_code,
                        li.description,
                        li.quantity,
                        li.line_unit_price,
                        li.basis_amount,
                        li.rate_pct,
                        li.line_total_amount,
                        li.amount_sign,
                        li.sort_order
                    FROM expected_invoice_line_item li
                    LEFT JOIN invoice_line_item_type lit ON lit.id = li.invoice_line_item_type_id
                    WHERE li.expected_invoice_header_id = ANY(%(header_ids)s)
                    ORDER BY li.expected_invoice_header_id, li.sort_order, li.id
                    """,
                    {"header_ids": header_ids},
                )

                line_rows = cur.fetchall()

                # Group line items by header_id
                lines_by_header: dict[int, list] = defaultdict(list)
                for row in line_rows:
                    hid = row["expected_invoice_header_id"]
                    lines_by_header[hid].append(
                        ExportExpectedInvoiceLineItem(
                            id=row["id"],
                            line_item_type_code=row.get("line_item_type_code"),
                            line_item_type_name=row.get("line_item_type_name"),
                            component_code=row.get("component_code"),
                            description=row.get("description"),
                            quantity=_dec_to_str(row.get("quantity")),
                            line_unit_price=_dec_to_str(row.get("line_unit_price")),
                            basis_amount=_dec_to_str(row.get("basis_amount")),
                            rate_pct=_dec_to_str(row.get("rate_pct")),
                            line_total_amount=_dec_to_str(row.get("line_total_amount")),
                            amount_sign=row.get("amount_sign"),
                            sort_order=row.get("sort_order"),
                        )
                    )

                # ---------------------------------------------------------
                # 5. Assemble response
                # ---------------------------------------------------------
                items = []
                for h in headers:
                    items.append(
                        ExportExpectedInvoice(
                            id=h["id"],
                            project_id=h["project_id"],
                            project_name=h.get("project_name"),
                            sage_id=h.get("sage_id"),
                            contract_id=h.get("contract_id"),
                            billing_period_id=h.get("billing_period_id"),
                            billing_month=h.get("billing_month"),
                            period_start=h.get("period_start"),
                            period_end=h.get("period_end"),
                            counterparty_id=h.get("counterparty_id"),
                            counterparty_name=h.get("counterparty_name"),
                            currency_code=h.get("currency_code"),
                            invoice_direction=h.get("invoice_direction"),
                            total_amount=_dec_to_str(h.get("total_amount")),
                            version_no=h.get("version_no"),
                            is_current=h.get("is_current"),
                            generated_at=h.get("generated_at"),
                            created_at=h.get("created_at"),
                            line_items=lines_by_header.get(h["id"], []),
                        )
                    )

                return ExportExpectedInvoiceResponse(
                    items=items,
                    total=total,
                    page=page,
                    page_size=page_size,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error exporting expected invoices")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export expected invoices: {str(e)}",
        )
