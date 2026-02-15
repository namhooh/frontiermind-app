"""
Meter Aggregate Loader for Billing Aggregate Ingestion Pipeline.

Handles batch insertion of canonical billing aggregates to the
meter_aggregate table using the backend's connection pool.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import execute_values, Json

from db.database import get_db_connection

logger = logging.getLogger(__name__)


class MeterAggregateLoader:
    """Loads billing aggregate data to meter_aggregate via the backend connection pool."""

    BATCH_SIZE = 1000

    COLUMNS = [
        'organization_id',
        'project_id',
        'meter_id',
        'billing_period_id',
        'clause_tariff_id',
        'period_type',
        'period_start',
        'period_end',
        'energy_wh',
        'energy_kwh',
        'total_production',
        'opening_reading',
        'closing_reading',
        'utilized_reading',
        'discount_reading',
        'sourced_energy',
        'source_system',
        'source_metadata',
        'aggregated_at',
    ]

    def load(
        self,
        records: List[Dict[str, Any]],
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """Load canonical billing aggregate records to meter_aggregate.

        Args:
            records: List of canonical billing aggregate dicts.

        Returns:
            Tuple of (rows_loaded, period_start, period_end)
        """
        if not records:
            return 0, None, None

        rows_loaded = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            rows_loaded += self._insert_batch(batch)

        # Compute date range from period_start values
        starts = [r['period_start'] for r in records if r.get('period_start')]
        ends = [r['period_end'] for r in records if r.get('period_end')]
        data_start = min(starts) if starts else None
        data_end = max(ends) if ends else None

        logger.info("Loaded %d billing aggregates to meter_aggregate", rows_loaded)
        return rows_loaded, data_start, data_end

    def _insert_batch(self, batch: List[Dict[str, Any]]) -> int:
        """Insert a batch of records using the connection pool."""
        if not batch:
            return 0

        values = []
        for record in batch:
            row = (
                record.get('organization_id'),
                record.get('project_id'),
                record.get('meter_id'),
                record.get('billing_period_id'),
                record.get('clause_tariff_id'),
                record.get('period_type', 'monthly'),
                record.get('period_start'),
                record.get('period_end'),
                self._to_decimal(record.get('energy_wh')),
                self._to_decimal(record.get('energy_kwh')),
                self._to_decimal(record.get('total_production')),
                self._to_decimal(record.get('opening_reading')),
                self._to_decimal(record.get('closing_reading')),
                self._to_decimal(record.get('utilized_reading')),
                self._to_decimal(record.get('discount_reading')),
                self._to_decimal(record.get('sourced_energy')),
                record.get('source_system'),
                Json(record.get('source_metadata')) if record.get('source_metadata') else None,
                record.get('aggregated_at'),
            )
            values.append(row)

        columns_str = ', '.join(self.COLUMNS)
        sql = f"""
            INSERT INTO meter_aggregate ({columns_str})
            VALUES %s
            ON CONFLICT DO NOTHING
        """

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=self.BATCH_SIZE)
                rows_affected = cur.rowcount

        logger.info("Inserted batch: %d rows into meter_aggregate", rows_affected)
        return rows_affected

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
