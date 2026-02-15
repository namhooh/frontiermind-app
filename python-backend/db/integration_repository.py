"""
Integration Repository for Data Ingestion.

Handles CRUD operations for:
- Integration credentials (API keys, OAuth tokens)
- Integration sites (external site to project mapping)
- Ingestion logs (audit trail)
"""

import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from cryptography.fernet import Fernet
from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class IntegrationRepository:
    """Repository for integration credential, site, and ingestion log operations."""

    def __init__(self):
        """Initialize repository with encryption key."""
        self._fernet = None
        encryption_key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
        if encryption_key:
            try:
                self._fernet = Fernet(encryption_key.encode())
            except Exception as e:
                logger.warning(f"Invalid encryption key, credentials will not be encrypted: {e}")

    # =====================================================
    # Encryption Helpers
    # =====================================================

    def _encrypt(self, value: str) -> Optional[bytes]:
        """Encrypt a value using Fernet and return bytes for BYTEA storage."""
        if not value:
            return None
        if not self._fernet:
            logger.warning("Encryption not configured, storing value as plaintext bytes")
            return value.encode("utf-8")
        return self._fernet.encrypt(value.encode("utf-8"))

    def _decrypt(self, value: Union[bytes, bytearray, memoryview, str]) -> Optional[str]:
        """Decrypt a BYTEA value using Fernet and return UTF-8 text."""
        if not value:
            return None

        if isinstance(value, memoryview):
            raw = value.tobytes()
        elif isinstance(value, bytearray):
            raw = bytes(value)
        elif isinstance(value, bytes):
            raw = value
        elif isinstance(value, str):
            raw = value.encode("utf-8")
        else:
            return str(value)

        if not self._fernet:
            return raw.decode("utf-8", errors="ignore")

        try:
            return self._fernet.decrypt(raw).decode("utf-8")
        except Exception:
            # Migration fallback: value may have been stored unencrypted.
            return raw.decode("utf-8", errors="ignore")

    def _build_credentials_json(
        self,
        auth_type: str,
        credentials: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> Optional[bytes]:
        """Build and encrypt a credentials JSON blob.

        Accepts either a pre-built credentials dict or individual fields.
        Returns the Fernet-encrypted string of the JSON.
        """
        if credentials:
            blob = credentials
        elif auth_type == "api_key" and api_key:
            blob = {"api_key": api_key}
        elif auth_type == "oauth2" and (access_token or refresh_token):
            blob = {}
            if access_token:
                blob["access_token"] = access_token
            if refresh_token:
                blob["refresh_token"] = refresh_token
            if scope:
                blob["scope"] = scope
        else:
            return None

        json_str = json.dumps(blob)
        return self._encrypt(json_str)

    def _unpack_credentials(
        self, encrypted_blob: Union[bytes, bytearray, memoryview, str]
    ) -> Dict[str, str]:
        """Decrypt and parse the encrypted_credentials BYTEA column."""
        decrypted = self._decrypt(encrypted_blob)
        if not decrypted:
            return {}
        try:
            return json.loads(decrypted)
        except (json.JSONDecodeError, TypeError):
            return {}

    # =====================================================
    # Credential Operations
    # =====================================================

    def create_credential(
        self,
        organization_id: int,
        data_source_id: int,
        auth_type: str,
        credentials: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        label: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new integration credential."""
        encrypted_creds = self._build_credentials_json(
            auth_type=auth_type,
            credentials=credentials,
            api_key=api_key,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not encrypted_creds:
            raise ValueError(
                "Missing or invalid credentials payload for auth_type "
                f"'{auth_type}'."
            )

        sql = """
            INSERT INTO integration_credential (
                organization_id, data_source_id, auth_type,
                encrypted_credentials, encryption_method,
                token_expires_at, label
            ) VALUES (%s, %s, %s, %s, 'fernet', %s, %s)
            RETURNING id, organization_id, data_source_id, auth_type, label,
                      is_active, last_used_at, last_error, error_count,
                      token_expires_at, created_at, updated_at
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, data_source_id, auth_type,
                    encrypted_creds,
                    token_expires_at, label
                ))
                result = cursor.fetchone()

        logger.info(f"Created integration credential {result['id']} for org {organization_id}")
        return dict(result)

    def get_credential(
        self,
        credential_id: int,
        organization_id: int,
        include_secrets: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get a credential by ID."""
        if include_secrets:
            sql = """
                SELECT id, organization_id, data_source_id, auth_type, label,
                       encrypted_credentials,
                       is_active, last_used_at, last_error, error_count,
                       token_expires_at, created_at, updated_at
                FROM integration_credential
                WHERE id = %s AND organization_id = %s
            """
        else:
            sql = """
                SELECT id, organization_id, data_source_id, auth_type, label,
                       is_active, last_used_at, last_error, error_count,
                       token_expires_at, created_at, updated_at
                FROM integration_credential
                WHERE id = %s AND organization_id = %s
            """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (credential_id, organization_id))
                result = cursor.fetchone()

        if not result:
            return None

        credential = dict(result)

        if include_secrets and credential.get('encrypted_credentials'):
            secrets = self._unpack_credentials(credential['encrypted_credentials'])
            credential.update(secrets)
            credential.pop('encrypted_credentials', None)

        return credential

    def list_credentials(
        self,
        organization_id: int,
        data_source_id: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """List credentials for an organization."""
        sql = """
            SELECT id, organization_id, data_source_id, auth_type, label,
                   is_active, last_used_at, last_error, error_count,
                   token_expires_at, created_at, updated_at
            FROM integration_credential
            WHERE organization_id = %s
        """
        params = [organization_id]

        if data_source_id is not None:
            sql += " AND data_source_id = %s"
            params.append(data_source_id)

        if is_active is not None:
            sql += " AND is_active = %s"
            params.append(is_active)

        sql += " ORDER BY created_at DESC"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                results = cursor.fetchall()

        return [dict(row) for row in results]

    def update_credential(
        self,
        credential_id: int,
        organization_id: int,
        label: Optional[str] = None,
        is_active: Optional[bool] = None,
        credentials: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Update a credential."""
        updates = []
        params = []

        if label is not None:
            updates.append("label = %s")
            params.append(label)

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        # Rebuild encrypted_credentials if any secret field is provided
        needs_cred_update = credentials or api_key or access_token or refresh_token
        if needs_cred_update:
            # Fetch existing credential to get auth_type and merge secrets
            existing = self.get_credential(credential_id, organization_id, include_secrets=True)
            if not existing:
                return None
            auth_type = existing.get("auth_type", "api_key")
            encrypted_creds = self._build_credentials_json(
                auth_type=auth_type,
                credentials=credentials,
                api_key=api_key,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            if encrypted_creds:
                updates.append("encrypted_credentials = %s")
                params.append(encrypted_creds)
            else:
                raise ValueError(
                    "Invalid credentials payload for credential update."
                )

        if token_expires_at is not None:
            updates.append("token_expires_at = %s")
            params.append(token_expires_at)

        if not updates:
            return self.get_credential(credential_id, organization_id)

        updates.append("updated_at = NOW()")

        sql = f"""
            UPDATE integration_credential
            SET {', '.join(updates)}
            WHERE id = %s AND organization_id = %s
            RETURNING id, organization_id, data_source_id, auth_type, label,
                      is_active, last_used_at, last_error, error_count,
                      token_expires_at, created_at, updated_at
        """
        params.extend([credential_id, organization_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                result = cursor.fetchone()

        if result:
            logger.info(f"Updated integration credential {credential_id}")
            return dict(result)
        return None

    def record_credential_usage(
        self,
        credential_id: int,
        organization_id: int,
        error: Optional[str] = None
    ) -> None:
        """Record credential usage (success or error)."""
        if error:
            sql = """
                UPDATE integration_credential
                SET last_used_at = NOW(),
                    last_error = %s,
                    error_count = error_count + 1,
                    updated_at = NOW()
                WHERE id = %s AND organization_id = %s
            """
            params = (error, credential_id, organization_id)
        else:
            sql = """
                UPDATE integration_credential
                SET last_used_at = NOW(),
                    last_error = NULL,
                    error_count = 0,
                    updated_at = NOW()
                WHERE id = %s AND organization_id = %s
            """
            params = (credential_id, organization_id)

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)

    def delete_credential(
        self,
        credential_id: int,
        organization_id: int
    ) -> bool:
        """Delete a credential (also deletes associated sites)."""
        sql = """
            DELETE FROM integration_credential
            WHERE id = %s AND organization_id = %s
            RETURNING id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (credential_id, organization_id))
                result = cursor.fetchone()

        if result:
            logger.info(f"Deleted integration credential {credential_id}")
            return True
        return False

    # =====================================================
    # Site Operations
    # =====================================================

    def create_site(
        self,
        organization_id: int,
        integration_credential_id: int,
        data_source_id: int,
        external_site_id: str,
        external_site_name: Optional[str] = None,
        project_id: Optional[int] = None,
        meter_id: Optional[int] = None,
        external_metadata: Optional[Dict[str, Any]] = None,
        sync_interval_minutes: int = 60
    ) -> Dict[str, Any]:
        """Create an integration site mapping."""
        sql = """
            INSERT INTO integration_site (
                organization_id, integration_credential_id, data_source_id,
                external_site_id, external_site_name,
                project_id, meter_id, external_metadata,
                sync_interval_minutes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, integration_credential_id, data_source_id,
                    external_site_id, external_site_name,
                    project_id, meter_id,
                    Json(external_metadata) if external_metadata else None,
                    sync_interval_minutes
                ))
                result = cursor.fetchone()

        logger.info(f"Created integration site {result['id']} for org {organization_id}")
        return dict(result)

    def get_site(
        self,
        site_id: int,
        organization_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get a site by ID."""
        sql = """
            SELECT * FROM integration_site
            WHERE id = %s AND organization_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (site_id, organization_id))
                result = cursor.fetchone()

        return dict(result) if result else None

    def list_sites(
        self,
        organization_id: int,
        integration_credential_id: Optional[int] = None,
        data_source_id: Optional[int] = None,
        project_id: Optional[int] = None,
        sync_enabled: Optional[bool] = None,
        is_active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """List sites for an organization with optional filters."""
        sql = "SELECT * FROM integration_site WHERE organization_id = %s"
        params = [organization_id]

        if integration_credential_id is not None:
            sql += " AND integration_credential_id = %s"
            params.append(integration_credential_id)

        if data_source_id is not None:
            sql += " AND data_source_id = %s"
            params.append(data_source_id)

        if project_id is not None:
            sql += " AND project_id = %s"
            params.append(project_id)

        if sync_enabled is not None:
            sql += " AND sync_enabled = %s"
            params.append(sync_enabled)

        if is_active is not None:
            sql += " AND is_active = %s"
            params.append(is_active)

        sql += " ORDER BY created_at DESC"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                results = cursor.fetchall()

        return [dict(row) for row in results]

    def update_site(
        self,
        site_id: int,
        organization_id: int,
        project_id: Optional[int] = None,
        meter_id: Optional[int] = None,
        external_site_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        sync_enabled: Optional[bool] = None,
        sync_interval_minutes: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Update a site."""
        updates = []
        params = []

        if project_id is not None:
            updates.append("project_id = %s")
            params.append(project_id)

        if meter_id is not None:
            updates.append("meter_id = %s")
            params.append(meter_id)

        if external_site_name is not None:
            updates.append("external_site_name = %s")
            params.append(external_site_name)

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        if sync_enabled is not None:
            updates.append("sync_enabled = %s")
            params.append(sync_enabled)

        if sync_interval_minutes is not None:
            updates.append("sync_interval_minutes = %s")
            params.append(sync_interval_minutes)

        if not updates:
            return self.get_site(site_id, organization_id)

        updates.append("updated_at = NOW()")

        sql = f"""
            UPDATE integration_site
            SET {', '.join(updates)}
            WHERE id = %s AND organization_id = %s
            RETURNING *
        """
        params.extend([site_id, organization_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                result = cursor.fetchone()

        if result:
            logger.info(f"Updated integration site {site_id}")
            return dict(result)
        return None

    def update_site_sync_status(
        self,
        site_id: int,
        organization_id: int,
        status: str,
        records_count: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Update site sync status after a sync attempt."""
        sql = """
            UPDATE integration_site
            SET last_sync_at = NOW(),
                last_sync_status = %s,
                last_sync_error = %s,
                last_sync_records_count = %s,
                updated_at = NOW()
            WHERE id = %s AND organization_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (status, error, records_count, site_id, organization_id))

    def get_sites_due_for_sync(
        self,
        organization_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get sites that are due for sync."""
        sql = """
            SELECT s.*, c.data_source_id as credential_data_source_id
            FROM integration_site s
            JOIN integration_credential c ON s.integration_credential_id = c.id
            WHERE s.is_active = true
              AND s.sync_enabled = true
              AND c.is_active = true
              AND (
                  s.last_sync_at IS NULL
                  OR s.last_sync_at < NOW() - (s.sync_interval_minutes || ' minutes')::INTERVAL
              )
        """
        params = []

        if organization_id:
            sql += " AND s.organization_id = %s"
            params.append(organization_id)

        sql += " ORDER BY s.last_sync_at NULLS FIRST"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                results = cursor.fetchall()

        return [dict(row) for row in results]

    def resolve_sites_batch(
        self,
        external_site_ids: List[str],
        organization_id: int,
        credential_id: Optional[int] = None,
    ) -> Dict[str, Dict[str, Optional[int]]]:
        """Resolve external_site_ids to project_id/meter_id via integration_site.

        Args:
            external_site_ids: List of external site identifiers to look up.
            organization_id: Organization scope.
            credential_id: Optional credential to narrow the lookup.

        Returns:
            Mapping of external_site_id -> {"project_id": ..., "meter_id": ...}
            for every active match found.
        """
        if not external_site_ids:
            return {}

        sql = """
            SELECT external_site_id, project_id, meter_id
            FROM integration_site
            WHERE organization_id = %s
              AND external_site_id = ANY(%s)
              AND is_active = true
        """
        params: list = [organization_id, list(external_site_ids)]

        if credential_id is not None:
            sql += " AND integration_credential_id = %s"
            params.append(credential_id)

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                results = cursor.fetchall()

        return {
            row["external_site_id"]: {
                "project_id": row["project_id"],
                "meter_id": row["meter_id"],
            }
            for row in results
        }

    def delete_site(
        self,
        site_id: int,
        organization_id: int
    ) -> bool:
        """Delete a site."""
        sql = """
            DELETE FROM integration_site
            WHERE id = %s AND organization_id = %s
            RETURNING id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (site_id, organization_id))
                result = cursor.fetchone()

        if result:
            logger.info(f"Deleted integration site {site_id}")
            return True
        return False

    # =====================================================
    # Ingestion Log Operations
    # =====================================================

    def start_ingestion_log(
        self,
        organization_id: int,
        data_source_id: int,
        file_path: str,
        file_size_bytes: Optional[int] = None,
        file_format: Optional[str] = None,
        file_hash: Optional[str] = None,
        integration_site_id: Optional[int] = None
    ) -> int:
        """Create an ingestion log entry when processing starts."""
        file_name = file_path.split('/')[-1] if '/' in file_path else file_path

        sql = """
            INSERT INTO ingestion_log (
                organization_id, integration_site_id, data_source_id,
                file_path, file_name, file_size_bytes, file_format, file_hash,
                ingestion_status, ingestion_stage
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'processing', 'validating')
            RETURNING id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, integration_site_id, data_source_id,
                    file_path, file_name, file_size_bytes, file_format, file_hash
                ))
                result = cursor.fetchone()

        log_id = result['id']
        logger.info(f"Started ingestion log {log_id} for {file_path}")
        return log_id

    def complete_ingestion_log(
        self,
        log_id: int,
        status: str,
        rows_loaded: Optional[int] = None,
        rows_valid: Optional[int] = None,
        rows_failed: Optional[int] = None,
        data_start_timestamp: Optional[datetime] = None,
        data_end_timestamp: Optional[datetime] = None,
        destination_path: Optional[str] = None,
        validation_errors: Optional[List[Dict]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Complete an ingestion log entry."""
        stage = 'complete' if status in ('success', 'skipped') else 'validating'

        sql = """
            UPDATE ingestion_log
            SET ingestion_status = %s,
                ingestion_stage = %s,
                rows_loaded = %s,
                rows_valid = %s,
                rows_failed = %s,
                data_start_timestamp = %s,
                data_end_timestamp = %s,
                destination_path = %s,
                validation_errors = %s,
                error_message = %s,
                processing_completed_at = NOW(),
                processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
            WHERE id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    status, stage,
                    rows_loaded, rows_valid, rows_failed,
                    data_start_timestamp, data_end_timestamp,
                    destination_path,
                    Json(validation_errors) if validation_errors else None,
                    error_message,
                    log_id
                ))

        logger.info(f"Completed ingestion log {log_id}: {status}")

    def is_duplicate_file(
        self,
        file_hash: str,
        organization_id: int
    ) -> bool:
        """Check if a file with the same hash was already successfully processed."""
        sql = """
            SELECT 1 FROM ingestion_log
            WHERE file_hash = %s
              AND organization_id = %s
              AND ingestion_status = 'success'
            LIMIT 1
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (file_hash, organization_id))
                return cursor.fetchone() is not None

    def get_ingestion_log_by_hash(
        self,
        file_hash: str,
        organization_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get an ingestion log entry by file hash."""
        sql = """
            SELECT * FROM ingestion_log
            WHERE file_hash = %s AND organization_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (file_hash, organization_id))
                result = cursor.fetchone()

        return dict(result) if result else None

    def get_ingestion_log(
        self,
        log_id: int,
        organization_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get an ingestion log entry."""
        sql = """
            SELECT * FROM ingestion_log
            WHERE id = %s AND organization_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (log_id, organization_id))
                result = cursor.fetchone()

        return dict(result) if result else None

    def list_ingestion_logs(
        self,
        organization_id: int,
        data_source_id: Optional[int] = None,
        status: Optional[str] = None,
        integration_site_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """List ingestion logs with pagination."""
        where_clauses = ["organization_id = %s"]
        params = [organization_id]

        if data_source_id is not None:
            where_clauses.append("data_source_id = %s")
            params.append(data_source_id)

        if status:
            where_clauses.append("ingestion_status = %s")
            params.append(status)

        if integration_site_id:
            where_clauses.append("integration_site_id = %s")
            params.append(integration_site_id)

        where_sql = " AND ".join(where_clauses)

        count_sql = f"SELECT COUNT(*) as count FROM ingestion_log WHERE {where_sql}"

        list_sql = f"""
            SELECT * FROM ingestion_log
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(count_sql, tuple(params))
                total = cursor.fetchone()['count']

                cursor.execute(list_sql, tuple(params) + (limit, offset))
                results = cursor.fetchall()

        return [dict(row) for row in results], total

    def get_ingestion_stats(
        self,
        organization_id: int,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get ingestion statistics by day."""
        sql = """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as files_processed,
                COUNT(*) FILTER (WHERE ingestion_status = 'success') as files_success,
                COUNT(*) FILTER (WHERE ingestion_status = 'quarantined') as files_quarantined,
                COALESCE(SUM(rows_loaded), 0) as rows_loaded,
                AVG(processing_time_ms) as avg_processing_ms
            FROM ingestion_log
            WHERE organization_id = %s
              AND created_at >= NOW() - (%s || ' days')::INTERVAL
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (organization_id, days))
                results = cursor.fetchall()

        return [dict(row) for row in results]

    # =====================================================
    # API Key Lookup (for API-first auth)
    # =====================================================

    def find_credential_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Find a credential by its plaintext API key.

        Iterates active api_key credentials and uses timing-safe comparison.
        """
        sql = """
            SELECT id, organization_id, data_source_id, auth_type,
                   encrypted_credentials, is_active,
                   created_at, updated_at
            FROM integration_credential
            WHERE auth_type = 'api_key'
              AND is_active = true
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                results = cursor.fetchall()

        for row in results:
            stored_blob = row.get('encrypted_credentials')
            if not stored_blob:
                continue

            secrets = self._unpack_credentials(stored_blob)
            stored_key = secrets.get('api_key')
            if not stored_key:
                continue

            if hmac.compare_digest(stored_key, api_key):
                credential = dict(row)
                credential.pop('encrypted_credentials', None)
                return credential

        return None
