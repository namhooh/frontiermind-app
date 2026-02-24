"""
Meter Aggregate Loader for Billing Aggregate Ingestion Pipeline.

Handles batch insertion of canonical billing aggregates to the
meter_aggregate table using the backend's connection pool.

Strategy:
  - Resolved rows (all required FKs present): INSERT ... ON CONFLICT DO UPDATE
  - Unresolved rows (missing FKs): logged with diagnostics and dropped
    The clean dedup index (idx_meter_aggregate_billing_dedup) excludes rows
    with NULL FKs, so only fully-resolved rows participate in billing.
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
        'meter_id',
        'billing_period_id',
        'clause_tariff_id',
        'contract_line_id',
        'period_type',
        'period_start',
        'period_end',
        'energy_wh',
        'energy_kwh',
        'total_production',
        'available_energy_kwh',
        'opening_reading',
        'closing_reading',
        'utilized_reading',
        'discount_reading',
        'sourced_energy',
        'ghi_irradiance_wm2',
        'poa_irradiance_wm2',
        'source_system',
        'source_metadata',
        'aggregated_at',
    ]

    # Columns to update on conflict (upsert)
    UPSERT_COLUMNS = [
        'energy_wh',
        'energy_kwh',
        'total_production',
        'available_energy_kwh',
        'opening_reading',
        'closing_reading',
        'utilized_reading',
        'discount_reading',
        'sourced_energy',
        'ghi_irradiance_wm2',
        'poa_irradiance_wm2',
        'source_system',
        'source_metadata',
        'aggregated_at',
    ]

    # Required FK fields — rows missing any of these are dropped with a warning
    REQUIRED_FKS = {'meter_id', 'billing_period_id', 'contract_line_id'}

    def load(
        self,
        records: List[Dict[str, Any]],
    ) -> Tuple[int, int, Optional[datetime], Optional[datetime]]:
        """Load canonical billing aggregate records to meter_aggregate.

        Splits records into resolved (all FKs present) and unresolved
        (missing required FKs). Resolved go to meter_aggregate via upsert;
        unresolved are logged with full diagnostics and dropped.

        Args:
            records: List of canonical billing aggregate dicts.

        Returns:
            Tuple of (rows_loaded, rows_dropped, period_start, period_end)
        """
        if not records:
            return 0, 0, None, None

        # Split into resolved and unresolved
        resolved = []
        unresolved = []
        for r in records:
            missing = [fk for fk in self.REQUIRED_FKS if r.get(fk) is None]
            if missing:
                r['_missing_fks'] = missing
                unresolved.append(r)
            else:
                resolved.append(r)

        # Log each unresolved row with diagnostics so issues are actionable
        if unresolved:
            logger.warning(
                "Dropping %d records with unresolved FKs (will not appear in billing):",
                len(unresolved),
            )
            for i, rec in enumerate(unresolved):
                missing = rec.get('_missing_fks', [])
                diag = rec.get('_unresolved_fks', [])
                source = rec.get('source_system', '?')
                period = rec.get('period_start', '?')
                org = rec.get('organization_id', '?')
                detail = f"missing=[{', '.join(missing)}]"
                if diag:
                    detail += f" resolution_errors=[{'; '.join(diag)}]"
                logger.warning(
                    "  [%d] org=%s period=%s source=%s %s",
                    i + 1, org, period, source, detail,
                )

        # Insert resolved rows
        rows_loaded = 0
        for i in range(0, len(resolved), self.BATCH_SIZE):
            batch = resolved[i:i + self.BATCH_SIZE]
            rows_loaded += self._insert_batch(batch)

        # Compute date range from period_start values
        starts = [r['period_start'] for r in records if r.get('period_start')]
        ends = [r['period_end'] for r in records if r.get('period_end')]
        data_start = min(starts) if starts else None
        data_end = max(ends) if ends else None

        rows_dropped = len(unresolved)
        logger.info(
            "Loaded %d billing aggregates to meter_aggregate, dropped %d unresolved",
            rows_loaded, rows_dropped,
        )
        return rows_loaded, rows_dropped, data_start, data_end

    def _insert_batch(self, batch: List[Dict[str, Any]]) -> int:
        """Insert a batch of resolved records using the connection pool.

        Uses ON CONFLICT with the idx_meter_aggregate_billing_dedup index
        to upsert: new rows are inserted, existing rows are updated.
        """
        if not batch:
            return 0

        values = []
        for record in batch:
            row = (
                record.get('organization_id'),
                record.get('meter_id'),
                record.get('billing_period_id'),
                record.get('clause_tariff_id'),
                record.get('contract_line_id'),
                record.get('period_type', 'monthly'),
                record.get('period_start'),
                record.get('period_end'),
                self._to_decimal(record.get('energy_wh')),
                self._to_decimal(record.get('energy_kwh')),
                self._to_decimal(record.get('total_production')),
                self._to_decimal(record.get('available_energy_kwh')),
                self._to_decimal(record.get('opening_reading')),
                self._to_decimal(record.get('closing_reading')),
                self._to_decimal(record.get('utilized_reading')),
                self._to_decimal(record.get('discount_reading')),
                self._to_decimal(record.get('sourced_energy')),
                self._to_decimal(record.get('ghi_irradiance_wm2')),
                self._to_decimal(record.get('poa_irradiance_wm2')),
                record.get('source_system'),
                Json(record.get('source_metadata')) if record.get('source_metadata') else None,
                record.get('aggregated_at'),
            )
            values.append(row)

        columns_str = ', '.join(self.COLUMNS)
        # Upsert: on dedup conflict, update data columns with new values
        update_set = ', '.join(
            f"{col} = EXCLUDED.{col}" for col in self.UPSERT_COLUMNS
        )
        sql = f"""
            INSERT INTO meter_aggregate ({columns_str})
            VALUES %s
            ON CONFLICT (organization_id, meter_id, billing_period_id, contract_line_id)
            WHERE period_type = 'monthly'
              AND meter_id IS NOT NULL
              AND billing_period_id IS NOT NULL
              AND contract_line_id IS NOT NULL
            DO UPDATE SET {update_set}
        """

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=self.BATCH_SIZE)
                rows_affected = cur.rowcount

        logger.info("Upserted batch: %d rows into meter_aggregate", rows_affected)
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
