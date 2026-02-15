"""
Base extractor interface for report data extraction.

Defines the abstract interface that all report type extractors must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from models.reports import ExtractedData, InvoiceReportType, ExtractedDataMetadata, BillingPeriodInfo
from db.invoice_repository import InvoiceRepository
from db.report_repository import ReportRepository

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """
    Abstract base class for report data extractors.

    Each report type (invoice_to_client, invoice_expected, etc.) has a
    concrete implementation that extracts data from the appropriate tables
    and transforms it into the ExtractedData format.
    """

    def __init__(
        self,
        invoice_repository: Optional[InvoiceRepository] = None,
        report_repository: Optional[ReportRepository] = None
    ):
        """
        Initialize the extractor with repository dependencies.

        Args:
            invoice_repository: Repository for invoice data queries
            report_repository: Repository for billing period lookups
        """
        self._invoice_repo = invoice_repository or InvoiceRepository()
        self._report_repo = report_repository or ReportRepository()

    @abstractmethod
    def get_report_type(self) -> InvoiceReportType:
        """
        Return the report type this extractor handles.

        Returns:
            InvoiceReportType enum value
        """
        pass

    @abstractmethod
    def extract(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        invoice_direction: Optional[str] = None
    ) -> ExtractedData:
        """
        Extract invoice data for report generation.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (required for security filtering)
            contract_id: Optional contract filter
            project_id: Optional project filter
            invoice_direction: Optional direction filter (receivable/payable)

        Returns:
            ExtractedData containing headers, line items, and metadata

        Raises:
            ValueError: If parameters are invalid
            psycopg2.Error: If database query fails
        """
        pass

    def validate_params(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None
    ) -> None:
        """
        Validate extraction parameters.

        Args:
            billing_period_id: Billing period ID
            org_id: Organization ID
            contract_id: Optional contract ID
            project_id: Optional project ID

        Raises:
            ValueError: If any parameter is invalid
        """
        if billing_period_id is None or billing_period_id <= 0:
            raise ValueError("billing_period_id must be a positive integer")

        if org_id is None or org_id <= 0:
            raise ValueError("org_id must be a positive integer")

        if contract_id is not None and contract_id <= 0:
            raise ValueError("contract_id must be a positive integer if provided")

        if project_id is not None and project_id <= 0:
            raise ValueError("project_id must be a positive integer if provided")

    def _build_extracted_data(
        self,
        raw_data: dict,
        report_type: InvoiceReportType
    ) -> ExtractedData:
        """
        Transform raw repository data into ExtractedData model.

        Args:
            raw_data: Dictionary from invoice repository with:
                - headers: List of header records
                - line_items: List of line item records
                - billing_period: Period info dict
                - metadata: Summary statistics dict
            report_type: The report type enum

        Returns:
            ExtractedData model instance
        """
        # Build billing period info
        billing_period = None
        if raw_data.get('billing_period'):
            bp = raw_data['billing_period']
            billing_period = BillingPeriodInfo(
                id=bp['id'],
                start_date=bp['start_date'],
                end_date=bp['end_date']
            )

        # Build metadata
        meta = raw_data.get('metadata', {})
        metadata = ExtractedDataMetadata(
            total_amount=meta.get('total_amount'),
            record_count=meta.get('record_count', 0),
            contract_names=meta.get('contract_names', [])
        )

        return ExtractedData(
            report_type=report_type,
            headers=raw_data.get('headers', []),
            line_items=raw_data.get('line_items', []),
            billing_period=billing_period,
            metadata=metadata,
            comparison_data=raw_data.get('comparison_data')
        )

    def _handle_empty_results(
        self,
        report_type: InvoiceReportType,
        billing_period_id: int
    ) -> ExtractedData:
        """
        Create an empty ExtractedData for cases with no results.

        Args:
            report_type: The report type enum
            billing_period_id: The billing period that was queried

        Returns:
            ExtractedData with empty collections
        """
        # Try to get billing period info even if no invoice data
        billing_period = None
        try:
            bp_data = self._report_repo.get_billing_period(billing_period_id)
            if bp_data:
                billing_period = BillingPeriodInfo(
                    id=bp_data['id'],
                    start_date=bp_data['start_date'],
                    end_date=bp_data['end_date']
                )
        except Exception as e:
            logger.warning(f"Failed to get billing period info: {e}")

        return ExtractedData(
            report_type=report_type,
            headers=[],
            line_items=[],
            billing_period=billing_period,
            metadata=ExtractedDataMetadata(
                record_count=0,
                contract_names=[]
            )
        )
