"""
Contract Processing API Endpoints

This module provides REST API endpoints for contract parsing and analysis.
Phase 1 implementation focuses on in-memory processing without database persistence.
"""

import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Query
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
from db.contract_repository import ContractRepository
from db.database import init_connection_pool

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

# Initialize database connection pool and repository (Phase 2)
# This is optional - endpoints will work without it (in-memory mode)
try:
    init_connection_pool()
    repository = ContractRepository()
    logger.info("Database repository initialized for API endpoints")
    USE_DATABASE = True
except Exception as e:
    logger.warning(f"Database not available, running in in-memory mode: {e}")
    repository = None
    USE_DATABASE = False


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
    ),
    project_id: Optional[int] = Query(None, description="Project ID for this contract"),
    organization_id: Optional[int] = Query(None, description="Organization ID"),
    counterparty_id: Optional[int] = Query(None, description="Counterparty ID"),
    contract_type_id: Optional[int] = Query(None, description="Contract type ID"),
    contract_status_id: Optional[int] = Query(None, description="Contract status ID"),
) -> ParseContractResponse:
    """
    Parse a contract file and extract structured clauses with PII protection.

    Args:
        file: Uploaded contract file (PDF or DOCX)
        project_id: Optional project ID to associate with contract
        organization_id: Optional organization ID
        counterparty_id: Optional counterparty ID
        contract_type_id: Optional contract type ID
        contract_status_id: Optional contract status ID

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

        # Initialize parser (with database if available)
        logger.info(f"Initializing ContractParser (database: {USE_DATABASE})")
        parser = ContractParser(use_database=USE_DATABASE)

        # Process contract
        logger.info(f"Processing contract: {file.filename}")

        if USE_DATABASE and repository:
            # Phase 2: Store contract record with metadata
            contract_id = repository.store_contract(
                name=file.filename,
                file_location=f"/uploads/{file.filename}",  # Placeholder - actual file upload TBD
                description="Contract uploaded via API",
                project_id=project_id,  # NEW
                organization_id=organization_id,  # NEW
                counterparty_id=counterparty_id,  # NEW
                contract_type_id=contract_type_id,  # NEW
                contract_status_id=contract_status_id,  # NEW
            )
            logger.info(
                f"Created contract record: id={contract_id}, "
                f"project_id={project_id}, org_id={organization_id}"
            )

            # Process and store in database
            result: ContractParseResult = parser.process_and_store_contract(
                contract_id=contract_id,
                file_bytes=file_bytes,
                filename=file.filename
            )
        else:
            # Phase 1: In-memory processing only
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
# Phase 2 Endpoints (Database-dependent)
# ============================================================================


class ContractResponse(BaseModel):
    """Response model for getting a contract by ID."""

    success: bool = Field(True, description="Whether request succeeded")
    contract: Dict[str, Any] = Field(..., description="Contract data from database")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "contract": {
                    "id": 123,
                    "name": "Energy Supply Agreement.pdf",
                    "description": "Contract uploaded via API",
                    "file_location": "/uploads/Energy Supply Agreement.pdf",
                    "parsing_status": "completed",
                    "pii_detected_count": 12,
                    "clauses_extracted_count": 5,
                    "processing_time_seconds": 8.45,
                    "created_at": "2026-01-11T10:30:00Z",
                },
            }
        }


class ClausesResponse(BaseModel):
    """Response model for getting clauses for a contract."""

    success: bool = Field(True, description="Whether request succeeded")
    contract_id: int = Field(..., description="Contract ID")
    clauses: List[Dict[str, Any]] = Field(..., description="List of clauses")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "contract_id": 123,
                "clauses": [
                    {
                        "id": 1,
                        "contract_id": 123,
                        "name": "Availability Guarantee",
                        "raw_text": "Seller shall ensure the Facility achieves a minimum annual Availability of 95%.",
                        "summary": "Requires 95% annual availability",
                        "beneficiary_party": "Buyer",
                        "confidence_score": 0.95,
                    }
                ],
            }
        }


@router.get(
    "/{contract_id}",
    response_model=ContractResponse,
    summary="Get contract by ID",
    description="""
    Retrieve contract metadata and parsing status from database.

    **Phase 2 Feature**: Requires database connection.

    Returns contract information including:
    - Parsing status (pending, processing, completed, failed)
    - PII and clause counts
    - Processing time
    - Created/updated timestamps
    """,
    responses={
        200: {
            "description": "Contract found",
            "model": ContractResponse,
        },
        404: {
            "description": "Contract not found",
            "model": ErrorResponse,
        },
        503: {
            "description": "Database not available",
            "model": ErrorResponse,
        },
    },
)
async def get_contract(contract_id: int) -> ContractResponse:
    """
    Get contract by ID from database.

    Args:
        contract_id: Contract ID

    Returns:
        ContractResponse with contract data

    Raises:
        HTTPException: If contract not found or database not available
    """
    if not USE_DATABASE or not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database storage not available",
                "details": "This endpoint requires database connection. Server running in in-memory mode.",
            },
        )

    try:
        contract = repository.get_contract(contract_id)

        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "ContractNotFound",
                    "message": f"Contract with ID {contract_id} not found",
                    "details": None,
                },
            )

        return ContractResponse(success=True, contract=contract)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving contract {contract_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "DatabaseError",
                "message": "Failed to retrieve contract from database",
                "details": str(e),
            },
        )


@router.get(
    "/{contract_id}/clauses",
    response_model=ClausesResponse,
    summary="Get clauses for a contract",
    description="""
    Retrieve all clauses extracted from a contract.

    **Phase 2 Feature**: Requires database connection.

    Returns extracted clauses with:
    - Clause name and raw text
    - AI-generated summary
    - Beneficiary party
    - Confidence score

    **Optional Query Parameters:**
    - `min_confidence`: Filter clauses by minimum confidence score (0.0 to 1.0)
    """,
    responses={
        200: {
            "description": "Clauses retrieved",
            "model": ClausesResponse,
        },
        404: {
            "description": "Contract not found",
            "model": ErrorResponse,
        },
        503: {
            "description": "Database not available",
            "model": ErrorResponse,
        },
    },
)
async def get_contract_clauses(
    contract_id: int, min_confidence: Optional[float] = None
) -> ClausesResponse:
    """
    Get all clauses for a contract from database.

    Args:
        contract_id: Contract ID
        min_confidence: Minimum confidence score filter (optional)

    Returns:
        ClausesResponse with list of clauses

    Raises:
        HTTPException: If contract not found or database not available
    """
    if not USE_DATABASE or not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database storage not available",
                "details": "This endpoint requires database connection. Server running in in-memory mode.",
            },
        )

    try:
        # Check if contract exists
        contract = repository.get_contract(contract_id)
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "success": False,
                    "error": "ContractNotFound",
                    "message": f"Contract with ID {contract_id} not found",
                    "details": None,
                },
            )

        # Get clauses
        clauses = repository.get_clauses(contract_id, min_confidence)

        return ClausesResponse(
            success=True, contract_id=contract_id, clauses=clauses
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving clauses for contract {contract_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "DatabaseError",
                "message": "Failed to retrieve clauses from database",
                "details": str(e),
            },
        )
