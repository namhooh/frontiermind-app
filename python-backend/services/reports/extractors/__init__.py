"""
Report data extractors package.

Provides type-specific data extractors for each invoice report type.
Each extractor queries the appropriate database tables and transforms
the data into the ExtractedData format for report generation.
"""

from typing import Optional

from models.reports import InvoiceReportType
from .base import BaseExtractor
from .invoice_to_client import InvoiceToClientExtractor
from .invoice_expected import InvoiceExpectedExtractor
from .invoice_received import InvoiceReceivedExtractor
from .invoice_comparison import InvoiceComparisonExtractor


# Registry mapping report types to extractor classes
_EXTRACTOR_REGISTRY = {
    InvoiceReportType.INVOICE_TO_CLIENT: InvoiceToClientExtractor,
    InvoiceReportType.INVOICE_EXPECTED: InvoiceExpectedExtractor,
    InvoiceReportType.INVOICE_RECEIVED: InvoiceReceivedExtractor,
    InvoiceReportType.INVOICE_COMPARISON: InvoiceComparisonExtractor,
}


def get_extractor(report_type: InvoiceReportType) -> BaseExtractor:
    """
    Factory function to get the appropriate extractor for a report type.

    Args:
        report_type: The type of report to generate

    Returns:
        An instance of the appropriate extractor class

    Raises:
        ValueError: If report_type is not supported

    Example:
        >>> extractor = get_extractor(InvoiceReportType.INVOICE_TO_CLIENT)
        >>> data = extractor.extract(billing_period_id=1, org_id=1)
    """
    extractor_class = _EXTRACTOR_REGISTRY.get(report_type)

    if extractor_class is None:
        supported = [rt.value for rt in _EXTRACTOR_REGISTRY.keys()]
        raise ValueError(
            f"Unsupported report type: {report_type}. "
            f"Supported types: {supported}"
        )

    return extractor_class()


def get_extractor_by_name(report_type_name: str) -> BaseExtractor:
    """
    Factory function to get an extractor by report type name string.

    Args:
        report_type_name: String name of the report type
            (e.g., 'invoice_to_client')

    Returns:
        An instance of the appropriate extractor class

    Raises:
        ValueError: If report_type_name is not recognized

    Example:
        >>> extractor = get_extractor_by_name('invoice_to_client')
        >>> data = extractor.extract(billing_period_id=1, org_id=1)
    """
    try:
        report_type = InvoiceReportType(report_type_name)
    except ValueError:
        supported = [rt.value for rt in InvoiceReportType]
        raise ValueError(
            f"Unknown report type: '{report_type_name}'. "
            f"Supported types: {supported}"
        )

    return get_extractor(report_type)


__all__ = [
    'BaseExtractor',
    'InvoiceToClientExtractor',
    'InvoiceExpectedExtractor',
    'InvoiceReceivedExtractor',
    'InvoiceComparisonExtractor',
    'get_extractor',
    'get_extractor_by_name',
]
