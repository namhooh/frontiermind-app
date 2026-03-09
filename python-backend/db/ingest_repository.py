"""
Repository for inbound_message and inbound_attachment CRUD operations.

Supports the unified inbound message model for email, token form, and token upload channels.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class IngestRepository:
    """CRUD operations for inbound_message and inbound_attachment tables."""

    # =========================================================================
    # INBOUND MESSAGE
    # =========================================================================

    def create_inbound_message(self, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO inbound_message (
                        organization_id, channel,
                        subject, body_text, raw_headers,
                        ses_message_id, in_reply_to, references_chain, s3_raw_path,
                        submission_token_id, response_data,
                        sender_email, sender_name, ip_address,
                        invoice_header_id, project_id, counterparty_id,
                        outbound_message_id, customer_contact_id,
                        attachment_count, inbound_message_status, classification_reason, failed_reason
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        data["organization_id"],
                        data["channel"],
                        data.get("subject"),
                        data.get("body_text"),
                        Json(data["raw_headers"]) if data.get("raw_headers") else None,
                        data.get("ses_message_id"),
                        data.get("in_reply_to"),
                        data.get("references_chain"),
                        data.get("s3_raw_path"),
                        data.get("submission_token_id"),
                        Json(data.get("response_data", {})),
                        data.get("sender_email"),
                        data.get("sender_name"),
                        data.get("ip_address"),
                        data.get("invoice_header_id"),
                        data.get("project_id"),
                        data.get("counterparty_id"),
                        data.get("outbound_message_id"),
                        data.get("customer_contact_id"),
                        data.get("attachment_count", 0),
                        data.get("inbound_message_status", "received"),
                        data.get("classification_reason"),
                        data.get("failed_reason"),
                    ),
                )
                conn.commit()
                return cur.fetchone()["id"]

    def get_inbound_message(self, message_id: int, org_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM inbound_message
                    WHERE id = %s AND organization_id = %s
                    """,
                    (message_id, org_id),
                )
                row = cur.fetchone()
                if not row:
                    return None

                msg = dict(row)

                # Attach attachments
                cur.execute(
                    """
                    SELECT * FROM inbound_attachment
                    WHERE inbound_message_id = %s
                    ORDER BY id
                    """,
                    (message_id,),
                )
                msg["attachments"] = [dict(a) for a in cur.fetchall()]
                return msg

    def list_inbound_messages(
        self,
        org_id: int,
        channel: Optional[str] = None,
        inbound_message_status: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                where = "WHERE organization_id = %s"
                params: List[Any] = [org_id]

                if channel:
                    where += " AND channel = %s"
                    params.append(channel)
                if inbound_message_status:
                    where += " AND inbound_message_status = %s"
                    params.append(inbound_message_status)
                if project_id is not None:
                    where += " AND project_id = %s"
                    params.append(project_id)

                cur.execute(
                    f"SELECT COUNT(*) as cnt FROM inbound_message {where}",
                    params,
                )
                total = cur.fetchone()["cnt"]

                cur.execute(
                    f"""
                    SELECT id, organization_id, channel,
                           subject, sender_email, sender_name, inbound_message_status,
                           classification_reason, failed_reason, attachment_count,
                           invoice_header_id, project_id, counterparty_id,
                           outbound_message_id, created_at,
                           reviewed_by, reviewed_at
                    FROM inbound_message
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                messages = [dict(row) for row in cur.fetchall()]

                # Batch-fetch attachments for all messages
                if messages:
                    msg_ids = [m["id"] for m in messages]
                    placeholders = ", ".join(["%s"] * len(msg_ids))
                    cur.execute(
                        f"""
                        SELECT id, inbound_message_id, filename, content_type,
                               size_bytes, attachment_processing_status,
                               extraction_result, reference_price_id, created_at
                        FROM inbound_attachment
                        WHERE inbound_message_id IN ({placeholders})
                        ORDER BY id
                        """,
                        msg_ids,
                    )
                    atts_by_msg: Dict[int, List[Dict[str, Any]]] = {}
                    for a in cur.fetchall():
                        a = dict(a)
                        atts_by_msg.setdefault(a["inbound_message_id"], []).append(a)
                    for m in messages:
                        m["attachments"] = atts_by_msg.get(m["id"], [])

                return messages, total

    def update_inbound_message_status(
        self,
        message_id: int,
        org_id: int,
        inbound_message_status: str,
        reviewed_by: Optional[str] = None,
        reason: Optional[str] = None,
        failed_reason: Optional[str] = None,
    ) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sets = ["inbound_message_status = %s"]
                params: List[Any] = [inbound_message_status]

                if reviewed_by:
                    sets.append("reviewed_by = %s")
                    params.append(reviewed_by)
                    sets.append("reviewed_at = NOW()")

                if reason:
                    sets.append("classification_reason = %s")
                    params.append(reason)

                if failed_reason:
                    sets.append("failed_reason = %s")
                    params.append(failed_reason)

                params.extend([message_id, org_id])
                cur.execute(
                    f"""
                    UPDATE inbound_message
                    SET {', '.join(sets)}
                    WHERE id = %s AND organization_id = %s
                    """,
                    params,
                )
                conn.commit()
                return cur.rowcount > 0

    def exists_by_s3_raw_path(self, s3_raw_path: str) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM inbound_message WHERE s3_raw_path = %s LIMIT 1",
                    (s3_raw_path,),
                )
                return cur.fetchone() is not None

    # =========================================================================
    # INBOUND ATTACHMENT
    # =========================================================================

    def create_inbound_attachment(self, data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO inbound_attachment (
                        inbound_message_id, filename, content_type,
                        size_bytes, s3_path, file_hash,
                        attachment_processing_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data["inbound_message_id"],
                        data.get("filename"),
                        data.get("content_type"),
                        data.get("size_bytes"),
                        data["s3_path"],
                        data.get("file_hash"),
                        data.get("attachment_processing_status", "pending"),
                    ),
                )
                conn.commit()
                return cur.fetchone()["id"]

    def get_attachment(self, attachment_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM inbound_attachment WHERE id = %s",
                    (attachment_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def list_attachments_for_message(self, message_id: int) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM inbound_attachment
                    WHERE inbound_message_id = %s
                    ORDER BY id
                    """,
                    (message_id,),
                )
                return [dict(row) for row in cur.fetchall()]

    def update_attachment_status(
        self,
        attachment_id: int,
        status: str,
        extraction_result: Optional[Dict] = None,
        reference_price_id: Optional[int] = None,
        failed_reason: Optional[str] = None,
    ) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sets = ["attachment_processing_status = %s"]
                params: List[Any] = [status]

                if extraction_result is not None:
                    sets.append("extraction_result = %s")
                    params.append(Json(extraction_result))

                if reference_price_id is not None:
                    sets.append("reference_price_id = %s")
                    params.append(reference_price_id)

                if failed_reason is not None:
                    sets.append("failed_reason = %s")
                    params.append(failed_reason)

                params.append(attachment_id)
                cur.execute(
                    f"""
                    UPDATE inbound_attachment
                    SET {', '.join(sets)}
                    WHERE id = %s
                    """,
                    params,
                )
                conn.commit()
                return cur.rowcount > 0

    # =========================================================================
    # LOOKUP METHODS
    # =========================================================================

    def get_org_by_email_address(self, email_prefix: str, domain: str) -> Optional[Dict[str, Any]]:
        """Look up organization by email address components."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT oea.organization_id, oea.display_name, o.name as organization_name
                    FROM org_email_address oea
                    JOIN organization o ON o.id = oea.organization_id
                    WHERE oea.email_prefix = %s AND oea.domain = %s AND oea.is_active = true
                    """,
                    (email_prefix, domain),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def find_contact_by_email(self, sender_email: str, org_id: int) -> Optional[Dict[str, Any]]:
        """Find a customer_contact matching the sender email within the org."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cc.id, cc.full_name, cc.email, cc.counterparty_id,
                           cp.name as counterparty_name
                    FROM customer_contact cc
                    JOIN counterparty cp ON cp.id = cc.counterparty_id
                    WHERE LOWER(cc.email) = LOWER(%s)
                      AND cc.organization_id = %s
                      AND cc.is_active = true
                    LIMIT 1
                    """,
                    (sender_email, org_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def find_outbound_by_message_id(self, ses_message_id: str) -> Optional[Dict[str, Any]]:
        """Find an outbound_message by its SES message ID for threading."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, organization_id, invoice_header_id,
                           submission_token_id, recipient_email
                    FROM outbound_message
                    WHERE ses_message_id = %s
                    LIMIT 1
                    """,
                    (ses_message_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    # =========================================================================
    # ATTACHMENT PROCESSING HELPERS
    # =========================================================================

    def get_message_for_attachment(self, attachment_id: int) -> Optional[Dict[str, Any]]:
        """Fetch the parent inbound_message for a given attachment."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT im.*
                    FROM inbound_message im
                    JOIN inbound_attachment ia ON ia.inbound_message_id = im.id
                    WHERE ia.id = %s
                    """,
                    (attachment_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def resolve_project_for_counterparty(
        self, counterparty_id: int, org_id: int
    ) -> Optional[int]:
        """
        Find the unique project with a REBASED_MARKET_PRICE tariff for a counterparty.

        Returns project_id if exactly one match, None otherwise.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ct.project_id
                    FROM clause_tariff ct
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    JOIN contract c ON c.id = ct.contract_id
                    WHERE c.counterparty_id = %s
                      AND c.organization_id = %s
                      AND esc.code = 'REBASED_MARKET_PRICE'
                      AND ct.is_current = true
                    """,
                    (counterparty_id, org_id),
                )
                rows = cur.fetchall()
                if len(rows) == 1:
                    return rows[0]["project_id"]
                return None

    # =========================================================================
    # DUAL-WRITE HELPERS
    # =========================================================================

    def create_inbound_message_for_token(
        self,
        org_id: int,
        channel: str,
        submission_token_id: int,
        response_data: Dict[str, Any],
        submitted_by_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        invoice_header_id: Optional[int] = None,
        project_id: Optional[int] = None,
        counterparty_id: Optional[int] = None,
    ) -> int:
        """Convenience method for dual-write from token submission flow."""
        return self.create_inbound_message({
            "organization_id": org_id,
            "channel": channel,
            "submission_token_id": submission_token_id,
            "response_data": response_data,
            "sender_email": submitted_by_email,
            "ip_address": ip_address,
            "invoice_header_id": invoice_header_id,
            "project_id": project_id,
            "counterparty_id": counterparty_id,
            "inbound_message_status": "approved",
        })
