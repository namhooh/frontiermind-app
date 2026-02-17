"""
Available Energy calculators.

Strategy pattern: each calculation method is a separate class,
dispatched via the AVAILABLE_ENERGY_CALCULATORS registry.

The method code is stored in clause.normalized_payload.available_energy_method
for AVAILABILITY clauses.

Data source: measured 15-min meter_reading data (energy_wh, irradiance_wm2),
NOT forecast data from production_forecast.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, List
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class BaseAvailableEnergyCalculator(ABC):
    """Abstract base for available energy calculation methods."""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def calculate(
        self,
        meter_data: pd.DataFrame,
        curtailment_intervals: pd.DataFrame
    ) -> Decimal:
        """
        Calculate available energy for curtailment compensation.

        Args:
            meter_data: DataFrame with columns [reading_timestamp, energy_wh,
                        irradiance_wm2] from meter_reading table.
                        Must cover the prior reference month.
            curtailment_intervals: DataFrame with columns [reading_timestamp,
                                   irradiance_wm2] for the curtailed intervals
                                   to compensate.

        Returns:
            Total available energy in Wh for the curtailed intervals.
        """
        pass


class IrradianceIntervalAdjustedCalculator(BaseAvailableEnergyCalculator):
    """
    E_Available(x) = (E_hist / Irr_hist) x (1/Intervals) x Irr(x)

    Used by: Ghana GRID contracts (Exhibit A).

    Inputs from meter_reading (measured, not forecast):
    - E_hist: Energy measured by billing meter for previous calendar month
              during Normal Operation (irradiance > threshold)
    - Irr_hist: Average in-plane irradiance for previous month during
                Normal Operation (irradiance > threshold)
    - Intervals: Total number of intervals under Normal Operation
    - Irr(x): In-plane irradiance for each curtailed interval x (kW/m2)

    Normal Operation: irradiance > irradiance_threshold_wm2 (default 100 W/m2)
    """

    def __init__(self, params: dict):
        super().__init__(params)
        self.irradiance_threshold = params.get('irradiance_threshold_wm2', 100)
        self.interval_minutes = params.get('interval_minutes', 15)

    def calculate(
        self,
        meter_data: pd.DataFrame,
        curtailment_intervals: pd.DataFrame
    ) -> Decimal:
        if meter_data.empty or curtailment_intervals.empty:
            return Decimal('0')

        # Filter to Normal Operation intervals (irradiance > threshold)
        normal_op = meter_data[
            meter_data['irradiance_wm2'].notna() &
            (meter_data['irradiance_wm2'] > self.irradiance_threshold)
        ]

        if normal_op.empty:
            logger.warning(
                "No Normal Operation intervals found "
                f"(threshold: {self.irradiance_threshold} W/m2)"
            )
            return Decimal('0')

        # E_hist: total energy during Normal Operation (Wh)
        e_hist = normal_op['energy_wh'].sum()

        # Irr_hist: average irradiance during Normal Operation (W/m2)
        irr_hist = normal_op['irradiance_wm2'].mean()

        # Intervals: count of Normal Operation intervals
        intervals = len(normal_op)

        if irr_hist <= 0 or intervals <= 0:
            return Decimal('0')

        # Calculate performance coefficient
        perf_coeff = e_hist / irr_hist / intervals

        # Sum available energy for each curtailed interval
        total_available_wh = Decimal('0')
        for _, row in curtailment_intervals.iterrows():
            irr_x = row.get('irradiance_wm2', 0) or 0
            if irr_x > 0:
                e_available_x = perf_coeff * irr_x
                total_available_wh += Decimal(str(e_available_x))

        logger.info(
            f"IrradianceIntervalAdjusted: E_hist={e_hist:.0f}Wh, "
            f"Irr_hist={irr_hist:.1f}W/m2, Intervals={intervals}, "
            f"curtailed_intervals={len(curtailment_intervals)}, "
            f"E_available={total_available_wh:.0f}Wh"
        )

        return total_available_wh


class MonthlyAverageIrradianceCalculator(BaseAvailableEnergyCalculator):
    """
    E_Available = E_avg_monthly x (Irr_actual / Irr_reference)

    Used by: contracts with simpler irradiance-ratio compensation.

    Inputs:
    - E_avg_monthly: Average monthly energy from historical/forecast data
    - Irr_actual: Actual irradiance during curtailed period
    - Irr_reference: Reference irradiance (from PVSyst or historical average)
    """

    def __init__(self, params: dict):
        super().__init__(params)
        self.reference_irradiance = params.get('reference_irradiance_wm2')
        self.reference_monthly_energy_kwh = params.get('reference_monthly_energy_kwh')

    def calculate(
        self,
        meter_data: pd.DataFrame,
        curtailment_intervals: pd.DataFrame
    ) -> Decimal:
        if curtailment_intervals.empty:
            return Decimal('0')

        if not self.reference_irradiance or not self.reference_monthly_energy_kwh:
            logger.warning(
                "MonthlyAverageIrradiance: missing reference_irradiance_wm2 "
                "or reference_monthly_energy_kwh in params"
            )
            return Decimal('0')

        # Average actual irradiance across curtailed intervals
        irr_actual = curtailment_intervals['irradiance_wm2'].mean()
        if not irr_actual or irr_actual <= 0:
            return Decimal('0')

        irr_ratio = irr_actual / self.reference_irradiance
        e_available_kwh = self.reference_monthly_energy_kwh * irr_ratio

        # Convert kWh to Wh for consistency
        e_available_wh = Decimal(str(e_available_kwh * 1000))

        logger.info(
            f"MonthlyAverageIrradiance: Irr_actual={irr_actual:.1f}, "
            f"Irr_ref={self.reference_irradiance:.1f}, "
            f"ratio={irr_ratio:.4f}, E_available={e_available_wh:.0f}Wh"
        )

        return e_available_wh


class FixedDeemedCalculator(BaseAvailableEnergyCalculator):
    """
    E_Available = fixed deemed energy per interval x number of curtailed intervals.

    Used by: contracts with a fixed deemed generation rate.
    """

    def __init__(self, params: dict):
        super().__init__(params)
        self.deemed_kwh_per_interval = params.get('deemed_kwh_per_interval', 0)

    def calculate(
        self,
        meter_data: pd.DataFrame,
        curtailment_intervals: pd.DataFrame
    ) -> Decimal:
        if curtailment_intervals.empty:
            return Decimal('0')

        n_intervals = len(curtailment_intervals)
        e_available_wh = Decimal(str(self.deemed_kwh_per_interval * 1000)) * n_intervals

        logger.info(
            f"FixedDeemed: {n_intervals} curtailed intervals x "
            f"{self.deemed_kwh_per_interval} kWh/interval = "
            f"{e_available_wh:.0f}Wh"
        )

        return e_available_wh


# =============================================================================
# Calculator Registry
# =============================================================================

AVAILABLE_ENERGY_CALCULATORS: Dict[str, type] = {
    'irradiance_interval_adjusted': IrradianceIntervalAdjustedCalculator,
    'monthly_average_irradiance': MonthlyAverageIrradianceCalculator,
    'fixed_deemed': FixedDeemedCalculator,
}


def calculate_available_energy(
    clause_payload: dict,
    meter_data: pd.DataFrame,
    curtailment_intervals: pd.DataFrame
) -> Decimal:
    """
    Dispatch to the correct available energy calculator based on clause payload.

    Args:
        clause_payload: clause.normalized_payload dict. Must contain
                        'available_energy_method' key.
        meter_data: Reference month meter readings.
        curtailment_intervals: Curtailed intervals to compensate.

    Returns:
        Available energy in Wh, or Decimal(0) if method is 'none' or unknown.
    """
    method = clause_payload.get('available_energy_method', 'none')
    if method == 'none':
        return Decimal('0')

    calculator_class = AVAILABLE_ENERGY_CALCULATORS.get(method)
    if not calculator_class:
        raise ValueError(f"Unknown available energy method: {method}")

    return calculator_class(clause_payload).calculate(meter_data, curtailment_intervals)
