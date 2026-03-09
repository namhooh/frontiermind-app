"""
Email Ingest Service.

Processes inbound emails arriving via SES → S3 → SNS:
1. Verify SNS signature
2. Handle subscription confirmations
3. Download raw MIME from S3
4. Parse headers, body, attachments
5. Route to organization via org_email_address
6. Thread detection (In-Reply-To / References)
7. Classify sender
8. Store inbound_message + inbound_attachment rows
"""

import email
import email.policy
import hashlib
import json
import logging
import os
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import httpx

from db.ingest_repository import IngestRepository
from services.ingest.noise_filter import is_noise
from services.ingest.sender_allowlist import classify_sender
from services.ingest.sns_verifier import SNSVerifier, SNSVerificationError

logger = logging.getLogger(__name__)


class EmailIngestService:
    """Processes SNS notifications for inbound emails."""

    def __init__(self, repo: IngestRepository):
        self.repo = repo
        self.sns_verifier = SNSVerifier()

    # =========================================================================
    # SNS ENTRY POINT
    # =========================================================================

    def process_sns_notification(self, sns_body: dict) -> Dict[str, Any]:
        """
        Process an SNS notification. Called from the webhook endpoint.

        Returns dict with processing result.
        """
        # Verify signature
        self.sns_verifier.verify(sns_body)

        msg_type = sns_body.get("Type")

        if msg_type == "SubscriptionConfirmation":
            return self._handle_subscription_confirmation(sns_body)

        if msg_type == "Notification":
            return self._handle_notification(sns_body)

        raise ValueError(f"Unknown SNS message type: {msg_type}")

    def _handle_subscription_confirmation(self, sns_body: dict) -> Dict[str, Any]:
        """Auto-confirm SNS subscription by visiting SubscribeURL."""
        subscribe_url = sns_body.get("SubscribeURL")
        if not subscribe_url:
            raise ValueError("SubscriptionConfirmation missing SubscribeURL")

        logger.info(f"Confirming SNS subscription: {subscribe_url}")
        resp = httpx.get(subscribe_url, timeout=10.0)
        resp.raise_for_status()

        return {"action": "subscription_confirmed"}

    def _handle_notification(self, sns_body: dict) -> Dict[str, Any]:
        """Parse the SNS notification and process the email.

        Supports two notification sources:
        - S3 event notification (triggered when SES stores the raw email in S3)
        - Legacy SES SNS action (direct SES → SNS with email content inline)
        """
        message_json = sns_body.get("Message", "{}")
        try:
            notification = json.loads(message_json)
        except json.JSONDecodeError:
            raise ValueError("SNS Message is not valid JSON")

        # Detect S3 event notification format
        records = notification.get("Records", [])
        if records and records[0].get("eventSource") == "aws:s3":
            return self._handle_s3_event(records[0])

        # Legacy: SES notification format
        return self._handle_ses_notification(notification)

    def _handle_s3_event(self, record: dict) -> Dict[str, Any]:
        """Handle S3 event notification — SES stored raw email in S3."""
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        s3_key = s3_info.get("object", {}).get("key", "")

        if not bucket or not s3_key:
            raise ValueError("S3 event missing bucket or key")

        # URL-decode the key (S3 events URL-encode keys with special chars)
        from urllib.parse import unquote_plus
        s3_key = unquote_plus(s3_key)

        # Skip non-email objects (e.g. attachments stored under ingest/)
        if s3_key.startswith("ingest/") or s3_key == "AMAZON_SES_SETUP_NOTIFICATION":
            logger.debug(f"Skipping non-email S3 object: {s3_key}")
            return {"action": "skipped", "reason": "not a raw email"}

        s3_raw_path = f"s3://{bucket}/{s3_key}"
        return self.process_inbound_email(s3_raw_path, bucket, s3_key)

    def _handle_ses_notification(self, ses_notification: dict) -> Dict[str, Any]:
        """Handle legacy SES SNS action notification."""
        mail_info = ses_notification.get("mail", {})
        receipt = ses_notification.get("receipt", {})

        # Extract S3 action — find the S3 action in receipt actions
        s3_action = None
        for action in receipt.get("action", {}) if isinstance(receipt.get("action"), list) else [receipt.get("action", {})]:
            if isinstance(action, dict) and action.get("type") == "S3":
                s3_action = action
                break

        # If no explicit S3 action, construct path from notification content
        if not s3_action:
            bucket = os.getenv("EMAIL_INGEST_S3_BUCKET", "frontiermind-email-ingest")
            message_id = mail_info.get("messageId", "")
            if not message_id:
                raise ValueError("No messageId in SES notification")
            s3_key = message_id
        else:
            bucket = s3_action.get("bucketName", os.getenv("EMAIL_INGEST_S3_BUCKET", "frontiermind-email-ingest"))
            s3_key = s3_action.get("objectKey", "")

        if not s3_key:
            raise ValueError("Cannot determine S3 key from SES notification")

        s3_raw_path = f"s3://{bucket}/{s3_key}"
        return self.process_inbound_email(s3_raw_path, bucket, s3_key)

    # =========================================================================
    # EMAIL PROCESSING
    # =========================================================================

    def process_inbound_email(
        self, s3_raw_path: str, bucket: str, s3_key: str
    ) -> Dict[str, Any]:
        """
        Process a single inbound email from S3.

        Inline processing — returns result, SNS retries on failure.
        """
        # 1. Idempotency check
        if self.repo.exists_by_s3_raw_path(s3_raw_path):
            logger.info(f"Skipping duplicate: {s3_raw_path}")
            return {"action": "skipped", "reason": "duplicate"}

        # 2. Download raw MIME from S3
        raw_bytes = self._download_from_s3(bucket, s3_key)

        # 3. Parse MIME
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

        # 4. Extract headers
        headers = {k.lower(): v for k, v in msg.items()}
        sender_email, sender_name = self._parse_from(msg)
        subject = msg.get("Subject", "")
        body_text = self._extract_body_text(msg)
        ses_message_id = headers.get("message-id", "").strip("<>")
        in_reply_to = headers.get("in-reply-to", "").strip("<>") or None
        references_chain = self._parse_references(headers.get("references", ""))

        # 5. Default org fallback for noise/unroutable emails
        default_org_id = int(os.getenv("DEFAULT_ORGANIZATION_ID", "1"))

        # 6. Noise check
        noise, noise_reason = is_noise(headers)
        if noise:
            logger.info(f"Noise detected: {noise_reason} — {sender_email}")
            msg_id = self.repo.create_inbound_message({
                "organization_id": default_org_id,
                "channel": "email",
                "subject": subject,
                "raw_headers": headers,
                "ses_message_id": ses_message_id,
                "s3_raw_path": s3_raw_path,
                "sender_email": sender_email,
                "sender_name": sender_name,
                "inbound_message_status": "noise",
                "classification_reason": noise_reason,
            })
            return {"action": "noise", "message_id": msg_id, "reason": noise_reason}

        # 7. Route to organization
        recipients = self._extract_recipients(msg)
        org_info = self._route_to_org(recipients)

        if not org_info:
            logger.warning(f"Unroutable email from {sender_email} to {recipients}")
            msg_id = self.repo.create_inbound_message({
                "organization_id": default_org_id,
                "channel": "email",
                "subject": subject,
                "raw_headers": headers,
                "ses_message_id": ses_message_id,
                "s3_raw_path": s3_raw_path,
                "sender_email": sender_email,
                "sender_name": sender_name,
                "inbound_message_status": "noise",
                "classification_reason": "unroutable recipient",
            })
            return {"action": "noise", "message_id": msg_id, "reason": "unroutable recipient"}

        org_id = org_info["organization_id"]

        # 7. Thread detection
        thread_context = self._resolve_thread(in_reply_to, references_chain)

        # 8. Classify sender
        sender_status, sender_reason, contact_id = classify_sender(
            sender_email, org_id, self.repo
        )

        # If we have thread context, inherit linking info
        invoice_header_id = thread_context.get("invoice_header_id")
        counterparty_id = thread_context.get("counterparty_id")
        project_id = thread_context.get("project_id")
        outbound_message_id = thread_context.get("outbound_message_id")

        # If sender is a known contact, inherit counterparty
        if contact_id and not counterparty_id:
            contact = self.repo.find_contact_by_email(sender_email, org_id)
            if contact:
                counterparty_id = contact.get("counterparty_id")

        # 9. Extract attachments
        attachment_parts = self._extract_attachments(msg)

        # 10. Create inbound_message
        msg_id = self.repo.create_inbound_message({
            "organization_id": org_id,
            "channel": "email",
            "subject": subject,
            "body_text": body_text,
            "raw_headers": headers,
            "ses_message_id": ses_message_id,
            "in_reply_to": in_reply_to,
            "references_chain": references_chain,
            "s3_raw_path": s3_raw_path,
            "sender_email": sender_email,
            "sender_name": sender_name,
            "invoice_header_id": invoice_header_id,
            "project_id": project_id,
            "counterparty_id": counterparty_id,
            "outbound_message_id": outbound_message_id,
            "customer_contact_id": contact_id,
            "attachment_count": len(attachment_parts),
            "inbound_message_status": sender_status,
            "classification_reason": sender_reason,
        })

        # 11. Upload attachments to S3 and create inbound_attachment rows
        attachment_ids = []
        for part in attachment_parts:
            att_id = self._store_attachment(msg_id, org_id, part)
            attachment_ids.append(att_id)

        logger.info(
            f"Inbound email processed: message_id={msg_id}, from={sender_email}, "
            f"org={org_id}, status={sender_status}, attachments={len(attachment_ids)}"
        )

        # 12. Auto-trigger extraction only when project is resolved
        if contact_id and attachment_ids and project_id:
            self._auto_extract_attachments(
                attachment_ids, org_id, msg_id, counterparty_id, project_id
            )
        elif contact_id and attachment_ids:
            logger.info(
                f"Skipping auto-extraction for message {msg_id}: "
                f"project_id not resolved, awaiting manual assignment"
            )

        return {
            "action": "processed",
            "message_id": msg_id,
            "inbound_message_status": sender_status,
            "attachment_count": len(attachment_ids),
        }

    # =========================================================================
    # AUTO-EXTRACTION
    # =========================================================================

    def _auto_extract_attachments(
        self,
        attachment_ids: list,
        org_id: int,
        message_id: int,
        counterparty_id: Optional[int],
        project_id: Optional[int],
    ) -> None:
        """
        Auto-trigger MRP extraction for attachments from known contacts.

        Failures here never fail the email ingestion — they are logged and
        the attachment stays in 'failed' status for manual retry.
        """
        from services.ingest.attachment_processing_service import AttachmentProcessingService

        service = AttachmentProcessingService(self.repo)
        any_success = False

        for att_id in attachment_ids:
            try:
                result = service.process_attachment(
                    attachment_id=att_id,
                    org_id=org_id,
                    project_id=project_id,
                )
                if result.get("success"):
                    any_success = True
                    logger.info(
                        f"Auto-extraction succeeded: attachment={att_id}, "
                        f"observation_id={result.get('observation_id')}"
                    )
                else:
                    logger.warning(
                        f"Auto-extraction skipped/failed: attachment={att_id}, "
                        f"reason={result.get('failed_reason')}"
                    )
            except Exception as e:
                logger.warning(
                    f"Auto-extraction error for attachment {att_id}: {e}",
                    exc_info=True,
                )

        if any_success:
            self.repo.update_inbound_message_status(
                message_id=message_id,
                org_id=org_id,
                inbound_message_status="auto_processed",
                reason="attachments auto-extracted",
            )

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _parse_from(msg: EmailMessage) -> tuple:
        """Extract email address and display name from From header."""
        from_header = msg.get("From", "")
        # email.utils handles "Name <addr>" and bare addr
        from email.utils import parseaddr
        name, addr = parseaddr(from_header)
        return addr.lower() if addr else "", name or None

    @staticmethod
    def _extract_body_text(msg: EmailMessage) -> Optional[str]:
        """Extract plain text body from MIME message."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        else:
            if msg.get_content_type() == "text/plain":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return None

    @staticmethod
    def _parse_references(references_str: str) -> List[str]:
        """Parse References header into list of message IDs (newest last)."""
        if not references_str:
            return []
        # References header contains space-separated message IDs in angle brackets
        import re
        return [mid.strip("<>") for mid in re.findall(r"<[^>]+>", references_str)]

    @staticmethod
    def _extract_recipients(msg: EmailMessage) -> List[str]:
        """Get all recipient addresses from To, Cc, and Delivered-To."""
        from email.utils import getaddresses
        addrs = []
        for header in ("To", "Cc", "Delivered-To", "X-Original-To"):
            val = msg.get_all(header, [])
            addrs.extend(getaddresses(val))
        return [addr.lower() for _, addr in addrs if addr]

    def _route_to_org(self, recipients: List[str]) -> Optional[Dict[str, Any]]:
        """Find organization by matching recipient to org_email_address."""
        for addr in recipients:
            if "@" not in addr:
                continue
            prefix, domain = addr.split("@", 1)
            org_info = self.repo.get_org_by_email_address(prefix, domain)
            if org_info:
                return org_info
        return None

    def _resolve_thread(
        self, in_reply_to: Optional[str], references_chain: List[str]
    ) -> Dict[str, Any]:
        """
        Resolve conversation thread by matching In-Reply-To or References
        to outbound_message.ses_message_id.
        """
        context: Dict[str, Any] = {}

        # Try In-Reply-To first
        if in_reply_to:
            outbound = self.repo.find_outbound_by_message_id(in_reply_to)
            if outbound:
                return self._context_from_outbound(outbound)

        # Walk References chain newest-first
        for ref_id in reversed(references_chain):
            outbound = self.repo.find_outbound_by_message_id(ref_id)
            if outbound:
                return self._context_from_outbound(outbound)

        return context

    @staticmethod
    def _context_from_outbound(outbound: Dict[str, Any]) -> Dict[str, Any]:
        """Build thread context from an outbound_message record."""
        return {
            "outbound_message_id": outbound["id"],
            "invoice_header_id": outbound.get("invoice_header_id"),
            "counterparty_id": None,  # outbound_message doesn't have counterparty_id directly
            "project_id": None,       # outbound_message doesn't have project_id directly
        }

    @staticmethod
    def _extract_attachments(msg: EmailMessage) -> List[Dict[str, Any]]:
        """Walk MIME parts and extract attachment metadata + bytes."""
        attachments = []
        if not msg.is_multipart():
            return attachments

        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" not in content_disposition and "inline" not in content_disposition:
                continue

            # Skip text parts that are the body
            if part.get_content_type() in ("text/plain", "text/html"):
                if "attachment" not in content_disposition:
                    continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            filename = part.get_filename() or "unnamed"
            content_type = part.get_content_type()

            attachments.append({
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(payload),
                "bytes": payload,
            })

        return attachments

    def _store_attachment(
        self, message_id: int, org_id: int, part: Dict[str, Any]
    ) -> int:
        """Upload attachment to S3 and create inbound_attachment record."""
        file_bytes = part["bytes"]
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        filename = part["filename"]

        # Determine extension
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[1].lower()

        from datetime import datetime
        now = datetime.utcnow()
        s3_key = (
            f"ingest/{org_id}/attachments/{now.year}/{now.month:02d}/"
            f"{file_hash[:16]}{ext}"
        )

        # Upload to S3
        bucket = os.getenv("EMAIL_INGEST_S3_BUCKET", "frontiermind-email-ingest")
        self._upload_to_s3(file_bytes, bucket, s3_key, part.get("content_type"))

        att_id = self.repo.create_inbound_attachment({
            "inbound_message_id": message_id,
            "filename": filename,
            "content_type": part.get("content_type"),
            "size_bytes": part["size_bytes"],
            "s3_path": f"s3://{bucket}/{s3_key}",
            "file_hash": file_hash,
        })

        return att_id

    @staticmethod
    def _download_from_s3(bucket: str, key: str) -> bytes:
        """Download raw email from S3."""
        import boto3
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    @staticmethod
    def _upload_to_s3(
        file_bytes: bytes, bucket: str, key: str, content_type: Optional[str] = None
    ) -> None:
        """Upload bytes to S3."""
        import boto3
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        s3.put_object(Bucket=bucket, Key=key, Body=file_bytes, **extra)
