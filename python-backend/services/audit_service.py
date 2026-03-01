"""
Audit logging service.

Writes structured events to the audit_log table using direct INSERTs
(bypassing the log_audit_event() PL/pgSQL function to avoid FK validation
on user_id/org_id that would fail for API-key-only auth).

All writes are designed to run inside FastAPI BackgroundTasks so they
never add latency to HTTP responses.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Request

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """Structured audit event matching the audit_log table schema."""

    action: str  # Must match audit_action_type enum
    resource_type: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    organization_id: Optional[int] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    request_method: Optional[str] = None
    request_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    records_affected: Optional[int] = None
    severity: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    compliance_relevant: bool = False
    data_classification: str = "internal"  # public, internal, confidential, restricted


class AuditService:
    """Writes audit events to the audit_log table."""

    def log_event(self, event: AuditEvent) -> None:
        """Insert a single audit event. Catches all exceptions internally."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            action, resource_type, resource_id, resource_name,
                            organization_id, user_id, session_id,
                            ip_address, user_agent, request_id,
                            request_method, request_path,
                            details, success, error_message,
                            duration_ms, records_affected,
                            severity, compliance_relevant, data_classification
                        ) VALUES (
                            %(action)s::audit_action_type,
                            %(resource_type)s,
                            %(resource_id)s,
                            %(resource_name)s,
                            %(organization_id)s,
                            %(user_id)s,
                            %(session_id)s,
                            %(ip_address)s::inet,
                            %(user_agent)s,
                            %(request_id)s,
                            %(request_method)s,
                            %(request_path)s,
                            %(details)s::jsonb,
                            %(success)s,
                            %(error_message)s,
                            %(duration_ms)s,
                            %(records_affected)s,
                            %(severity)s::audit_severity,
                            %(compliance_relevant)s,
                            %(data_classification)s::data_classification_level
                        )
                        """,
                        {
                            "action": event.action,
                            "resource_type": event.resource_type,
                            "resource_id": event.resource_id,
                            "resource_name": event.resource_name,
                            "organization_id": event.organization_id,
                            "user_id": event.user_id,
                            "session_id": event.session_id,
                            "ip_address": event.ip_address,
                            "user_agent": event.user_agent,
                            "request_id": event.request_id,
                            "request_method": event.request_method,
                            "request_path": event.request_path,
                            "details": _json_dumps(event.details),
                            "success": event.success,
                            "error_message": event.error_message,
                            "duration_ms": event.duration_ms,
                            "records_affected": event.records_affected,
                            "severity": event.severity,
                            "compliance_relevant": event.compliance_relevant,
                            "data_classification": event.data_classification,
                        },
                    )
        except Exception:
            logger.exception("Failed to write audit event: %s %s", event.action, event.resource_type)


# Module-level singleton
audit_service = AuditService()


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from proxy headers or direct connection."""
    ip = request.headers.get("X-Real-IP")
    if ip:
        return ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _json_dumps(obj: Any) -> str:
    """Serialize to JSON string for the JSONB column."""
    import json
    return json.dumps(obj, default=str)


def log_business_event(
    background_tasks: BackgroundTasks,
    request: Request,
    *,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    organization_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    records_affected: Optional[int] = None,
    severity: str = "INFO",
    compliance_relevant: bool = False,
    data_classification: str = "internal",
) -> None:
    """Schedule an audit event as a background task.

    Extracts IP, user-agent, and request_id from the Request object.
    If organization_id is not passed explicitly, falls back to
    ``request.state.audit_org_id`` (set by API-key auth middleware).
    """
    if organization_id is None:
        organization_id = getattr(request.state, "audit_org_id", None)

    request_id = getattr(request.state, "audit_request_id", None)

    event = AuditEvent(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        organization_id=organization_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        request_method=request.method,
        request_path=str(request.url.path),
        details=details or {},
        success=success,
        error_message=error_message,
        records_affected=records_affected,
        severity=severity,
        compliance_relevant=compliance_relevant,
        data_classification=data_classification,
    )

    background_tasks.add_task(audit_service.log_event, event)
