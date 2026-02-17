"""
Pricing Rule — calculates billable amounts for GRID tariff contracts.

GRID tariff billing formula:
    Rate = MAX(floor, MIN((1 - discount) x GRP, ceiling))
    Amount = Rate x Energy Output

This rule reads clause_tariff.logic_parameters for pricing parameters
and reference_price for the current GRP.

Pricing parameters stored in clause_tariff.logic_parameters:
- discount_pct: Solar discount (0-1)
- floor_rate: Minimum rate per kWh
- ceiling_rate: Maximum rate per kWh
- grp_method: How GRP is calculated (for reference)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
import logging

import pandas as pd

from services.rules.base_rule import BaseRule
from models.contract import RuleResult

logger = logging.getLogger(__name__)


class PricingRule(BaseRule):
    """
    Evaluates GRID tariff pricing and calculates expected billable amount.

    This rule compares:
    - Expected amount (from our calculation using GRP, discount, floor/ceiling)
    - Against what was invoiced (if available)

    For pure calculation (no comparison), returns the expected amount.
    """

    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Calculate expected billing amount for the period.

        Note: This rule uses clause_tariff.logic_parameters (not
        clause.normalized_payload like other rules). The caller must
        provide tariff parameters in self.params.

        Required in self.params:
        - discount_pct: Solar discount (0-1)
        - floor_rate: Floor rate per kWh
        - ceiling_rate: Ceiling rate per kWh
        - grp_per_kwh: Current Grid Reference Price per kWh

        Returns:
            RuleResult where:
            - calculated_value = expected total amount
            - threshold_value = energy output (kWh)
            - shortfall = variance if received invoice differs
        """
        # Get pricing parameters
        discount_pct = Decimal(str(self.params.get('discount_pct', 0)))
        floor_rate = Decimal(str(self.params.get('floor_rate', 0)))
        ceiling_rate = Decimal(str(self.params.get('ceiling_rate', Decimal('999999'))))
        grp_per_kwh = Decimal(str(self.params.get('grp_per_kwh', 0)))

        if grp_per_kwh <= 0:
            logger.warning(
                f"Clause {self.clause_id}: grp_per_kwh not set or zero — "
                "cannot calculate GRID tariff pricing"
            )
            return RuleResult(
                clause_id=self.clause_id,
                rule_type='pricing',
                breach=False,
                calculated_value=0,
                threshold_value=0,
                shortfall=0,
                ld_amount=Decimal('0.00'),
                details={'note': 'grp_per_kwh not available'}
            )

        # Calculate effective rate
        discounted_rate = (Decimal('1') - discount_pct) * grp_per_kwh
        effective_rate = max(floor_rate, min(discounted_rate, ceiling_rate))

        # Calculate energy output from meter data
        energy_kwh = self._calculate_energy_kwh(meter_data)

        # Calculate expected amount
        expected_amount = effective_rate * energy_kwh

        # Check if we have a received amount to compare against
        received_amount = Decimal(str(self.params.get('received_amount', 0)))
        variance = Decimal('0')
        breach = False

        if received_amount > 0:
            variance = received_amount - expected_amount
            # Breach if variance exceeds threshold (default 1% tolerance)
            tolerance_pct = Decimal(str(self.params.get('variance_tolerance_pct', 1)))
            variance_pct = abs(variance / expected_amount * 100) if expected_amount > 0 else Decimal('0')
            breach = variance_pct > tolerance_pct

        details = {
            'grp_per_kwh': float(grp_per_kwh),
            'discount_pct': float(discount_pct),
            'discounted_rate': float(discounted_rate),
            'floor_rate': float(floor_rate),
            'ceiling_rate': float(ceiling_rate),
            'effective_rate': float(effective_rate),
            'energy_kwh': float(energy_kwh),
            'expected_amount': float(expected_amount),
            'received_amount': float(received_amount),
            'variance': float(variance),
            'rate_binding': (
                'floor' if effective_rate == floor_rate
                else 'ceiling' if effective_rate == ceiling_rate
                else 'discounted'
            ),
        }

        logger.info(
            f"Pricing clause {self.clause_id}: "
            f"GRP={grp_per_kwh:.6f}, discount={discount_pct:.2%}, "
            f"rate={effective_rate:.6f} ({details['rate_binding']}), "
            f"energy={energy_kwh:.0f}kWh, amount={expected_amount:.2f}"
        )

        return RuleResult(
            clause_id=self.clause_id,
            rule_type='pricing',
            breach=breach,
            calculated_value=float(expected_amount),
            threshold_value=float(energy_kwh),
            shortfall=float(variance),
            ld_amount=Decimal('0.00'),  # Pricing variances are not LDs
            details=details
        )

    def _calculate_energy_kwh(self, meter_data: pd.DataFrame) -> Decimal:
        """Sum energy production from meter data in kWh."""
        if meter_data.empty:
            return Decimal('0')

        if 'energy_kwh' in meter_data.columns:
            return Decimal(str(meter_data['energy_kwh'].sum()))
        elif 'energy_wh' in meter_data.columns:
            return Decimal(str(meter_data['energy_wh'].sum() / 1000))
        elif 'total_production' in meter_data.columns:
            return Decimal(str(meter_data['total_production'].sum()))
        else:
            logger.warning("No energy column found in meter_data for pricing")
            return Decimal('0')
