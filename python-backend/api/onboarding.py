"""
FastAPI endpoints for project onboarding.

Two-phase workflow:
  POST /api/onboard/preview  — parse files, return preview data
  POST /api/onboard/commit   — apply previewed data to production tables
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from middleware.api_key_auth import require_api_key
from models.onboarding import (
    OnboardingCommitRequest,
    OnboardingCommitResponse,
    OnboardingOverrides,
    OnboardingPreviewResponse,
)
from db.database import init_connection_pool
from services.onboarding.onboarding_service import OnboardingError, OnboardingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboard", tags=["onboarding"])

# Lazy-initialized service singleton
_service: Optional[OnboardingService] = None


def _get_service() -> OnboardingService:
    global _service
    if _service is None:
        init_connection_pool()
        _service = OnboardingService()
    return _service


@router.post("/preview", response_model=OnboardingPreviewResponse)
async def preview_onboarding(
    external_project_id: Optional[str] = Form(None),
    external_contract_id: Optional[str] = Form(None),
    excel_file: UploadFile = File(...),
    ppa_pdf_file: Optional[UploadFile] = File(None),
    auth: dict = Depends(require_api_key),
):
    """
    Parse source files and return preview data for human review.

    No production database writes occur during preview.
    """
    organization_id = auth["organization_id"]

    try:
        overrides = OnboardingOverrides(
            external_project_id=external_project_id,
            external_contract_id=external_contract_id,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    excel_bytes = await excel_file.read()
    if not excel_bytes:
        raise HTTPException(status_code=400, detail="Excel file is empty")

    pdf_bytes = None
    pdf_filename = None
    if ppa_pdf_file:
        pdf_bytes = await ppa_pdf_file.read()
        pdf_filename = ppa_pdf_file.filename

    try:
        service = _get_service()
        result = service.preview(
            organization_id=organization_id,
            overrides=overrides,
            excel_bytes=excel_bytes,
            excel_filename=excel_file.filename or "template.xlsx",
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
        )
        return result
    except OnboardingError as e:
        logger.error(f"Preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Preview failed unexpectedly: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during preview")


@router.post("/commit", response_model=OnboardingCommitResponse)
async def commit_onboarding(
    request: OnboardingCommitRequest,
    auth: dict = Depends(require_api_key),
):
    """
    Commit previewed onboarding data to production tables.

    Requires a valid, non-expired preview_id from the preview endpoint.
    """
    organization_id = auth["organization_id"]

    try:
        service = _get_service()
        result = service.commit(
            organization_id=organization_id,
            preview_id=request.preview_id,
            overrides=request.overrides,
        )
        return result
    except OnboardingError as e:
        logger.error(f"Commit failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Commit failed unexpectedly: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during commit")
