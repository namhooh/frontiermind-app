"""
Core notification orchestrator.

Coordinates email sending: resolves recipients, renders templates,
generates submission tokens, sends via SES, and logs everything.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from .ses_client import SESClient, SESError
from .template_renderer import EmailTemplateRenderer
from .token_service import TokenService

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Orchestrates email notifications.

    Pipeline: resolve recipients -> render template -> generate token (if needed)
              -> send via SES -> log in outbound_message -> audit log
    """

    def __init__(self, notification_repo, ses_client: Optional[SESClient] = None, frontend_url: Optional[str] = None):
        self.repo = notification_repo
        self.ses = ses_client or SESClient()
        self.renderer = EmailTemplateRenderer()
        self.token_service = TokenService(notification_repo)
        self.app_base_url = frontend_url or os.getenv("APP_BASE_URL", "https://frontiermind-app.vercel.app")

    # =========================================================================
    # IMMEDIATE SEND
    # =========================================================================

    def send_immediate(
        self,
        org_id: int,
        template_id: int,
        recipient_emails: List[str],
        invoice_header_id: Optional[int] = None,
        include_submission_link: bool = False,
        submission_fields: Optional[List[str]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
        subject_override: Optional[str] = None,
        body_html_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send email immediately (user-initiated).

        Returns:
            Dict with emails_sent count, outbound_message_ids, and optional submission_token_id
        """
        # Load template
        template = self.repo.get_template(template_id, org_id)
        if not template:
            raise ValueError(f"Email template {template_id} not found")

        # Build context from invoice if provided
        context = self._build_invoice_context(org_id, invoice_header_id)
        if extra_context:
            context.update(extra_context)

        # Generate submission token if requested
        submission_token_id = None
        if include_submission_link and invoice_header_id:
            token_raw = self.token_service.generate_token(
                org_id=org_id,
                invoice_header_id=invoice_header_id,
                fields=submission_fields or [],
            )
            submission_token_id = token_raw["token_id"]
            full_url = f"{self.app_base_url}/submit/{token_raw['token']}"
            context["submission_url"] = full_url
            self.token_service.store_submission_url(token_raw["token_id"], full_url)

        # Render email (use overrides if provided, otherwise template values)
        rendered = self.renderer.render_email(
            subject_template=subject_override or template["subject_template"],
            body_html_template=body_html_override or template["body_html"],
            body_text_template=template.get("body_text"),
            context=context,
        )

        # Send to each recipient
        outbound_message_ids = []
        emails_sent = 0

        for email_addr in recipient_emails:
            log_id, success = self._send_single_email(
                org_id=org_id,
                template_id=template_id,
                recipient_email=email_addr,
                subject=rendered["subject"],
                html_body=rendered["html"],
                text_body=rendered.get("text"),
                invoice_header_id=invoice_header_id,
                submission_token_id=submission_token_id,
            )
            outbound_message_ids.append(log_id)
            if success:
                emails_sent += 1

        return {
            "emails_sent": emails_sent,
            "outbound_message_ids": outbound_message_ids,
            "submission_token_id": submission_token_id,
        }

    # =========================================================================
    # SCHEDULED PROCESSING
    # =========================================================================

    def process_due_schedules(self) -> int:
        """
        Process all due notification schedules.

        Called by APScheduler every 5 minutes.
        Returns number of emails sent.
        """
        due_schedules = self.repo.get_due_schedules()
        total_sent = 0

        for schedule in due_schedules:
            try:
                sent = self._process_single_schedule(schedule)
                total_sent += sent
                self.repo.update_schedule_after_run(
                    schedule["id"], "completed"
                )
            except Exception as e:
                logger.error(
                    f"Schedule {schedule['id']} failed: {e}", exc_info=True
                )
                self.repo.update_schedule_after_run(
                    schedule["id"], "failed", str(e)
                )

        if total_sent > 0:
            logger.info(f"Scheduled run complete: {total_sent} emails sent")

        return total_sent

    INVOICE_SCHEDULE_TYPES = {"invoice_reminder", "invoice_initial"}
    DIRECT_SEND_TYPES = {"custom", "compliance_alert"}

    def _process_single_schedule(self, schedule: Dict[str, Any]) -> int:
        """Process a single notification schedule — dispatches to invoice or direct-send path."""
        schedule_type = schedule.get("email_schedule_type")

        if schedule_type in self.DIRECT_SEND_TYPES:
            return self._process_direct_schedule(schedule)
        elif schedule_type in self.INVOICE_SCHEDULE_TYPES:
            return self._process_invoice_schedule(schedule)
        else:
            logger.debug(
                f"Schedule {schedule['id']}: email_schedule_type '{schedule_type}' not supported"
            )
            return 0

    def _process_direct_schedule(self, schedule: Dict[str, Any]) -> int:
        """Process a direct-send schedule — sends to stored recipient_emails, no invoice matching."""
        org_id = schedule["organization_id"]
        conditions = schedule.get("conditions") or {}
        recipient_emails = conditions.get("recipient_emails", [])

        if not recipient_emails:
            logger.debug(f"Schedule {schedule['id']}: no recipient_emails in conditions")
            return 0

        # Build context
        context = {
            "schedule_name": schedule.get("name", ""),
            "schedule_type": schedule.get("email_schedule_type", ""),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "sender_name": "FrontierMind",
        }

        # Render email
        rendered = self.renderer.render_email(
            subject_template=schedule["subject_template"],
            body_html_template=schedule["body_html"],
            body_text_template=schedule.get("body_text"),
            context=context,
        )

        emails_sent = 0
        for email_addr in recipient_emails:
            _, success = self._send_single_email(
                org_id=org_id,
                template_id=schedule["email_template_id"],
                schedule_id=schedule["id"],
                recipient_email=email_addr,
                subject=rendered["subject"],
                html_body=rendered["html"],
                text_body=rendered.get("text"),
            )
            if success:
                emails_sent += 1

        return emails_sent

    def _process_invoice_schedule(self, schedule: Dict[str, Any]) -> int:
        """Process an invoice-based schedule — matches invoices and resolves contacts."""
        org_id = schedule["organization_id"]
        conditions = schedule.get("conditions") or {}

        # Auto-exclude paid invoices when due_date_relative is configured
        if "due_date_relative" in conditions:
            statuses = conditions.get("invoice_status")
            if statuses and "paid" in statuses:
                conditions = {**conditions, "invoice_status": [s for s in statuses if s != "paid"]}
            elif not statuses:
                conditions = {**conditions, "invoice_status": ["sent", "verified"]}

        is_daily = schedule.get("report_frequency") == "daily"

        # Find matching invoices
        invoices = self.repo.get_invoices_matching_conditions(
            org_id=org_id,
            conditions=conditions,
            project_id=schedule.get("project_id"),
            contract_id=schedule.get("contract_id"),
            counterparty_id=schedule.get("counterparty_id"),
        )

        if not invoices:
            logger.debug(f"Schedule {schedule['id']}: no matching invoices")
            return 0

        emails_sent = 0
        max_reminders = schedule.get("max_reminders") or 999
        escalation_after = schedule.get("escalation_after") or 999

        for invoice in invoices:
            # Daily dedup: skip if already sent today for this invoice
            if is_daily and self.repo.has_sent_today_for_invoice(
                org_id, invoice["id"], schedule["id"]
            ):
                continue

            # Check reminder count
            reminder_count = self.repo.count_reminders_for_invoice(
                org_id, invoice["id"], schedule["id"]
            )
            if reminder_count >= max_reminders:
                continue

            # Resolve recipients from customer_contact
            counterparty_id = invoice.get("counterparty_id")
            if not counterparty_id:
                continue

            include_escalation = reminder_count >= escalation_after
            contacts = self.repo.get_invoice_contacts(
                counterparty_id, include_escalation=include_escalation
            )
            if not contacts:
                continue

            # Build context
            context = {
                "invoice_number": invoice.get("invoice_number", "N/A"),
                "total_amount": invoice.get("total_amount"),
                "due_date": invoice.get("due_date"),
                "days_overdue": invoice.get("days_overdue", 0),
                "counterparty_name": invoice.get("counterparty_name", ""),
                "contract_name": invoice.get("contract_name", ""),
                "period_start": invoice.get("period_start"),
                "period_end": invoice.get("period_end"),
                "reminder_count": reminder_count + 1,
                "max_reminders": max_reminders,
                "sender_name": "FrontierMind",
            }

            # Generate submission token if configured
            submission_token_id = None
            if schedule.get("include_submission_link"):
                token_raw = self.token_service.generate_token(
                    org_id=org_id,
                    invoice_header_id=invoice["id"],
                    counterparty_id=counterparty_id,
                    fields=schedule.get("submission_fields") or [],
                )
                submission_token_id = token_raw["token_id"]
                full_url = f"{self.app_base_url}/submit/{token_raw['token']}"
                context["submission_url"] = full_url
                self.token_service.store_submission_url(token_raw["token_id"], full_url)

            # Render email
            rendered = self.renderer.render_email(
                subject_template=schedule["subject_template"],
                body_html_template=schedule["body_html"],
                body_text_template=schedule.get("body_text"),
                context=context,
            )

            # Send to each contact
            for contact in contacts:
                _, success = self._send_single_email(
                    org_id=org_id,
                    template_id=schedule["email_template_id"],
                    schedule_id=schedule["id"],
                    recipient_email=contact["email"],
                    recipient_name=contact.get("full_name"),
                    subject=rendered["subject"],
                    html_body=rendered["html"],
                    text_body=rendered.get("text"),
                    invoice_header_id=invoice["id"],
                    submission_token_id=submission_token_id,
                    reminder_count=reminder_count + 1,
                )
                if success:
                    emails_sent += 1

        return emails_sent

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_org_sender(self, org_id: int) -> Dict[str, Optional[str]]:
        """Look up the org's default email sender from org_email_address table.

        Returns dict with 'sender_name' and 'sender_email', or empty values
        to fall back to global SES defaults.
        """
        try:
            from db.database import get_db_connection

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT display_name, email_prefix, domain
                        FROM org_email_address
                        WHERE organization_id = %s
                          AND label = 'default'
                          AND is_active = true
                        LIMIT 1
                        """,
                        (org_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        row = dict(row)
                        return {
                            "sender_name": row.get("display_name"),
                            "sender_email": f"{row['email_prefix']}@{row['domain']}",
                        }
        except Exception as e:
            logger.warning(f"Failed to look up org sender for org_id={org_id}: {e}")

        return {"sender_name": None, "sender_email": None}

    def _send_single_email(
        self,
        org_id: int,
        template_id: int,
        recipient_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        schedule_id: Optional[int] = None,
        recipient_name: Optional[str] = None,
        invoice_header_id: Optional[int] = None,
        submission_token_id: Optional[int] = None,
        reminder_count: int = 0,
    ) -> tuple:
        """Send a single email and log the result. Returns (log_id, success)."""
        # Look up org-specific sender
        org_sender = self._get_org_sender(org_id)

        # Create log entry (pending)
        log_id = self.repo.create_outbound_message({
            "organization_id": org_id,
            "email_notification_schedule_id": schedule_id,
            "email_template_id": template_id,
            "recipient_email": recipient_email,
            "recipient_name": recipient_name,
            "subject": subject,
            "email_status": "sending",
            "reminder_count": reminder_count,
            "invoice_header_id": invoice_header_id,
            "submission_token_id": submission_token_id,
            "sent_at": datetime.now(timezone.utc),
        })

        try:
            ses_message_id = self.ses.send_email(
                to=[recipient_email],
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                sender_name=org_sender["sender_name"],
                sender_email=org_sender["sender_email"],
            )
            self.repo.update_outbound_message_status(
                log_id, "delivered", ses_message_id=ses_message_id
            )
            return log_id, True
        except SESError as e:
            logger.error(f"Email send failed for {recipient_email}: {e}")
            self.repo.update_outbound_message_status(
                log_id, "failed", error_message=str(e)
            )
            return log_id, False

    def _build_invoice_context(
        self, org_id: int, invoice_header_id: Optional[int]
    ) -> Dict[str, Any]:
        """Build template context from an invoice."""
        context: Dict[str, Any] = {"sender_name": "FrontierMind"}

        if not invoice_header_id:
            return context

        # Query invoice details
        from db.database import get_db_connection

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ih.invoice_number, ih.total_amount, ih.due_date,
                           ih.status, ih.invoice_date,
                           c.name as contract_name,
                           cp.name as counterparty_name,
                           bp.start_date as period_start,
                           bp.end_date as period_end,
                           EXTRACT(DAY FROM NOW() - ih.due_date)::INTEGER as days_overdue
                    FROM invoice_header ih
                    LEFT JOIN contract c ON c.id = ih.contract_id
                    LEFT JOIN counterparty cp ON cp.id = c.counterparty_id
                    LEFT JOIN billing_period bp ON bp.id = ih.billing_period_id
                    WHERE ih.id = %s AND c.organization_id = %s
                    """,
                    (invoice_header_id, org_id),
                )
                row = cursor.fetchone()
                if row:
                    invoice = dict(row)
                    context.update({
                        "invoice_number": invoice.get("invoice_number", "N/A"),
                        "total_amount": invoice.get("total_amount"),
                        "due_date": invoice.get("due_date"),
                        "days_overdue": invoice.get("days_overdue", 0),
                        "counterparty_name": invoice.get("counterparty_name", ""),
                        "contract_name": invoice.get("contract_name", ""),
                        "period_start": invoice.get("period_start"),
                        "period_end": invoice.get("period_end"),
                    })

        return context
