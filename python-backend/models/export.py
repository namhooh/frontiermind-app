"""
Pydantic models for the Export API.

Response models for expected invoice export endpoints,
designed for ERP (SAGE) integration via REST API.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class ExportExpectedInvoiceLineItem(BaseModel):
    """A single line item within an expected invoice."""
    model_config = ConfigDict(json_encoders={Decimal: str})

    id: int
    line_item_type_code: Optional[str] = None
    line_item_type_name: Optional[str] = None
    component_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[str] = None
    line_unit_price: Optional[str] = None
    basis_amount: Optional[str] = None
    rate_pct: Optional[str] = None
    line_total_amount: Optional[str] = None
    amount_sign: Optional[int] = None
    sort_order: Optional[int] = None


class ExportExpectedInvoice(BaseModel):
    """An expected invoice header with nested line items."""
    id: int
    project_id: int
    project_name: Optional[str] = None
    sage_id: Optional[str] = None
    contract_id: Optional[int] = None
    billing_period_id: Optional[int] = None
    billing_month: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    counterparty_id: Optional[int] = None
    counterparty_name: Optional[str] = None
    currency_code: Optional[str] = None
    invoice_direction: Optional[str] = None
    total_amount: Optional[str] = None
    version_no: Optional[int] = None
    is_current: Optional[bool] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    line_items: List[ExportExpectedInvoiceLineItem] = Field(default_factory=list)


class ExportExpectedInvoiceResponse(BaseModel):
    """Paginated response for expected invoice export."""
    items: List[ExportExpectedInvoice]
    total: int
    page: int
    page_size: int
