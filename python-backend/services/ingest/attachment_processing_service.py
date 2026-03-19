"""
Attachment Processing Service.

Orchestration layer between S3-stored inbound attachments and extraction services.
Currently supports MRP extraction; structured for future routing to other extractors.
"""

import hashlib
import logging
import os
from datetime import date
from typing import Any, Dict, Optional

from db.ingest_repository import IngestRepository

logger = logging.getLogger(__name__)

# File types eligible for MRP extraction
MRP_EXTRACTABLE_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class AttachmentProcessingService:
    """Orchestrates extraction from inbound attachments."""

    def __init__(self, repo: IngestRepository):
        self.repo = repo

    def process_attachment(
        self,
        attachment_id: int,
        org_id: int,
        project_id: Optional[int] = None,
        billing_month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run MRP extraction on an inbound attachment.

        Args:
            attachment_id: The inbound_attachment row ID.
            org_id: Organization ID (for access control and extraction).
            project_id: Explicit project. If None, resolved from message context.
            billing_month: YYYY-MM-DD first-of-month. Defaults to current month.

        Returns:
            Dict with extraction results or failure info.
        """
        # 1. Fetch attachment
        att = self.repo.get_attachment(attachment_id)
        if not att:
            return {"success": False, "status": "failed", "failed_reason": "Attachment not found"}

        # 2. Validate file type
        content_type = (att.get("content_type") or "").lower()
        if content_type not in MRP_EXTRACTABLE_TYPES:
            self.repo.update_attachment_status(attachment_id, "skipped")
            return {
                "success": False,
                "status": "skipped",
                "failed_reason": f"Unsupported file type: {content_type}",
            }

        # 3. Fetch parent message for context
        message = self.repo.get_message_for_attachment(attachment_id)
        if not message:
            self.repo.update_attachment_status(
                attachment_id, "failed", failed_reason="Parent message not found"
            )
            return {"success": False, "status": "failed", "failed_reason": "Parent message not found"}

        # 4. Resolve project_id
        if not project_id:
            project_id = message.get("project_id")

        if not project_id and message.get("counterparty_id"):
            project_id = self.repo.resolve_project_for_counterparty(
                message["counterparty_id"], org_id
            )

        if not project_id:
            self.repo.update_attachment_status(
                attachment_id, "failed",
                failed_reason="Cannot resolve project — provide project_id explicitly",
            )
            return {
                "success": False,
                "status": "failed",
                "failed_reason": "Cannot resolve project — provide project_id explicitly",
            }

        # 5. Mark as processing
        self.repo.update_attachment_status(attachment_id, "processing")

        # 6. Download file from S3
        try:
            file_bytes = self._download_from_s3(att["s3_path"])
        except Exception as e:
            reason = f"S3 download failed: {e}"
            logger.error(reason)
            self.repo.update_attachment_status(attachment_id, "failed", failed_reason=reason)
            return {"success": False, "status": "failed", "failed_reason": reason}

        # 7. Default billing_month to current month
        if not billing_month:
            today = date.today()
            billing_month = today.replace(day=1).isoformat()

        # 8. Run MRP extraction
        try:
            from services.mrp.extraction_service import MRPExtractionService

            extractor = MRPExtractionService()

            file_hash = hashlib.sha256(file_bytes).hexdigest()
            operating_year = MRPExtractionService._compute_operating_year(
                project_id, date.fromisoformat(billing_month)
            )

            result = extractor.extract_and_store(
                file_bytes=file_bytes,
                filename=att.get("filename") or "attachment",
                project_id=project_id,
                org_id=org_id,
                billing_month=billing_month,
                operating_year=operating_year,
                s3_path=att["s3_path"],
                file_hash=file_hash,
                inbound_attachment_id=attachment_id,
            )

            # 9. Success — update attachment
            self.repo.update_attachment_status(
                attachment_id,
                "extracted",
                extraction_result=result,
                reference_price_id=result.get("observation_id"),
            )

            logger.info(
                f"Attachment {attachment_id} extracted: "
                f"observation_id={result.get('observation_id')}, "
                f"mrp={result.get('mrp_per_kwh')}"
            )

            return {
                "success": True,
                "status": "extracted",
                "observation_id": result.get("observation_id"),
                "mrp_per_kwh": result.get("mrp_per_kwh"),
                "confidence": result.get("extraction_confidence"),
                "billing_month": result.get("billing_month_stored"),
            }

        except Exception as e:
            reason = f"MRP extraction failed: {e}"
            logger.error(reason, exc_info=True)
            self.repo.update_attachment_status(attachment_id, "failed", failed_reason=reason)
            return {"success": False, "status": "failed", "failed_reason": reason}

    @staticmethod
    def _download_from_s3(s3_path: str) -> bytes:
        """Download file bytes from an s3://bucket/key path."""
        import boto3

        if s3_path.startswith("s3://"):
            parts = s3_path[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
        else:
            bucket = os.getenv("EMAIL_INGEST_S3_BUCKET", "frontiermind-email")
            key = s3_path

        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
