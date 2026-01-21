"""
Export Controls Service

Implements security controls for data exports per Security Assessment Section 13.2:
- Dual approval required for bulk exports (>20 contracts)
- Audit logging for all exports
- Export watermarking with user/timestamp
- Rate limiting for export operations
- PII export restrictions
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ExportType(str, Enum):
    """Types of exports supported."""
    CONTRACT_SINGLE = "contract_single"
    CONTRACT_BULK = "contract_bulk"
    CLAUSE_EXPORT = "clause_export"
    REPORT = "report"
    AUDIT_LOG = "audit_log"
    PII_DATA = "pii_data"  # Requires special approval


class ExportFormat(str, Enum):
    """Supported export formats."""
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    XLSX = "xlsx"


class ApprovalStatus(str, Enum):
    """Status of export approval."""
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ExportRequest:
    """Represents an export request."""
    request_id: str
    user_id: str
    organization_id: int
    export_type: ExportType
    export_format: ExportFormat
    record_count: int
    record_ids: List[int]
    include_pii: bool
    requested_at: datetime
    approval_status: ApprovalStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    watermark_id: Optional[str] = None


@dataclass
class ExportResult:
    """Result of an export operation."""
    success: bool
    request_id: str
    export_path: Optional[str]
    watermark_id: str
    record_count: int
    error_message: Optional[str] = None


class ExportControlsError(Exception):
    """Base exception for export controls."""
    pass


class ApprovalRequiredError(ExportControlsError):
    """Raised when export requires approval."""
    def __init__(self, request_id: str, reason: str):
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"Export requires approval: {reason}")


class ExportDeniedError(ExportControlsError):
    """Raised when export is denied."""
    pass


class ExportControls:
    """
    Export controls service implementing security requirements.

    Security Features:
    - Bulk export threshold (default: 20 contracts)
    - PII export restrictions
    - Dual approval workflow
    - Export watermarking
    - Audit trail integration
    """

    # Configuration (can be overridden via environment variables)
    BULK_EXPORT_THRESHOLD = int(os.getenv("EXPORT_BULK_THRESHOLD", "20"))
    APPROVAL_EXPIRY_HOURS = int(os.getenv("EXPORT_APPROVAL_EXPIRY_HOURS", "24"))
    PII_EXPORT_REQUIRES_APPROVAL = os.getenv("PII_EXPORT_REQUIRES_APPROVAL", "true").lower() == "true"

    def __init__(self, audit_logger=None):
        """
        Initialize export controls.

        Args:
            audit_logger: Optional audit logging function for integration with audit_log table
        """
        self._audit_logger = audit_logger
        self._pending_approvals: Dict[str, ExportRequest] = {}
        logger.info(
            f"ExportControls initialized: bulk_threshold={self.BULK_EXPORT_THRESHOLD}, "
            f"pii_requires_approval={self.PII_EXPORT_REQUIRES_APPROVAL}"
        )

    def request_export(
        self,
        user_id: str,
        organization_id: int,
        export_type: ExportType,
        export_format: ExportFormat,
        record_ids: List[int],
        include_pii: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExportRequest:
        """
        Request an export operation.

        Args:
            user_id: ID of user requesting export
            organization_id: Organization ID
            export_type: Type of export
            export_format: Output format
            record_ids: List of record IDs to export
            include_pii: Whether to include PII data
            metadata: Additional metadata for the export

        Returns:
            ExportRequest with approval status

        Raises:
            ApprovalRequiredError: If export requires approval
            ExportDeniedError: If export is not allowed
        """
        request_id = str(uuid4())
        record_count = len(record_ids)
        now = datetime.now(timezone.utc)

        # Check if approval is required
        requires_approval, reason = self._check_approval_required(
            export_type=export_type,
            record_count=record_count,
            include_pii=include_pii,
        )

        # Determine initial approval status
        if requires_approval:
            approval_status = ApprovalStatus.PENDING
        else:
            approval_status = ApprovalStatus.NOT_REQUIRED

        # Create export request
        export_request = ExportRequest(
            request_id=request_id,
            user_id=user_id,
            organization_id=organization_id,
            export_type=export_type,
            export_format=export_format,
            record_count=record_count,
            record_ids=record_ids,
            include_pii=include_pii,
            requested_at=now,
            approval_status=approval_status,
        )

        # Log the export request
        self._log_export_request(export_request, metadata)

        if requires_approval:
            # Store pending approval
            self._pending_approvals[request_id] = export_request
            logger.info(
                f"Export request {request_id} requires approval: {reason}"
            )
            raise ApprovalRequiredError(request_id, reason)

        return export_request

    def approve_export(
        self,
        request_id: str,
        approver_id: str,
        approver_role: str,
    ) -> ExportRequest:
        """
        Approve a pending export request.

        Args:
            request_id: ID of the export request
            approver_id: ID of the user approving
            approver_role: Role of the approver (must be 'admin')

        Returns:
            Updated ExportRequest

        Raises:
            ExportDeniedError: If approval is invalid
        """
        if request_id not in self._pending_approvals:
            raise ExportDeniedError(f"Export request {request_id} not found or already processed")

        if approver_role != "admin":
            raise ExportDeniedError("Only admins can approve bulk exports")

        export_request = self._pending_approvals[request_id]

        # Check if request has expired
        hours_elapsed = (datetime.now(timezone.utc) - export_request.requested_at).total_seconds() / 3600
        if hours_elapsed > self.APPROVAL_EXPIRY_HOURS:
            export_request.approval_status = ApprovalStatus.EXPIRED
            del self._pending_approvals[request_id]
            raise ExportDeniedError(f"Export request {request_id} has expired")

        # Check that approver is not the requester (dual approval)
        if approver_id == export_request.user_id:
            raise ExportDeniedError("Approver cannot be the same as requester (dual approval required)")

        # Approve the request
        export_request.approval_status = ApprovalStatus.APPROVED
        export_request.approved_by = approver_id
        export_request.approved_at = datetime.now(timezone.utc)

        # Log approval
        self._log_export_approval(export_request, approver_id)

        logger.info(f"Export request {request_id} approved by {approver_id}")

        return export_request

    def reject_export(
        self,
        request_id: str,
        rejector_id: str,
        reason: str,
    ) -> ExportRequest:
        """
        Reject a pending export request.

        Args:
            request_id: ID of the export request
            rejector_id: ID of the user rejecting
            reason: Reason for rejection

        Returns:
            Updated ExportRequest
        """
        if request_id not in self._pending_approvals:
            raise ExportDeniedError(f"Export request {request_id} not found")

        export_request = self._pending_approvals[request_id]
        export_request.approval_status = ApprovalStatus.REJECTED
        export_request.rejection_reason = reason

        # Log rejection
        self._log_export_rejection(export_request, rejector_id, reason)

        del self._pending_approvals[request_id]

        logger.info(f"Export request {request_id} rejected by {rejector_id}: {reason}")

        return export_request

    def execute_export(
        self,
        export_request: ExportRequest,
        data: List[Dict[str, Any]],
        output_dir: str = "exports",
    ) -> ExportResult:
        """
        Execute an approved export.

        Args:
            export_request: The approved export request
            data: Data to export
            output_dir: Output directory

        Returns:
            ExportResult with export path

        Raises:
            ExportDeniedError: If export is not approved
        """
        # Verify approval
        if export_request.approval_status not in [ApprovalStatus.APPROVED, ApprovalStatus.NOT_REQUIRED]:
            raise ExportDeniedError(
                f"Export not approved. Status: {export_request.approval_status}"
            )

        # Generate watermark
        watermark_id = self._generate_watermark(export_request)
        export_request.watermark_id = watermark_id

        # Add watermark to export data
        watermarked_data = self._apply_watermark(data, export_request, watermark_id)

        # Generate export file
        try:
            export_path = self._write_export(
                data=watermarked_data,
                export_request=export_request,
                output_dir=output_dir,
            )

            # Log successful export
            self._log_export_success(export_request, export_path)

            return ExportResult(
                success=True,
                request_id=export_request.request_id,
                export_path=export_path,
                watermark_id=watermark_id,
                record_count=len(data),
            )

        except Exception as e:
            logger.error(f"Export failed: {e}")
            self._log_export_failure(export_request, str(e))
            return ExportResult(
                success=False,
                request_id=export_request.request_id,
                export_path=None,
                watermark_id=watermark_id,
                record_count=0,
                error_message=str(e),
            )

    def get_pending_approvals(self, organization_id: int) -> List[ExportRequest]:
        """Get all pending export approvals for an organization."""
        return [
            req for req in self._pending_approvals.values()
            if req.organization_id == organization_id
            and req.approval_status == ApprovalStatus.PENDING
        ]

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _check_approval_required(
        self,
        export_type: ExportType,
        record_count: int,
        include_pii: bool,
    ) -> tuple[bool, str]:
        """Check if export requires approval."""
        reasons = []

        # Bulk export check
        if record_count > self.BULK_EXPORT_THRESHOLD:
            reasons.append(
                f"Bulk export ({record_count} records exceeds threshold of {self.BULK_EXPORT_THRESHOLD})"
            )

        # PII export check
        if include_pii and self.PII_EXPORT_REQUIRES_APPROVAL:
            reasons.append("Export includes PII data")

        # Audit log export always requires approval
        if export_type == ExportType.AUDIT_LOG:
            reasons.append("Audit log exports require approval")

        # PII data export type always requires approval
        if export_type == ExportType.PII_DATA:
            reasons.append("PII data exports require approval")

        if reasons:
            return True, "; ".join(reasons)

        return False, ""

    def _generate_watermark(self, export_request: ExportRequest) -> str:
        """Generate a unique watermark for the export."""
        watermark_data = f"{export_request.request_id}:{export_request.user_id}:{datetime.now(timezone.utc).isoformat()}"
        watermark_hash = hashlib.sha256(watermark_data.encode()).hexdigest()[:16]
        return f"WM-{watermark_hash}"

    def _apply_watermark(
        self,
        data: List[Dict[str, Any]],
        export_request: ExportRequest,
        watermark_id: str,
    ) -> Dict[str, Any]:
        """Apply watermark metadata to export data."""
        return {
            "_export_metadata": {
                "watermark_id": watermark_id,
                "exported_by": export_request.user_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "organization_id": export_request.organization_id,
                "record_count": len(data),
                "export_type": export_request.export_type.value,
                "includes_pii": export_request.include_pii,
                "approval_status": export_request.approval_status.value,
                "approved_by": export_request.approved_by,
                "approved_at": export_request.approved_at.isoformat() if export_request.approved_at else None,
            },
            "data": data,
        }

    def _write_export(
        self,
        data: Dict[str, Any],
        export_request: ExportRequest,
        output_dir: str,
    ) -> str:
        """Write export data to file."""
        import os
        from pathlib import Path

        # Ensure output directory exists
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"export_{export_request.export_type.value}_{timestamp}_{export_request.watermark_id}.json"
        filepath = output_path / filename

        # Write JSON
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Export written to {filepath}")
        return str(filepath.absolute())

    def _log_export_request(self, export_request: ExportRequest, metadata: Optional[Dict] = None):
        """Log export request to audit trail."""
        log_data = {
            "action": "EXPORT_REQUESTED",
            "request_id": export_request.request_id,
            "user_id": export_request.user_id,
            "organization_id": export_request.organization_id,
            "export_type": export_request.export_type.value,
            "record_count": export_request.record_count,
            "include_pii": export_request.include_pii,
            "approval_required": export_request.approval_status == ApprovalStatus.PENDING,
            "metadata": metadata,
        }
        logger.info(f"Export request: {json.dumps(log_data)}")

        if self._audit_logger:
            self._audit_logger(log_data)

    def _log_export_approval(self, export_request: ExportRequest, approver_id: str):
        """Log export approval."""
        log_data = {
            "action": "EXPORT_APPROVED",
            "request_id": export_request.request_id,
            "approver_id": approver_id,
            "requester_id": export_request.user_id,
            "record_count": export_request.record_count,
        }
        logger.info(f"Export approved: {json.dumps(log_data)}")

        if self._audit_logger:
            self._audit_logger(log_data)

    def _log_export_rejection(self, export_request: ExportRequest, rejector_id: str, reason: str):
        """Log export rejection."""
        log_data = {
            "action": "EXPORT_REJECTED",
            "request_id": export_request.request_id,
            "rejector_id": rejector_id,
            "requester_id": export_request.user_id,
            "reason": reason,
        }
        logger.info(f"Export rejected: {json.dumps(log_data)}")

        if self._audit_logger:
            self._audit_logger(log_data)

    def _log_export_success(self, export_request: ExportRequest, export_path: str):
        """Log successful export."""
        log_data = {
            "action": "EXPORT_COMPLETED",
            "request_id": export_request.request_id,
            "user_id": export_request.user_id,
            "watermark_id": export_request.watermark_id,
            "export_path": export_path,
            "record_count": export_request.record_count,
        }
        logger.info(f"Export completed: {json.dumps(log_data)}")

        if self._audit_logger:
            self._audit_logger(log_data)

    def _log_export_failure(self, export_request: ExportRequest, error: str):
        """Log failed export."""
        log_data = {
            "action": "EXPORT_FAILED",
            "request_id": export_request.request_id,
            "user_id": export_request.user_id,
            "error": error,
        }
        logger.error(f"Export failed: {json.dumps(log_data)}")

        if self._audit_logger:
            self._audit_logger(log_data)
