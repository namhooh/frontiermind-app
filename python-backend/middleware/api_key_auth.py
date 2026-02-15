"""
API Key Authentication Middleware.

FastAPI dependency that extracts a Bearer token from the Authorization header,
validates it against the integration_credential table, and returns the
associated organization_id.

Used by the ingestion endpoints to authenticate API push clients (e.g. Snowflake).
"""

import hmac
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.integration_repository import IntegrationRepository

logger = logging.getLogger(__name__)

# HTTPBearer extracts "Bearer <token>" from the Authorization header
_bearer_scheme = HTTPBearer(auto_error=False)


class APIKeyAuth:
    """Validates API keys against the integration_credential table."""

    def __init__(self, repository: Optional[IntegrationRepository] = None):
        self.repository = repository

    def _get_repository(self) -> IntegrationRepository:
        if self.repository is None:
            self.repository = IntegrationRepository()
        return self.repository

    async def __call__(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    ) -> dict:
        """
        FastAPI dependency that authenticates an API key.

        Returns:
            dict with 'organization_id' and 'credential_id' on success.

        Raises:
            HTTPException 401 if missing or invalid.
        """
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header. Use: Authorization: Bearer <api_key>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        repo = self._get_repository()
        credential = repo.find_credential_by_api_key(token)

        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not credential.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key is disabled",
            )

        # Record usage
        repo.record_credential_usage(
            credential_id=credential["id"],
            organization_id=credential["organization_id"],
        )

        return {
            "organization_id": credential["organization_id"],
            "credential_id": credential["id"],
            "data_source_id": credential.get("data_source_id"),
        }


# Singleton instance for use as a FastAPI dependency
require_api_key = APIKeyAuth()
