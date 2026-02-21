"""
GRP Extraction Service.

Handles OCR extraction of utility invoices, Claude-based structured extraction
of line items, GRP calculation, and storage as monthly reference_price observations.

Pipeline:
1. OCR via LlamaParse
2. Structured extraction via Claude
3. GRP calculation via existing calculator
4. Upsert into reference_price as monthly observation
"""

import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import anthropic
from llama_parse import LlamaParse
from pydantic import BaseModel, Field

from db.database import get_db_connection
from psycopg2.extras import Json
from services.calculations.grid_reference_price import calculate_grp
from services.prompts.grp_extraction_prompt import GRP_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class GRPExtractionError(Exception):
    """Raised when GRP extraction fails."""
    pass


# =========================================================================
# Pydantic models for Claude extraction output validation
# =========================================================================

class ExtractionLineItem(BaseModel):
    description: str = ""
    type_code: str = ""
    amount: Optional[float] = 0
    kwh: Optional[float] = 0
    rate: Optional[float] = None
    unit: Optional[str] = None


class InvoiceMetadata(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    billing_period_start: Optional[str] = None
    billing_period_end: Optional[str] = None
    utility_name: Optional[str] = None
    account_number: Optional[str] = None
    total_amount: Optional[float] = None


class ExtractionResult(BaseModel):
    line_items: List[ExtractionLineItem] = Field(min_length=1)
    invoice_metadata: InvoiceMetadata = Field(default_factory=InvoiceMetadata)
    extraction_confidence: str = "medium"


class GRPExtractionService:
    """Extract utility invoice data, calculate GRP, and store as monthly observation."""

    def __init__(self):
        llama_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not llama_api_key:
            raise GRPExtractionError("LLAMA_CLOUD_API_KEY not found in environment")

        self.llama_parser = LlamaParse(
            api_key=llama_api_key,
            result_type="markdown",
            num_workers=1,
        )
        self.anthropic_client = anthropic.Anthropic()

    def extract_and_store(
        self,
        file_bytes: bytes,
        filename: str,
        project_id: int,
        org_id: int,
        billing_month: str,
        operating_year: int,
        s3_path: str,
        file_hash: str,
        submission_response_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Full pipeline: OCR → extract → calculate → store.

        Args:
            file_bytes: Raw file content (PDF/image).
            filename: Original filename for logging.
            project_id: Project for this GRP observation.
            org_id: Organization ID.
            billing_month: First of month, e.g. "2025-10-01".
            operating_year: Contract operating year.
            s3_path: S3 path where document was uploaded.
            file_hash: SHA-256 hash of file for dedup.
            submission_response_id: Link to submission_response if via token.

        Returns:
            Dict with observation_id, grp_per_kwh, totals, and line_items_count.
        """
        logger.info(f"GRP extraction starting: {filename} for project {project_id}, month {billing_month}")

        # Step 1: OCR
        ocr_text = self._ocr_document(file_bytes, filename)
        logger.info(f"OCR complete: {len(ocr_text)} characters")

        # Step 2: Claude structured extraction
        extraction = self._extract_line_items(ocr_text)
        line_items = extraction.get("line_items", [])
        metadata = extraction.get("invoice_metadata", {})
        confidence = extraction.get("extraction_confidence", "medium")

        logger.info(f"Extraction complete: {len(line_items)} line items, confidence={confidence}")

        # Step 2b: Reconcile billing period
        billing_month = self._reconcile_billing_period(
            user_billing_month=billing_month,
            extracted_metadata=metadata,
            filename=filename,
        )

        if not line_items:
            raise GRPExtractionError("No line items extracted from invoice")

        # Step 3: Calculate GRP using existing calculator
        # Convert extracted line items to the format expected by calculate_grp
        calculator_items = self._to_calculator_format(line_items)

        # Fetch logic_parameters for GRP method
        logic_parameters = self._fetch_grp_logic_parameters(project_id)

        grp_value = calculate_grp(logic_parameters, calculator_items)
        if grp_value is None:
            raise GRPExtractionError(
                "GRP calculation returned None — no VARIABLE_ENERGY items with kWh found"
            )

        # Calculate totals for storage
        total_variable_charges = sum(
            Decimal(str(item.get("amount", 0) or 0))
            for item in line_items
            if item.get("type_code") == "VARIABLE_ENERGY"
        )
        total_kwh = sum(
            Decimal(str(item.get("kwh", 0) or 0))
            for item in line_items
            if item.get("type_code") == "VARIABLE_ENERGY"
        )

        # Step 4: Store as monthly observation
        observation_id = self._store_observation(
            project_id=project_id,
            org_id=org_id,
            operating_year=operating_year,
            billing_month=billing_month,
            grp_value=grp_value,
            total_variable_charges=total_variable_charges,
            total_kwh=total_kwh,
            s3_path=s3_path,
            file_hash=file_hash,
            line_items=line_items,
            metadata=metadata,
            confidence=confidence,
            submission_response_id=submission_response_id,
        )

        result = {
            "observation_id": observation_id,
            "grp_per_kwh": float(grp_value),
            "total_variable_charges": float(total_variable_charges),
            "total_kwh_invoiced": float(total_kwh),
            "line_items_count": len(line_items),
            "extraction_confidence": confidence,
        }

        logger.info(
            f"GRP stored: observation_id={observation_id}, "
            f"grp={grp_value:.6f}/kWh, items={len(line_items)}"
        )

        return result

    # =========================================================================
    # OCR
    # =========================================================================

    def _ocr_document(self, file_bytes: bytes, filename: str) -> str:
        """Extract text from PDF/image via LlamaParse."""
        tmp_dir = Path("/tmp/grp_extraction")
        tmp_dir.mkdir(exist_ok=True)
        # Use UUID-based name to prevent path traversal from user-supplied filenames
        safe_ext = Path(filename).suffix.lower() if filename else ".pdf"
        tmp_path = tmp_dir / f"{uuid4().hex}{safe_ext}"

        try:
            tmp_path.write_bytes(file_bytes)
            documents = self.llama_parser.load_data(str(tmp_path))
            return "\n\n".join(doc.text for doc in documents)
        except Exception as e:
            raise GRPExtractionError(f"OCR failed: {e}") from e
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # =========================================================================
    # Structured Extraction
    # =========================================================================

    def _extract_line_items(self, ocr_text: str) -> Dict[str, Any]:
        """Use Claude to extract structured line items from OCR text."""
        prompt = GRP_EXTRACTION_PROMPT.replace("{ocr_text}", ocr_text)

        try:
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            json_text = content
            if "```json" in content:
                json_text = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_text = content.split("```")[1].split("```")[0]

            raw_data = json.loads(json_text.strip())

        except json.JSONDecodeError as e:
            raise GRPExtractionError(f"Failed to parse Claude extraction response: {e}") from e
        except Exception as e:
            raise GRPExtractionError(f"Claude extraction failed: {e}") from e

        # Validate extraction output through Pydantic
        try:
            validated = ExtractionResult.model_validate(raw_data)
            return validated.model_dump()
        except Exception as e:
            raise GRPExtractionError(
                f"Claude extraction output failed schema validation: {e}"
            ) from e

    # =========================================================================
    # Billing Period Reconciliation
    # =========================================================================

    @staticmethod
    def _reconcile_billing_period(
        user_billing_month: str,
        extracted_metadata: Dict,
        filename: str,
    ) -> str:
        """
        Compare user-provided billing_month against extracted billing_period.
        If the extraction found a clear billing period that differs from what
        the user entered, use the extracted period instead and log a warning.

        Returns the (possibly corrected) billing_month as YYYY-MM-DD string.
        """
        from datetime import date

        extracted_start = extracted_metadata.get("billing_period_start")
        if not extracted_start:
            return user_billing_month  # No extracted date — trust the user

        try:
            extracted_date = date.fromisoformat(extracted_start)
        except (ValueError, TypeError):
            return user_billing_month  # Unparseable — trust the user

        # Normalize both to first-of-month for comparison
        user_date = date.fromisoformat(user_billing_month)
        user_month = user_date.replace(day=1)
        extracted_month = extracted_date.replace(day=1)

        if user_month == extracted_month:
            return user_billing_month  # They agree

        # Mismatch detected — trust the extracted period from the invoice
        logger.warning(
            f"Billing period mismatch for '{filename}': "
            f"user provided {user_billing_month}, "
            f"invoice shows {extracted_start}. "
            f"Using extracted period: {extracted_month.isoformat()}"
        )

        # Store the mismatch in metadata for audit trail
        extracted_metadata["period_mismatch"] = {
            "user_provided": user_billing_month,
            "extracted": extracted_start,
            "resolution": "used_extracted",
        }

        return extracted_month.isoformat()

    # =========================================================================
    # Format Conversion
    # =========================================================================

    @staticmethod
    def _to_calculator_format(line_items: List[Dict]) -> List[Dict]:
        """Convert extracted line items to the format expected by calculate_grp."""
        return [
            {
                "invoice_line_item_type_code": item.get("type_code", ""),
                "line_total_amount": item.get("amount", 0),
                "quantity": item.get("kwh", 0) or 0,
            }
            for item in line_items
        ]

    # =========================================================================
    # Logic Parameters
    # =========================================================================

    @staticmethod
    def _fetch_grp_logic_parameters(project_id: int) -> Dict:
        """Fetch logic_parameters from the REBASED_MARKET_PRICE clause_tariff."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ct.logic_parameters
                    FROM clause_tariff ct
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s
                      AND ct.is_current = true
                      AND esc.code = 'REBASED_MARKET_PRICE'
                    """,
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or not row["logic_parameters"]:
                    # Default to utility_variable_charges_tou if no tariff configured
                    return {"grp_method": "utility_variable_charges_tou"}
                params = row["logic_parameters"]
                # Fill in default grp_method when DB value is null
                if not params.get("grp_method"):
                    params["grp_method"] = "utility_variable_charges_tou"
                return params

    # =========================================================================
    # Storage
    # =========================================================================

    @staticmethod
    def _store_observation(
        project_id: int,
        org_id: int,
        operating_year: int,
        billing_month: str,
        grp_value: Decimal,
        total_variable_charges: Decimal,
        total_kwh: Decimal,
        s3_path: str,
        file_hash: str,
        line_items: List[Dict],
        metadata: Dict,
        confidence: str,
        submission_response_id: Optional[int],
    ) -> int:
        """Upsert monthly observation into reference_price."""
        # Calculate period_end from billing_month
        from datetime import date, timedelta
        from calendar import monthrange

        period_start = date.fromisoformat(billing_month)
        _, last_day = monthrange(period_start.year, period_start.month)
        period_end = period_start.replace(day=last_day)

        # Get currency_id for the project
        with get_db_connection() as conn:
            with conn.cursor() as cur:
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

                source_metadata = {
                    "extracted_line_items": line_items,
                    "invoice_metadata": metadata,
                    "ocr_model": "llama_parse",
                    "extraction_model": "claude-sonnet-4-20250514",
                    "confidence": confidence,
                    "extraction_confidence": confidence,
                }

                cur.execute(
                    """
                    INSERT INTO reference_price (
                        project_id, organization_id, operating_year,
                        period_start, period_end,
                        calculated_grp_per_kwh, currency_id,
                        total_variable_charges, total_kwh_invoiced,
                        observation_type, source_document_path, source_document_hash,
                        source_metadata, verification_status, submission_response_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'monthly', %s, %s, %s, 'pending', %s
                    )
                    ON CONFLICT (project_id, observation_type, period_start) DO UPDATE SET
                        calculated_grp_per_kwh = EXCLUDED.calculated_grp_per_kwh,
                        total_variable_charges = EXCLUDED.total_variable_charges,
                        total_kwh_invoiced = EXCLUDED.total_kwh_invoiced,
                        source_document_path = EXCLUDED.source_document_path,
                        source_document_hash = EXCLUDED.source_document_hash,
                        source_metadata = EXCLUDED.source_metadata,
                        submission_response_id = EXCLUDED.submission_response_id,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        project_id,
                        org_id,
                        operating_year,
                        period_start,
                        period_end,
                        grp_value,
                        currency_id,
                        total_variable_charges,
                        total_kwh,
                        s3_path,
                        file_hash,
                        Json(source_metadata),
                        submission_response_id,
                    ),
                )
                observation_id = cur.fetchone()["id"]
                conn.commit()
                return observation_id
