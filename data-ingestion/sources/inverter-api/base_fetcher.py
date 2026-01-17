"""
Base Fetcher Class

Abstract base class for all inverter API fetchers.
Provides common functionality for credential management, S3 upload, and status tracking.
Supports both API key and OAuth 2.0 authentication.
"""

import base64
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
import requests
from cryptography.fernet import Fernet

from .config import Config

logger = logging.getLogger(__name__)


# OAuth provider configurations
OAUTH_PROVIDERS = {
    "enphase": {
        "token_url": "https://api.enphaseenergy.com/oauth/token",
        "auth_url": "https://api.enphaseenergy.com/oauth/authorize",
        "scopes": ["read"],
    },
    "sma": {
        "token_url": "https://auth.sma.de/oauth2/token",
        "auth_url": "https://auth.sma.de/oauth2/authorize",
        "scopes": ["monitoring.read"],
    },
}


class BaseFetcher(ABC):
    """Abstract base class for inverter API fetchers."""

    # Override in subclasses
    SOURCE_TYPE: str = ""

    def __init__(self, config: Optional[Config] = None, dry_run: bool = False):
        """
        Initialize fetcher.

        Args:
            config: Configuration object. If None, loads from AWS Secrets.
            dry_run: If True, don't upload to S3 or update database.
        """
        self.config = config or Config.from_aws_secrets()
        self.dry_run = dry_run
        self.s3_client = boto3.client("s3", region_name=self.config.aws_region)
        self._fernet: Optional[Fernet] = None

    @property
    def fernet(self) -> Fernet:
        """Get Fernet cipher for credential encryption/decryption."""
        if self._fernet is None:
            if not self.config.encryption_key:
                raise ValueError("Encryption key not configured")
            self._fernet = Fernet(self.config.encryption_key.encode())
        return self._fernet

    def decrypt_credentials(self, encrypted_data: bytes) -> Dict[str, Any]:
        """Decrypt credential data."""
        decrypted = self.fernet.decrypt(encrypted_data)
        return json.loads(decrypted.decode())

    def get_credentials(self) -> List[Dict[str, Any]]:
        """
        Fetch active credentials for this source type from Supabase.

        Returns:
            List of credential records with decrypted credentials.
        """
        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
        }

        # Fetch active credentials for this source type
        # Note: In production, filter by data_source_id instead of source_type
        response = requests.get(
            f"{self.config.supabase_url}/rest/v1/integration_credential",
            headers=headers,
            params={
                "is_active": "eq.true",
                "select": "*",
            },
        )
        response.raise_for_status()

        credentials = response.json()

        # Decrypt credentials
        for cred in credentials:
            if cred.get("encrypted_credentials"):
                try:
                    # Handle base64 encoded bytes from database
                    import base64
                    encrypted = base64.b64decode(cred["encrypted_credentials"])
                    cred["decrypted"] = self.decrypt_credentials(encrypted)
                except Exception as e:
                    logger.error(f"Failed to decrypt credential {cred['id']}: {e}")
                    cred["decrypted"] = None

        return credentials

    def get_sites_for_credential(self, credential_id: int) -> List[Dict[str, Any]]:
        """
        Fetch active sites for a credential.

        Args:
            credential_id: The credential ID.

        Returns:
            List of site records.
        """
        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
        }

        response = requests.get(
            f"{self.config.supabase_url}/rest/v1/integration_site",
            headers=headers,
            params={
                "integration_credential_id": f"eq.{credential_id}",
                "is_active": "eq.true",
                "sync_enabled": "eq.true",
                "select": "*",
            },
        )
        response.raise_for_status()

        return response.json()

    def upload_to_s3(
        self,
        data: Dict[str, Any],
        organization_id: int,
        site_id: str,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Upload data to S3 raw folder.

        Args:
            data: Data to upload as JSON.
            organization_id: Organization ID for path.
            site_id: External site ID for filename.
            timestamp: Timestamp for path. Defaults to now.

        Returns:
            S3 key of uploaded file.
        """
        timestamp = timestamp or datetime.now(timezone.utc)
        date_str = timestamp.strftime("%Y-%m-%d")
        time_str = timestamp.strftime("%H%M%S")

        s3_key = f"raw/{self.SOURCE_TYPE}/{organization_id}/{date_str}/site_{site_id}_{time_str}.json"

        if self.dry_run:
            logger.info(f"[DRY RUN] Would upload to s3://{self.config.s3_bucket}/{s3_key}")
            logger.debug(f"Data: {json.dumps(data, indent=2)}")
            return s3_key

        self.s3_client.put_object(
            Bucket=self.config.s3_bucket,
            Key=s3_key,
            Body=json.dumps(data, default=str),
            ContentType="application/json",
            Metadata={
                "organization-id": str(organization_id),
                "source-type": self.SOURCE_TYPE,
                "site-id": site_id,
            },
        )

        logger.info(f"Uploaded to s3://{self.config.s3_bucket}/{s3_key}")
        return s3_key

    def update_site_sync_status(
        self,
        site_id: int,
        status: str,
        error: Optional[str] = None,
        records_count: Optional[int] = None,
    ) -> None:
        """
        Update sync status for a site.

        Args:
            site_id: Internal site ID.
            status: Status string ('success', 'error', 'partial').
            error: Error message if failed.
            records_count: Number of records fetched.
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would update site {site_id} status to {status}")
            return

        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
            "Content-Type": "application/json",
        }

        # Call the database function
        response = requests.post(
            f"{self.config.supabase_url}/rest/v1/rpc/update_site_sync_status",
            headers=headers,
            json={
                "p_site_id": site_id,
                "p_status": status,
                "p_error": error,
                "p_records_count": records_count,
            },
        )

        if response.status_code != 200:
            logger.warning(f"Failed to update sync status: {response.text}")

    def record_credential_success(self, credential_id: int) -> None:
        """Record successful use of credential."""
        if self.dry_run:
            return

        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
        }

        requests.post(
            f"{self.config.supabase_url}/rest/v1/rpc/integration_credential_record_success",
            headers=headers,
            json={"p_credential_id": credential_id},
        )

    def record_credential_error(self, credential_id: int, error_message: str) -> None:
        """Record error when using credential."""
        if self.dry_run:
            return

        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
        }

        requests.post(
            f"{self.config.supabase_url}/rest/v1/rpc/integration_credential_record_error",
            headers=headers,
            json={
                "p_credential_id": credential_id,
                "p_error_message": error_message,
            },
        )

    # -------------------------------------------------------------------------
    # OAuth Token Management
    # -------------------------------------------------------------------------

    def is_oauth_credential(self, credential: Dict[str, Any]) -> bool:
        """Check if credential uses OAuth 2.0 authentication."""
        decrypted = credential.get("decrypted", {})
        return decrypted and "access_token" in decrypted and "refresh_token" in decrypted

    def needs_token_refresh(
        self,
        credential: Dict[str, Any],
        buffer_minutes: int = 5,
    ) -> bool:
        """
        Check if OAuth token needs refresh.

        Args:
            credential: Credential record with token_expires_at field.
            buffer_minutes: Refresh if token expires within this many minutes.

        Returns:
            True if token needs refresh, False otherwise.
        """
        if not self.is_oauth_credential(credential):
            return False

        expires_at = credential.get("token_expires_at")
        if not expires_at:
            # No expiry set, assume needs refresh
            return True

        # Parse expiry timestamp
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"Invalid token_expires_at format: {expires_at}")
                return True

        # Check if token expires within buffer window
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=buffer_minutes)

        return expires_at <= (now + buffer)

    def refresh_oauth_token(
        self,
        credential: Dict[str, Any],
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> Dict[str, Any]:
        """
        Refresh expired OAuth token.

        Args:
            credential: Credential record with decrypted tokens.
            provider: OAuth provider name (e.g., 'enphase', 'sma').
            client_id: OAuth client ID.
            client_secret: OAuth client secret.

        Returns:
            Updated credential with new tokens.

        Raises:
            ValueError: If provider not configured or refresh fails.
        """
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown OAuth provider: {provider}")

        provider_config = OAUTH_PROVIDERS[provider]
        decrypted = credential.get("decrypted", {})
        refresh_token = decrypted.get("refresh_token")

        if not refresh_token:
            raise ValueError(f"No refresh token available for credential {credential['id']}")

        logger.info(f"Refreshing OAuth token for credential {credential['id']} ({provider})")

        # Request new tokens
        token_response = requests.post(
            provider_config["token_url"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        if token_response.status_code != 200:
            error_msg = f"Token refresh failed: {token_response.status_code} - {token_response.text}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        token_data = token_response.json()

        # Update decrypted credentials
        new_decrypted = {
            **decrypted,
            "access_token": token_data["access_token"],
        }

        # Update refresh token if provided (some providers rotate refresh tokens)
        if "refresh_token" in token_data:
            new_decrypted["refresh_token"] = token_data["refresh_token"]

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Update database
        if not self.dry_run:
            self._update_credential_tokens(
                credential_id=credential["id"],
                decrypted_credentials=new_decrypted,
                expires_at=new_expires_at,
            )

        # Update local credential dict
        credential["decrypted"] = new_decrypted
        credential["token_expires_at"] = new_expires_at.isoformat()
        credential["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()

        logger.info(f"Token refreshed successfully for credential {credential['id']}")

        return credential

    def _update_credential_tokens(
        self,
        credential_id: int,
        decrypted_credentials: Dict[str, Any],
        expires_at: datetime,
    ) -> None:
        """
        Update credential tokens in database.

        Args:
            credential_id: Credential ID to update.
            decrypted_credentials: New decrypted credentials.
            expires_at: New token expiry timestamp.
        """
        # Encrypt the new credentials
        encrypted = self.fernet.encrypt(json.dumps(decrypted_credentials).encode())
        encrypted_b64 = base64.b64encode(encrypted).decode()

        headers = {
            "apikey": self.config.supabase_service_key,
            "Authorization": f"Bearer {self.config.supabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

        response = requests.patch(
            f"{self.config.supabase_url}/rest/v1/integration_credential",
            headers=headers,
            params={"id": f"eq.{credential_id}"},
            json={
                "encrypted_credentials": encrypted_b64,
                "token_expires_at": expires_at.isoformat(),
                "token_refreshed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        if response.status_code not in (200, 204):
            logger.error(f"Failed to update credential tokens: {response.status_code} - {response.text}")
            raise ValueError(f"Failed to update credential tokens: {response.text}")

    def get_credentials_with_refresh(
        self,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> List[Dict[str, Any]]:
        """
        Get credentials, refreshing OAuth tokens if needed.

        Args:
            provider: OAuth provider name for token refresh.
            client_id: OAuth client ID.
            client_secret: OAuth client secret.

        Returns:
            List of credential records with valid tokens.
        """
        credentials = self.get_credentials()
        valid_credentials = []

        for cred in credentials:
            if not cred.get("decrypted"):
                logger.warning(f"Skipping credential {cred['id']} - decryption failed")
                continue

            try:
                # Check if OAuth token refresh is needed
                if self.is_oauth_credential(cred) and self.needs_token_refresh(cred):
                    cred = self.refresh_oauth_token(
                        credential=cred,
                        provider=provider,
                        client_id=client_id,
                        client_secret=client_secret,
                    )

                valid_credentials.append(cred)

            except Exception as e:
                logger.error(f"Failed to refresh token for credential {cred['id']}: {e}")
                self.record_credential_error(cred["id"], f"Token refresh failed: {e}")
                # Continue to next credential instead of failing

        return valid_credentials

    def get_access_token(self, credential: Dict[str, Any]) -> str:
        """
        Get access token from credential.

        Works for both API key and OAuth credentials.

        Args:
            credential: Credential record with decrypted data.

        Returns:
            API key or OAuth access token.
        """
        decrypted = credential.get("decrypted", {})

        # OAuth credential
        if "access_token" in decrypted:
            return decrypted["access_token"]

        # API key credential
        if "api_key" in decrypted:
            return decrypted["api_key"]

        raise ValueError(f"No access token or API key found in credential {credential.get('id')}")

    @abstractmethod
    def fetch_site_data(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch data for a single site from the manufacturer API.

        Args:
            api_key: API key or access token.
            site_id: External site ID.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Data in canonical format ready for S3 upload.
        """
        pass

    @abstractmethod
    def fetch_sites_list(self, api_key: str) -> List[Dict[str, Any]]:
        """
        Fetch list of sites available for this API key.

        Args:
            api_key: API key or access token.

        Returns:
            List of site info dictionaries.
        """
        pass

    def run(self, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Run the fetcher for all active credentials and sites.

        Args:
            lookback_hours: Hours to look back for data. Defaults to config value.

        Returns:
            Summary of fetch results.
        """
        lookback_hours = lookback_hours or self.config.default_lookback_hours
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=lookback_hours)

        results = {
            "source_type": self.SOURCE_TYPE,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "credentials_processed": 0,
            "sites_processed": 0,
            "files_uploaded": 0,
            "errors": [],
        }

        try:
            credentials = self.get_credentials()
        except Exception as e:
            logger.error(f"Failed to fetch credentials: {e}")
            results["errors"].append(f"Failed to fetch credentials: {e}")
            return results

        for cred in credentials:
            if not cred.get("decrypted"):
                continue

            results["credentials_processed"] += 1
            api_key = cred["decrypted"].get("api_key")

            if not api_key:
                logger.warning(f"No API key found for credential {cred['id']}")
                continue

            try:
                sites = self.get_sites_for_credential(cred["id"])

                for site in sites:
                    try:
                        results["sites_processed"] += 1
                        external_site_id = site["external_site_id"]

                        # Fetch data from manufacturer API
                        data = self.fetch_site_data(
                            api_key=api_key,
                            site_id=external_site_id,
                            start_time=start_time,
                            end_time=end_time,
                        )

                        # Upload to S3
                        self.upload_to_s3(
                            data=data,
                            organization_id=site["organization_id"],
                            site_id=external_site_id,
                        )
                        results["files_uploaded"] += 1

                        # Update sync status
                        records_count = len(data.get("readings", []))
                        self.update_site_sync_status(
                            site_id=site["id"],
                            status="success",
                            records_count=records_count,
                        )

                    except Exception as e:
                        error_msg = f"Error fetching site {site.get('external_site_id')}: {e}"
                        logger.error(error_msg)
                        results["errors"].append(error_msg)
                        self.update_site_sync_status(
                            site_id=site["id"],
                            status="error",
                            error=str(e),
                        )

                self.record_credential_success(cred["id"])

            except Exception as e:
                error_msg = f"Error with credential {cred['id']}: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
                self.record_credential_error(cred["id"], str(e))

        logger.info(
            f"Fetch complete: {results['files_uploaded']} files uploaded, "
            f"{len(results['errors'])} errors"
        )

        return results
