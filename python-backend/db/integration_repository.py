"""
Integration Repository for Data Ingestion.

Handles CRUD operations for:
- Integration credentials (API keys, OAuth tokens)
- Integration sites (external site to project mapping)
- Ingestion logs (audit trail)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    # Credential Operations
    # =====================================================

    def create_credential(
        self,
        organization_id: int,
        source_type: str,
        auth_type: str,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new integration credential.

        Args:
            organization_id: Organization ID
            source_type: Source type (solaredge, enphase, etc.)
            auth_type: Authentication type (api_key, oauth2)
            api_key: API key for API key auth
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            token_expires_at: Token expiration time
            label: Optional label for this credential

        Returns:
            Created credential (without sensitive data)
        """
        # Encrypt sensitive data
        encrypted_api_key = self._encrypt(api_key) if api_key else None
        encrypted_access_token = self._encrypt(access_token) if access_token else None
        encrypted_refresh_token = self._encrypt(refresh_token) if refresh_token else None

        sql = """
            INSERT INTO integration_credential (
                organization_id, source_type, auth_type,
                api_key_encrypted, access_token_encrypted, refresh_token_encrypted,
                token_expires_at, label
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, organization_id, source_type, auth_type, label,
                      is_active, last_used_at, last_error, error_count,
                      token_expires_at, created_at, updated_at
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, source_type, auth_type,
                    encrypted_api_key, encrypted_access_token, encrypted_refresh_token,
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
        """
        Get a credential by ID.

        Args:
            credential_id: Credential ID
            organization_id: Organization ID (for RLS)
            include_secrets: If True, decrypt and include sensitive data

        Returns:
            Credential dict or None if not found
        """
        if include_secrets:
            sql = """
                SELECT id, organization_id, source_type, auth_type, label,
                       api_key_encrypted, access_token_encrypted, refresh_token_encrypted,
                       is_active, last_used_at, last_error, error_count,
                       token_expires_at, created_at, updated_at
                FROM integration_credential
                WHERE id = %s AND organization_id = %s
            """
        else:
            sql = """
                SELECT id, organization_id, source_type, auth_type, label,
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

        # Decrypt secrets if requested
        if include_secrets:
            if credential.get('api_key_encrypted'):
                credential['api_key'] = self._decrypt(credential['api_key_encrypted'])
            if credential.get('access_token_encrypted'):
                credential['access_token'] = self._decrypt(credential['access_token_encrypted'])
            if credential.get('refresh_token_encrypted'):
                credential['refresh_token'] = self._decrypt(credential['refresh_token_encrypted'])

            # Remove encrypted fields from response
            credential.pop('api_key_encrypted', None)
            credential.pop('access_token_encrypted', None)
            credential.pop('refresh_token_encrypted', None)

        return credential

    def list_credentials(
        self,
        organization_id: int,
        source_type: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        List credentials for an organization.

        Args:
            organization_id: Organization ID
            source_type: Optional filter by source type
            is_active: Optional filter by active status

        Returns:
            List of credentials (without sensitive data)
        """
        sql = """
            SELECT id, organization_id, source_type, auth_type, label,
                   is_active, last_used_at, last_error, error_count,
                   token_expires_at, created_at, updated_at
            FROM integration_credential
            WHERE organization_id = %s
        """
        params = [organization_id]

        if source_type:
            sql += " AND source_type = %s"
            params.append(source_type)

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
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update a credential.

        Args:
            credential_id: Credential ID
            organization_id: Organization ID (for RLS)
            label: New label
            is_active: New active status
            api_key: New API key
            access_token: New access token
            refresh_token: New refresh token
            token_expires_at: New token expiration

        Returns:
            Updated credential or None if not found
        """
        updates = []
        params = []

        if label is not None:
            updates.append("label = %s")
            params.append(label)

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        if api_key is not None:
            updates.append("api_key_encrypted = %s")
            params.append(self._encrypt(api_key))

        if access_token is not None:
            updates.append("access_token_encrypted = %s")
            params.append(self._encrypt(access_token))

        if refresh_token is not None:
            updates.append("refresh_token_encrypted = %s")
            params.append(self._encrypt(refresh_token))

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
            RETURNING id, organization_id, source_type, auth_type, label,
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
        """
        Record credential usage (success or error).

        Args:
            credential_id: Credential ID
            organization_id: Organization ID
            error: Error message if failed
        """
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
        """
        Delete a credential (also deletes associated sites).

        Args:
            credential_id: Credential ID
            organization_id: Organization ID

        Returns:
            True if deleted, False if not found
        """
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
        credential_id: int,
        source_type: str,
        external_site_id: str,
        external_site_name: Optional[str] = None,
        project_id: Optional[int] = None,
        meter_id: Optional[int] = None,
        external_metadata: Optional[Dict[str, Any]] = None,
        sync_interval_minutes: int = 60
    ) -> Dict[str, Any]:
        """
        Create an integration site mapping.

        Args:
            organization_id: Organization ID
            credential_id: Credential ID to use for this site
            source_type: Source type
            external_site_id: External system's site ID
            external_site_name: External system's site name
            project_id: Internal project ID mapping
            meter_id: Internal meter ID mapping
            external_metadata: Additional metadata from external system
            sync_interval_minutes: How often to sync (default 60)

        Returns:
            Created site
        """
        sql = """
            INSERT INTO integration_site (
                organization_id, credential_id, source_type,
                external_site_id, external_site_name,
                project_id, meter_id, external_metadata,
                sync_interval_minutes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, credential_id, source_type,
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
        credential_id: Optional[int] = None,
        source_type: Optional[str] = None,
        project_id: Optional[int] = None,
        sync_enabled: Optional[bool] = None,
        is_active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        List sites for an organization with optional filters.

        Args:
            organization_id: Organization ID
            credential_id: Optional filter by credential
            source_type: Optional filter by source type
            project_id: Optional filter by project
            sync_enabled: Optional filter by sync enabled
            is_active: Optional filter by active status

        Returns:
            List of sites
        """
        sql = "SELECT * FROM integration_site WHERE organization_id = %s"
        params = [organization_id]

        if credential_id is not None:
            sql += " AND credential_id = %s"
            params.append(credential_id)

        if source_type:
            sql += " AND source_type = %s"
            params.append(source_type)

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
        """
        Update site sync status after a sync attempt.

        Args:
            site_id: Site ID
            organization_id: Organization ID
            status: Sync status (success, error, partial)
            records_count: Number of records synced
            error: Error message if failed
        """
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
        """
        Get sites that are due for sync.

        Args:
            organization_id: Optional filter by organization

        Returns:
            List of sites due for sync
        """
        sql = """
            SELECT s.*, c.source_type as credential_source_type
            FROM integration_site s
            JOIN integration_credential c ON s.credential_id = c.id
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
        source_type: str,
        file_path: str,
        file_size_bytes: Optional[int] = None,
        file_format: Optional[str] = None,
        file_hash: Optional[str] = None,
        integration_site_id: Optional[int] = None
    ) -> int:
        """
        Create an ingestion log entry when processing starts.

        Args:
            organization_id: Organization ID
            source_type: Source type
            file_path: S3 file path
            file_size_bytes: File size
            file_format: File format (json, csv, parquet)
            file_hash: SHA256 hash for deduplication
            integration_site_id: Associated integration site

        Returns:
            Log entry ID
        """
        # Extract filename from path
        file_name = file_path.split('/')[-1] if '/' in file_path else file_path

        sql = """
            INSERT INTO ingestion_log (
                organization_id, integration_site_id, source_type,
                file_path, file_name, file_size_bytes, file_format, file_hash,
                status, stage
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'processing', 'validating')
            RETURNING id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    organization_id, integration_site_id, source_type,
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
        rows_invalid: Optional[int] = None,
        data_start_timestamp: Optional[datetime] = None,
        data_end_timestamp: Optional[datetime] = None,
        destination_path: Optional[str] = None,
        validation_errors: Optional[List[Dict]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Complete an ingestion log entry.

        Args:
            log_id: Log entry ID
            status: Final status (success, quarantined, skipped, error)
            rows_loaded: Number of rows successfully loaded
            rows_valid: Number of valid rows
            rows_invalid: Number of invalid rows
            data_start_timestamp: Earliest timestamp in data
            data_end_timestamp: Latest timestamp in data
            destination_path: Final S3 destination path
            validation_errors: List of validation errors
            error_message: Error message if failed
        """
        stage = 'complete' if status in ('success', 'skipped') else 'validating'

        sql = """
            UPDATE ingestion_log
            SET status = %s,
                stage = %s,
                rows_loaded = %s,
                rows_valid = %s,
                rows_invalid = %s,
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
                    rows_loaded, rows_valid, rows_invalid,
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
        """
        Check if a file with the same hash was already successfully processed.

        Args:
            file_hash: SHA256 hash of file
            organization_id: Organization ID

        Returns:
            True if duplicate found
        """
        sql = """
            SELECT 1 FROM ingestion_log
            WHERE file_hash = %s
              AND organization_id = %s
              AND status = 'success'
            LIMIT 1
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (file_hash, organization_id))
                return cursor.fetchone() is not None

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
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        integration_site_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        List ingestion logs with pagination.

        Args:
            organization_id: Organization ID
            source_type: Optional filter by source type
            status: Optional filter by status
            integration_site_id: Optional filter by site
            limit: Max results per page
            offset: Offset for pagination

        Returns:
            Tuple of (logs list, total count)
        """
        # Build WHERE clause
        where_clauses = ["organization_id = %s"]
        params = [organization_id]

        if source_type:
            where_clauses.append("source_type = %s")
            params.append(source_type)

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        if integration_site_id:
            where_clauses.append("integration_site_id = %s")
            params.append(integration_site_id)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        count_sql = f"SELECT COUNT(*) as count FROM ingestion_log WHERE {where_sql}"

        # Get paginated results
        list_sql = f"""
            SELECT * FROM ingestion_log
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get count
                cursor.execute(count_sql, tuple(params))
                total = cursor.fetchone()['count']

                # Get logs
                cursor.execute(list_sql, tuple(params) + (limit, offset))
                results = cursor.fetchall()

        return [dict(row) for row in results], total

    def get_ingestion_stats(
        self,
        organization_id: int,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get ingestion statistics by day.

        Args:
            organization_id: Organization ID
            days: Number of days to look back

        Returns:
            List of daily stats
        """
        sql = """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as files_processed,
                COUNT(*) FILTER (WHERE status = 'success') as files_success,
                COUNT(*) FILTER (WHERE status = 'quarantined') as files_quarantined,
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
    # Encryption Helpers
    # =====================================================

    def _encrypt(self, value: str) -> Optional[str]:
        """Encrypt a value using Fernet."""
        if not value:
            return None
        if not self._fernet:
            logger.warning("Encryption not configured, storing value unencrypted")
            return value
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> Optional[str]:
        """Decrypt a value using Fernet."""
        if not value:
            return None
        if not self._fernet:
            # Value might be stored unencrypted
            return value
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except Exception:
            # Value might be stored unencrypted (migration period)
            return value
