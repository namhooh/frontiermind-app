"""
Contract Processing API Endpoints

This module provides REST API endpoints for contract parsing and analysis.
Phase 1 implementation focuses on in-memory processing without database persistence.
"""

import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from services.contract_parser import (
    ContractParser,
    ContractParserError,
    DocumentParsingError,
    ClauseExtractionError,
)
from models.contract import ExtractedClause, ContractParseResult

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/contracts",
    tags=["contracts"],
    responses={
        404: {"description": "Contract not found"},
        500: {"description": "Internal server error"},
    },
)


# ============================================================================
# Request/Response Models
# ============================================================================


class ParseContractResponse(BaseModel):
    """Response model for contract parsing endpoint."""

    success: bool = Field(..., description="Whether parsing succeeded")
    contract_id: int = Field(
        ..., description="Contract ID (0 for Phase 1 - no DB storage)"
    )
    clauses_extracted: int = Field(..., description="Number of clauses extracted")
    pii_detected: int = Field(..., description="Number of PII entities detected")
    pii_anonymized: int = Field(..., description="Number of PII entities anonymized")
    processing_time: float = Field(..., description="Processing time in seconds")
    clauses: List[ExtractedClause] = Field(
        ..., description="List of extracted clauses with structured data"
    )
    message: str = Field(..., description="Human-readable status message")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "contract_id": 0,
                "clauses_extracted": 5,
                "pii_detected": 12,
                "pii_anonymized": 12,
                "processing_time": 8.45,
                "clauses": [
                    {
                        "clause_name": "Availability Guarantee",
                        "section_reference": "4.1",
                        "clause_type": "availability",
                        "clause_category": "availability",
                        "raw_text": "Seller shall ensure the Facility achieves a minimum annual Availability of 95%.",
                        "summary": "Requires 95% annual availability",
                        "responsible_party": "Seller",
                        "beneficiary_party": "Buyer",
                        "normalized_payload": {
                            "threshold": 95.0,
                            "metric": "availability",
                            "period": "annual",
                        },
                        "confidence_score": 0.95,
                    }
                ],
                "message": "Contract parsed successfully. 5 clauses extracted, 12 PII entities anonymized.",
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response model."""

    success: bool = Field(False, description="Always false for errors")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[str] = Field(None, description="Additional error details")

    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "DocumentParsingError",
                "message": "Failed to parse document",
                "details": "No text extracted from PDF",
            }
        }


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/parse",
    response_model=ParseContractResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse contract and extract clauses",
    description="""
    Upload a contract file (PDF or DOCX) for parsing and clause extraction.

    **Pipeline:**
    1. Upload document (PDF/DOCX)
    2. LlamaParse OCR (extracts text from scanned documents)
    3. PII Detection (local, Presidio)
    4. PII Anonymization (local, replaces PII with placeholders)
    5. Clause Extraction (Claude API - receives ONLY anonymized text)

    **Privacy Guarantee:**
    - Claude AI only sees anonymized text (PII redacted)
    - PII detection/anonymization happens BEFORE Claude API call
    - LlamaParse OCR is preprocessing step, privacy boundary is Claude

    **Phase 1 Note:**
    - Returns results in-memory only (no database storage)
    - contract_id will be 0 (database integration in Phase 2)
    - PII mappings included in response but not persisted

    **Supported formats:** PDF, DOCX
    **File size limit:** 10MB (recommended)
    """,
    responses={
        200: {
            "description": "Contract parsed successfully",
            "model": ParseContractResponse,
        },
        400: {
            "description": "Invalid file format or empty file",
            "model": ErrorResponse,
        },
        413: {
            "description": "File too large",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error during processing",
            "model": ErrorResponse,
        },
    },
)
async def parse_contract(
    file: UploadFile = File(
        ...,
        description="Contract file to parse (PDF or DOCX)",
        media_type="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
) -> ParseContractResponse:
    """
    Parse a contract file and extract structured clauses with PII protection.

    Args:
        file: Uploaded contract file (PDF or DOCX)

    Returns:
        ParseContractResponse with extracted clauses and processing metadata

    Raises:
        HTTPException: For validation errors, processing failures, or unsupported formats
    """
    logger.info(f"Received contract parsing request: {file.filename}")

    # Validate file format
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "ValidationError",
                "message": "No filename provided",
                "details": "File must have a valid filename",
            },
        )

    # Check file extension
    allowed_extensions = {".pdf", ".docx"}
    file_ext = file.filename.lower().split(".")[-1]
    if f".{file_ext}" not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "UnsupportedFileFormat",
                "message": f"Unsupported file format: .{file_ext}",
                "details": f"Supported formats: {', '.join(allowed_extensions)}",
            },
        )

    # Read file bytes
    file_bytes = await file.read()

    # Validate file size (10MB limit)
    max_size = 10 * 1024 * 1024  # 10MB
    if len(file_bytes) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "success": False,
                "error": "FileTooLarge",
                "message": f"File size exceeds {max_size // (1024 * 1024)}MB limit",
                "details": f"File size: {len(file_bytes) // (1024 * 1024)}MB",
            },
        )

    # Check for empty file
    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "EmptyFile",
                "message": "Uploaded file is empty",
                "details": "File must contain data",
            },
        )

    try:

        # Initialize parser
        logger.info("Initializing ContractParser")
        parser = ContractParser()

        # Process contract
        logger.info(f"Processing contract: {file.filename}")
        result: ContractParseResult = parser.process_contract(
            file_bytes, file.filename
        )

        # Build success response
        response = ParseContractResponse(
            success=True,
            contract_id=result.contract_id,  # 0 for Phase 1
            clauses_extracted=len(result.clauses),
            pii_detected=result.pii_detected,
            pii_anonymized=result.pii_anonymized,
            processing_time=result.processing_time,
            clauses=result.clauses,
            message=(
                f"Contract parsed successfully. "
                f"{len(result.clauses)} clauses extracted, "
                f"{result.pii_anonymized} PII entities anonymized."
            ),
        )

        logger.info(
            f"Contract parsing completed: {file.filename} - "
            f"{len(result.clauses)} clauses, {result.pii_anonymized} PII redacted, "
            f"{result.processing_time:.2f}s"
        )

        return response

    except DocumentParsingError as e:
        logger.error(f"Document parsing failed for {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "DocumentParsingError",
                "message": "Failed to parse document",
                "details": str(e),
            },
        )

    except ClauseExtractionError as e:
        logger.error(f"Clause extraction failed for {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "ClauseExtractionError",
                "message": "Failed to extract clauses from contract",
                "details": str(e),
            },
        )

    except ContractParserError as e:
        logger.error(f"Contract parsing error for {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "ContractParserError",
                "message": "Contract processing failed",
                "details": str(e),
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error processing {file.filename}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "InternalServerError",
                "message": "An unexpected error occurred during contract processing",
                "details": str(e),
            },
        )

    finally:
        # Ensure file is closed
        await file.close()


# ============================================================================
# Phase 2 Endpoints (Database-dependent - to be implemented later)
# ============================================================================

# TODO Phase 2: GET /api/contracts/{contract_id}
# TODO Phase 2: GET /api/contracts/{contract_id}/clauses
# TODO Phase 2: POST /api/contracts/{contract_id}/decrypt-pii (admin only)
