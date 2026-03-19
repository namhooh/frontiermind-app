"""
MRP (Market Reference Price) Management API Endpoints.

Admin endpoints for querying, verifying, aggregating, and uploading
MRP observations. All endpoints require X-Organization-ID header.
"""

import hashlib
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form, status
from psycopg2.extras import Json

from db.database import get_db_connection, init_connection_pool
from middleware.api_key_auth import require_api_key
from middleware.supabase_auth import require_supabase_auth
from middleware.authorization import require_write_access, require_approve_access
from middleware.rate_limiter import limiter
from models.mrp import (
    AggregateMRPRequest,
    AggregateMRPResponse,
    AdminUploadResponse,
    MRPObservation,
    MRPObservationListResponse,
    ManualMRPBatchRequest,
    ManualMRPBatchResponse,
    ObservationType,
    VerificationStatus,
    VerifyObservationRequest,
    VerifyObservationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["mrp"],
    responses={
        404: {"description": "Resource not found"},
        500: {"description": "Internal server error"},
    },
)

# Ensure connection pool is ready
try:
    init_connection_pool()
except Exception as e:
    logger.warning(f"MRP API: Database initialization failed: {e}")


# File upload constraints (reuse values from submissions)
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


# =============================================================================
# Helpers
# =============================================================================

def _get_org_id(request: Request) -> int:
    """Extract and validate X-Organization-ID header."""
    org_id = request.headers.get("X-Organization-ID")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "MissingOrganization",
                    "message": "X-Organization-ID header required"},
        )
    try:
        return int(org_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "InvalidOrganization",
                    "message": "X-Organization-ID must be an integer"},
        )


def _validate_project_ownership(project_id: int, org_id: int) -> None:
    """Verify project exists and belongs to the given organization."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM project WHERE id = %s AND organization_id = %s",
                (project_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"success": False, "message": "Project not found"},
                )


def _reaggregate_annual(cur, project_id: int, org_id: int, operating_year: int) -> None:
    """Re-aggregate the annual MRP observation if one already exists.

    Preserves the original include_pending setting from source_metadata.
    Runs within the caller's transaction (no commit).
    """
    # Check if an annual observation exists for this operating year
    cur.execute(
        """
        SELECT id, source_metadata
        FROM reference_price
        WHERE project_id = %s AND organization_id = %s
          AND operating_year = %s AND observation_type = 'annual'
        """,
        (project_id, org_id, operating_year),
    )
    annual_row = cur.fetchone()
    if not annual_row:
        return  # No annual observation to update

    # Determine include_pending from original aggregation metadata
    agg_meta = (annual_row["source_metadata"] or {}).get("aggregation", {})
    include_pending = agg_meta.get("include_pending", True)

    # Fetch monthly observations with the same filter
    # Always exclude disputed observations from aggregation
    status_filter = "AND rp.verification_status != 'disputed'"
    if not include_pending:
        status_filter = "AND rp.verification_status = 'jointly_verified'"

    cur.execute(
        f"""
        SELECT rp.id, rp.period_start, rp.verification_status,
               rp.total_variable_charges, rp.total_kwh_invoiced
        FROM reference_price rp
        WHERE rp.project_id = %s AND rp.organization_id = %s
          AND rp.operating_year = %s AND rp.observation_type = 'monthly'
          {status_filter}
        ORDER BY rp.period_start
        """,
        (project_id, org_id, operating_year),
    )
    monthly_rows = cur.fetchall()

    if not monthly_rows:
        return  # No qualifying months — leave existing annual as-is

    # Count total monthly for excluded calculation
    cur.execute(
        """
        SELECT COUNT(*) as total_monthly FROM reference_price
        WHERE project_id = %s AND organization_id = %s
          AND operating_year = %s AND observation_type = 'monthly'
        """,
        (project_id, org_id, operating_year),
    )
    total_monthly = cur.fetchone()["total_monthly"]
    months_included = len(monthly_rows)
    months_excluded = total_monthly - months_included

    total_charges = Decimal("0")
    total_kwh = Decimal("0")
    included_ids = []

    for row in monthly_rows:
        total_charges += Decimal(str(row["total_variable_charges"] or 0))
        total_kwh += Decimal(str(row["total_kwh_invoiced"] or 0))
        included_ids.append(row["id"])

    if total_kwh == 0:
        return  # Cannot divide by zero — leave existing annual

    annual_mrp = total_charges / total_kwh

    # Period boundaries
    period_start = monthly_rows[0]["period_start"]
    period_end_row = monthly_rows[-1]["period_start"]
    from calendar import monthrange
    _, last_day = monthrange(period_end_row.year, period_end_row.month)
    period_end = period_end_row.replace(day=last_day)

    source_metadata = {
        "aggregation": {
            "method": "weighted_average",
            "formula": "SUM(total_variable_charges) / SUM(total_kwh_invoiced)",
            "months_included": months_included,
            "months_excluded": months_excluded,
            "included_observation_ids": included_ids,
            "include_pending": include_pending,
            "aggregated_at": datetime.utcnow().isoformat(),
        },
    }

    cur.execute(
        """
        UPDATE reference_price
        SET calculated_mrp_per_kwh = %s,
            total_variable_charges = %s,
            total_kwh_invoiced = %s,
            period_start = %s,
            period_end = %s,
            source_metadata = %s,
            verification_status = 'pending',
            verified_at = NULL,
            updated_at = NOW()
        WHERE id = %s
        """,
        (
            annual_mrp, total_charges, total_kwh,
            period_start, period_end,
            Json(source_metadata),
            annual_row["id"],
        ),
    )
    logger.info(
        f"Re-aggregated annual MRP for project {project_id}, OY {operating_year}: "
        f"{float(annual_mrp):.4f} from {months_included} months"
    )


# =============================================================================
# POST /api/projects/{project_id}/mrp-refresh
# =============================================================================

@router.post(
    "/projects/{project_id}/mrp-refresh",
    summary="Refresh stale annual MRP observations",
)
def refresh_mrp(request: Request, project_id: int, auth: dict = Depends(require_supabase_auth)):
    """
    Re-aggregate annual MRP observations that are stale.

    An annual observation is stale when any of its constituent monthly
    observations have been updated more recently than the annual itself.
    Called on page load to ensure the dashboard always shows fresh data.
    """
    require_write_access(auth)
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    refreshed = []
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Find annual observations whose monthly data has changed
                cur.execute(
                    """
                    SELECT a.id, a.operating_year, a.updated_at AS annual_updated
                    FROM reference_price a
                    WHERE a.project_id = %s AND a.organization_id = %s
                      AND a.observation_type = 'annual'
                      AND EXISTS (
                          SELECT 1 FROM reference_price m
                          WHERE m.project_id = a.project_id
                            AND m.organization_id = a.organization_id
                            AND m.operating_year = a.operating_year
                            AND m.observation_type = 'monthly'
                            AND m.updated_at > a.updated_at
                      )
                    """,
                    (project_id, org_id),
                )
                stale_annuals = cur.fetchall()

                for row in stale_annuals:
                    _reaggregate_annual(cur, project_id, org_id, row["operating_year"])
                    refreshed.append(row["operating_year"])

                if refreshed:
                    conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing MRP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return {"success": True, "refreshed_operating_years": refreshed}


# =============================================================================
# GET /api/projects/{project_id}/mrp-observations
# =============================================================================

@router.get(
    "/projects/{project_id}/mrp-observations",
    response_model=MRPObservationListResponse,
    summary="List MRP observations for a project",
)
def list_mrp_observations(
    request: Request,
    project_id: int,
    operating_year: Optional[int] = Query(None, ge=0, description="Filter by operating year (0 = baseline/pre-COD)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    observation_type: Optional[str] = Query("monthly", description="monthly or annual"),
    auth: dict = Depends(require_supabase_auth),
) -> MRPObservationListResponse:
    """List monthly or annual MRP observations for a project."""
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    # Build query with dynamic filters
    conditions = ["rp.project_id = %s", "rp.organization_id = %s"]
    params: list = [project_id, org_id]

    if observation_type:
        if observation_type not in ("monthly", "annual"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"success": False, "message": "observation_type must be 'monthly' or 'annual'"},
            )
        conditions.append("rp.observation_type = %s")
        params.append(observation_type)

    if operating_year is not None:
        conditions.append("rp.operating_year = %s")
        params.append(operating_year)

    if verification_status:
        valid_statuses = {"pending", "jointly_verified", "disputed", "estimated"}
        if verification_status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"success": False, "message": f"Invalid verification_status. Must be one of: {', '.join(sorted(valid_statuses))}"},
            )
        conditions.append("rp.verification_status = %s")
        params.append(verification_status)

    where_clause = " AND ".join(conditions)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        rp.id, rp.project_id, rp.operating_year,
                        rp.period_start, rp.period_end, rp.observation_type,
                        rp.calculated_mrp_per_kwh, rp.total_variable_charges,
                        rp.total_kwh_invoiced, rp.verification_status,
                        rp.verified_at, rp.source_metadata,
                        rp.created_at, rp.updated_at
                    FROM reference_price rp
                    WHERE {where_clause}
                    ORDER BY rp.period_start DESC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
    except Exception as e:
        logger.error(f"Error listing MRP observations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    observations = []
    for row in rows:
        obs = dict(row)
        # Convert Decimal fields to float for JSON serialization
        for field in ("calculated_mrp_per_kwh", "total_variable_charges", "total_kwh_invoiced"):
            if obs.get(field) is not None:
                obs[field] = float(obs[field])
        observations.append(MRPObservation(**obs))

    return MRPObservationListResponse(
        observations=observations,
        total=len(observations),
    )


# =============================================================================
# POST /api/projects/{project_id}/mrp-aggregate
# =============================================================================

@router.post(
    "/projects/{project_id}/mrp-aggregate",
    response_model=AggregateMRPResponse,
    summary="Aggregate monthly MRP into annual observation",
)
async def aggregate_mrp(
    request: Request,
    project_id: int,
    body: AggregateMRPRequest,
    auth: dict = Depends(require_supabase_auth),
) -> AggregateMRPResponse:
    """
    Aggregate monthly observations into a single annual MRP value.

    Weighted average: SUM(total_variable_charges) / SUM(total_kwh_invoiced)
    """
    require_write_access(auth)
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Fetch all monthly observations for the operating year
                # Always exclude disputed observations from aggregation
                status_filter = "AND rp.verification_status != 'disputed'"
                params: list = [project_id, org_id, body.operating_year]
                if not body.include_pending:
                    status_filter = "AND rp.verification_status = 'jointly_verified'"

                cur.execute(
                    f"""
                    SELECT
                        rp.id, rp.period_start, rp.verification_status,
                        rp.total_variable_charges, rp.total_kwh_invoiced
                    FROM reference_price rp
                    WHERE rp.project_id = %s
                      AND rp.organization_id = %s
                      AND rp.operating_year = %s
                      AND rp.observation_type = 'monthly'
                      {status_filter}
                    ORDER BY rp.period_start
                    """,
                    tuple(params),
                )
                monthly_rows = cur.fetchall()

                if not monthly_rows:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={
                            "success": False,
                            "message": f"No qualifying monthly observations found for operating year {body.operating_year}",
                        },
                    )

                # Count excluded months (all monthly obs minus included)
                cur.execute(
                    """
                    SELECT COUNT(*) as total_monthly
                    FROM reference_price
                    WHERE project_id = %s
                      AND organization_id = %s
                      AND operating_year = %s
                      AND observation_type = 'monthly'
                    """,
                    (project_id, org_id, body.operating_year),
                )
                total_monthly = cur.fetchone()["total_monthly"]
                months_included = len(monthly_rows)
                months_excluded = total_monthly - months_included

                # Weighted average: SUM(charges) / SUM(kwh)
                total_charges = Decimal("0")
                total_kwh = Decimal("0")
                included_ids = []

                for row in monthly_rows:
                    charges = Decimal(str(row["total_variable_charges"] or 0))
                    kwh = Decimal(str(row["total_kwh_invoiced"] or 0))
                    total_charges += charges
                    total_kwh += kwh
                    included_ids.append(row["id"])

                if total_kwh == 0:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "success": False,
                            "message": "Cannot aggregate: total kWh is zero across included months",
                        },
                    )

                annual_mrp = total_charges / total_kwh

                # Determine period boundaries from included months
                period_start = monthly_rows[0]["period_start"]
                period_end_row = monthly_rows[-1]["period_start"]
                from calendar import monthrange
                _, last_day = monthrange(period_end_row.year, period_end_row.month)
                period_end = period_end_row.replace(day=last_day)

                # Get currency_id from the project's clause_tariff
                cur.execute(
                    """
                    SELECT ct.currency_id
                    FROM clause_tariff ct
                    WHERE ct.project_id = %s AND ct.is_current = true
                    LIMIT 1
                    """,
                    (project_id,),
                )
                currency_row = cur.fetchone()
                currency_id = currency_row["currency_id"] if currency_row else None

                # Build aggregation metadata
                source_metadata = {
                    "aggregation": {
                        "method": "weighted_average",
                        "formula": "SUM(total_variable_charges) / SUM(total_kwh_invoiced)",
                        "months_included": months_included,
                        "months_excluded": months_excluded,
                        "included_observation_ids": included_ids,
                        "include_pending": body.include_pending,
                        "aggregated_at": datetime.utcnow().isoformat(),
                    },
                }

                # Upsert annual row
                cur.execute(
                    """
                    INSERT INTO reference_price (
                        project_id, organization_id, operating_year,
                        period_start, period_end,
                        calculated_mrp_per_kwh, currency_id,
                        total_variable_charges, total_kwh_invoiced,
                        observation_type, source_metadata, verification_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'annual', %s, 'pending'
                    )
                    ON CONFLICT (project_id, operating_year)
                        WHERE observation_type = 'annual'
                    DO UPDATE SET
                        period_start = EXCLUDED.period_start,
                        period_end = EXCLUDED.period_end,
                        calculated_mrp_per_kwh = EXCLUDED.calculated_mrp_per_kwh,
                        total_variable_charges = EXCLUDED.total_variable_charges,
                        total_kwh_invoiced = EXCLUDED.total_kwh_invoiced,
                        source_metadata = EXCLUDED.source_metadata,
                        verification_status = 'pending',
                        verified_at = NULL,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        project_id,
                        org_id,
                        body.operating_year,
                        period_start,
                        period_end,
                        annual_mrp,
                        currency_id,
                        total_charges,
                        total_kwh,
                        Json(source_metadata),
                    ),
                )
                observation_id = cur.fetchone()["id"]
                conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error aggregating MRP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return AggregateMRPResponse(
        observation_id=observation_id,
        annual_mrp_per_kwh=float(annual_mrp),
        operating_year=body.operating_year,
        months_included=months_included,
        months_excluded=months_excluded,
        total_variable_charges=float(total_charges),
        total_kwh_invoiced=float(total_kwh),
        message=f"Annual MRP aggregated from {months_included} month(s) for operating year {body.operating_year}",
    )


# =============================================================================
# DELETE /api/projects/{project_id}/mrp-observations/{observation_id}
# =============================================================================

@router.delete(
    "/projects/{project_id}/mrp-observations/{observation_id}",
    summary="Delete a disputed MRP observation",
)
async def delete_observation(
    request: Request,
    project_id: int,
    observation_id: int,
    auth: dict = Depends(require_supabase_auth),
):
    """Delete an MRP observation. Only disputed observations may be deleted."""
    require_write_access(auth)
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, verification_status, operating_year, observation_type
                    FROM reference_price
                    WHERE id = %s AND project_id = %s AND organization_id = %s
                    """,
                    (observation_id, project_id, org_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "message": "Observation not found"},
                    )

                if row["verification_status"] != "disputed":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "success": False,
                            "message": "Only disputed observations can be deleted",
                        },
                    )

                operating_year = row["operating_year"]
                obs_type = row["observation_type"]

                cur.execute(
                    "DELETE FROM reference_price WHERE id = %s AND project_id = %s AND organization_id = %s",
                    (observation_id, project_id, org_id),
                )

                # Re-aggregate annual if a monthly observation was deleted
                if obs_type == "monthly":
                    _reaggregate_annual(cur, project_id, org_id, operating_year)

                conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting observation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return {
        "success": True,
        "message": f"Observation {observation_id} deleted",
    }


# =============================================================================
# PATCH /api/projects/{project_id}/mrp-observations/{observation_id}
# =============================================================================

@router.patch(
    "/projects/{project_id}/mrp-observations/{observation_id}",
    response_model=VerifyObservationResponse,
    summary="Verify or dispute an MRP observation",
)
async def verify_observation(
    request: Request,
    project_id: int,
    observation_id: int,
    body: VerifyObservationRequest,
    auth: dict = Depends(require_supabase_auth),
) -> VerifyObservationResponse:
    """Update verification status of an MRP observation."""
    require_approve_access(auth)
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Fetch the observation
                cur.execute(
                    """
                    SELECT id, verification_status, source_metadata
                    FROM reference_price
                    WHERE id = %s AND project_id = %s AND organization_id = %s
                    """,
                    (observation_id, project_id, org_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "message": "Observation not found"},
                    )

                current_status = row["verification_status"]
                if current_status != "pending" and current_status == body.verification_status.value:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"success": False, "message": f"Observation is already '{current_status}'"},
                    )

                # Merge notes into source_metadata
                existing_metadata = row["source_metadata"] or {}
                if body.notes:
                    verification_log = existing_metadata.get("verification_log", [])
                    verification_log.append({
                        "status": body.verification_status.value,
                        "notes": body.notes,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    existing_metadata["verification_log"] = verification_log

                # Set verified_at when jointly_verified
                verified_at = None
                if body.verification_status == VerificationStatus.JOINTLY_VERIFIED:
                    verified_at = datetime.utcnow()

                cur.execute(
                    """
                    UPDATE reference_price
                    SET verification_status = %s,
                        verified_at = COALESCE(%s, verified_at),
                        source_metadata = %s,
                        updated_at = NOW()
                    WHERE id = %s AND project_id = %s AND organization_id = %s
                    RETURNING id, verification_status, verified_at, operating_year, observation_type
                    """,
                    (
                        body.verification_status.value,
                        verified_at,
                        Json(existing_metadata),
                        observation_id,
                        project_id,
                        org_id,
                    ),
                )
                updated = cur.fetchone()

                # Re-aggregate annual observation if this was a monthly observation
                if updated["observation_type"] == "monthly":
                    _reaggregate_annual(cur, project_id, org_id, updated["operating_year"])

                conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying observation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return VerifyObservationResponse(
        observation_id=updated["id"],
        verification_status=updated["verification_status"],
        verified_at=updated["verified_at"],
        message=f"Observation {observation_id} marked as {updated['verification_status']}",
    )


# =============================================================================
# POST /api/projects/{project_id}/mrp-upload
# =============================================================================

@router.post(
    "/projects/{project_id}/mrp-upload",
    response_model=AdminUploadResponse,
    summary="Admin direct upload of utility invoice (no token)",
)
@limiter.limit("5/minute")
async def admin_mrp_upload(
    request: Request,
    project_id: int,
    file: UploadFile = File(...),
    billing_month: str = Form(..., description="Billing month in YYYY-MM format"),
    auth: dict = Depends(require_supabase_auth),
) -> AdminUploadResponse:
    """
    Admin upload endpoint — same pipeline as token upload but authenticated
    via X-Organization-ID header (no submission token required).
    """
    require_write_access(auth)
    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    # 1. Validate billing_month format
    try:
        if len(billing_month) == 7:
            billing_month_date = date.fromisoformat(billing_month + "-01")
        else:
            billing_month_date = date.fromisoformat(billing_month)
            billing_month_date = billing_month_date.replace(day=1)
        billing_month_str = billing_month_date.isoformat()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Invalid billing_month format. Use YYYY-MM or YYYY-MM-DD."},
        )

    # 2. Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "No file provided"},
        )

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "File type not allowed. Accepted: PDF, PNG, JPG."},
        )

    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": f"Content type '{file.content_type}' not allowed."},
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "File too large. Maximum size is 20 MB."},
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "File is empty"},
        )

    # 3. Hash for dedup
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 4. Duplicate check
    from api.submissions import _check_duplicate_document
    try:
        _check_duplicate_document(project_id, file_hash)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"success": False, "message": str(e)},
        )

    # 5. Upload to S3
    from api.submissions import _upload_to_s3

    year = billing_month_date.year
    month = billing_month_date.month
    safe_filename = f"{file_hash[:16]}{ext}"
    s3_key = f"mrp-uploads/{org_id}/{project_id}/{year}/{month:02d}/{safe_filename}"

    _upload_to_s3(file_bytes, s3_key, file.content_type)

    # 6. Determine operating year from COD
    from api.submissions import _determine_operating_year, _get_cod_date

    operating_year, cod_date = _determine_operating_year(project_id, billing_month_date)

    # 7. Validate billing_month >= COD
    if cod_date and billing_month_date < cod_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Billing month cannot precede project COD date"},
        )

    # 8. Extract and store MRP
    try:
        from services.mrp.extraction_service import MRPExtractionService

        extraction_service = MRPExtractionService()
        result = extraction_service.extract_and_store(
            file_bytes=file_bytes,
            filename=file.filename,
            project_id=project_id,
            org_id=org_id,
            billing_month=billing_month_str,
            operating_year=operating_year,
            s3_path=s3_key,
            file_hash=file_hash,
        )
    except Exception as e:
        logger.error(f"MRP extraction failed (admin upload): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": f"Extraction failed: {str(e)}"},
        )

    return AdminUploadResponse(
        observation_id=result["observation_id"],
        mrp_per_kwh=result["mrp_per_kwh"],
        total_variable_charges=result["total_variable_charges"],
        total_kwh_invoiced=result["total_kwh_invoiced"],
        line_items_count=result["line_items_count"],
        extraction_confidence=result["extraction_confidence"],
        message="Invoice processed successfully via admin upload",
        billing_month_stored=result.get("billing_month_stored"),
        period_mismatch=result.get("period_mismatch"),
    )


# =============================================================================
# POST /api/projects/{project_id}/mrp-manual
# =============================================================================

@router.post(
    "/projects/{project_id}/mrp-manual",
    response_model=ManualMRPBatchResponse,
    summary="Manually insert MRP tariff rates (JSON, no file upload)",
)
async def manual_mrp_entry(
    request: Request,
    project_id: int,
    body: ManualMRPBatchRequest,
    auth: dict = Depends(require_supabase_auth),
) -> ManualMRPBatchResponse:
    """
    Insert manually-sourced MRP tariff rates for a project.

    Accepts per-kWh rates (not invoice totals), so total_variable_charges
    and total_kwh_invoiced are left NULL. Supports pre-COD baseline data
    when is_baseline=True (sets operating_year=0).
    """
    require_write_access(auth)
    from calendar import monthrange

    org_id = auth["organization_id"]
    _validate_project_ownership(project_id, org_id)

    # Resolve currency_id
    currency_id = None
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if body.currency_code:
                    cur.execute(
                        "SELECT id FROM currency WHERE UPPER(code) = UPPER(%s)",
                        (body.currency_code,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"success": False, "message": f"Unknown currency code: {body.currency_code}"},
                        )
                    currency_id = row["id"]
                else:
                    cur.execute(
                        """
                        SELECT ct.currency_id
                        FROM clause_tariff ct
                        WHERE ct.project_id = %s AND ct.is_current = true
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    row = cur.fetchone()
                    currency_id = row["currency_id"] if row else None

                # Fetch oy_start_date for operating_year calculation
                cur.execute("""
                    SELECT ct.logic_parameters->>'oy_start_date' AS oy_start_date
                    FROM project p
                    LEFT JOIN clause_tariff ct
                        ON ct.project_id = p.id AND ct.is_current = true
                    WHERE p.id = %s
                    LIMIT 1
                """, (project_id,))
                proj_row = cur.fetchone()
                cod_date = None
                if proj_row and proj_row.get("oy_start_date"):
                    cod_date = date.fromisoformat(proj_row["oy_start_date"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving currency/COD: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    # Insert all entries in a single transaction
    observation_ids = []
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for entry in body.entries:
                    # Parse billing_month → period boundaries
                    try:
                        billing_date = date.fromisoformat(entry.billing_month + "-01")
                    except ValueError:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"success": False, "message": f"Invalid billing_month: {entry.billing_month}"},
                        )

                    period_start = billing_date
                    _, last_day = monthrange(billing_date.year, billing_date.month)
                    period_end = billing_date.replace(day=last_day)

                    # Determine operating_year
                    if body.is_baseline and cod_date and billing_date < cod_date.replace(day=1):
                        operating_year = 0
                    elif cod_date:
                        year_diff = billing_date.year - cod_date.year
                        if billing_date.month < cod_date.month:
                            year_diff -= 1
                        operating_year = max(1, year_diff + 1)
                    else:
                        operating_year = 0 if body.is_baseline else 1

                    # Build source_metadata
                    source_metadata = {
                        "entry_method": "manual",
                        "entered_at": datetime.utcnow().isoformat(),
                    }
                    if entry.tariff_components:
                        source_metadata["tariff_components"] = entry.tariff_components
                    if entry.notes:
                        source_metadata["notes"] = entry.notes

                    # Upsert into reference_price
                    cur.execute(
                        """
                        INSERT INTO reference_price (
                            project_id, organization_id, operating_year,
                            period_start, period_end,
                            calculated_mrp_per_kwh, currency_id,
                            total_variable_charges, total_kwh_invoiced,
                            observation_type, source_metadata, verification_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            NULL, NULL,
                            'monthly', %s, 'estimated'
                        )
                        ON CONFLICT (project_id, observation_type, period_start)
                        DO UPDATE SET
                            calculated_mrp_per_kwh = EXCLUDED.calculated_mrp_per_kwh,
                            currency_id = EXCLUDED.currency_id,
                            operating_year = EXCLUDED.operating_year,
                            period_end = EXCLUDED.period_end,
                            source_metadata = EXCLUDED.source_metadata,
                            verification_status = 'estimated',
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (
                            project_id,
                            org_id,
                            operating_year,
                            period_start,
                            period_end,
                            entry.mrp_per_kwh,
                            currency_id,
                            Json(source_metadata),
                        ),
                    )
                    observation_ids.append(cur.fetchone()["id"])

                conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inserting manual MRP entries: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return ManualMRPBatchResponse(
        inserted_count=len(observation_ids),
        observation_ids=observation_ids,
        message=f"Inserted {len(observation_ids)} manual MRP rate(s) successfully",
    )
