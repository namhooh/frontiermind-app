"""
OAuth API Endpoints

Provides endpoints for OAuth flow support, including state generation
for CSRF protection.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from middleware.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/oauth",
    tags=["oauth"],
    responses={
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"},
    },
)


class StateRequest(BaseModel):
    """Request body for generating OAuth state."""

    organization_id: int = Field(..., description="Organization ID to embed in state")


class StateResponse(BaseModel):
    """Response containing the generated OAuth state."""

    state: str = Field(..., description="URL-safe base64-encoded HMAC-signed state")


@router.post("/state", response_model=StateResponse)
@limiter.limit("30/minute")
async def generate_oauth_state(request: Request, body: StateRequest) -> StateResponse:
    """
    Generate HMAC-signed OAuth state for frontend CSRF protection.

    The state parameter is used in OAuth flows to prevent CSRF attacks.
    This endpoint generates a signed state that includes:
    - Organization ID
    - Timestamp (for expiry validation)
    - HMAC signature (for integrity verification)

    The state is valid for 10 minutes and must be validated by the
    OAuth callback endpoint.

    Args:
        body: Request containing the organization_id

    Returns:
        StateResponse with URL-safe base64-encoded signed state
    """
    secret = os.getenv("OAUTH_STATE_SECRET")
    if not secret:
        logger.error("OAUTH_STATE_SECRET not configured")
        raise HTTPException(
            status_code=500,
            detail="OAuth state generation not configured",
        )

    # Create payload with timestamp for expiry
    payload = {
        "organization_id": body.organization_id,
        "ts": int(time.time() * 1000),  # Milliseconds for JS compatibility
    }
    data = json.dumps(payload, separators=(",", ":"))

    # Generate HMAC-SHA256 signature
    sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).digest()
    sig_b64 = base64.b64encode(sig).decode()

    # Combine data and signature
    state_obj = {"data": data, "sig": sig_b64}
    state_json = json.dumps(state_obj, separators=(",", ":"))

    # Base64 encode and make URL-safe
    state = base64.b64encode(state_json.encode()).decode()
    state = state.replace("+", "-").replace("/", "_").rstrip("=")

    logger.info(f"Generated OAuth state for organization {body.organization_id}")

    return StateResponse(state=state)
