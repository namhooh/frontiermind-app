"""
Invoice-to-client data extractor.

Extracts data for generating client invoices from invoice_header
and invoice_line_item tables.
"""

import logging
from typing import Optional

from models.reports import ExtractedData, InvoiceReportType
from .base import BaseExtractor

logger = logging.getLogger(__name__)


class InvoiceToClientExtractor(BaseExtractor):
    """
    Extractor for invoice_to_client report type.

    Queries invoice_header and invoice_line_item tables to extract
    data for generating invoices to be sent to clients.
    """

    def get_report_type(self) -> InvoiceReportType:
        """Return the report type this extractor handles."""
        return InvoiceReportType.INVOICE_TO_CLIENT

    def extract(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        invoice_direction: Optional[str] = None
    ) -> ExtractedData:
        """
        Extract invoice-to-client data for report generation.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (required for security filtering)
            contract_id: Optional contract filter
            project_id: Optional project filter
            invoice_direction: Accepted for interface consistency but not used
                (invoice_header has no direction column)

        Returns:
            ExtractedData containing invoice headers, line items, and metadata

        Raises:
            ValueError: If parameters are invalid
            psycopg2.Error: If database query fails
        """
        # Validate parameters
        self.validate_params(billing_period_id, org_id, contract_id, project_id)

        logger.info(
            f"Extracting invoice_to_client data: "
            f"billing_period_id={billing_period_id}, org_id={org_id}, "
            f"contract_id={contract_id}, project_id={project_id}"
        )

        # Query the repository
        raw_data = self._invoice_repo.get_invoice_to_client_data(
            billing_period_id=billing_period_id,
            org_id=org_id,
            contract_id=contract_id,
            project_id=project_id
        )

        # Handle empty results
        if not raw_data.get('headers'):
            logger.warning(
                f"No invoice_to_client data found for billing_period_id={billing_period_id}"
            )
            return self._handle_empty_results(
                InvoiceReportType.INVOICE_TO_CLIENT,
                billing_period_id
            )

        # Transform to ExtractedData
        extracted = self._build_extracted_data(
            raw_data,
            InvoiceReportType.INVOICE_TO_CLIENT
        )

        logger.info(
            f"Extracted invoice_to_client data: "
            f"{len(extracted.headers)} invoices, "
            f"{len(extracted.line_items)} line items"
        )

        return extracted
