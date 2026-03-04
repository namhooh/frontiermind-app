"""
Submission token generation and validation.

Generates secure URL-safe tokens for counterparty data collection.
Stores SHA-256 hash in database (raw token never persisted).
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class TokenService:
    """Manages submission tokens for external data collection."""

    DEFAULT_EXPIRY_HOURS = 168  # 7 days

    def __init__(self, notification_repo):
        self.repo = notification_repo

    def generate_token(
        self,
        org_id: int,
        invoice_header_id: Optional[int] = None,
        counterparty_id: Optional[int] = None,
        fields: Optional[List[str]] = None,
        expiry_hours: int = DEFAULT_EXPIRY_HOURS,
        max_uses: int = 1,
        outbound_message_id: Optional[int] = None,
        project_id: Optional[int] = None,
        submission_type: str = "form_response",
        submission_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a new submission token.

        Args:
            project_id: Project context for MRP and other project-scoped submissions.
            submission_type: 'form_response' (default) or 'mrp_upload'.
            submission_url: Full URL to embed in submission_fields for later retrieval.

        Returns:
            Dict with 'token' (raw URL-safe string) and 'token_id' (DB id)
        """
        # Generate 64-byte URL-safe token
        raw_token = secrets.token_urlsafe(64)

        # Store SHA-256 hash
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        # Wrap fields in an object so we can attach submission_url
        fields_data: Dict[str, Any] = {"fields": fields or []}
        if submission_url:
            fields_data["submission_url"] = submission_url

        token_id = self.repo.create_submission_token({
            "organization_id": org_id,
            "token_hash": token_hash,
            "submission_fields": fields_data,
            "max_uses": max_uses,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
            "invoice_header_id": invoice_header_id,
            "counterparty_id": counterparty_id,
            "outbound_message_id": outbound_message_id,
            "project_id": project_id,
            "submission_type": submission_type,
        })

        logger.info(
            f"Created submission token: id={token_id}, org={org_id}, "
            f"invoice={invoice_header_id}, expires_in={expiry_hours}h"
        )

        return {
            "token": raw_token,
            "token_id": token_id,
        }

    def store_submission_url(self, token_id: int, submission_url: str) -> None:
        """Persist the submission URL into the token's submission_fields JSONB."""
        self.repo.update_submission_token_url(token_id, submission_url)

    def validate_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a raw token string.

        Returns:
            Token record dict if valid, None if invalid/expired/used
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        record = self.repo.get_submission_token_by_hash(token_hash)

        if not record:
            logger.warning("Token validation failed: not found")
            return None

        if record["submission_token_status"] != "active":
            logger.warning(f"Token validation failed: submission_token_status={record['submission_token_status']}")
            return None

        if record["expires_at"] < datetime.now(timezone.utc):
            logger.warning("Token validation failed: expired")
            return None

        if record["use_count"] >= record["max_uses"]:
            logger.warning("Token validation failed: max uses reached")
            return None

        return record

    def use_token(
        self,
        token_record: Dict[str, Any],
        response_data: Dict[str, Any],
        submitted_by_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> int:
        """
        Record a submission against a token.

        Args:
            token_record: Token dict from validate_token()
            response_data: Submitted form data
            submitted_by_email: Email of submitter
            ip_address: IP of submitter
            channel: Override channel ('token_form' or 'token_upload').
                     Defaults based on submission_type.

        Returns:
            inbound_message ID
        """
        # Increment usage (atomic: WHERE status='active' ensures only one wins)
        success = self.repo.use_submission_token(token_record["id"])
        if not success:
            raise ValueError("Token already used or expired")

        # Determine channel
        if channel is None:
            submission_type = token_record.get("submission_type", "form_response")
            channel = "token_upload" if submission_type == "mrp_upload" else "token_form"

        # Store as inbound_message
        inbound_message_id = self.repo.create_inbound_message({
            "organization_id": token_record["organization_id"],
            "submission_token_id": token_record["id"],
            "response_data": response_data,
            "submitted_by_email": submitted_by_email,
            "ip_address": ip_address,
            "invoice_header_id": token_record.get("invoice_header_id"),
            "channel": channel,
            "project_id": token_record.get("project_id"),
            "counterparty_id": token_record.get("counterparty_id"),
        })

        logger.info(
            f"Submission recorded: inbound_message_id={inbound_message_id}, "
            f"token_id={token_record['id']}, channel={channel}"
        )

        return inbound_message_id
