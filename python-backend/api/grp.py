"""
GRP (Grid Reference Price) Management API Endpoints.

Admin endpoints for querying, verifying, aggregating, and uploading
GRP observations. All endpoints require X-Organization-ID header.
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
from middleware.rate_limiter import limiter
from models.grp import (
    AggregateGRPRequest,
    AggregateGRPResponse,
    AdminUploadResponse,
    GRPObservation,
    GRPObservationListResponse,
    ObservationType,
    VerificationStatus,
    VerifyObservationRequest,
    VerifyObservationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["grp"],
    dependencies=[Depends(require_api_key)],
    responses={
        401: {"description": "Missing or invalid API key"},
        404: {"description": "Resource not found"},
        500: {"description": "Internal server error"},
    },
)

# Ensure connection pool is ready
try:
    init_connection_pool()
except Exception as e:
    logger.warning(f"GRP API: Database initialization failed: {e}")


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
    """Re-aggregate the annual GRP observation if one already exists.

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
    status_filter = ""
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

    annual_grp = total_charges / total_kwh

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
        SET calculated_grp_per_kwh = %s,
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
            annual_grp, total_charges, total_kwh,
            period_start, period_end,
            Json(source_metadata),
            annual_row["id"],
        ),
    )
    logger.info(
        f"Re-aggregated annual GRP for project {project_id}, OY {operating_year}: "
        f"{float(annual_grp):.4f} from {months_included} months"
    )


# =============================================================================
# POST /api/projects/{project_id}/grp-refresh
# =============================================================================

@router.post(
    "/projects/{project_id}/grp-refresh",
    summary="Refresh stale annual GRP observations",
)
async def refresh_grp(request: Request, project_id: int):
    """
    Re-aggregate annual GRP observations that are stale.

    An annual observation is stale when any of its constituent monthly
    observations have been updated more recently than the annual itself.
    Called on page load to ensure the dashboard always shows fresh data.
    """
    org_id = _get_org_id(request)
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
        logger.error(f"Error refreshing GRP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return {"success": True, "refreshed_operating_years": refreshed}


# =============================================================================
# GET /api/projects/{project_id}/grp-observations
# =============================================================================

@router.get(
    "/projects/{project_id}/grp-observations",
    response_model=GRPObservationListResponse,
    summary="List GRP observations for a project",
)
async def list_grp_observations(
    request: Request,
    project_id: int,
    operating_year: Optional[int] = Query(None, ge=1, description="Filter by operating year"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    observation_type: Optional[str] = Query("monthly", description="monthly or annual"),
) -> GRPObservationListResponse:
    """List monthly or annual GRP observations for a project."""
    org_id = _get_org_id(request)
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
                        rp.calculated_grp_per_kwh, rp.total_variable_charges,
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
        logger.error(f"Error listing GRP observations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    observations = []
    for row in rows:
        obs = dict(row)
        # Convert Decimal fields to float for JSON serialization
        for field in ("calculated_grp_per_kwh", "total_variable_charges", "total_kwh_invoiced"):
            if obs.get(field) is not None:
                obs[field] = float(obs[field])
        observations.append(GRPObservation(**obs))

    return GRPObservationListResponse(
        observations=observations,
        total=len(observations),
    )


# =============================================================================
# POST /api/projects/{project_id}/grp-aggregate
# =============================================================================

@router.post(
    "/projects/{project_id}/grp-aggregate",
    response_model=AggregateGRPResponse,
    summary="Aggregate monthly GRP into annual observation",
)
async def aggregate_grp(
    request: Request,
    project_id: int,
    body: AggregateGRPRequest,
) -> AggregateGRPResponse:
    """
    Aggregate monthly observations into a single annual GRP value.

    Weighted average: SUM(total_variable_charges) / SUM(total_kwh_invoiced)
    """
    org_id = _get_org_id(request)
    _validate_project_ownership(project_id, org_id)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Fetch all monthly observations for the operating year
                status_filter = ""
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

                annual_grp = total_charges / total_kwh

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
                        calculated_grp_per_kwh, currency_id,
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
                        calculated_grp_per_kwh = EXCLUDED.calculated_grp_per_kwh,
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
                        annual_grp,
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
        logger.error(f"Error aggregating GRP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})

    return AggregateGRPResponse(
        observation_id=observation_id,
        annual_grp_per_kwh=float(annual_grp),
        operating_year=body.operating_year,
        months_included=months_included,
        months_excluded=months_excluded,
        total_variable_charges=float(total_charges),
        total_kwh_invoiced=float(total_kwh),
        message=f"Annual GRP aggregated from {months_included} month(s) for operating year {body.operating_year}",
    )


# =============================================================================
# PATCH /api/projects/{project_id}/grp-observations/{observation_id}
# =============================================================================

@router.patch(
    "/projects/{project_id}/grp-observations/{observation_id}",
    response_model=VerifyObservationResponse,
    summary="Verify or dispute a GRP observation",
)
async def verify_observation(
    request: Request,
    project_id: int,
    observation_id: int,
    body: VerifyObservationRequest,
) -> VerifyObservationResponse:
    """Update verification status of a GRP observation."""
    org_id = _get_org_id(request)
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
# POST /api/projects/{project_id}/grp-upload
# =============================================================================

@router.post(
    "/projects/{project_id}/grp-upload",
    response_model=AdminUploadResponse,
    summary="Admin direct upload of utility invoice (no token)",
)
@limiter.limit("5/minute")
async def admin_grp_upload(
    request: Request,
    project_id: int,
    file: UploadFile = File(...),
    billing_month: str = Form(..., description="Billing month in YYYY-MM format"),
) -> AdminUploadResponse:
    """
    Admin upload endpoint — same pipeline as token upload but authenticated
    via X-Organization-ID header (no submission token required).
    """
    org_id = _get_org_id(request)
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
    s3_key = f"grp-uploads/{org_id}/{project_id}/{year}/{month:02d}/{safe_filename}"

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

    # 8. Extract and store GRP
    try:
        from services.grp.extraction_service import GRPExtractionService

        extraction_service = GRPExtractionService()
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
        logger.error(f"GRP extraction failed (admin upload): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": f"Extraction failed: {str(e)}"},
        )

    return AdminUploadResponse(
        observation_id=result["observation_id"],
        grp_per_kwh=result["grp_per_kwh"],
        total_variable_charges=result["total_variable_charges"],
        total_kwh_invoiced=result["total_kwh_invoiced"],
        line_items_count=result["line_items_count"],
        extraction_confidence=result["extraction_confidence"],
        message="Invoice processed successfully via admin upload",
        billing_month_stored=result.get("billing_month_stored"),
        period_mismatch=result.get("period_mismatch"),
    )
