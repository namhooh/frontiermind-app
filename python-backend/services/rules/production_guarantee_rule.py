"""
Production Guarantee Rule — evaluates annual energy output vs guaranteed kWh.

Reads production_guarantee by operating_year, compares to meter_aggregate
annual total. Supports the 'energy_output' variant of PERFORMANCE_GUARANTEE.

This rule is for annual evaluation only (operating year boundary).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
import logging

import pandas as pd

from services.rules.base_rule import BaseRule
from models.contract import RuleResult

logger = logging.getLogger(__name__)


class ProductionGuaranteeRule(BaseRule):
    """
    Evaluates whether actual annual energy production meets the guaranteed output.

    Reads from clause.normalized_payload:
    - variant: must be 'energy_output' for this rule
    - guaranteed_annual_production_kwh: backup if production_guarantee table not loaded
    - shortfall_formula_type: determines how shortfall payment is calculated
    - measurement_period: 'annual' (enforced)

    External inputs (loaded by caller or from DB):
    - guaranteed_kwh from production_guarantee table for the operating year
    - actual_kwh from meter_aggregate annual totals
    """

    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Evaluate production guarantee for the period.

        For annual guarantees, period_start/period_end should span a full
        operating year.

        Args:
            meter_data: DataFrame with energy_wh column (or energy_kwh).
            period_start: Start of operating year.
            period_end: End of operating year.
            excused_events: Events that excuse shortfall.

        Returns:
            RuleResult with breach status and shortfall details.
        """
        # Get guaranteed threshold
        guaranteed_kwh = self._get_guaranteed_kwh()
        if not guaranteed_kwh or guaranteed_kwh <= 0:
            logger.warning(
                f"Clause {self.clause_id}: No guaranteed_kwh available — "
                "skipping production guarantee evaluation"
            )
            return RuleResult(
                clause_id=self.clause_id,
                rule_type='production_guarantee',
                breach=False,
                calculated_value=0,
                threshold_value=0,
                shortfall=0,
                ld_amount=Decimal('0.00'),
                details={'note': 'No guaranteed_kwh configured'}
            )

        # Calculate actual production
        actual_kwh = self._calculate_actual_production(meter_data)

        # Calculate excused energy (if any)
        excused_kwh = self._calculate_excused_energy(excused_events)
        adjusted_guaranteed = guaranteed_kwh - excused_kwh

        # Determine breach
        shortfall_kwh = max(Decimal('0'), adjusted_guaranteed - actual_kwh)
        breach = shortfall_kwh > 0

        # Calculate LD if breach
        ld_amount = Decimal('0.00')
        if breach:
            ld_amount = self._calculate_shortfall_payment(shortfall_kwh)

        details = {
            'actual_kwh': float(actual_kwh),
            'guaranteed_kwh': float(guaranteed_kwh),
            'excused_kwh': float(excused_kwh),
            'adjusted_guaranteed_kwh': float(adjusted_guaranteed),
            'shortfall_kwh': float(shortfall_kwh),
            'period': f"{period_start.date()} to {period_end.date()}",
        }

        logger.info(
            f"Production guarantee clause {self.clause_id}: "
            f"actual={actual_kwh:.0f}kWh, guaranteed={guaranteed_kwh:.0f}kWh, "
            f"shortfall={shortfall_kwh:.0f}kWh, breach={breach}"
        )

        return RuleResult(
            clause_id=self.clause_id,
            rule_type='production_guarantee',
            breach=breach,
            calculated_value=float(actual_kwh),
            threshold_value=float(guaranteed_kwh),
            shortfall=float(shortfall_kwh),
            ld_amount=ld_amount,
            details=details
        )

    def _get_guaranteed_kwh(self) -> Decimal:
        """Get guaranteed kWh from params or production_guarantee table."""
        # Direct from clause payload
        val = self.params.get('guaranteed_annual_production_kwh')
        if val:
            return Decimal(str(val))
        return Decimal('0')

    def _calculate_actual_production(self, meter_data: pd.DataFrame) -> Decimal:
        """Sum actual energy production from meter data."""
        if meter_data.empty:
            return Decimal('0')

        # Prefer energy_kwh if available, else convert energy_wh
        if 'energy_kwh' in meter_data.columns:
            total = meter_data['energy_kwh'].sum()
        elif 'energy_wh' in meter_data.columns:
            total = meter_data['energy_wh'].sum() / 1000
        elif 'value' in meter_data.columns:
            total = meter_data['value'].sum()
        else:
            logger.warning("No energy column found in meter_data")
            return Decimal('0')

        return Decimal(str(total))

    def _calculate_excused_energy(self, excused_events: pd.DataFrame) -> Decimal:
        """
        Calculate energy that should be excused from guarantee evaluation.

        Uses shortfall_excused_events from clause payload to filter relevant
        excuse types, then estimates energy using excused hours.
        """
        excused_hours = self._calculate_excused_hours(
            excused_events,
            datetime.min,  # Full period
            datetime.max
        )

        if excused_hours <= 0:
            return Decimal('0')

        # Estimate excused energy: proportional to guaranteed / total hours
        guaranteed_kwh = self._get_guaranteed_kwh()
        total_hours_per_year = Decimal('8760')
        excused_kwh = guaranteed_kwh * Decimal(str(excused_hours)) / total_hours_per_year

        return excused_kwh

    def _calculate_shortfall_payment(self, shortfall_kwh: Decimal) -> Decimal:
        """
        Calculate shortfall payment based on formula type.

        Shortfall formula types:
        - price_differential: SP = MAX(0, shortfall x (P_Alternate - P_Solar))
        - fixed_rate_per_kwh: SP = shortfall x fixed_rate
        - none: no payment

        P_Alternate and P_Solar are external inputs that must be provided
        in params or fetched from reference_price table.
        """
        formula_type = self.params.get('shortfall_formula_type', 'none')

        if formula_type == 'none':
            return Decimal('0.00')

        if formula_type == 'price_differential':
            p_alternate = Decimal(str(self.params.get('p_alternate', 0)))
            p_solar = Decimal(str(self.params.get('p_solar', 0)))
            price_diff = max(Decimal('0'), p_alternate - p_solar)
            payment = shortfall_kwh * price_diff

        elif formula_type == 'fixed_rate_per_kwh':
            rate = Decimal(str(self.params.get('shortfall_rate_per_kwh', 0)))
            payment = shortfall_kwh * rate

        else:
            logger.warning(f"Unknown shortfall_formula_type: {formula_type}")
            return Decimal('0.00')

        # Apply annual cap if configured
        cap = self.params.get('shortfall_cap_usd')
        if cap:
            cap_decimal = Decimal(str(cap))
            if payment > cap_decimal:
                logger.info(
                    f"Shortfall payment {payment:.2f} exceeds cap {cap_decimal:.2f}"
                )
                payment = cap_decimal

        return payment.quantize(Decimal('0.01'))
