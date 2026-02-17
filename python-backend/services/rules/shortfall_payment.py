"""
Shortfall Payment Calculator.

Formula: SP = MAX(0, (E_Guaranteed - E_Period) x (P_Alternate - P_Solar))
Annual cap: configurable per production_guarantee row (shortfall_cap_usd)

P_Alternate: Grid Reference Price for the guarantee period (from reference_price table)
P_Solar: Average payment made by customer for solar power (from invoice data)

This is a standalone calculator used by ProductionGuaranteeRule and can
also be called directly for year-end settlement calculations.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ShortfallPaymentCalculator:
    """
    Calculates shortfall payment using the price differential method.

    SP = MAX(0, (E_Guaranteed - E_Period) x (P_Alternate - P_Solar))

    With annual cap enforcement and FX conversion support.
    """

    def __init__(
        self,
        guaranteed_kwh: Decimal,
        actual_kwh: Decimal,
        p_alternate: Decimal,
        p_solar: Decimal,
        annual_cap_usd: Optional[Decimal] = None,
        fx_rate: Optional[Decimal] = None,
    ):
        """
        Args:
            guaranteed_kwh: Guaranteed annual energy output (from production_guarantee).
            actual_kwh: Actual metered annual energy output.
            p_alternate: Grid Reference Price per kWh (from reference_price).
            p_solar: Average solar payment per kWh (from invoice totals).
            annual_cap_usd: Optional annual cap in USD.
            fx_rate: Optional FX rate (local currency per USD) for cap conversion.
        """
        self.guaranteed_kwh = guaranteed_kwh
        self.actual_kwh = actual_kwh
        self.p_alternate = p_alternate
        self.p_solar = p_solar
        self.annual_cap_usd = annual_cap_usd
        self.fx_rate = fx_rate

    def calculate(self) -> Dict[str, Any]:
        """
        Calculate shortfall payment.

        Returns:
            Dict with:
                - shortfall_kwh: Energy shortfall (guaranteed - actual)
                - price_differential: P_Alternate - P_Solar
                - raw_payment: Before cap
                - capped_payment: After applying annual cap
                - cap_applied: Whether the cap was binding
                - cap_local_currency: Cap converted to local currency (if fx_rate provided)
        """
        shortfall_kwh = max(Decimal('0'), self.guaranteed_kwh - self.actual_kwh)
        price_diff = max(Decimal('0'), self.p_alternate - self.p_solar)
        raw_payment = shortfall_kwh * price_diff

        cap_applied = False
        capped_payment = raw_payment
        cap_local = None

        if self.annual_cap_usd and self.annual_cap_usd > 0:
            # Convert cap to local currency if FX rate provided
            if self.fx_rate and self.fx_rate > 0:
                cap_local = self.annual_cap_usd * self.fx_rate
                if raw_payment > cap_local:
                    capped_payment = cap_local
                    cap_applied = True
            else:
                # Compare in USD (assume payment is in USD)
                if raw_payment > self.annual_cap_usd:
                    capped_payment = self.annual_cap_usd
                    cap_applied = True

        result = {
            'shortfall_kwh': float(shortfall_kwh),
            'price_differential': float(price_diff),
            'raw_payment': float(raw_payment.quantize(Decimal('0.01'))),
            'capped_payment': float(capped_payment.quantize(Decimal('0.01'))),
            'cap_applied': cap_applied,
            'cap_local_currency': float(cap_local) if cap_local else None,
        }

        logger.info(
            f"Shortfall payment: "
            f"shortfall={shortfall_kwh:.0f}kWh, "
            f"P_alt={self.p_alternate:.6f}, P_solar={self.p_solar:.6f}, "
            f"raw={raw_payment:.2f}, capped={capped_payment:.2f}, "
            f"cap_applied={cap_applied}"
        )

        return result
