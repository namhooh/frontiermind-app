"""
Report email delivery service.

Sends completed reports to recipients via SES, with a presigned
S3 download link included in the email body.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Presigned URL expiry for report download links in emails (24 hours)
EMAIL_DOWNLOAD_LINK_EXPIRY = 86400


class ReportDeliveryService:
    """
    Delivers generated reports via email.

    Reuses:
    - services/email/ses_client.SESClient for sending
    - services/email/template_renderer.EmailTemplateRenderer for rendering
    - services/reports/storage.get_storage() for presigned download URLs
    """

    def __init__(self, ses_client=None, renderer=None, storage=None):
        # Lazy imports to avoid circular dependencies
        from services.email.ses_client import SESClient
        from services.email.template_renderer import EmailTemplateRenderer
        from services.reports.storage import get_storage

        self._ses = ses_client or SESClient()
        self._renderer = renderer or EmailTemplateRenderer()
        self._storage = storage or get_storage()

    def deliver_report_email(
        self,
        report_record: Dict[str, Any],
        recipients: List[str],
        schedule_name: str,
    ) -> int:
        """
        Send a report-ready email to recipients.

        Args:
            report_record: The generated_report database record (must be completed)
            recipients: List of email addresses
            schedule_name: Human-readable schedule name for the email

        Returns:
            Number of emails sent
        """
        file_path = report_record.get("file_path")
        if not file_path:
            logger.warning(
                f"Report {report_record['id']}: no file_path, cannot deliver"
            )
            return 0

        # Generate presigned download URL (24-hour expiry for email links)
        download_url = self._storage.get_presigned_url(
            file_path,
            expiry=EMAIL_DOWNLOAD_LINK_EXPIRY,
        )

        # Build template context
        file_format = report_record.get("file_format", "pdf").upper()
        context = {
            "report_name": report_record.get("name", "Report"),
            "schedule_name": schedule_name,
            "file_format": file_format,
            "record_count": report_record.get("record_count", 0),
            "file_size_display": _format_file_size(
                report_record.get("file_size_bytes")
            ),
            "download_url": download_url,
            "expiry_hours": EMAIL_DOWNLOAD_LINK_EXPIRY // 3600,
        }

        # Render email from file template
        html_body = self._renderer.render_file_template(
            "report_ready.html", context
        )
        subject = f"Report Ready: {report_record.get('name', 'Report')}"

        # Lazy import to avoid circular dependency
        from db.notification_repository import NotificationRepository
        notification_repo = NotificationRepository()

        # Send to each recipient
        emails_sent = 0
        for email_addr in recipients:
            try:
                result = self._ses.send_email(
                    to=[email_addr],
                    subject=subject,
                    html_body=html_body,
                )
                ses_message_id = result.get("MessageId") if isinstance(result, dict) else None
                emails_sent += 1
                logger.info(
                    f"Report {report_record['id']}: "
                    f"delivery email sent to {email_addr}"
                )

                # Log to email_log for audit trail
                try:
                    notification_repo.create_email_log({
                        "organization_id": report_record.get("organization_id"),
                        "recipient_email": email_addr,
                        "subject": subject,
                        "email_status": "delivered",
                        "ses_message_id": ses_message_id,
                        "sent_at": datetime.now(timezone.utc),
                    })
                except Exception as log_err:
                    logger.warning(
                        f"Report {report_record['id']}: "
                        f"email_log creation failed for {email_addr}: {log_err}"
                    )

            except Exception as e:
                logger.error(
                    f"Report {report_record['id']}: "
                    f"failed to send to {email_addr}: {e}"
                )

                # Log failure to email_log
                try:
                    notification_repo.create_email_log({
                        "organization_id": report_record.get("organization_id"),
                        "recipient_email": email_addr,
                        "subject": subject,
                        "email_status": "failed",
                    })
                except Exception as log_err:
                    logger.warning(
                        f"Report {report_record['id']}: "
                        f"email_log failure creation failed for {email_addr}: {log_err}"
                    )

        return emails_sent


def _format_file_size(size_bytes: Any) -> str:
    """Format file size in human-readable form."""
    if not size_bytes:
        return "Unknown"
    size = int(size_bytes)
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"
