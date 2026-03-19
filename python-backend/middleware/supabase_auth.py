"""
Supabase JWT Authentication Middleware.

FastAPI dependency that verifies Supabase JWT tokens from the Authorization header,
extracts the user ID, and validates org membership against the X-Organization-ID header.

Used by dashboard-facing endpoints (notifications, etc.) where the frontend sends
the Supabase session JWT rather than an integration API key.
"""

import logging
import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.database import get_db_connection

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# Cache the JWT secret at module level (loaded once)
_jwt_secret: Optional[str] = None


def _get_jwt_secret() -> str:
    global _jwt_secret
    if _jwt_secret is None:
        _jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")
    if not _jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: SUPABASE_JWT_SECRET not set",
        )
    return _jwt_secret


def _get_org_id_from_header(request: Request) -> int:
    """Extract and validate X-Organization-ID header."""
    org_id = request.headers.get("X-Organization-ID")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "MissingOrganization",
                    "message": "X-Organization-ID header required"},
        )
    try:
        return int(org_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "InvalidOrganization",
                    "message": "X-Organization-ID must be an integer"},
        )


def _validate_org_membership(user_id: str, org_id: int) -> dict:
    """
    Verify user is a member of the organization.

    Queries the `role` table (Supabase-managed) to confirm the user
    has an active membership in the given organization.

    Returns dict with user_id, organization_id, role.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role_type FROM role
                    WHERE user_id = %s
                      AND organization_id = %s
                      AND is_active = true
                    LIMIT 1
                    """,
                    (user_id, org_id),
                )
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"Org membership check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable for auth check",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "NotMember",
                    "message": "User is not a member of this organization"},
        )

    return {
        "user_id": user_id,
        "organization_id": org_id,
        "role": row["role_type"],
    }


class SupabaseAuth:
    """Verifies Supabase JWT and validates org membership."""

    async def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    ) -> dict:
        """
        FastAPI dependency that authenticates a Supabase JWT.

        Returns:
            dict with 'user_id', 'organization_id', 'role' on success.

        Raises:
            HTTPException 401/403 on failure.
        """
        # Dev auth bypass – skip JWT validation entirely (never in production)
        if os.getenv("DEV_AUTH_BYPASS") == "true" and os.getenv("ENVIRONMENT") != "production":
            org_id = _get_org_id_from_header(request)
            return {
                "user_id": os.getenv("DEV_USER_ID", "dev-user"),
                "organization_id": org_id,
                "role": "admin",
            }

        # Demo access token – allows read-only demo access in production
        # Pinned to org 1 only; mutating methods are blocked.
        demo_token = os.getenv("DEMO_ACCESS_TOKEN")
        if (
            demo_token
            and credentials is not None
            and credentials.credentials == demo_token
        ):
            org_id = _get_org_id_from_header(request)
            # Pin demo to org 1
            if org_id != 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Demo access is restricted to organization 1",
                )
            # Block mutating methods for demo
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Demo access is read-only",
                )
            return {
                "user_id": "demo-user",
                "organization_id": 1,
                "role": "viewer",
            }

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header. Use: Authorization: Bearer <jwt>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Decode JWT
        secret = _get_jwt_secret()
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'sub' claim",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate org membership
        org_id = _get_org_id_from_header(request)
        auth_info = _validate_org_membership(user_id, org_id)

        # Expose for audit middleware
        request.state.audit_org_id = org_id

        return auth_info


# Singleton instance for use as a FastAPI dependency
require_supabase_auth = SupabaseAuth()


class JWTOnly:
    """
    Validates the JWT and looks up the user's org membership from the role table.

    Unlike SupabaseAuth, this does NOT require X-Organization-ID header.
    Used for bootstrap endpoints like /api/team/me where the frontend
    doesn't yet know its organization_id.

    Returns dict with 'user_id', 'organization_id', 'role'.
    """

    async def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    ) -> dict:
        # Dev auth bypass — match SupabaseAuth: skip JWT and DB lookup entirely
        if os.getenv("DEV_AUTH_BYPASS") == "true" and os.getenv("ENVIRONMENT") != "production":
            org_id_header = request.headers.get("X-Organization-ID")
            return {
                "user_id": os.getenv("DEV_USER_ID", "dev-user"),
                "organization_id": int(org_id_header) if org_id_header else 1,
                "role": "admin",
            }

        # Demo token
        demo_token = os.getenv("DEMO_ACCESS_TOKEN")
        if demo_token and credentials is not None and credentials.credentials == demo_token:
            return {"user_id": "demo-user", "organization_id": 1, "role": "viewer"}

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        if not token:
            raise HTTPException(status_code=401, detail="Empty token", headers={"WWW-Authenticate": "Bearer"})

        secret = _get_jwt_secret()
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired", headers={"WWW-Authenticate": "Bearer"})
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}", headers={"WWW-Authenticate": "Bearer"})

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim", headers={"WWW-Authenticate": "Bearer"})

        # Look up membership from role table (no org header needed)
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT organization_id, role_type FROM role WHERE user_id = %s AND is_active = true LIMIT 1",
                        (user_id,),
                    )
                    row = cur.fetchone()
        except Exception as e:
            logger.error(f"DB error in JWTOnly: {e}")
            raise HTTPException(status_code=503, detail="Database unavailable for auth check")

        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"success": False, "error": "NotMember", "message": "No active membership found"},
            )

        return {"user_id": user_id, "organization_id": row["organization_id"], "role": row["role_type"]}


require_jwt_only = JWTOnly()
