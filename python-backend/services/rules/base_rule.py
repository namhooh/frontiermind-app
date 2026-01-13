"""
Base class for all contract compliance rules.

Rules evaluate contract clauses against meter data to detect breaches
and calculate liquidated damages (LDs).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal
import pandas as pd
import logging

from models.contract import RuleResult

logger = logging.getLogger(__name__)


class BaseRule(ABC):
    """
    Abstract base class for contract compliance rules.

    Each rule type (availability, capacity factor, pricing) inherits from this
    class and implements the evaluate() method with specific calculation logic.
    """

    def __init__(self, clause: Dict[str, Any]):
        """
        Initialize rule with clause data.

        Args:
            clause: Clause dict with keys:
                - id: Clause ID
                - name: Clause name
                - normalized_payload: JSONB with rule parameters
                - contract_id: Parent contract ID
                - project_id: Project ID
        """
        self.clause = clause
        self.clause_id = clause['id']
        self.clause_name = clause['name']
        self.contract_id = clause['contract_id']
        self.project_id = clause['project_id']
        self.params = clause.get('normalized_payload', {})

    @abstractmethod
    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Evaluate the rule for the given period.

        Args:
            meter_data: DataFrame with columns [reading_timestamp, value, meter_id]
            period_start: Start of evaluation period (inclusive)
            period_end: End of evaluation period (exclusive)
            excused_events: DataFrame with columns [time_start, time_end, event_type]

        Returns:
            RuleResult with breach status, calculated values, and LD amount
        """
        pass

    def _calculate_excused_hours(
        self,
        excused_events: pd.DataFrame,
        period_start: datetime,
        period_end: datetime
    ) -> float:
        """
        Calculate total excused hours from force majeure and other excused events.

        Args:
            excused_events: DataFrame with [time_start, time_end, event_type]
            period_start: Evaluation period start
            period_end: Evaluation period end

        Returns:
            Total excused hours
        """
        if excused_events.empty:
            return 0.0

        # Get excused event types from clause parameters
        excused_types = self.params.get('excused_events', [])

        # Filter to relevant event types
        relevant_events = excused_events[
            excused_events['event_type'].isin(excused_types)
        ]

        if relevant_events.empty:
            return 0.0

        # Calculate hours for each event (clamped to period boundaries)
        total_hours = 0.0
        for _, event in relevant_events.iterrows():
            event_start = max(event['time_start'], period_start)
            event_end = min(event['time_end'], period_end)

            if event_end > event_start:
                duration = (event_end - event_start).total_seconds() / 3600
                total_hours += duration

        logger.debug(
            f"Calculated {total_hours:.2f} excused hours from {len(relevant_events)} events"
        )
        return total_hours

    def _get_ld_parameters(self) -> Dict[str, Any]:
        """
        Extract LD calculation parameters from normalized_payload.

        Returns:
            Dict with keys:
                - ld_per_point: Decimal ($/percentage point)
                - ld_cap_annual: Optional[Decimal] (max LD per year)
                - ld_cap_period: Optional[Decimal] (max LD per period)
                - ld_currency: str (USD, EUR, etc.)
        """
        return {
            'ld_per_point': Decimal(str(self.params.get('ld_per_point', 0))),
            'ld_cap_annual': (
                Decimal(str(self.params['ld_cap_annual']))
                if 'ld_cap_annual' in self.params
                else None
            ),
            'ld_cap_period': (
                Decimal(str(self.params['ld_cap_period']))
                if 'ld_cap_period' in self.params
                else None
            ),
            'ld_currency': self.params.get('ld_currency', 'USD'),
        }

    def _calculate_ld_amount(
        self,
        shortfall: float,
        ld_params: Dict[str, Any],
        cap_context: Optional[str] = None
    ) -> Decimal:
        """
        Calculate LD amount with cap enforcement.

        Args:
            shortfall: Shortfall amount (percentage points, MW, etc.)
            ld_params: LD parameters from _get_ld_parameters()
            cap_context: Optional context for logging cap enforcement

        Returns:
            LD amount (Decimal)
        """
        if shortfall <= 0:
            return Decimal('0.00')

        # Calculate raw LD
        ld_amount = Decimal(str(shortfall)) * ld_params['ld_per_point']

        # Apply caps if specified
        cap = ld_params.get('ld_cap_period') or ld_params.get('ld_cap_annual')
        if cap and ld_amount > cap:
            logger.info(
                f"LD amount ${ld_amount:,.2f} exceeds cap ${cap:,.2f} "
                f"({cap_context or 'unspecified'}). Applying cap."
            )
            ld_amount = cap

        return ld_amount.quantize(Decimal('0.01'))
