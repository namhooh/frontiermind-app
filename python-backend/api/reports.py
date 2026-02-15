"""
Reports API Endpoints

REST API for generating and managing invoice reports.
Supports templates, on-demand generation, scheduled reports, and downloads.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, status, Query, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from models.reports import (
    InvoiceReportType,
    FileFormat,
    ReportStatus,
    ReportFrequency,
    DeliveryMethod,
    GenerateReportRequest,
    CreateTemplateRequest,
    UpdateTemplateRequest,
    CreateScheduleRequest,
    UpdateScheduleRequest,
    ReportTemplateResponse,
    GeneratedReportResponse,
    ScheduledReportResponse,
    ReportConfig,
)
from db.report_repository import ReportRepository
from db.database import init_connection_pool
from services.reports import (
    ReportGenerator,
    ReportGenerationError,
    get_storage,
    StorageError,
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
    responses={
        404: {"description": "Resource not found"},
        500: {"description": "Internal server error"},
    },
)

# Initialize database connection and repository (independently)
report_repository = None
storage = None

try:
    init_connection_pool()
    report_repository = ReportRepository()
    logger.info("Report API: Database initialized")
except Exception as e:
    logger.warning(f"Report API: Database initialization failed: {e}")

try:
    storage = get_storage()
    logger.info("Report API: Storage initialized")
except Exception as e:
    logger.warning(f"Report API: Storage initialization failed: {e}")


# ============================================================================
# Helper Functions
# ============================================================================


def get_org_id(request: Request) -> int:
    """
    Extract and validate organization ID from request header.
    Raises HTTPException if missing or invalid.
    """
    org_id = request.headers.get("X-Organization-ID")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": "MissingOrganization",
                "message": "X-Organization-ID header required",
            },
        )
    try:
        return int(org_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "InvalidOrganization",
                "message": "X-Organization-ID must be an integer",
            },
        )


def require_repository():
    """Raise exception if repository not available."""
    if not report_repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database connection not available",
            },
        )


def require_storage():
    """Raise exception if storage not available."""
    if not storage:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "StorageNotAvailable",
                "message": "Storage service not available",
            },
        )


# ============================================================================
# Response Models
# ============================================================================


class SuccessResponse(BaseModel):
    """Generic success response."""
    success: bool = True
    message: str


class TemplateListResponse(BaseModel):
    """Response for listing templates."""
    success: bool = True
    templates: List[ReportTemplateResponse]
    total: int


class GeneratedReportListResponse(BaseModel):
    """Response for listing generated reports."""
    success: bool = True
    reports: List[GeneratedReportResponse]
    total: int


class ScheduledReportListResponse(BaseModel):
    """Response for listing scheduled reports."""
    success: bool = True
    schedules: List[ScheduledReportResponse]
    total: int


class GenerateReportResponse(BaseModel):
    """Response for report generation request."""
    success: bool = True
    report_id: int
    status: str
    message: str


class DownloadUrlResponse(BaseModel):
    """Response with presigned download URL."""
    success: bool = True
    download_url: str
    filename: str
    expires_in_seconds: int = 300


# ============================================================================
# Template Endpoints
# ============================================================================


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="List report templates",
    description="Get all report templates for the organization.",
)
async def list_templates(
    request: Request,
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    include_inactive: bool = Query(False, description="Include inactive templates"),
) -> TemplateListResponse:
    """List all report templates for the organization."""
    require_repository()
    org_id = get_org_id(request)

    try:
        templates = report_repository.list_templates(
            org_id=org_id,
            project_id=project_id,
            include_inactive=include_inactive,
        )

        return TemplateListResponse(
            success=True,
            templates=[ReportTemplateResponse(**t) for t in templates],
            total=len(templates),
        )

    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.get(
    "/templates/{template_id}",
    response_model=ReportTemplateResponse,
    summary="Get template by ID",
    description="Get a specific report template.",
)
async def get_template(
    request: Request,
    template_id: int,
) -> ReportTemplateResponse:
    """Get a report template by ID."""
    require_repository()
    org_id = get_org_id(request)

    try:
        template = report_repository.get_template(template_id, org_id)

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Template {template_id} not found",
                },
            )

        return ReportTemplateResponse(**template)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.post(
    "/templates",
    response_model=ReportTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create report template",
    description="Create a new report template.",
)
async def create_template(
    request: Request,
    template_data: CreateTemplateRequest,
) -> ReportTemplateResponse:
    """Create a new report template."""
    require_repository()
    org_id = get_org_id(request)

    try:
        template_id = report_repository.create_template(
            org_id=org_id,
            data=template_data.model_dump(exclude_none=True),
        )

        template = report_repository.get_template(template_id, org_id)
        logger.info(f"Created template {template_id} for org {org_id}")

        return ReportTemplateResponse(**template)

    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.put(
    "/templates/{template_id}",
    response_model=ReportTemplateResponse,
    summary="Update report template",
    description="Update an existing report template.",
)
async def update_template(
    request: Request,
    template_id: int,
    template_data: UpdateTemplateRequest,
) -> ReportTemplateResponse:
    """Update a report template."""
    require_repository()
    org_id = get_org_id(request)

    try:
        # Check template exists
        existing = report_repository.get_template(template_id, org_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Template {template_id} not found",
                },
            )

        # Update
        updates = template_data.model_dump(exclude_none=True)
        if updates:
            report_repository.update_template(template_id, org_id, updates)

        template = report_repository.get_template(template_id, org_id)
        logger.info(f"Updated template {template_id}")

        return ReportTemplateResponse(**template)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.delete(
    "/templates/{template_id}",
    response_model=SuccessResponse,
    summary="Deactivate report template",
    description="Soft-delete a report template (sets is_active=false).",
)
async def delete_template(
    request: Request,
    template_id: int,
) -> SuccessResponse:
    """Deactivate a report template."""
    require_repository()
    org_id = get_org_id(request)

    try:
        success = report_repository.deactivate_template(template_id, org_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Template {template_id} not found",
                },
            )

        logger.info(f"Deactivated template {template_id}")
        return SuccessResponse(success=True, message="Template deactivated")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


# ============================================================================
# Report Generation Endpoints
# ============================================================================


@router.post(
    "/generate",
    response_model=GenerateReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a report",
    description="""
    Generate a report based on a template or ad-hoc configuration.

    The report is generated asynchronously. Poll the status endpoint
    to check for completion.
    """,
)
async def generate_report(
    request: Request,
    background_tasks: BackgroundTasks,
    report_request: GenerateReportRequest,
) -> GenerateReportResponse:
    """Generate a report (async)."""
    require_repository()
    org_id = get_org_id(request)

    try:
        # Get template if specified
        template = None
        if report_request.template_id:
            template = report_repository.get_template(
                report_request.template_id, org_id
            )
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": f"Template {report_request.template_id} not found",
                    },
                )

        # Determine report type and format
        report_type = (
            report_request.report_type
            or (template and template.get("report_type"))
            or InvoiceReportType.INVOICE_TO_CLIENT
        )
        file_format = (
            report_request.file_format
            or (template and template.get("file_format"))
            or FileFormat.CSV
        )

        # Generate report name
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_name = (
            report_request.name
            or (template and template.get("name"))
            or f"{report_type.value}_{timestamp}"
        )

        # Create generated_report record
        report_id = report_repository.create_generated_report(
            org_id=org_id,
            report_type=report_type.value if isinstance(report_type, InvoiceReportType) else report_type,
            name=report_name,
            file_format=file_format.value if isinstance(file_format, FileFormat) else file_format,
            generation_source="on_demand",
            billing_period_id=report_request.billing_period_id,
            template_id=report_request.template_id,
            contract_id=report_request.contract_id,
            project_id=report_request.project_id,
            invoice_direction=report_request.invoice_direction,
        )

        # Queue background generation
        background_tasks.add_task(
            _generate_report_task,
            report_id=report_id,
        )

        logger.info(f"Queued report generation: id={report_id}")

        return GenerateReportResponse(
            success=True,
            report_id=report_id,
            status=ReportStatus.PENDING.value,
            message="Report generation started",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating report generation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "GenerationError", "message": str(e)},
        )


async def _generate_report_task(report_id: int):
    """Background task to generate a report."""
    try:
        generator = ReportGenerator(
            report_repository=report_repository,
            storage=storage,
        )
        file_path = generator.generate(report_id)
        logger.info(f"Report {report_id} generated: {file_path}")

    except ReportGenerationError as e:
        logger.error(f"Report generation failed for {report_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error generating report {report_id}: {e}")


@router.get(
    "/generated",
    response_model=GeneratedReportListResponse,
    summary="List generated reports",
    description="Get all generated reports for the organization.",
)
async def list_generated_reports(
    request: Request,
    template_id: Optional[int] = Query(None, description="Filter by template"),
    report_type: Optional[str] = Query(None, description="Filter by report type"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    billing_period_id: Optional[int] = Query(None, description="Filter by billing period"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> GeneratedReportListResponse:
    """List generated reports with filters."""
    require_repository()
    org_id = get_org_id(request)

    try:
        filters = {}
        if template_id:
            filters["template_id"] = template_id
        if report_type:
            filters["report_type"] = report_type
        if status_filter:
            filters["status"] = status_filter
        if billing_period_id:
            filters["billing_period_id"] = billing_period_id

        reports, total = report_repository.list_generated_reports(
            org_id=org_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )

        # Add download URLs for completed reports
        for report in reports:
            if report.get("report_status") == "completed" and report.get("file_path"):
                try:
                    report["download_url"] = storage.get_presigned_url(
                        report["file_path"]
                    )
                except Exception:
                    report["download_url"] = None

        return GeneratedReportListResponse(
            success=True,
            reports=[GeneratedReportResponse(**r) for r in reports],
            total=total,
        )

    except Exception as e:
        logger.error(f"Error listing generated reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.get(
    "/generated/{report_id}",
    response_model=GeneratedReportResponse,
    summary="Get generated report",
    description="Get details of a generated report.",
)
async def get_generated_report(
    request: Request,
    report_id: int,
) -> GeneratedReportResponse:
    """Get a generated report by ID."""
    require_repository()
    org_id = get_org_id(request)

    try:
        report = report_repository.get_generated_report(report_id, org_id)

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Report {report_id} not found",
                },
            )

        # Add download URL if completed
        if report.get("report_status") == "completed" and report.get("file_path"):
            try:
                report["download_url"] = storage.get_presigned_url(report["file_path"])
            except Exception:
                report["download_url"] = None

        return GeneratedReportResponse(**report)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting report {report_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.get(
    "/generated/{report_id}/download",
    response_model=DownloadUrlResponse,
    summary="Get download URL",
    description="Get a presigned URL to download the report file.",
)
async def get_download_url(
    request: Request,
    report_id: int,
    expiry: int = Query(300, ge=60, le=3600, description="URL expiry in seconds"),
) -> DownloadUrlResponse:
    """Get a presigned download URL for a report."""
    require_repository()
    require_storage()
    org_id = get_org_id(request)

    try:
        report = report_repository.get_generated_report(report_id, org_id)

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Report {report_id} not found",
                },
            )

        if report.get("report_status") != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "error": "ReportNotReady",
                    "message": f"Report status is {report.get('report_status')}, not completed",
                },
            )

        file_path = report.get("file_path")
        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "FileNotFound",
                    "message": "Report file not found",
                },
            )

        # Generate presigned URL - use actual filename with extension from S3 path
        download_url = storage.get_presigned_url(
            file_path=file_path,
            expiry=expiry,
            filename_override=file_path.split("/")[-1],
        )

        # Increment download count
        report_repository.increment_download_count(report_id)

        # Extract filename from path
        filename = file_path.split("/")[-1]

        return DownloadUrlResponse(
            success=True,
            download_url=download_url,
            filename=filename,
            expires_in_seconds=expiry,
        )

    except HTTPException:
        raise
    except StorageError as e:
        logger.error(f"Storage error getting download URL for {report_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "StorageError", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"Error getting download URL for {report_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "InternalError", "message": str(e)},
        )


# ============================================================================
# Scheduled Report Endpoints
# ============================================================================


@router.get(
    "/scheduled",
    response_model=ScheduledReportListResponse,
    summary="List scheduled reports",
    description="Get all scheduled reports for the organization.",
)
async def list_scheduled_reports(
    request: Request,
    include_inactive: bool = Query(False, description="Include inactive schedules"),
) -> ScheduledReportListResponse:
    """List scheduled reports."""
    require_repository()
    org_id = get_org_id(request)

    try:
        schedules = report_repository.list_scheduled_reports(
            org_id=org_id,
            include_inactive=include_inactive,
        )

        return ScheduledReportListResponse(
            success=True,
            schedules=[ScheduledReportResponse(**s) for s in schedules],
            total=len(schedules),
        )

    except Exception as e:
        logger.error(f"Error listing scheduled reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.get(
    "/scheduled/{schedule_id}",
    response_model=ScheduledReportResponse,
    summary="Get scheduled report",
    description="Get a specific scheduled report.",
)
async def get_scheduled_report(
    request: Request,
    schedule_id: int,
) -> ScheduledReportResponse:
    """Get a scheduled report by ID."""
    require_repository()
    org_id = get_org_id(request)

    try:
        schedule = report_repository.get_scheduled_report(schedule_id, org_id)

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Schedule {schedule_id} not found",
                },
            )

        return ScheduledReportResponse(**schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schedule {schedule_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.post(
    "/scheduled",
    response_model=ScheduledReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create scheduled report",
    description="Create a new scheduled report.",
)
async def create_scheduled_report(
    request: Request,
    schedule_data: CreateScheduleRequest,
) -> ScheduledReportResponse:
    """Create a new scheduled report."""
    require_repository()
    org_id = get_org_id(request)

    try:
        # Verify template exists
        template = report_repository.get_template(schedule_data.template_id, org_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Template {schedule_data.template_id} not found",
                },
            )

        schedule_id = report_repository.create_scheduled_report(
            org_id=org_id,
            data=schedule_data.model_dump(exclude_none=True),
        )

        schedule = report_repository.get_scheduled_report(schedule_id, org_id)
        logger.info(f"Created scheduled report {schedule_id}")

        return ScheduledReportResponse(**schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating scheduled report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.put(
    "/scheduled/{schedule_id}",
    response_model=ScheduledReportResponse,
    summary="Update scheduled report",
    description="Update an existing scheduled report.",
)
async def update_scheduled_report(
    request: Request,
    schedule_id: int,
    schedule_data: UpdateScheduleRequest,
) -> ScheduledReportResponse:
    """Update a scheduled report."""
    require_repository()
    org_id = get_org_id(request)

    try:
        # Check schedule exists
        existing = report_repository.get_scheduled_report(schedule_id, org_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Schedule {schedule_id} not found",
                },
            )

        # Update
        updates = schedule_data.model_dump(exclude_none=True)
        if updates:
            report_repository.update_scheduled_report(schedule_id, org_id, updates)

        schedule = report_repository.get_scheduled_report(schedule_id, org_id)
        logger.info(f"Updated scheduled report {schedule_id}")

        return ScheduledReportResponse(**schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating schedule {schedule_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.delete(
    "/scheduled/{schedule_id}",
    response_model=SuccessResponse,
    summary="Deactivate scheduled report",
    description="Deactivate a scheduled report (soft delete).",
)
async def delete_scheduled_report(
    request: Request,
    schedule_id: int,
) -> SuccessResponse:
    """Deactivate a scheduled report."""
    require_repository()
    org_id = get_org_id(request)

    try:
        # Check schedule exists
        existing = report_repository.get_scheduled_report(schedule_id, org_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "NotFound",
                    "message": f"Schedule {schedule_id} not found",
                },
            )

        # Deactivate
        report_repository.update_scheduled_report(
            schedule_id, org_id, {"is_active": False}
        )

        logger.info(f"Deactivated scheduled report {schedule_id}")
        return SuccessResponse(success=True, message="Schedule deactivated")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating schedule {schedule_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


# ============================================================================
# Utility Endpoints
# ============================================================================


@router.get(
    "/formats",
    summary="List available formats",
    description="Get list of available output formats.",
)
async def list_formats() -> Dict[str, Any]:
    """List available output formats."""
    from services.reports.formatters import is_format_available

    formats = []
    for fmt in FileFormat:
        formats.append({
            "format": fmt.value,
            "available": is_format_available(fmt),
        })

    return {
        "success": True,
        "formats": formats,
    }


@router.get(
    "/types",
    summary="List report types",
    description="Get list of available report types.",
)
async def list_report_types() -> Dict[str, Any]:
    """List available report types."""
    types = [
        {
            "type": rt.value,
            "name": rt.value.replace("_", " ").title(),
        }
        for rt in InvoiceReportType
    ]

    return {
        "success": True,
        "types": types,
    }
