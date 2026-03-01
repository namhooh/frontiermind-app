"""
Audit logging middleware.

Automatically logs every HTTP request to the audit_log table via a
BackgroundTask so the INSERT happens after the response is sent.

Skips noisy endpoints (health, docs) and maps HTTP methods to
audit_action_type enum values.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.background import BackgroundTask

from services.audit_service import AuditEvent, audit_service, get_client_ip

logger = logging.getLogger(__name__)

# Paths to skip (exact match against request.url.path)
_SKIP_PATHS = frozenset({"/", "/health", "/docs", "/redoc", "/openapi.json"})

# HTTP method -> audit_action_type mapping
_METHOD_ACTION = {
    "GET": "READ",
    "HEAD": "READ",
    "POST": "CREATE",
    "PUT": "UPDATE",
    "PATCH": "UPDATE",
    "DELETE": "DELETE",
    "OPTIONS": "READ",
}


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request as an audit event after the response is sent."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip noisy paths
        if path in _SKIP_PATHS:
            return await call_next(request)

        # Generate and attach request_id
        request_id = str(uuid.uuid4())
        request.state.audit_request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Determine action from status code first (override method mapping for auth failures)
        status_code = response.status_code
        if status_code in (401, 403):
            action = "ACCESS_DENIED"
        else:
            action = _METHOD_ACTION.get(request.method, "READ")

        # Pick up org_id if auth middleware set it
        organization_id = getattr(request.state, "audit_org_id", None)
        # Fallback: check X-Organization-ID header
        if organization_id is None:
            org_header = request.headers.get("X-Organization-ID")
            if org_header:
                try:
                    organization_id = int(org_header)
                except (ValueError, TypeError):
                    pass

        event = AuditEvent(
            action=action,
            resource_type="http_request",
            request_id=request_id,
            request_method=request.method,
            request_path=path,
            organization_id=organization_id,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            duration_ms=duration_ms,
            success=status_code < 400,
            error_message=None if status_code < 400 else f"HTTP {status_code}",
            severity="WARNING" if status_code >= 400 else "INFO",
            details={"status_code": status_code},
        )

        # Schedule audit write as a background task on the response
        # so it runs after the response body has been sent.
        existing_background = response.background
        async def _write_audit():
            if existing_background:
                await existing_background()
            audit_service.log_event(event)

        response.background = BackgroundTask(_write_audit)

        return response
