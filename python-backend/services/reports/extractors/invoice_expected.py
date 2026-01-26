"""
Expected invoice data extractor.

Extracts data for generating expected invoice reports from
expected_invoice_header and expected_invoice_line_item tables.
"""

import logging
from typing import Optional

from models.reports import ExtractedData, InvoiceReportType
from .base import BaseExtractor

logger = logging.getLogger(__name__)


class InvoiceExpectedExtractor(BaseExtractor):
    """
    Extractor for invoice_expected report type.

    Queries expected_invoice_header and expected_invoice_line_item tables
    to extract data for expected invoice reports based on contract terms.
    """

    def get_report_type(self) -> InvoiceReportType:
        """Return the report type this extractor handles."""
        return InvoiceReportType.INVOICE_EXPECTED

    def extract(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None
    ) -> ExtractedData:
        """
        Extract expected invoice data for report generation.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (required for security filtering)
            contract_id: Optional contract filter
            project_id: Optional project filter

        Returns:
            ExtractedData containing expected invoice headers, line items, and metadata

        Raises:
            ValueError: If parameters are invalid
            psycopg2.Error: If database query fails
        """
        # Validate parameters
        self.validate_params(billing_period_id, org_id, contract_id, project_id)

        logger.info(
            f"Extracting invoice_expected data: "
            f"billing_period_id={billing_period_id}, org_id={org_id}, "
            f"contract_id={contract_id}, project_id={project_id}"
        )

        # Query the repository
        raw_data = self._invoice_repo.get_invoice_expected_data(
            billing_period_id=billing_period_id,
            org_id=org_id,
            contract_id=contract_id,
            project_id=project_id
        )

        # Handle empty results
        if not raw_data.get('headers'):
            logger.warning(
                f"No invoice_expected data found for billing_period_id={billing_period_id}"
            )
            return self._handle_empty_results(
                InvoiceReportType.INVOICE_EXPECTED,
                billing_period_id
            )

        # Transform to ExtractedData
        extracted = self._build_extracted_data(
            raw_data,
            InvoiceReportType.INVOICE_EXPECTED
        )

        logger.info(
            f"Extracted invoice_expected data: "
            f"{len(extracted.headers)} expected invoices, "
            f"{len(extracted.line_items)} line items"
        )

        return extracted
