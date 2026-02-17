"""
Grid Reference Price (GRP) calculators.

The GRP is the utility grid tariff reference price used in GRID-discount
pricing models. Calculated annually from Utility Reference Invoices.

Formula: GRP = total_variable_charges / total_kwh_invoiced

Filters:
- Only variable energy charges (invoice_line_item_type_code == 'VARIABLE_ENERGY')
- Exclude TAX line items
- The method code is stored in clause_tariff.logic_parameters.grp_method.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class BaseGRPCalculator(ABC):
    """Abstract base for GRP calculation methods."""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def calculate(self, invoice_line_items: List[dict]) -> Optional[Decimal]:
        """
        Calculate Grid Reference Price from invoice line items.

        Args:
            invoice_line_items: List of dicts with keys:
                - line_total_amount: Decimal
                - quantity: Decimal (kWh)
                - invoice_line_item_type_code: str (e.g. 'VARIABLE_ENERGY', 'DEMAND', 'FIXED', 'TAX')

        Returns:
            GRP per kWh in local currency, or None if insufficient data.
        """
        pass


class UtilityVariableChargesToUCalculator(BaseGRPCalculator):
    """
    GRP = sum(variable energy charges, non-tax) / sum(kWh invoiced)

    Used by: Ghana GRID contracts (Exhibit A).

    Included: Variable energy charges from Utility Reference Invoices
    Excluded: VAT/taxes, demand charges, fixed charges
    """

    def calculate(self, invoice_line_items: List[dict]) -> Optional[Decimal]:
        if not invoice_line_items:
            logger.warning("GRP calculation: no invoice line items provided")
            return None

        total_variable_charges = Decimal('0')
        total_kwh = Decimal('0')

        for item in invoice_line_items:
            type_code = item.get('invoice_line_item_type_code', '')

            # Only include VARIABLE_ENERGY charges
            if type_code != 'VARIABLE_ENERGY':
                continue

            amount = Decimal(str(item.get('line_total_amount', 0) or 0))
            kwh = Decimal(str(item.get('quantity', 0) or 0))

            total_variable_charges += amount
            total_kwh += kwh

        if total_kwh <= 0:
            logger.warning(
                "GRP calculation: zero kWh invoiced after filtering. "
                f"Total items: {len(invoice_line_items)}"
            )
            return None

        grp = total_variable_charges / total_kwh

        logger.info(
            f"GRP (UtilityVariableChargesToU): "
            f"charges={total_variable_charges:.2f}, "
            f"kWh={total_kwh:.2f}, "
            f"GRP={grp:.6f}/kWh"
        )

        return grp


class UtilityTotalChargesCalculator(BaseGRPCalculator):
    """
    GRP = sum(all non-tax charges) / sum(kWh invoiced)

    Simpler method that includes all charges except taxes.
    """

    def calculate(self, invoice_line_items: List[dict]) -> Optional[Decimal]:
        if not invoice_line_items:
            return None

        total_charges = Decimal('0')
        total_kwh = Decimal('0')

        for item in invoice_line_items:
            type_code = item.get('invoice_line_item_type_code', '')

            # Exclude TAX line items
            if type_code == 'TAX':
                continue

            amount = Decimal(str(item.get('line_total_amount', 0) or 0))
            kwh = Decimal(str(item.get('quantity', 0) or 0))

            total_charges += amount
            total_kwh += kwh

        if total_kwh <= 0:
            return None

        grp = total_charges / total_kwh

        logger.info(
            f"GRP (UtilityTotalCharges): "
            f"charges={total_charges:.2f}, kWh={total_kwh:.2f}, "
            f"GRP={grp:.6f}/kWh"
        )

        return grp


# =============================================================================
# Calculator Registry
# =============================================================================

GRP_CALCULATORS: Dict[str, type] = {
    'utility_variable_charges_tou': UtilityVariableChargesToUCalculator,
    'utility_total_charges': UtilityTotalChargesCalculator,
}


def calculate_grp(
    logic_parameters: dict,
    invoice_line_items: List[dict]
) -> Optional[Decimal]:
    """
    Dispatch to the correct GRP calculator based on logic_parameters.

    Args:
        logic_parameters: clause_tariff.logic_parameters dict.
                          Must contain 'grp_method' key.
        invoice_line_items: Utility Reference Invoice line items.

    Returns:
        GRP per kWh, or None if insufficient data.
    """
    method = logic_parameters.get('grp_method')
    if not method:
        logger.warning("No grp_method specified in logic_parameters")
        return None

    calculator_class = GRP_CALCULATORS.get(method)
    if not calculator_class:
        raise ValueError(f"Unknown GRP method: {method}")

    return calculator_class(logic_parameters).calculate(invoice_line_items)
