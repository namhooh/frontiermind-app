"""
Capacity factor rule for generation guarantees.

Evaluates whether a power plant met contracted generation output requirements.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Any
import pandas as pd
import logging

from services.rules.base_rule import BaseRule
from models.contract import RuleResult

logger = logging.getLogger(__name__)


class CapacityFactorRule(BaseRule):
    """
    Evaluate plant capacity factor guarantees.

    Capacity Factor = (actual_generation / expected_generation) × 100

    Example:
        - Nameplate capacity: 10 MW
        - Period: January 2025 (744 hours)
        - Expected: 10 MW × 744 hours × 0.95 efficiency = 7,068 MWh
        - Actual: 6,000 MWh
        - Capacity factor: (6,000 / 7,068) × 100 = 84.9%
        - Threshold: 85%
        - Shortfall: 0.1 percentage points
        - LD: 0.1 × $100,000 = $10,000
    """

    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Evaluate capacity factor guarantee for the period.

        Args:
            meter_data: DataFrame with [reading_timestamp, value, meter_id]
                       where value represents generation (MWh)
            period_start: Start of evaluation period
            period_end: End of evaluation period
            excused_events: DataFrame with [time_start, time_end, event_type]

        Returns:
            RuleResult with breach status and LD amount
        """
        # Get parameters from clause
        threshold = float(self.params.get('threshold', 85.0))
        nameplate_capacity = float(self.params.get('nameplate_capacity_mw', 0))
        efficiency_factor = float(self.params.get('efficiency_factor', 0.95))

        if nameplate_capacity <= 0:
            logger.error(
                f"Invalid nameplate_capacity_mw in clause {self.clause_id}: "
                f"{nameplate_capacity}"
            )
            return RuleResult(
                breach=True,
                rule_type='capacity_factor',
                clause_id=self.clause_id,
                calculated_value=None,
                threshold_value=threshold,
                shortfall=None,
                ld_amount=None,
                details={'error': 'Invalid nameplate_capacity_mw parameter'}
            )

        # Calculate total period hours
        total_hours = (period_end - period_start).total_seconds() / 3600

        # Calculate excused hours (subtract from expected generation)
        excused_hours = self._calculate_excused_hours(
            excused_events, period_start, period_end
        )

        # Calculate expected generation
        available_hours = total_hours - excused_hours
        expected_generation = nameplate_capacity * available_hours * efficiency_factor

        # Calculate actual generation (sum of meter readings)
        if meter_data.empty:
            logger.warning(
                f"No meter data for capacity factor calculation "
                f"(clause {self.clause_id})"
            )
            actual_generation = 0.0
        else:
            actual_generation = meter_data['value'].sum()

        # Calculate capacity factor
        if expected_generation <= 0:
            logger.warning(
                f"Invalid expected_generation for clause {self.clause_id}: "
                f"{expected_generation}"
            )
            capacity_factor = 0.0
        else:
            capacity_factor = (actual_generation / expected_generation) * 100

        # Determine breach
        breach = capacity_factor < threshold
        shortfall = max(0.0, threshold - capacity_factor)

        # Calculate LD if breach occurred
        ld_amount = None
        if breach:
            ld_params = self._get_ld_parameters()
            ld_amount = self._calculate_ld_amount(
                shortfall,
                ld_params,
                cap_context=f"capacity factor breach {period_start.strftime('%Y-%m')}"
            )

        # Build result
        result = RuleResult(
            breach=breach,
            rule_type='capacity_factor',
            clause_id=self.clause_id,
            calculated_value=round(capacity_factor, 2),
            threshold_value=threshold,
            shortfall=round(shortfall, 2) if breach else None,
            ld_amount=ld_amount,
            details={
                'actual_generation_mwh': round(actual_generation, 2),
                'expected_generation_mwh': round(expected_generation, 2),
                'nameplate_capacity_mw': nameplate_capacity,
                'total_hours': round(total_hours, 2),
                'excused_hours': round(excused_hours, 2),
                'available_hours': round(available_hours, 2),
                'efficiency_factor': efficiency_factor,
                'capacity_factor_percent': round(capacity_factor, 2),
                'threshold_percent': threshold,
            }
        )

        logger.info(
            f"Capacity factor evaluation: {capacity_factor:.2f}% vs {threshold}% "
            f"({'BREACH' if breach else 'OK'}) - "
            f"Clause {self.clause_id} '{self.clause_name}'"
        )

        return result
