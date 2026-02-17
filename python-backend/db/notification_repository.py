"""
Notification repository for database operations.

Provides CRUD operations for email_template, email_notification_schedule,
email_log, submission_token, and submission_response tables
as defined in migration 032_email_notification_engine.sql.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class NotificationRepository:
    """Repository for notification-related database operations."""

    # =========================================================================
    # EMAIL TEMPLATE METHODS
    # =========================================================================

    def get_template(self, template_id: int, org_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, organization_id, email_schedule_type, name, description,
                           subject_template, body_html, body_text,
                           available_variables, is_system, is_active,
                           created_at, updated_at
                    FROM email_template
                    WHERE id = %s AND organization_id = %s
                    """,
                    (template_id, org_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_templates(
        self,
        org_id: int,
        email_schedule_type: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, organization_id, email_schedule_type, name, description,
                           subject_template, body_html, body_text,
                           available_variables, is_system, is_active,
                           created_at, updated_at
                    FROM email_template
                    WHERE organization_id = %s
                """
                params: List[Any] = [org_id]

                if email_schedule_type:
                    query += " AND email_schedule_type = %s"
                    params.append(email_schedule_type)

                if not include_inactive:
                    query += " AND is_active = true"

                query += " ORDER BY name"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def create_template(self, org_id: int, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO email_template (
                        organization_id, email_schedule_type, name, description,
                        subject_template, body_html, body_text,
                        available_variables
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        org_id,
                        data["email_schedule_type"],
                        data["name"],
                        data.get("description"),
                        data["subject_template"],
                        data["body_html"],
                        data.get("body_text"),
                        Json(data.get("available_variables", [])),
                    ),
                )
                conn.commit()
                return cursor.fetchone()["id"]

    def update_template(
        self, template_id: int, org_id: int, updates: Dict[str, Any]
    ) -> bool:
        if not updates:
            return True

        set_clauses = []
        params: List[Any] = []

        for key, value in updates.items():
            if key in ("id", "organization_id", "is_system", "created_at"):
                continue
            if key == "available_variables":
                set_clauses.append(f"{key} = %s")
                params.append(Json(value))
            else:
                set_clauses.append(f"{key} = %s")
                params.append(value)

        if not set_clauses:
            return True

        params.extend([template_id, org_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE email_template
                    SET {', '.join(set_clauses)}
                    WHERE id = %s AND organization_id = %s
                    """,
                    params,
                )
                conn.commit()
                return cursor.rowcount > 0

    def deactivate_template(self, template_id: int, org_id: int) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_template
                    SET is_active = false
                    WHERE id = %s AND organization_id = %s AND is_system = false
                    """,
                    (template_id, org_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    # =========================================================================
    # EMAIL NOTIFICATION SCHEDULE METHODS
    # =========================================================================

    def get_schedule(self, schedule_id: int, org_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, organization_id, email_template_id, name,
                           email_schedule_type, report_frequency, day_of_month, time_of_day,
                           timezone, conditions, max_reminders, escalation_after,
                           include_submission_link, submission_fields,
                           is_active, last_run_at, last_run_status, last_run_error,
                           next_run_at, project_id, contract_id, counterparty_id,
                           created_at, updated_at
                    FROM email_notification_schedule
                    WHERE id = %s AND organization_id = %s
                    """,
                    (schedule_id, org_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_schedules(
        self,
        org_id: int,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, organization_id, email_template_id, name,
                           email_schedule_type, report_frequency, day_of_month, time_of_day,
                           timezone, conditions, max_reminders, escalation_after,
                           include_submission_link, submission_fields,
                           is_active, last_run_at, last_run_status, last_run_error,
                           next_run_at, project_id, contract_id, counterparty_id,
                           created_at, updated_at
                    FROM email_notification_schedule
                    WHERE organization_id = %s
                """
                params: List[Any] = [org_id]

                if not include_inactive:
                    query += " AND is_active = true"

                query += " ORDER BY name"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def create_schedule(self, org_id: int, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO email_notification_schedule (
                        organization_id, email_template_id, name, email_schedule_type,
                        report_frequency, day_of_month, time_of_day, timezone,
                        conditions, max_reminders, escalation_after,
                        include_submission_link, submission_fields,
                        project_id, contract_id, counterparty_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        org_id,
                        data["email_template_id"],
                        data["name"],
                        data["email_schedule_type"],
                        data["report_frequency"],
                        data.get("day_of_month"),
                        data.get("time_of_day", "09:00:00"),
                        data.get("timezone", "UTC"),
                        Json(data.get("conditions", {})),
                        data.get("max_reminders", 3),
                        data.get("escalation_after", 1),
                        data.get("include_submission_link", False),
                        Json(data.get("submission_fields", [])),
                        data.get("project_id"),
                        data.get("contract_id"),
                        data.get("counterparty_id"),
                    ),
                )
                conn.commit()
                return cursor.fetchone()["id"]

    def update_schedule(
        self, schedule_id: int, org_id: int, updates: Dict[str, Any]
    ) -> bool:
        if not updates:
            return True

        set_clauses = []
        params: List[Any] = []

        json_fields = {"conditions", "submission_fields"}

        for key, value in updates.items():
            if key in ("id", "organization_id", "created_at"):
                continue
            if key in json_fields:
                set_clauses.append(f"{key} = %s")
                params.append(Json(value))
            else:
                set_clauses.append(f"{key} = %s")
                params.append(value)

        if not set_clauses:
            return True

        params.extend([schedule_id, org_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE email_notification_schedule
                    SET {', '.join(set_clauses)}
                    WHERE id = %s AND organization_id = %s
                    """,
                    params,
                )
                conn.commit()
                return cursor.rowcount > 0

    def get_due_schedules(self) -> List[Dict[str, Any]]:
        """Get all active schedules where next_run_at <= now()."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT s.*, t.subject_template, t.body_html, t.body_text
                    FROM email_notification_schedule s
                    JOIN email_template t ON t.id = s.email_template_id
                    WHERE s.is_active = true
                      AND s.next_run_at IS NOT NULL
                      AND s.next_run_at <= NOW()
                    ORDER BY s.next_run_at
                    FOR UPDATE OF s SKIP LOCKED
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def update_schedule_after_run(
        self,
        schedule_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update schedule after a run attempt."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE email_notification_schedule
                    SET last_run_at = NOW(),
                        last_run_status = %s,
                        last_run_error = %s
                    WHERE id = %s
                    """,
                    (status, error, schedule_id),
                )
                conn.commit()

    # =========================================================================
    # EMAIL LOG METHODS
    # =========================================================================

    def create_email_log(self, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO email_log (
                        organization_id, email_notification_schedule_id, email_template_id,
                        recipient_email, recipient_name, subject, email_status,
                        ses_message_id, reminder_count, invoice_header_id,
                        submission_token_id, sent_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data["organization_id"],
                        data.get("email_notification_schedule_id"),
                        data.get("email_template_id"),
                        data["recipient_email"],
                        data.get("recipient_name"),
                        data["subject"],
                        data.get("email_status", "pending"),
                        data.get("ses_message_id"),
                        data.get("reminder_count", 0),
                        data.get("invoice_header_id"),
                        data.get("submission_token_id"),
                        data.get("sent_at"),
                    ),
                )
                conn.commit()
                return cursor.fetchone()["id"]

    def update_email_log_status(
        self,
        log_id: int,
        status: str,
        ses_message_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                sets = ["email_status = %s"]
                params: List[Any] = [status]

                if ses_message_id:
                    sets.append("ses_message_id = %s")
                    params.append(ses_message_id)
                if status == "delivered":
                    sets.append("delivered_at = NOW()")
                elif status == "bounced":
                    sets.append("bounced_at = NOW()")
                if status in ("sending", "delivered"):
                    sets.append("sent_at = COALESCE(sent_at, NOW())")
                if error_message:
                    sets.append("error_message = %s")
                    params.append(error_message)

                params.append(log_id)
                cursor.execute(
                    f"UPDATE email_log SET {', '.join(sets)} WHERE id = %s",
                    params,
                )
                conn.commit()

    def list_email_logs(
        self,
        org_id: int,
        invoice_header_id: Optional[int] = None,
        schedule_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                where = "WHERE organization_id = %s"
                params: List[Any] = [org_id]

                if invoice_header_id:
                    where += " AND invoice_header_id = %s"
                    params.append(invoice_header_id)
                if schedule_id:
                    where += " AND email_notification_schedule_id = %s"
                    params.append(schedule_id)
                if status:
                    where += " AND email_status = %s"
                    params.append(status)

                # Count
                cursor.execute(f"SELECT COUNT(*) as cnt FROM email_log {where}", params)
                total = cursor.fetchone()["cnt"]

                # Data
                cursor.execute(
                    f"""
                    SELECT id, organization_id, email_notification_schedule_id, email_template_id,
                           recipient_email, recipient_name, subject, email_status,
                           ses_message_id, reminder_count, invoice_header_id,
                           submission_token_id, error_message, sent_at,
                           delivered_at, created_at
                    FROM email_log
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                return [dict(row) for row in cursor.fetchall()], total

    def count_reminders_for_invoice(
        self,
        org_id: int,
        invoice_header_id: int,
        schedule_id: Optional[int] = None,
    ) -> int:
        """Count how many reminder emails have been sent for an invoice."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT COUNT(*) as cnt FROM email_log
                    WHERE organization_id = %s
                      AND invoice_header_id = %s
                      AND email_status NOT IN ('failed', 'suppressed')
                """
                params: List[Any] = [org_id, invoice_header_id]

                if schedule_id:
                    query += " AND email_notification_schedule_id = %s"
                    params.append(schedule_id)

                cursor.execute(query, params)
                return cursor.fetchone()["cnt"]

    # =========================================================================
    # INVOICE QUERY METHODS (for schedule processing)
    # =========================================================================

    def get_invoices_matching_conditions(
        self,
        org_id: int,
        conditions: Dict[str, Any],
        project_id: Optional[int] = None,
        contract_id: Optional[int] = None,
        counterparty_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find invoices matching schedule conditions.

        Conditions JSONB format:
        {
            "invoice_status": ["sent", "verified"],
            "days_overdue_min": 0,
            "days_overdue_max": 30,
            "min_amount": 1000
        }
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT ih.id, ih.invoice_number, ih.total_amount,
                           ih.status, ih.due_date, ih.invoice_date,
                           ih.contract_id, ih.billing_period_id,
                           c.name as contract_name,
                           cp.name as counterparty_name,
                           cp.id as counterparty_id,
                           bp.start_date as period_start,
                           bp.end_date as period_end,
                           EXTRACT(DAY FROM NOW() - ih.due_date)::INTEGER as days_overdue
                    FROM invoice_header ih
                    LEFT JOIN contract c ON c.id = ih.contract_id
                    LEFT JOIN counterparty cp ON cp.id = c.counterparty_id
                    LEFT JOIN billing_period bp ON bp.id = ih.billing_period_id
                    WHERE c.organization_id = %s
                """
                params: List[Any] = [org_id]

                # Status filter
                statuses = conditions.get("invoice_status")
                if statuses:
                    placeholders = ", ".join(["%s"] * len(statuses))
                    query += f" AND ih.status IN ({placeholders})"
                    params.extend(statuses)

                # Overdue filters
                if conditions.get("days_overdue_min") is not None:
                    query += " AND ih.due_date IS NOT NULL AND (NOW() - ih.due_date) >= INTERVAL '1 day' * %s"
                    params.append(conditions["days_overdue_min"])
                if conditions.get("days_overdue_max") is not None:
                    query += " AND ih.due_date IS NOT NULL AND (NOW() - ih.due_date) <= INTERVAL '1 day' * %s"
                    params.append(conditions["days_overdue_max"])

                # Amount filters
                if conditions.get("min_amount") is not None:
                    query += " AND ih.total_amount >= %s"
                    params.append(conditions["min_amount"])
                if conditions.get("max_amount") is not None:
                    query += " AND ih.total_amount <= %s"
                    params.append(conditions["max_amount"])

                # Scope filters
                if project_id:
                    query += " AND ih.project_id = %s"
                    params.append(project_id)
                if contract_id:
                    query += " AND ih.contract_id = %s"
                    params.append(contract_id)
                if counterparty_id:
                    query += " AND c.counterparty_id = %s"
                    params.append(counterparty_id)

                query += " ORDER BY ih.due_date"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def get_invoice_contacts(
        self,
        counterparty_id: int,
        include_escalation: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get contacts for a counterparty that should receive invoice emails."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, full_name, email, role, escalation_only
                    FROM customer_contact
                    WHERE counterparty_id = %s
                      AND is_active = true
                      AND include_in_invoice_email = true
                      AND email IS NOT NULL
                """
                params: List[Any] = [counterparty_id]

                if not include_escalation:
                    query += " AND escalation_only = false"

                query += " ORDER BY full_name"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # SUBMISSION TOKEN METHODS
    # =========================================================================

    def create_submission_token(self, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO submission_token (
                        organization_id, token_hash, submission_fields,
                        max_uses, expires_at, invoice_header_id,
                        counterparty_id, email_log_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data["organization_id"],
                        data["token_hash"],
                        Json(data.get("submission_fields", [])),
                        data.get("max_uses", 1),
                        data["expires_at"],
                        data.get("invoice_header_id"),
                        data.get("counterparty_id"),
                        data.get("email_log_id"),
                    ),
                )
                conn.commit()
                return cursor.fetchone()["id"]

    def get_submission_token_by_hash(
        self, token_hash: str
    ) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT st.*,
                           ih.invoice_number, ih.total_amount, ih.due_date,
                           cp.name as counterparty_name,
                           o.name as organization_name
                    FROM submission_token st
                    LEFT JOIN invoice_header ih ON ih.id = st.invoice_header_id
                    LEFT JOIN counterparty cp ON cp.id = st.counterparty_id
                    LEFT JOIN organization o ON o.id = st.organization_id
                    WHERE st.token_hash = %s
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def use_submission_token(self, token_id: int) -> bool:
        """Increment use_count and set status to 'used' if max_uses reached."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE submission_token
                    SET use_count = use_count + 1,
                        submission_token_status = CASE
                            WHEN use_count + 1 >= max_uses THEN 'used'::submission_token_status
                            ELSE submission_token_status
                        END
                    WHERE id = %s AND submission_token_status = 'active'
                    RETURNING id
                    """,
                    (token_id,),
                )
                conn.commit()
                return cursor.fetchone() is not None

    def expire_stale_tokens(self) -> int:
        """Set expired status on tokens past their expires_at."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE submission_token
                    SET submission_token_status = 'expired'
                    WHERE submission_token_status = 'active' AND expires_at < NOW()
                    """
                )
                conn.commit()
                count = cursor.rowcount
                if count > 0:
                    logger.info(f"Expired {count} stale submission tokens")
                return count

    # =========================================================================
    # SUBMISSION RESPONSE METHODS
    # =========================================================================

    def create_submission_response(self, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO submission_response (
                        organization_id, submission_token_id,
                        response_data, submitted_by_email, ip_address,
                        invoice_header_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data["organization_id"],
                        data["submission_token_id"],
                        Json(data["response_data"]),
                        data.get("submitted_by_email"),
                        data.get("ip_address"),
                        data.get("invoice_header_id"),
                    ),
                )
                conn.commit()
                return cursor.fetchone()["id"]

    def list_submission_responses(
        self,
        org_id: int,
        invoice_header_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                where = "WHERE sr.organization_id = %s"
                params: List[Any] = [org_id]

                if invoice_header_id:
                    where += " AND sr.invoice_header_id = %s"
                    params.append(invoice_header_id)

                cursor.execute(
                    f"SELECT COUNT(*) as cnt FROM submission_response sr {where}",
                    params,
                )
                total = cursor.fetchone()["cnt"]

                cursor.execute(
                    f"""
                    SELECT sr.id, sr.organization_id, sr.submission_token_id,
                           sr.response_data, sr.submitted_by_email,
                           sr.invoice_header_id, sr.created_at
                    FROM submission_response sr
                    {where}
                    ORDER BY sr.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                return [dict(row) for row in cursor.fetchall()], total
