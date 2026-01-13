"""
Event detection service for identifying operational anomalies from meter data.

Analyzes time-series meter readings to detect:
- Equipment failures (zero output for extended periods)
- Performance degradation (output below expected levels)
- Grid outages (simultaneous failures across meters)
"""

from datetime import datetime
from typing import List, Dict, Any
import logging
import pandas as pd

from models.event import DetectedEvent
from services.meter_aggregator import MeterAggregator
from db.event_repository import EventRepository

logger = logging.getLogger(__name__)


class EventDetector:
    """
    Detect operational events from meter data.

    Uses time-series analysis to identify anomalies that represent
    equipment failures, performance issues, and grid outages.
    """

    def __init__(self):
        """Initialize event detector with meter aggregator and event repository."""
        self.meter_aggregator = MeterAggregator()
        self.event_repo = EventRepository()

    def detect_events(
        self,
        project_id: int,
        period_start: datetime,
        period_end: datetime
    ) -> List[DetectedEvent]:
        """
        Analyze meter data to identify operational anomalies.

        Args:
            project_id: Project ID to analyze
            period_start: Start of analysis period
            period_end: End of analysis period

        Returns:
            List of DetectedEvent objects with:
            - event_type (equipment_failure, performance_degradation, etc.)
            - severity (1-5)
            - time_start, time_end
            - raw_data (outage duration, affected capacity, etc.)
        """
        logger.info(
            f"Detecting events for project {project_id} "
            f"from {period_start} to {period_end}"
        )

        # Load meter data for the period
        meter_data = self.meter_aggregator.load_meter_readings(
            project_id=project_id,
            meter_type='PRODUCTION',
            period_start=period_start,
            period_end=period_end
        )

        if meter_data.empty:
            logger.warning(f"No meter data found for project {project_id}")
            return []

        # Detect different types of events
        detected_events = []

        # 1. Detect outages (zero readings)
        outage_events = self._detect_outages(meter_data, project_id)
        detected_events.extend(outage_events)

        # 2. Detect performance degradation (below expected output)
        # Note: Requires expected capacity, which we can infer from meter data
        degradation_events = self._detect_degradation(meter_data, project_id)
        detected_events.extend(degradation_events)

        logger.info(
            f"Detected {len(detected_events)} events "
            f"({len(outage_events)} outages, {len(degradation_events)} degradations)"
        )

        return detected_events

    def _detect_outages(
        self,
        meter_df: pd.DataFrame,
        project_id: int
    ) -> List[DetectedEvent]:
        """
        Detect equipment/grid outages from meter readings.

        Logic:
        1. Find consecutive zero readings
        2. Group into outage periods
        3. Classify by duration
        4. Determine severity and event type

        Args:
            meter_df: DataFrame with meter readings
            project_id: Project ID

        Returns:
            List of DetectedEvent objects for outages
        """
        if meter_df.empty:
            return []

        # Mark zero readings
        outage_mask = meter_df['value'] == 0

        # Find consecutive groups using shift()
        meter_df = meter_df.copy()
        meter_df['outage_group'] = (outage_mask != outage_mask.shift()).cumsum()

        # Filter only outage groups
        outage_groups = meter_df[outage_mask].groupby('outage_group')

        events = []
        for group_id, group in outage_groups:
            if len(group) < 2:  # Skip single-hour blips
                continue

            time_start = group['reading_timestamp'].min()
            time_end = group['reading_timestamp'].max()
            duration_hours = len(group)

            # Determine event type and severity based on duration
            if duration_hours >= 24:
                event_type_code = 'EQUIP_FAIL'  # Equipment Failure
                # Severity increases with duration: 24hrs=3, 48hrs=4, 72+hrs=5
                severity = min(5, 3 + (duration_hours // 24) - 1)
            elif duration_hours >= 4:
                event_type_code = 'GRID_OUTAGE'  # Grid Outage
                severity = 3
            else:
                # Short outages (2-3 hours)
                event_type_code = 'EQUIP_FAIL'  # Equipment Failure
                severity = 2

            # Get event_type_id from repository
            event_type_id = self.event_repo.get_event_type_id_by_code(event_type_code)
            if not event_type_id:
                logger.warning(f"Event type '{event_type_code}' not found in database, skipping")
                continue

            # Calculate affected capacity (if available in meter data)
            affected_capacity_mw = 0
            if 'capacity' in group.columns:
                affected_capacity_mw = group['capacity'].iloc[0]

            # Build raw_data with event details
            raw_data = {
                'severity': severity,
                'outage_hours': duration_hours,
                'affected_capacity_mw': float(affected_capacity_mw) if affected_capacity_mw else None,
                'detection_method': 'consecutive_zero_readings',
                'meter_count': len(group['meter_id'].unique()) if 'meter_id' in group.columns else 1
            }

            events.append(DetectedEvent(
                event_type=event_type_code,
                event_type_id=event_type_id,
                severity=severity,
                time_start=time_start,
                time_end=time_end,
                description=f"{event_type_code.replace('_', ' ').title()}: {duration_hours} hours",
                raw_data=raw_data,
                metric_outcome={},
                affected_meters=list(group['meter_id'].unique()) if 'meter_id' in group.columns else []
            ))

        return events

    def _detect_degradation(
        self,
        meter_df: pd.DataFrame,
        project_id: int
    ) -> List[DetectedEvent]:
        """
        Detect performance degradation (output below expected).

        Logic:
        1. Calculate expected output based on capacity
        2. Identify periods where actual < 80% of expected
        3. Group consecutive degraded hours
        4. Determine severity by magnitude

        Args:
            meter_df: DataFrame with meter readings
            project_id: Project ID

        Returns:
            List of DetectedEvent objects for degradation
        """
        if meter_df.empty:
            return []

        # Calculate expected capacity (use max non-zero value as reference)
        non_zero_values = meter_df[meter_df['value'] > 0]['value']
        if non_zero_values.empty:
            logger.warning("No non-zero readings found, cannot detect degradation")
            return []

        # Use 90th percentile of non-zero values as expected capacity
        # (more robust than max, which could be an outlier)
        expected_capacity = non_zero_values.quantile(0.90)

        if expected_capacity == 0:
            return []

        # Calculate performance ratio
        meter_df = meter_df.copy()
        meter_df['performance_ratio'] = meter_df['value'] / expected_capacity

        # Identify degradation (< 80% of capacity, but not complete outage)
        degradation_mask = (
            (meter_df['performance_ratio'] < 0.8) &
            (meter_df['performance_ratio'] > 0)  # Not a complete outage
        )

        # Group consecutive degradation periods
        meter_df['degradation_group'] = (
            degradation_mask != degradation_mask.shift()
        ).cumsum()

        degradation_groups = meter_df[degradation_mask].groupby('degradation_group')

        events = []
        for group_id, group in degradation_groups:
            if len(group) < 4:  # Skip brief dips (< 4 hours)
                continue

            time_start = group['reading_timestamp'].min()
            time_end = group['reading_timestamp'].max()
            duration_hours = len(group)

            avg_performance = group['performance_ratio'].mean()
            degradation_pct = (1 - avg_performance) * 100
            avg_output_mw = group['value'].mean()

            # Severity based on magnitude of degradation
            if degradation_pct >= 40:
                severity = 5
            elif degradation_pct >= 30:
                severity = 4
            elif degradation_pct >= 20:
                severity = 3
            else:
                severity = 2

            # Get event_type_id from repository
            event_type_code = 'UNDERPERF'  # Underperformance
            event_type_id = self.event_repo.get_event_type_id_by_code(event_type_code)
            if not event_type_id:
                logger.warning(f"Event type '{event_type_code}' not found in database, skipping")
                continue

            # Build raw_data with degradation details
            raw_data = {
                'severity': severity,
                'degradation_percentage': float(degradation_pct),
                'avg_output_mw': float(avg_output_mw),
                'expected_output_mw': float(expected_capacity),
                'duration_hours': duration_hours,
                'detection_method': 'performance_ratio_analysis',
                'performance_ratio': float(avg_performance)
            }

            # Build metric_outcome with calculated metrics
            metric_outcome = {
                'avg_performance_ratio': float(avg_performance),
                'min_performance_ratio': float(group['performance_ratio'].min()),
                'max_performance_ratio': float(group['performance_ratio'].max())
            }

            events.append(DetectedEvent(
                event_type=event_type_code,
                event_type_id=event_type_id,
                severity=severity,
                time_start=time_start,
                time_end=time_end,
                description=f"Performance degradation: {degradation_pct:.1f}% below expected",
                raw_data=raw_data,
                metric_outcome=metric_outcome,
                affected_meters=list(group['meter_id'].unique()) if 'meter_id' in group.columns else []
            ))

        return events
