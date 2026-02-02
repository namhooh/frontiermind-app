"""
Temporary PII Redaction API endpoint.

Standalone endpoint for OCR + PII redaction without clause extraction or database storage.
"""

import logging
import time
import os
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional

from llama_parse import LlamaParse
from services.pii_detector import PIIDetector, PIIDetectionError, PIIAnonymizationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pii-redaction-temp", tags=["pii-redaction-temp"])

# Maximum file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


class PIIEntityDetail(BaseModel):
    entity_type: str
    original_value: str
    position_start: int
    position_end: int
    confidence: float


class PIISummaryResponse(BaseModel):
    total_entities: int
    entities_by_type: Dict[str, int]
    entity_details: List[PIIEntityDetail]


class PIIRedactionResponse(BaseModel):
    success: bool
    redacted_text: str
    original_text_length: int
    pii_summary: PIISummaryResponse
    processing_time: float
    error: Optional[str] = None


@router.post("/process", response_model=PIIRedactionResponse)
async def process_pii_redaction(file: UploadFile = File(...)):
    """
    Process a document for PII redaction.

    1. Validate file format and size
    2. Parse document with LlamaParse (OCR)
    3. Detect PII with Presidio
    4. Anonymize PII
    5. Return redacted text + PII summary
    """
    start_time = time.time()

    # Validate file extension
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {file_ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read and validate file size
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(file_bytes) / (1024 * 1024):.1f}MB. Maximum: {MAX_FILE_SIZE / (1024 * 1024):.0f}MB"
        )

    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        # Step 1: Parse document with LlamaParse
        logger.info(f"PII Redaction: Parsing document '{file.filename}'")
        raw_text = await _parse_document(file_bytes, file.filename or "document.pdf")
        logger.info(f"PII Redaction: Parsed {len(raw_text)} characters")

        # Step 2: Detect PII
        logger.info("PII Redaction: Detecting PII")
        pii_detector = PIIDetector()
        pii_entities = pii_detector.detect(raw_text)
        logger.info(f"PII Redaction: Detected {len(pii_entities)} entities")

        # Step 3: Anonymize PII
        logger.info("PII Redaction: Anonymizing PII")
        anonymized_result = pii_detector.anonymize(raw_text, pii_entities)
        logger.info(f"PII Redaction: Anonymized {anonymized_result.pii_count} entities")

        # Build PII summary
        entities_by_type: Dict[str, int] = {}
        entity_details: List[PIIEntityDetail] = []

        for entity in pii_entities:
            entities_by_type[entity.entity_type] = entities_by_type.get(entity.entity_type, 0) + 1
            entity_details.append(PIIEntityDetail(
                entity_type=entity.entity_type,
                original_value=entity.text,
                position_start=entity.start,
                position_end=entity.end,
                confidence=entity.score,
            ))

        processing_time = time.time() - start_time

        return PIIRedactionResponse(
            success=True,
            redacted_text=anonymized_result.anonymized_text,
            original_text_length=len(raw_text),
            pii_summary=PIISummaryResponse(
                total_entities=len(pii_entities),
                entities_by_type=entities_by_type,
                entity_details=entity_details,
            ),
            processing_time=processing_time,
        )

    except (PIIDetectionError, PIIAnonymizationError) as e:
        processing_time = time.time() - start_time
        logger.error(f"PII Redaction failed: {e}")
        raise HTTPException(status_code=500, detail=f"PII processing failed: {str(e)}")

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"PII Redaction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


async def _parse_document(file_bytes: bytes, filename: str) -> str:
    """Parse document using LlamaParse API."""
    llama_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not llama_api_key:
        raise HTTPException(status_code=500, detail="LLAMA_CLOUD_API_KEY not configured")

    llama_parser = LlamaParse(
        api_key=llama_api_key,
        result_type="text",
        system_prompt=(
            "Extract all text from this document. "
            "Preserve the original structure and formatting."
        ),
    )

    temp_dir = Path("/tmp/pii_redaction_temp")
    temp_dir.mkdir(exist_ok=True)

    temp_file = temp_dir / filename
    temp_file.write_bytes(file_bytes)

    try:
        documents = llama_parser.load_data(str(temp_file))
        text = "\n\n".join([doc.text for doc in documents])

        if not text or not text.strip():
            raise HTTPException(status_code=422, detail="No text extracted from document")

        return text
    finally:
        if temp_file.exists():
            temp_file.unlink()
