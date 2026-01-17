"""
Database Loader for Meter Data

Handles batch insertion of canonical meter readings to Supabase PostgreSQL.
Also manages ingestion_log table for audit trail.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values, Json

logger = logging.getLogger(__name__)


class Loader:
    """Loads meter data to Supabase PostgreSQL."""

    BATCH_SIZE = 1000  # Insert in batches

    def __init__(self, database_url: str):
        """
        Initialize loader with database connection.

        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url
        self._conn = None

    @property
    def conn(self):
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        return self._conn

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def load_meter_readings(
        self,
        records: List[Dict]
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Load canonical records to meter_reading table.

        Args:
            records: List of canonical meter reading records

        Returns:
            Tuple of (rows_loaded, data_start_timestamp, data_end_timestamp)
        """
        if not records:
            return 0, None, None

        rows_loaded = 0
        data_start = None
        data_end = None

        # Process in batches
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            loaded = self._insert_batch(batch)
            rows_loaded += loaded

        # Calculate data range
        timestamps = [r['reading_timestamp'] for r in records if r.get('reading_timestamp')]
        if timestamps:
            data_start = min(timestamps)
            data_end = max(timestamps)

        return rows_loaded, data_start, data_end

    def _insert_batch(self, batch: List[Dict]) -> int:
        """Insert a batch of records."""
        if not batch:
            return 0

        columns = [
            'organization_id', 'project_id', 'meter_id', 'source_system',
            'external_site_id', 'external_device_id',
            'reading_timestamp', 'reading_interval_seconds',
            'energy_wh', 'power_w', 'irradiance_wm2', 'temperature_c',
            'other_metrics', 'quality', 'ingested_at'
        ]

        # Prepare values
        values = []
        for record in batch:
            row = (
                record.get('organization_id'),
                record.get('project_id'),
                record.get('meter_id'),
                record.get('source_system'),
                record.get('external_site_id'),
                record.get('external_device_id'),
                record.get('reading_timestamp'),
                record.get('reading_interval_seconds', 3600),
                self._to_decimal(record.get('energy_wh')),
                self._to_decimal(record.get('power_w')),
                self._to_decimal(record.get('irradiance_wm2')),
                self._to_decimal(record.get('temperature_c')),
                Json(record.get('other_metrics')) if record.get('other_metrics') else None,
                record.get('quality', 'measured'),
                record.get('ingested_at', datetime.now(timezone.utc)),
            )
            values.append(row)

        # Build INSERT statement
        columns_str = ', '.join(columns)
        sql = f"""
            INSERT INTO meter_reading ({columns_str})
            VALUES %s
            ON CONFLICT DO NOTHING
        """

        try:
            with self.conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=self.BATCH_SIZE)
                rows_affected = cur.rowcount
            self.conn.commit()
            logger.info(f"Inserted {rows_affected} rows")
            return rows_affected
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert batch: {e}")
            raise

    def _to_decimal(self, value: Any) -> Optional[Decimal]:
        """Convert value to Decimal for database insertion."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except:
            return None

    def is_duplicate_file(self, file_hash: str, organization_id: int) -> bool:
        """
        Check if file with same hash was already processed.

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

        with self.conn.cursor() as cur:
            cur.execute(sql, (file_hash, organization_id))
            return cur.fetchone() is not None

    def start_ingestion_log(
        self,
        organization_id: int,
        source_type: str,
        file_path: str,
        file_size: Optional[int] = None,
        file_format: Optional[str] = None,
        file_hash: Optional[str] = None,
        site_id: Optional[int] = None
    ) -> int:
        """
        Create ingestion log entry.

        Returns:
            Log entry ID
        """
        sql = """
            INSERT INTO ingestion_log (
                organization_id, integration_site_id, source_type,
                file_path, file_name, file_size_bytes, file_format, file_hash,
                status, stage
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'processing', 'validating')
            RETURNING id
        """

        # Extract filename from path
        filename = file_path.split('/')[-1]

        with self.conn.cursor() as cur:
            cur.execute(sql, (
                organization_id, site_id, source_type,
                file_path, filename, file_size, file_format, file_hash
            ))
            log_id = cur.fetchone()[0]
        self.conn.commit()

        logger.info(f"Started ingestion log: {log_id}")
        return log_id

    def complete_ingestion_log_success(
        self,
        log_id: int,
        rows_loaded: int,
        data_start: Optional[datetime] = None,
        data_end: Optional[datetime] = None,
        destination_path: Optional[str] = None
    ) -> None:
        """Mark ingestion as successful."""
        sql = """
            UPDATE ingestion_log
            SET status = 'success',
                stage = 'complete',
                rows_loaded = %s,
                rows_valid = %s,
                data_start_timestamp = %s,
                data_end_timestamp = %s,
                destination_path = %s,
                processing_completed_at = NOW(),
                processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
            WHERE id = %s
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, (
                rows_loaded, rows_loaded,
                data_start, data_end,
                destination_path,
                log_id
            ))
        self.conn.commit()

        logger.info(f"Completed ingestion log {log_id}: success, {rows_loaded} rows")

    def complete_ingestion_log_quarantine(
        self,
        log_id: int,
        validation_errors: List[Dict],
        error_message: Optional[str] = None,
        destination_path: Optional[str] = None
    ) -> None:
        """Mark ingestion as quarantined due to validation failure."""
        sql = """
            UPDATE ingestion_log
            SET status = 'quarantined',
                stage = 'validating',
                validation_errors = %s,
                error_message = %s,
                destination_path = %s,
                processing_completed_at = NOW(),
                processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
            WHERE id = %s
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, (
                Json(validation_errors),
                error_message,
                destination_path,
                log_id
            ))
        self.conn.commit()

        logger.info(f"Completed ingestion log {log_id}: quarantined")

    def complete_ingestion_log_skipped(
        self,
        log_id: int,
        reason: str
    ) -> None:
        """Mark ingestion as skipped (e.g., duplicate)."""
        sql = """
            UPDATE ingestion_log
            SET status = 'skipped',
                stage = 'complete',
                error_message = %s,
                processing_completed_at = NOW(),
                processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
            WHERE id = %s
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, (reason, log_id))
        self.conn.commit()

        logger.info(f"Completed ingestion log {log_id}: skipped - {reason}")

    def complete_ingestion_log_error(
        self,
        log_id: int,
        error_message: str,
        destination_path: Optional[str] = None
    ) -> None:
        """Mark ingestion as failed with error."""
        sql = """
            UPDATE ingestion_log
            SET status = 'error',
                error_message = %s,
                destination_path = %s,
                processing_completed_at = NOW(),
                processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
            WHERE id = %s
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, (error_message, destination_path, log_id))
        self.conn.commit()

        logger.info(f"Completed ingestion log {log_id}: error - {error_message}")
