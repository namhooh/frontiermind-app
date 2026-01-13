"""
Meter data aggregation service for rules engine.

Loads meter readings and excused events from database into pandas DataFrames
for efficient time-series analysis.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
import logging

from db.database import get_db_connection

logger = logging.getLogger(__name__)


class MeterAggregator:
    """
    Service for loading and aggregating meter data.

    Uses pandas DataFrames for efficient time-series operations needed by
    the rules engine.
    """

    def load_meter_readings(
        self,
        project_id: int,
        meter_type: str,
        period_start: datetime,
        period_end: datetime
    ) -> pd.DataFrame:
        """
        Load meter readings for a project and period.

        Args:
            project_id: Project ID
            meter_type: Meter type code (e.g., 'generation', 'availability')
            period_start: Start of period (inclusive)
            period_end: End of period (exclusive)

        Returns:
            DataFrame with columns:
                - reading_timestamp (datetime)
                - value (float)
                - meter_id (int)
                - unit_of_measure (str)
        """
        query = """
            SELECT
                mr.reading_timestamp,
                mr.value,
                mr.meter_id,
                m.unit as unit_of_measure
            FROM meter_reading mr
            JOIN meter m ON m.id = mr.meter_id
            JOIN meter_type mt ON mt.id = m.meter_type_id
            WHERE m.project_id = %s
              AND mt.code = %s
              AND mr.reading_timestamp >= %s
              AND mr.reading_timestamp < %s
            ORDER BY mr.reading_timestamp
        """

        try:
            with get_db_connection(dict_cursor=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (project_id, meter_type, period_start, period_end)
                    )
                    rows = cursor.fetchall()

            # Convert list of dicts to DataFrame
            if rows:
                df = pd.DataFrame(rows)
                # Convert value column to numeric (handle Decimal types)
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                # Ensure timestamp column is datetime
                df['reading_timestamp'] = pd.to_datetime(df['reading_timestamp'])
            else:
                df = pd.DataFrame(columns=[
                    'reading_timestamp', 'value', 'meter_id', 'unit_of_measure'
                ])

            logger.info(
                f"Loaded {len(df)} meter readings for project {project_id}, "
                f"type '{meter_type}', period {period_start} to {period_end}"
            )

            return df

        except Exception as e:
            logger.error(
                f"Failed to load meter readings for project {project_id}: {e}"
            )
            return pd.DataFrame(columns=[
                'reading_timestamp', 'value', 'meter_id', 'unit_of_measure'
            ])

    def load_excused_events(
        self,
        project_id: int,
        period_start: datetime,
        period_end: datetime,
        excused_types: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Load excused events (force majeure, grid outages, etc.) for a project.

        Args:
            project_id: Project ID
            period_start: Start of period
            period_end: End of period
            excused_types: Optional list of event type codes to include

        Returns:
            DataFrame with columns:
                - event_id (int)
                - time_start (datetime)
                - time_end (datetime)
                - event_type (str)
                - description (str)
        """
        # Build query with optional type filter
        type_filter = ""
        params = [project_id, period_start, period_end]

        if excused_types:
            placeholders = ','.join(['%s'] * len(excused_types))
            type_filter = f"AND et.code IN ({placeholders})"
            params.extend(excused_types)

        query = f"""
            SELECT
                e.id AS event_id,
                e.time_start,
                e.time_end,
                et.code AS event_type,
                e.description
            FROM event e
            JOIN event_type et ON et.id = e.event_type_id
            WHERE e.project_id = %s
              AND e.time_start < %s
              AND (e.time_end IS NULL OR e.time_end >= %s)
              {type_filter}
            ORDER BY e.time_start
        """

        try:
            with get_db_connection(dict_cursor=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()

            # Convert list of dicts to DataFrame
            if rows:
                df = pd.DataFrame(rows)
                # Convert timestamp columns to datetime
                df['time_start'] = pd.to_datetime(df['time_start'])
                df['time_end'] = pd.to_datetime(df['time_end'])
                # Handle ongoing events (time_end = NULL) by setting to period_end
                df['time_end'] = df['time_end'].fillna(period_end)
            else:
                df = pd.DataFrame(columns=[
                    'event_id', 'time_start', 'time_end', 'event_type', 'description'
                ])

            logger.info(
                f"Loaded {len(df)} excused events for project {project_id}, "
                f"period {period_start} to {period_end}"
            )

            return df

        except Exception as e:
            logger.error(
                f"Failed to load excused events for project {project_id}: {e}"
            )
            return pd.DataFrame(columns=[
                'event_id', 'time_start', 'time_end', 'event_type', 'description'
            ])

    def validate_data_completeness(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        expected_interval_minutes: int = 60
    ) -> Dict[str, Any]:
        """
        Validate that meter data covers the entire period without gaps.

        Args:
            meter_data: DataFrame from load_meter_readings()
            period_start: Expected start of data
            period_end: Expected end of data
            expected_interval_minutes: Expected time between readings

        Returns:
            Dict with keys:
                - complete (bool): True if data is complete
                - coverage_percent (float): Percentage of period with data
                - gaps (List[Dict]): List of gap periods
                - notes (List[str]): Human-readable notes
        """
        if meter_data.empty:
            return {
                'complete': False,
                'coverage_percent': 0.0,
                'gaps': [{'start': period_start, 'end': period_end}],
                'notes': ['No meter data found for period']
            }

        # Make period_start and period_end timezone-aware to match database timestamps
        import pytz
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=pytz.UTC)
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=pytz.UTC)

        # Calculate expected number of readings
        period_hours = (period_end - period_start).total_seconds() / 3600
        expected_readings = int(period_hours * (60 / expected_interval_minutes))
        actual_readings = len(meter_data)
        coverage_percent = min(100.0, (actual_readings / expected_readings) * 100)

        # Detect gaps
        gaps = []
        notes = []

        # Check for leading gap
        first_reading = meter_data['reading_timestamp'].min()
        if first_reading > period_start:
            gap_hours = (first_reading - period_start).total_seconds() / 3600
            if gap_hours > 1:  # Only report gaps > 1 hour
                gaps.append({
                    'start': period_start,
                    'end': first_reading,
                    'duration_hours': round(gap_hours, 2)
                })
                notes.append(
                    f"Missing data at start: {period_start} to {first_reading}"
                )

        # Check for trailing gap
        last_reading = meter_data['reading_timestamp'].max()
        if last_reading < period_end:
            gap_hours = (period_end - last_reading).total_seconds() / 3600
            if gap_hours > 1:
                gaps.append({
                    'start': last_reading,
                    'end': period_end,
                    'duration_hours': round(gap_hours, 2)
                })
                notes.append(
                    f"Missing data at end: {last_reading} to {period_end}"
                )

        # Determine if complete
        complete = len(gaps) == 0 and coverage_percent >= 95.0

        if not complete:
            notes.append(
                f"Coverage: {coverage_percent:.1f}% "
                f"({actual_readings}/{expected_readings} readings)"
            )

        return {
            'complete': complete,
            'coverage_percent': round(coverage_percent, 2),
            'gaps': gaps,
            'notes': notes
        }
