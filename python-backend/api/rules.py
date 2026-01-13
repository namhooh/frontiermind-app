"""
API endpoints for rules engine.

Provides REST interface for evaluating contracts and querying results.
"""

from datetime import datetime
from typing import Optional, List
from decimal import Decimal
import logging

from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel, Field

from services.rules_engine import RulesEngine
from db.rules_repository import RulesRepository
from models.contract import RuleEvaluationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules", tags=["Rules Engine"])


# Request/Response Models

class EvaluateRulesRequest(BaseModel):
    """Request body for POST /api/rules/evaluate"""
    contract_id: int = Field(..., description="Contract ID to evaluate")
    period_start: datetime = Field(..., description="Start of evaluation period (ISO 8601)")
    period_end: datetime = Field(..., description="End of evaluation period (ISO 8601)")


class DefaultEventResponse(BaseModel):
    """Response model for default event"""
    id: int
    project_id: int
    contract_id: int
    contract_name: str
    time_occurred: datetime
    time_identified: datetime
    time_cured: Optional[datetime]
    severity: str
    status: str
    metadata_detail: dict
    created_at: datetime


# Endpoints

@router.post("/evaluate", response_model=RuleEvaluationResult)
async def evaluate_rules(request: EvaluateRulesRequest):
    """
    Evaluate contract clauses for a period.

    Runs the rules engine to:
    1. Detect operational events from meter data
    2. Load contract clauses with guarantees
    3. Load meter data for the period
    4. Calculate compliance metrics (availability, capacity factor, etc.)
    5. Detect breaches and calculate liquidated damages
    6. Store results in default_event and rule_output tables
    7. Link breaches to operational events
    8. Generate notifications for stakeholders

    **Example Request:**
    ```json
    {
      "contract_id": 1,
      "period_start": "2024-11-01T00:00:00Z",
      "period_end": "2024-12-01T00:00:00Z"
    }
    ```

    **Example Response:**
    ```json
    {
      "contract_id": 1,
      "period_start": "2024-11-01T00:00:00Z",
      "period_end": "2024-12-01T00:00:00Z",
      "default_events": [
        {
          "breach": true,
          "rule_type": "availability",
          "clause_id": 5,
          "calculated_value": 91.5,
          "threshold_value": 95.0,
          "shortfall": 3.5,
          "ld_amount": 175000.00,
          "details": {...}
        }
      ],
      "ld_total": 175000.00,
      "notifications_generated": 1,
      "processing_notes": ["Detected 3 operational events", "Evaluation complete: 1/3 clauses breached"]
    }
    ```
    """
    try:
        # Validate date range
        if request.period_start >= request.period_end:
            raise HTTPException(
                status_code=400,
                detail="period_start must be before period_end"
            )

        engine = RulesEngine()

        result = engine.evaluate_period(
            contract_id=request.contract_id,
            period_start=request.period_start,
            period_end=request.period_end
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rules evaluation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Rules evaluation failed: {str(e)}"
        )


@router.get("/defaults", response_model=List[DefaultEventResponse])
async def get_default_events(
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    contract_id: Optional[int] = Query(None, description="Filter by contract ID"),
    status: Optional[str] = Query(None, description="Filter by status (open, cured, closed)"),
    time_start: Optional[datetime] = Query(None, description="Filter events starting after this time (ISO 8601)"),
    time_end: Optional[datetime] = Query(None, description="Filter events starting before this time (ISO 8601)"),
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Maximum number of results (1-1000)"),
    offset: Optional[int] = Query(0, ge=0, description="Number of results to skip for pagination")
):
    """
    Query default events (contract breaches).

    Returns a list of default events with optional filters and pagination support.

    **Query Parameters:**
    - `project_id`: Filter by project ID
    - `contract_id`: Filter by contract ID
    - `status`: Filter by status (open, cured, closed)
    - `time_start`: Filter events starting after this time (ISO 8601 format)
    - `time_end`: Filter events starting before this time (ISO 8601 format)
    - `limit`: Maximum number of results (default: 100, max: 1000)
    - `offset`: Number of results to skip (for pagination)

    **Example:**
    ```
    GET /api/rules/defaults?contract_id=1&status=open&limit=20&offset=0
    GET /api/rules/defaults?time_start=2024-11-01T00:00:00Z&time_end=2024-12-01T00:00:00Z
    ```

    **Response:**
    ```json
    [
      {
        "id": 12,
        "project_id": 1,
        "contract_id": 1,
        "contract_name": "Solar PPA Q4 2024",
        "time_occurred": "2024-11-01T00:00:00Z",
        "time_identified": "2024-12-05T10:30:00Z",
        "time_cured": null,
        "severity": "high",
        "status": "open",
        "metadata_detail": {...},
        "created_at": "2024-12-05T10:30:00Z"
      }
    ]
    ```
    """
    try:
        # Validate date range
        if time_start and time_end and time_start > time_end:
            raise HTTPException(
                status_code=400,
                detail="time_start must be before time_end"
            )

        repository = RulesRepository()

        events = repository.get_default_events(
            project_id=project_id,
            contract_id=contract_id,
            status=status,
            time_start=time_start,
            time_end=time_end,
            limit=limit,
            offset=offset
        )

        return events

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query default events: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Query failed: {str(e)}"
        )


@router.post("/defaults/{default_event_id}/cure")
async def cure_default_event(
    default_event_id: int = Path(..., description="Default event ID to cure")
):
    """
    Mark a default event as cured.

    Updates the status to 'cured' and sets time_cured to now.
    Returns information about the cured breach including LD amounts.

    **Example:**
    ```
    POST /api/rules/defaults/12/cure
    ```

    **Response:**
    ```json
    {
      "success": true,
      "message": "Default event 12 marked as cured",
      "default_event_id": 12,
      "rule_outputs": [
        {
          "id": 45,
          "rule_type": "availability",
          "ld_amount": 175000.00,
          "breach": true,
          "description": "Availability breach: 91.50%"
        }
      ],
      "total_ld": 175000.00
    }
    ```

    **Note:** Invoice updates are not yet implemented.
    Future enhancement: This endpoint will automatically update invoices
    to reflect the cured status and adjust LD amounts accordingly.
    """
    try:
        repository = RulesRepository()

        # Get rule outputs before curing to show LD information
        rule_outputs = repository.get_rule_outputs_for_default_event(default_event_id)

        # Calculate total LD
        total_ld = Decimal('0.00')
        for output in rule_outputs:
            if output.get('ld_amount'):
                total_ld += Decimal(str(output['ld_amount']))

        # Cure the default event
        success = repository.cure_default_event(default_event_id)

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to cure default event {default_event_id}"
            )

        # TODO: Update invoice when invoice management is implemented
        # This would involve:
        # 1. Finding invoices linked to this default_event
        # 2. Adjusting invoice line items
        # 3. Recalculating invoice totals
        # 4. Marking invoice for review/regeneration

        return {
            "success": True,
            "message": f"Default event {default_event_id} marked as cured",
            "default_event_id": default_event_id,
            "rule_outputs": [
                {
                    "id": ro.get("id"),
                    "rule_type": ro.get("rule_type"),
                    "ld_amount": float(ro.get("ld_amount", 0)),
                    "breach": ro.get("breach"),
                    "description": ro.get("description")
                }
                for ro in rule_outputs
            ],
            "total_ld": float(total_ld),
            "invoice_updated": False,  # TODO: Implement invoice update
            "notes": [
                "Default event cured successfully",
                "Invoice update not yet implemented (future enhancement)"
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to cure default event {default_event_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cure default event: {str(e)}"
        )
