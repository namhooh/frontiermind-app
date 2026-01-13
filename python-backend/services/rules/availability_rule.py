"""
Availability rule for plant uptime guarantees.

Evaluates whether a power plant met contracted availability requirements
during an evaluation period, accounting for excused events.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Any
import pandas as pd
import logging

from services.rules.base_rule import BaseRule
from models.contract import RuleResult

logger = logging.getLogger(__name__)


class AvailabilityRule(BaseRule):
    """
    Evaluate plant availability guarantees.

    Availability = (operating_hours) / (total_hours - excused_hours) × 100

    Example:
        - Period: November 2024 (720 hours)
        - Operating hours: 619.75 (meter value > 0)
        - Excused hours: 28.5 (force majeure)
        - Availability: 619.75 / (720 - 28.5) × 100 = 89.7%
        - Threshold: 95%
        - Shortfall: 5.3 percentage points
        - LD: 5.3 × $50,000 = $265,000
    """

    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Evaluate availability guarantee for the period.

        Args:
            meter_data: DataFrame with [reading_timestamp, value, meter_id]
                       where value represents operational status (MW output)
            period_start: Start of evaluation period
            period_end: End of evaluation period
            excused_events: DataFrame with [time_start, time_end, event_type]

        Returns:
            RuleResult with breach status and LD amount
        """
        # Get threshold from clause parameters
        threshold = float(self.params.get('threshold', 95.0))
        threshold_unit = self.params.get('threshold_unit', 'percent')

        # Calculate total period hours
        total_hours = (period_end - period_start).total_seconds() / 3600

        # Calculate excused hours
        excused_hours = self._calculate_excused_hours(
            excused_events, period_start, period_end
        )

        # Calculate actual operating hours (where meter value > 0)
        if meter_data.empty:
            logger.warning(
                f"No meter data for availability calculation "
                f"(clause {self.clause_id}, period {period_start} to {period_end})"
            )
            return RuleResult(
                breach=True,
                rule_type='availability',
                clause_id=self.clause_id,
                calculated_value=0.0,
                threshold_value=threshold,
                shortfall=threshold,
                ld_amount=None,
                details={
                    'error': 'No meter data available',
                    'total_hours': total_hours,
                    'excused_hours': excused_hours,
                }
            )

        # Count hours where value > 0 (plant was operating)
        # Note: Meter data is assumed to be hourly or sub-hourly readings
        operating_mask = meter_data['value'] > 0
        operating_hours = operating_mask.sum()

        # Handle sub-hourly data (e.g., 15-minute intervals)
        if len(meter_data) > total_hours:
            # Assume evenly spaced readings, scale to hours
            readings_per_hour = len(meter_data) / total_hours
            operating_hours = operating_mask.sum() / readings_per_hour

        # Calculate availability percentage
        denominator = total_hours - excused_hours
        if denominator <= 0:
            logger.warning(
                f"Invalid denominator for availability calculation: "
                f"total_hours={total_hours}, excused_hours={excused_hours}"
            )
            availability = 0.0
        else:
            availability = (operating_hours / denominator) * 100

        # Determine breach
        breach = availability < threshold
        shortfall = max(0.0, threshold - availability)

        # Calculate LD if breach occurred
        ld_amount = None
        if breach:
            ld_params = self._get_ld_parameters()
            ld_amount = self._calculate_ld_amount(
                shortfall,
                ld_params,
                cap_context=f"availability breach {period_start.strftime('%Y-%m')}"
            )

        # Build result
        result = RuleResult(
            breach=breach,
            rule_type='availability',
            clause_id=self.clause_id,
            calculated_value=round(availability, 2),
            threshold_value=threshold,
            shortfall=round(shortfall, 2) if breach else None,
            ld_amount=ld_amount,
            details={
                'total_hours': round(total_hours, 2),
                'excused_hours': round(excused_hours, 2),
                'operating_hours': round(operating_hours, 2),
                'denominator_hours': round(denominator, 2),
                'availability_percent': round(availability, 2),
                'threshold_percent': threshold,
                'meter_readings_count': len(meter_data),
                'excused_events_count': len(excused_events) if not excused_events.empty else 0,
            }
        )

        logger.info(
            f"Availability evaluation: {availability:.2f}% vs {threshold}% "
            f"({'BREACH' if breach else 'OK'}) - "
            f"Clause {self.clause_id} '{self.clause_name}'"
        )

        return result
