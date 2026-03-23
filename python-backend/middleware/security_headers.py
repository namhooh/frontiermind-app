"""
Security headers middleware.

Adds standard HTTP security headers to every response to mitigate
clickjacking, MIME-sniffing, XSS, and other common attack vectors.

CSP is skipped for /docs and /redoc (Swagger UI requires inline scripts/styles).
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths where the strict API CSP would break the UI
_SKIP_CSP_PATHS = frozenset({"/docs", "/redoc"})

# Security headers applied to every response
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# Strict CSP for API-only responses (JSON, no HTML rendering)
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        # Apply strict CSP only for API paths (skip Swagger UI)
        if request.url.path not in _SKIP_CSP_PATHS:
            response.headers["Content-Security-Policy"] = _API_CSP

        return response
