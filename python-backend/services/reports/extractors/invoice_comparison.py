"""
Invoice comparison/variance analysis data extractor.

Extracts data for generating variance analysis reports from
invoice_comparison and invoice_comparison_line_item tables,
along with related expected and received invoice data.
"""

import logging
from typing import Optional

from models.reports import ExtractedData, InvoiceReportType
from .base import BaseExtractor

logger = logging.getLogger(__name__)


class InvoiceComparisonExtractor(BaseExtractor):
    """
    Extractor for invoice_comparison report type.

    Queries invoice_comparison and invoice_comparison_line_item tables,
    along with expected and received invoice tables for context, to
    extract data for variance analysis reports.
    """

    def get_report_type(self) -> InvoiceReportType:
        """Return the report type this extractor handles."""
        return InvoiceReportType.INVOICE_COMPARISON

    def extract(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None
    ) -> ExtractedData:
        """
        Extract invoice comparison data for report generation.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (required for security filtering)
            contract_id: Optional contract filter
            project_id: Optional project filter

        Returns:
            ExtractedData containing comparison records, line items,
            metadata, and aggregated variance statistics

        Raises:
            ValueError: If parameters are invalid
            psycopg2.Error: If database query fails
        """
        # Validate parameters
        self.validate_params(billing_period_id, org_id, contract_id, project_id)

        logger.info(
            f"Extracting invoice_comparison data: "
            f"billing_period_id={billing_period_id}, org_id={org_id}, "
            f"contract_id={contract_id}, project_id={project_id}"
        )

        # Query the repository
        raw_data = self._invoice_repo.get_invoice_comparison_data(
            billing_period_id=billing_period_id,
            org_id=org_id,
            contract_id=contract_id,
            project_id=project_id
        )

        # Handle empty results
        if not raw_data.get('headers'):
            logger.warning(
                f"No invoice_comparison data found for billing_period_id={billing_period_id}"
            )
            return self._handle_empty_results(
                InvoiceReportType.INVOICE_COMPARISON,
                billing_period_id
            )

        # Transform to ExtractedData
        extracted = self._build_extracted_data(
            raw_data,
            InvoiceReportType.INVOICE_COMPARISON
        )

        # Log comparison statistics
        comp_data = raw_data.get('comparison_data', {})
        logger.info(
            f"Extracted invoice_comparison data: "
            f"{len(extracted.headers)} comparisons, "
            f"{len(extracted.line_items)} line items, "
            f"total_variance={comp_data.get('total_variance', 0)}, "
            f"matched={comp_data.get('matched_count', 0)}, "
            f"overbilled={comp_data.get('overbilled_count', 0)}, "
            f"underbilled={comp_data.get('underbilled_count', 0)}"
        )

        return extracted
