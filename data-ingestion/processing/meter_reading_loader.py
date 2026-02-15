"""
Meter Reading Loader for API-First Ingestion Pipeline.

Handles batch insertion of canonical meter readings to PostgreSQL
using the backend's connection pool (not raw psycopg2.connect).
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import execute_values, Json

from db.database import get_db_connection

logger = logging.getLogger(__name__)


class MeterReadingLoader:
    """Loads meter data to PostgreSQL via the backend connection pool."""

    BATCH_SIZE = 1000

    COLUMNS = [
        'organization_id', 'project_id', 'meter_id', 'source_system',
        'external_site_id', 'external_device_id',
        'reading_timestamp', 'reading_interval',
        'energy_wh', 'power_w', 'irradiance_wm2', 'temperature_c',
        'other_metrics', 'quality', 'ingested_at'
    ]

    INTERVAL_MAP = {
        1: 'sec',
        60: 'min',
        900: '15min',
        3600: 'hourly',
        86400: 'daily',
    }

    def load(
        self,
        records: List[Dict],
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Load canonical records to meter_reading table.

        Args:
            records: List of canonical meter reading dicts.

        Returns:
            Tuple of (rows_loaded, data_start_timestamp, data_end_timestamp)
        """
        if not records:
            return 0, None, None

        rows_loaded = 0

        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            rows_loaded += self._insert_batch(batch)

        timestamps = [r['reading_timestamp'] for r in records if r.get('reading_timestamp')]
        data_start = min(timestamps) if timestamps else None
        data_end = max(timestamps) if timestamps else None

        logger.info(f"Loaded {rows_loaded} meter readings")
        return rows_loaded, data_start, data_end

    def _insert_batch(self, batch: List[Dict]) -> int:
        """Insert a batch of records using the connection pool."""
        if not batch:
            return 0

        values = []
        for record in batch:
            interval_seconds = record.get('reading_interval', 3600)
            if isinstance(interval_seconds, int):
                interval_enum = self._seconds_to_interval(interval_seconds)
            else:
                interval_enum = str(interval_seconds) if interval_seconds else '15min'

            row = (
                record.get('organization_id'),
                record.get('project_id'),
                record.get('meter_id'),
                record.get('source_system'),
                record.get('external_site_id'),
                record.get('external_device_id'),
                record.get('reading_timestamp'),
                interval_enum,
                self._to_decimal(record.get('energy_wh')),
                self._to_decimal(record.get('power_w')),
                self._to_decimal(record.get('irradiance_wm2')),
                self._to_decimal(record.get('temperature_c')),
                Json(record.get('other_metrics')) if record.get('other_metrics') else None,
                record.get('quality', 'measured'),
                record.get('ingested_at'),
            )
            values.append(row)

        columns_str = ', '.join(self.COLUMNS)
        sql = f"""
            INSERT INTO meter_reading ({columns_str})
            VALUES %s
            ON CONFLICT DO NOTHING
        """

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=self.BATCH_SIZE)
                rows_affected = cur.rowcount

        logger.info(f"Inserted batch: {rows_affected} rows")
        return rows_affected

    @staticmethod
    def _seconds_to_interval(seconds: int) -> str:
        """Map integer seconds to updated_frequency enum value."""
        mapped = MeterReadingLoader.INTERVAL_MAP.get(seconds)
        if mapped is None:
            logger.warning("Unmapped interval_seconds=%d, defaulting to '15min'", seconds)
            return '15min'
        return mapped

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        """Convert value to Decimal for database insertion."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return None
