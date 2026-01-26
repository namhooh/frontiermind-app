"""
CSV output formatter.

Flattens ExtractedData into CSV format with headers and line items.
"""

import csv
import io
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, List

from models.reports import ExtractedData, FileFormat, InvoiceReportType
from .base import BaseFormatter

logger = logging.getLogger(__name__)


class CSVFormatter(BaseFormatter):
    """
    Formatter that outputs report data as CSV.

    Supports:
    - Flattening hierarchical data to rows
    - Custom delimiter configuration
    - Header row generation
    - Multiple sheet simulation via sections
    """

    def get_file_format(self) -> FileFormat:
        """Return CSV file format."""
        return FileFormat.CSV

    def get_content_type(self) -> str:
        """Return CSV MIME type."""
        return "text/csv"

    def get_file_extension(self) -> str:
        """Return csv extension."""
        return "csv"

    def format(
        self,
        extracted_data: ExtractedData,
        template_config: Dict[str, Any]
    ) -> bytes:
        """
        Format extracted data as CSV.

        Args:
            extracted_data: The data to format
            template_config: Configuration options:
                - delimiter (str): Field delimiter (default: ',')
                - include_headers (bool): Include header row (default: True)
                - include_line_items (bool): Include line items section (default: True)

        Returns:
            CSV-encoded bytes (UTF-8 with BOM for Excel compatibility)

        Raises:
            ValueError: If formatting fails
        """
        logger.info(
            f"Formatting {extracted_data.report_type.value} data as CSV"
        )

        # Get config options
        delimiter = template_config.get('delimiter', ',')
        include_headers = template_config.get('include_headers', True)
        include_line_items = template_config.get('include_line_items', True)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter)

        try:
            # Write metadata section
            writer.writerow(['Report Type', extracted_data.report_type.value])
            writer.writerow(['Generated At', datetime.utcnow().isoformat()])

            if extracted_data.billing_period:
                writer.writerow(['Billing Period Start',
                    self._format_value(extracted_data.billing_period.start_date)])
                writer.writerow(['Billing Period End',
                    self._format_value(extracted_data.billing_period.end_date)])

            writer.writerow(['Total Records', extracted_data.metadata.record_count])
            if extracted_data.metadata.total_amount is not None:
                writer.writerow(['Total Amount', str(extracted_data.metadata.total_amount)])

            writer.writerow([])  # Blank row separator

            # Write headers section
            if extracted_data.headers and include_headers:
                writer.writerow(['--- INVOICES ---'])
                header_columns = self._get_header_columns(extracted_data.report_type)
                writer.writerow(header_columns)

                for header in extracted_data.headers:
                    row = [self._format_value(header.get(col)) for col in header_columns]
                    writer.writerow(row)

                writer.writerow([])  # Blank row separator

            # Write line items section
            if extracted_data.line_items and include_line_items:
                writer.writerow(['--- LINE ITEMS ---'])
                line_item_columns = self._get_line_item_columns(extracted_data.report_type)
                writer.writerow(line_item_columns)

                for item in extracted_data.line_items:
                    row = [self._format_value(item.get(col)) for col in line_item_columns]
                    writer.writerow(row)

            # Write comparison summary for comparison reports
            if extracted_data.comparison_data:
                writer.writerow([])
                writer.writerow(['--- VARIANCE SUMMARY ---'])
                for key, value in extracted_data.comparison_data.items():
                    writer.writerow([key, self._format_value(value)])

            # Get CSV content and add BOM for Excel compatibility
            csv_content = output.getvalue()
            return ('\ufeff' + csv_content).encode('utf-8')

        except Exception as e:
            logger.error(f"CSV formatting failed: {e}")
            raise ValueError(f"Failed to format data as CSV: {e}")

    def _format_value(self, value: Any) -> str:
        """Format a value for CSV output."""
        if value is None:
            return ''
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        return str(value)

    def _get_header_columns(self, report_type: InvoiceReportType) -> List[str]:
        """Get column names for the headers section based on report type."""
        base_columns = ['id', 'contract_name', 'project_name']

        if report_type == InvoiceReportType.INVOICE_TO_CLIENT:
            return base_columns + [
                'invoice_number', 'invoice_date', 'due_date',
                'total_amount', 'status'
            ]
        elif report_type == InvoiceReportType.INVOICE_EXPECTED:
            return base_columns + [
                'expected_total_amount', 'created_at'
            ]
        elif report_type == InvoiceReportType.INVOICE_RECEIVED:
            return base_columns + [
                'vendor_invoice_number', 'invoice_date', 'due_date',
                'total_amount', 'status', 'received_date'
            ]
        elif report_type == InvoiceReportType.INVOICE_COMPARISON:
            return [
                'id', 'contract_name', 'project_name',
                'expected_total_amount', 'received_total_amount',
                'header_variance', 'comparison_status'
            ]
        else:
            return base_columns + ['total_amount']

    def _get_line_item_columns(self, report_type: InvoiceReportType) -> List[str]:
        """Get column names for line items section based on report type."""
        if report_type == InvoiceReportType.INVOICE_TO_CLIENT:
            return [
                'id', 'invoice_header_id', 'description',
                'quantity', 'line_unit_price', 'line_total_amount',
                'line_item_type'
            ]
        elif report_type == InvoiceReportType.INVOICE_EXPECTED:
            return [
                'id', 'expected_invoice_header_id', 'description',
                'line_total_amount', 'line_item_type'
            ]
        elif report_type == InvoiceReportType.INVOICE_RECEIVED:
            return [
                'id', 'received_invoice_header_id', 'description',
                'line_total_amount', 'line_item_type'
            ]
        elif report_type == InvoiceReportType.INVOICE_COMPARISON:
            return [
                'id', 'invoice_comparison_id',
                'expected_description', 'expected_line_amount',
                'received_description', 'received_line_amount',
                'variance_amount'
            ]
        else:
            return ['id', 'description', 'line_total_amount']
