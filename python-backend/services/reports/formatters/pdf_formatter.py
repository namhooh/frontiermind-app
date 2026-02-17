"""
PDF output formatter using WeasyPrint and Jinja2 templates.

Renders HTML templates with data and converts to PDF.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from models.reports import ExtractedData, FileFormat, InvoiceReportType
from .base import BaseFormatter

logger = logging.getLogger(__name__)

# Lazy import dependencies
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from utils.jinja_filters import register_filters
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logger.warning("jinja2 not installed - PDF formatting unavailable")

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    logger.warning("weasyprint not installed - PDF formatting unavailable")


class PDFFormatter(BaseFormatter):
    """
    Formatter that outputs report data as PDF using WeasyPrint.

    Supports:
    - Jinja2 HTML templates per report type
    - CSS styling for professional output
    - Custom branding (logo, header/footer text)
    - Page headers and footers
    """

    # Template directory relative to this file
    TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

    # Template file mapping by report type
    TEMPLATE_MAP = {
        InvoiceReportType.INVOICE_TO_CLIENT: "invoice_to_client.html",
        InvoiceReportType.INVOICE_EXPECTED: "invoice_expected.html",
        InvoiceReportType.INVOICE_RECEIVED: "invoice_received.html",
        InvoiceReportType.INVOICE_COMPARISON: "invoice_comparison.html",
    }

    def __init__(self):
        """Initialize formatter and check dependencies."""
        if not JINJA2_AVAILABLE:
            raise ImportError(
                "jinja2 is required for PDF formatting. "
                "Install with: pip install jinja2"
            )
        if not WEASYPRINT_AVAILABLE:
            raise ImportError(
                "weasyprint is required for PDF formatting. "
                "Install with: pip install weasyprint"
            )

        # Initialize Jinja2 environment
        self._env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATES_DIR)),
            autoescape=select_autoescape(['html', 'xml'])
        )

        # Register custom filters from shared utility
        register_filters(self._env)

    def get_file_format(self) -> FileFormat:
        """Return PDF file format."""
        return FileFormat.PDF

    def get_content_type(self) -> str:
        """Return PDF MIME type."""
        return "application/pdf"

    def get_file_extension(self) -> str:
        """Return pdf extension."""
        return "pdf"

    def format(
        self,
        extracted_data: ExtractedData,
        template_config: Dict[str, Any]
    ) -> bytes:
        """
        Format extracted data as PDF.

        Args:
            extracted_data: The data to format
            template_config: Configuration options:
                - logo_path (str): Path to logo image
                - header_text (str): Custom header text
                - footer_text (str): Custom footer text
                - include_charts (bool): Include charts (not yet implemented)

        Returns:
            PDF file as bytes

        Raises:
            ValueError: If formatting fails
        """
        logger.info(
            f"Formatting {extracted_data.report_type.value} data as PDF"
        )

        try:
            # Get the appropriate template
            template_name = self.TEMPLATE_MAP.get(
                extracted_data.report_type,
                "base.html"
            )

            # Check if template exists, fall back to base
            template_path = self.TEMPLATES_DIR / template_name
            if not template_path.exists():
                logger.warning(
                    f"Template {template_name} not found, using base template"
                )
                template_name = "base.html"

            template = self._env.get_template(template_name)

            # Build template context
            context = self._build_context(extracted_data, template_config)

            # Render HTML
            html_content = template.render(**context)

            # Load CSS
            css_path = self.TEMPLATES_DIR / "styles.css"
            stylesheets = []
            if css_path.exists():
                stylesheets.append(CSS(filename=str(css_path)))

            # Convert to PDF
            html = HTML(string=html_content, base_url=str(self.TEMPLATES_DIR))
            pdf_bytes = html.write_pdf(stylesheets=stylesheets)

            logger.info(
                f"Generated PDF: {len(pdf_bytes)} bytes"
            )
            return pdf_bytes

        except Exception as e:
            logger.error(f"PDF formatting failed: {e}")
            raise ValueError(f"Failed to format data as PDF: {e}")

    def _build_context(
        self,
        extracted_data: ExtractedData,
        template_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the template context dictionary."""
        context = {
            # Report metadata
            'report_type': extracted_data.report_type.value,
            'report_type_label': self._get_report_type_label(extracted_data.report_type),
            'generated_at': datetime.utcnow(),

            # Billing period
            'billing_period': None,

            # Data
            'headers': extracted_data.headers,
            'line_items': extracted_data.line_items,
            'metadata': {
                'total_amount': extracted_data.metadata.total_amount,
                'record_count': extracted_data.metadata.record_count,
                'contract_names': extracted_data.metadata.contract_names,
            },

            # Comparison data (for comparison reports)
            'comparison_data': extracted_data.comparison_data,

            # Branding from template_config
            'logo_path': template_config.get('logo_path'),
            'header_text': template_config.get('header_text', 'Invoice Report'),
            'footer_text': template_config.get('footer_text', 'Generated by FrontierMind'),

            # Display options
            'include_charts': template_config.get('include_charts', False),
            'include_summary': template_config.get('include_summary', True),
            'include_line_items': template_config.get('include_line_items', True),
        }

        # Add billing period if available
        if extracted_data.billing_period:
            context['billing_period'] = {
                'id': extracted_data.billing_period.id,
                'start_date': extracted_data.billing_period.start_date,
                'end_date': extracted_data.billing_period.end_date,
            }

        return context

    def _get_report_type_label(self, report_type: InvoiceReportType) -> str:
        """Get human-readable label for report type."""
        labels = {
            InvoiceReportType.INVOICE_TO_CLIENT: "Invoice to Client",
            InvoiceReportType.INVOICE_EXPECTED: "Expected Invoice",
            InvoiceReportType.INVOICE_RECEIVED: "Received Invoice",
            InvoiceReportType.INVOICE_COMPARISON: "Invoice Comparison",
        }
        return labels.get(report_type, report_type.value)

