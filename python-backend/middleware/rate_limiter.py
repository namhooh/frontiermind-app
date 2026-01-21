"""
Rate Limiting Middleware for FastAPI.

Implements per-endpoint rate limiting as specified in the Security Assessment:
- Default: 100 requests/minute for standard endpoints
- File uploads: 10 requests/minute (expensive operations)
- Auth endpoints: 5 requests/minute (brute force protection)
- Admin endpoints: 50 requests/minute
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
import os
import logging

logger = logging.getLogger(__name__)

# Rate limit configurations (from Security Assessment Section 8.3)
RATE_LIMITS = {
    # Default rate limit for most endpoints
    "default": os.getenv("RATE_LIMIT_DEFAULT", "100/minute"),

    # Stricter limits for expensive operations
    "upload": os.getenv("RATE_LIMIT_UPLOAD", "10/minute"),

    # Auth-related endpoints (brute force protection)
    "auth": os.getenv("RATE_LIMIT_AUTH", "5/minute"),

    # Admin endpoints
    "admin": os.getenv("RATE_LIMIT_ADMIN", "50/minute"),

    # API discovery/health endpoints (more lenient)
    "health": os.getenv("RATE_LIMIT_HEALTH", "300/minute"),

    # Export endpoints (prevent data exfiltration)
    "export": os.getenv("RATE_LIMIT_EXPORT", "20/minute"),
}


def get_client_identifier(request: Request) -> str:
    """
    Get a unique identifier for the client.

    Priority:
    1. X-Real-IP header (from reverse proxy)
    2. X-Forwarded-For header (from load balancer)
    3. Client IP address

    Note: In production with proper proxy configuration, use X-Real-IP.
    """
    # Try X-Real-IP first (set by nginx/other proxies)
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip

    # Try X-Forwarded-For (load balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()

    # Fall back to direct client IP
    return get_remote_address(request)


# Initialize the limiter with client identifier function
limiter = Limiter(
    key_func=get_client_identifier,
    default_limits=[RATE_LIMITS["default"]],
    storage_uri=os.getenv("REDIS_URL", "memory://"),  # Use Redis in production
    strategy="fixed-window",
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a structured JSON response with retry information.
    """
    logger.warning(
        f"Rate limit exceeded for {get_client_identifier(request)} "
        f"on {request.url.path}"
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down and try again later.",
            "detail": str(exc.detail) if hasattr(exc, 'detail') else "Rate limit exceeded",
            "retry_after": getattr(exc, 'retry_after', 60),
        },
        headers={
            "Retry-After": str(getattr(exc, 'retry_after', 60)),
            "X-RateLimit-Limit": str(exc.detail) if hasattr(exc, 'detail') else "unknown",
        }
    )


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # Add the limiter to app state
    app.state.limiter = limiter

    # Add SlowAPI middleware
    app.add_middleware(SlowAPIMiddleware)

    # Add custom exception handler
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    logger.info(
        f"Rate limiting configured: "
        f"default={RATE_LIMITS['default']}, "
        f"upload={RATE_LIMITS['upload']}, "
        f"auth={RATE_LIMITS['auth']}"
    )


# Decorator shortcuts for common rate limits
def limit_default(func):
    """Apply default rate limit (100/minute)."""
    return limiter.limit(RATE_LIMITS["default"])(func)


def limit_upload(func):
    """Apply upload rate limit (10/minute) for expensive operations."""
    return limiter.limit(RATE_LIMITS["upload"])(func)


def limit_auth(func):
    """Apply auth rate limit (5/minute) for brute force protection."""
    return limiter.limit(RATE_LIMITS["auth"])(func)


def limit_admin(func):
    """Apply admin rate limit (50/minute)."""
    return limiter.limit(RATE_LIMITS["admin"])(func)


def limit_health(func):
    """Apply health check rate limit (300/minute)."""
    return limiter.limit(RATE_LIMITS["health"])(func)


def limit_export(func):
    """Apply export rate limit (20/minute) to prevent data exfiltration."""
    return limiter.limit(RATE_LIMITS["export"])(func)
