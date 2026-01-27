"""
Invoice API Endpoints

Provides REST API endpoints for invoice management including:
- Creating invoices from workflow data
- Retrieving invoice details
"""

import logging
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime

from middleware.rate_limiter import limiter
from db.database import init_connection_pool
from db.invoice_repository import InvoiceRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/invoices",
    tags=["invoices"],
    responses={
        500: {"description": "Internal server error"},
    },
)

# Initialize database connection pool and repository
try:
    init_connection_pool()
    repository = InvoiceRepository()
    USE_DATABASE = True
except Exception as e:
    logger.warning(f"Database not available: {e}")
    repository = None
    USE_DATABASE = False


# ============================================================================
# Request/Response Models
# ============================================================================


class InvoiceLineItemRequest(BaseModel):
    """Line item data for invoice creation."""
    description: str = Field(..., description="Line item description")
    quantity: float = Field(1, description="Quantity")
    unit: str = Field("", description="Unit of measure")
    rate: float = Field(0, description="Unit price/rate")
    amount: float = Field(..., description="Line total amount")
    invoice_line_item_type_id: Optional[int] = Field(None, description="Line item type ID")
    meter_aggregate_id: Optional[int] = Field(None, description="Meter aggregate ID (for energy items)")


class InvoiceDataRequest(BaseModel):
    """Invoice header data for creation."""
    invoice_number: Optional[str] = Field(None, description="Invoice number (auto-generated if not provided)")
    invoice_date: str = Field(..., description="Invoice date (ISO format)")
    due_date: Optional[str] = Field(None, description="Due date (ISO format)")
    total_amount: float = Field(..., description="Total invoice amount")
    status: str = Field("draft", description="Invoice status")


class DefaultEventInput(BaseModel):
    """Input for creating a default event with an invoice."""
    description: str = Field(..., description="Event description")
    rule_type: str = Field(..., description="Rule type (e.g., availability_guarantee)")
    calculated_value: float = Field(..., description="Calculated metric value")
    threshold_value: float = Field(..., description="Threshold from contract")
    shortfall: float = Field(..., description="Difference (threshold - calculated)")
    ld_amount: float = Field(..., description="Liquidated damages amount")
    time_start: str = Field(..., description="Period start (ISO date)")
    time_end: str = Field(..., description="Period end (ISO date)")


class CreateInvoiceRequest(BaseModel):
    """Request body for creating an invoice."""
    project_id: int = Field(..., description="Project ID")
    organization_id: int = Field(..., description="Organization ID")
    contract_id: int = Field(..., description="Contract ID")
    billing_period_id: int = Field(..., description="Billing period ID")
    invoice_data: InvoiceDataRequest = Field(..., description="Invoice header data")
    line_items: List[InvoiceLineItemRequest] = Field(..., description="Invoice line items")
    default_events: Optional[List[DefaultEventInput]] = Field(None, description="Default events to persist (availability-based LD)")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": 1,
                "organization_id": 1,
                "contract_id": 1,
                "billing_period_id": 1,
                "invoice_data": {
                    "invoice_number": "INV-2026-001",
                    "invoice_date": "2026-01-26",
                    "total_amount": 12500.00,
                    "status": "draft"
                },
                "line_items": [
                    {
                        "description": "Energy delivery - January 2026",
                        "quantity": 500,
                        "unit": "MWh",
                        "rate": 25.00,
                        "amount": 12500.00
                    }
                ]
            }
        }


class CreateInvoiceResponse(BaseModel):
    """Response for invoice creation."""
    success: bool = Field(True, description="Whether creation succeeded")
    invoice_id: int = Field(..., description="Created invoice ID")
    message: str = Field(..., description="Success message")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "invoice_id": 123,
                "message": "Invoice created successfully with 3 line items"
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = Field(False, description="Always false for errors")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "",
    response_model=CreateInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invoice",
    description="""
    Create an invoice from workflow data.

    This endpoint is called after the user reviews the invoice preview
    in the workflow UI and confirms the data is correct.

    The invoice is persisted to the database and can then be used
    for report generation.
    """,
    responses={
        201: {
            "description": "Invoice created successfully",
            "model": CreateInvoiceResponse,
        },
        400: {
            "description": "Invalid request data",
            "model": ErrorResponse,
        },
        503: {
            "description": "Database not available",
            "model": ErrorResponse,
        },
    },
)
@limiter.limit("30/minute")
async def create_invoice(
    request: Request,
    body: CreateInvoiceRequest
) -> CreateInvoiceResponse:
    """
    Create an invoice from workflow data.

    Args:
        body: Invoice creation request with header and line items

    Returns:
        CreateInvoiceResponse with the new invoice ID

    Raises:
        HTTPException: If database not available or creation fails
    """
    if not USE_DATABASE or not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database storage not available",
            },
        )

    try:
        # Convert request to repository format
        invoice_data = {
            "invoice_number": body.invoice_data.invoice_number,
            "invoice_date": body.invoice_data.invoice_date,
            "due_date": body.invoice_data.due_date,
            "total_amount": Decimal(str(body.invoice_data.total_amount)),
            "status": body.invoice_data.status,
        }

        line_items = [
            {
                "description": item.description,
                "quantity": Decimal(str(item.quantity)),
                "rate": Decimal(str(item.rate)),
                "amount": Decimal(str(item.amount)),
                "invoice_line_item_type_id": item.invoice_line_item_type_id,
                "meter_aggregate_id": item.meter_aggregate_id,
            }
            for item in body.line_items
        ]

        invoice_id = repository.create_invoice(
            org_id=body.organization_id,
            project_id=body.project_id,
            contract_id=body.contract_id,
            billing_period_id=body.billing_period_id,
            invoice_data=invoice_data,
            line_items=line_items,
        )

        # Persist default events if provided (availability-based LD from frontend)
        events_created = 0
        if body.default_events:
            from db.rules_repository import RulesRepository
            rules_repo = RulesRepository()

            for event in body.default_events:
                # Create default_event record
                default_event_id = rules_repo.create_default_event(
                    project_id=body.project_id,
                    contract_id=body.contract_id,
                    time_start=datetime.fromisoformat(event.time_start),
                    status='open',
                    metadata_detail={
                        "rule_type": event.rule_type,
                        "calculated_value": event.calculated_value,
                        "threshold_value": event.threshold_value,
                        "shortfall": event.shortfall,
                        "ld_amount": event.ld_amount,
                        "source": "invoice_workflow",
                        "invoice_id": invoice_id,
                        "time_end": event.time_end,
                    },
                    description=event.description,
                )

                if default_event_id:
                    # Create rule_output record linked to default_event
                    rules_repo.create_rule_output_simple(
                        default_event_id=default_event_id,
                        project_id=body.project_id,
                        ld_amount=Decimal(str(event.ld_amount)),
                        metadata={
                            "rule_type": event.rule_type,
                            "calculated_value": event.calculated_value,
                            "threshold_value": event.threshold_value,
                            "shortfall": event.shortfall,
                        }
                    )
                    events_created += 1

            logger.info(f"Created {events_created} default events for invoice {invoice_id}")

        message = f"Invoice created successfully with {len(line_items)} line items"
        if events_created > 0:
            message += f" and {events_created} default events"

        return CreateInvoiceResponse(
            success=True,
            invoice_id=invoice_id,
            message=message
        )

    except Exception as e:
        logger.error(f"Error creating invoice: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "InvoiceCreationError",
                "message": f"Failed to create invoice: {str(e)}",
            },
        )
