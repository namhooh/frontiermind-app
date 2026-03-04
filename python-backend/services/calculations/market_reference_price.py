"""
Market Reference Price (MRP) calculators.

The MRP is the utility grid tariff reference price used in GRID-discount
pricing models. Calculated annually from Utility Reference Invoices.

Formula: MRP = total_variable_charges / total_kwh_invoiced

Filters:
- Only variable energy charges (invoice_line_item_type_code == 'VARIABLE_ENERGY')
- Exclude TAX line items
- The method code is stored in clause_tariff.logic_parameters.mrp_method.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class BaseMRPCalculator(ABC):
    """Abstract base for MRP calculation methods."""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def calculate(self, invoice_line_items: List[dict]) -> Optional[Decimal]:
        """
        Calculate Market Reference Price from invoice line items.

        Args:
            invoice_line_items: List of dicts with keys:
                - line_total_amount: Decimal
                - quantity: Decimal (kWh)
                - invoice_line_item_type_code: str (e.g. 'VARIABLE_ENERGY', 'DEMAND', 'FIXED', 'TAX')

        Returns:
            MRP per kWh in local currency, or None if insufficient data.
        """
        pass


class UtilityVariableChargesToUCalculator(BaseMRPCalculator):
    """
    MRP = sum(variable energy charges, non-tax) / sum(kWh invoiced)

    Used by: Ghana GRID contracts (Exhibit A).

    Included: Variable energy charges from Utility Reference Invoices
    Excluded: VAT/taxes, demand charges, fixed charges
    """

    def calculate(self, invoice_line_items: List[dict]) -> Optional[Decimal]:
        if not invoice_line_items:
            logger.warning("MRP calculation: no invoice line items provided")
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
                "MRP calculation: zero kWh invoiced after filtering. "
                f"Total items: {len(invoice_line_items)}"
            )
            return None

        mrp = total_variable_charges / total_kwh

        logger.info(
            f"MRP (UtilityVariableChargesToU): "
            f"charges={total_variable_charges:.2f}, "
            f"kWh={total_kwh:.2f}, "
            f"MRP={mrp:.6f}/kWh"
        )

        return mrp


class UtilityTotalChargesCalculator(BaseMRPCalculator):
    """
    MRP = sum(all non-tax charges) / sum(kWh invoiced)

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

        mrp = total_charges / total_kwh

        logger.info(
            f"MRP (UtilityTotalCharges): "
            f"charges={total_charges:.2f}, kWh={total_kwh:.2f}, "
            f"MRP={mrp:.6f}/kWh"
        )

        return mrp


# =============================================================================
# Calculator Registry
# =============================================================================

MRP_CALCULATORS: Dict[str, type] = {
    'utility_variable_charges_tou': UtilityVariableChargesToUCalculator,
    'utility_total_charges': UtilityTotalChargesCalculator,
}


def calculate_mrp(
    logic_parameters: dict,
    invoice_line_items: List[dict]
) -> Optional[Decimal]:
    """
    Dispatch to the correct MRP calculator based on logic_parameters.

    Args:
        logic_parameters: clause_tariff.logic_parameters dict.
                          Must contain 'mrp_method' key.
        invoice_line_items: Utility Reference Invoice line items.

    Returns:
        MRP per kWh, or None if insufficient data.
    """
    method = logic_parameters.get('mrp_method') or 'utility_variable_charges_tou'
    if method == 'utility_variable_charges_tou' and not logic_parameters.get('mrp_method'):
        logger.info("No mrp_method specified — defaulting to utility_variable_charges_tou")

    calculator_class = MRP_CALCULATORS.get(method)
    if not calculator_class:
        raise ValueError(f"Unknown MRP method: {method}")

    return calculator_class(logic_parameters).calculate(invoice_line_items)
