"""
Report generator orchestrator.

Coordinates the report generation pipeline:
1. Load report configuration from database
2. Extract data using appropriate extractor
3. Format output using appropriate formatter
4. Upload to S3 storage
5. Update database with results
"""

import hashlib
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

from models.reports import (
    ExtractedData,
    InvoiceReportType,
    FileFormat,
    ReportStatus,
    ReportConfig,
)
from db.report_repository import ReportRepository
from db.invoice_repository import InvoiceRepository
from .extractors import get_extractor, BaseExtractor
from .formatters import get_formatter, BaseFormatter, is_format_available
from .storage import ReportStorage

logger = logging.getLogger(__name__)


class ReportGenerationError(Exception):
    """Exception raised when report generation fails."""
    pass


class ReportGenerator:
    """
    Main orchestrator for report generation.

    Coordinates the full pipeline from data extraction to file storage,
    handling status updates and error handling throughout.
    """

    def __init__(
        self,
        report_repository: Optional[ReportRepository] = None,
        invoice_repository: Optional[InvoiceRepository] = None,
        storage: Optional[ReportStorage] = None
    ):
        """
        Initialize the generator with dependencies.

        Args:
            report_repository: Repository for report metadata
            invoice_repository: Repository for invoice data
            storage: S3 storage service
        """
        self._report_repo = report_repository or ReportRepository()
        self._invoice_repo = invoice_repository or InvoiceRepository()
        self._storage = storage or ReportStorage()

    def generate(self, generated_report_id: int) -> str:
        """
        Generate a report and return the S3 file path.

        This is the main entry point for report generation. It:
        1. Loads the generated_report record
        2. Loads the associated template configuration
        3. Extracts data using the appropriate extractor
        4. Formats the data using the appropriate formatter
        5. Uploads to S3
        6. Updates the database with results

        Args:
            generated_report_id: ID of the generated_report record

        Returns:
            S3 file path of the generated report

        Raises:
            ReportGenerationError: If any step fails
            ValueError: If report not found or invalid configuration
        """
        start_time = time.time()
        logger.info(f"Starting report generation: id={generated_report_id}")

        try:
            # Step 1: Load report record and update status to processing
            report = self._load_report(generated_report_id)
            self._update_status(generated_report_id, ReportStatus.PROCESSING)

            # Step 2: Build configuration
            config = self._build_config(report)

            # Step 3: Extract data
            extracted_data = self._extract_data(config)

            # Step 4: Format output
            output_bytes = self._format_output(extracted_data, config)

            # Step 5: Upload to S3
            file_path = self._upload_to_storage(
                output_bytes,
                config,
                report['name']
            )

            # Step 6: Calculate file hash and update database
            file_hash = self._calculate_hash(output_bytes)
            summary_data = self._build_summary(extracted_data)

            self._report_repo.update_report_status(
                report_id=generated_report_id,
                status=ReportStatus.COMPLETED.value,
                file_path=file_path,
                file_size_bytes=len(output_bytes),
                file_hash=file_hash,
                record_count=extracted_data.metadata.record_count,
                summary_data=summary_data
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Report generation completed: id={generated_report_id}, "
                f"path={file_path}, size={len(output_bytes)}, time={elapsed_ms}ms"
            )

            return file_path

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.error(
                f"Report generation failed: id={generated_report_id}, "
                f"error={error_msg}, time={elapsed_ms}ms"
            )

            # Update status to failed
            try:
                self._report_repo.update_report_status(
                    report_id=generated_report_id,
                    status=ReportStatus.FAILED.value,
                    error=error_msg[:1000]  # Truncate long errors
                )
            except Exception as update_error:
                logger.error(f"Failed to update error status: {update_error}")

            raise ReportGenerationError(f"Report generation failed: {error_msg}") from e

    def generate_from_config(
        self,
        config: ReportConfig,
        report_name: str
    ) -> tuple[bytes, str]:
        """
        Generate a report directly from a config without database records.

        Useful for preview/testing or programmatic generation.

        Args:
            config: Report configuration
            report_name: Name for the output file

        Returns:
            Tuple of (output_bytes, suggested_filename)

        Raises:
            ReportGenerationError: If generation fails
        """
        logger.info(
            f"Generating report from config: type={config.report_type.value}, "
            f"format={config.file_format.value}"
        )

        try:
            # Extract data
            extracted_data = self._extract_data(config)

            # Format output
            output_bytes = self._format_output(extracted_data, config)

            # Build filename
            formatter = get_formatter(config.file_format)
            filename = formatter.get_filename(report_name)

            return output_bytes, filename

        except Exception as e:
            raise ReportGenerationError(f"Report generation failed: {e}") from e

    def _load_report(self, report_id: int) -> Dict[str, Any]:
        """Load and validate the generated_report record."""
        # We need org_id to load the report, but we don't have it yet
        # Use a direct query that doesn't require org_id for internal use
        from db.database import get_db_connection

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, organization_id, report_template_id,
                        report_type, name, report_status,
                        file_format, billing_period_id,
                        contract_id, project_id, invoice_direction
                    FROM generated_report
                    WHERE id = %s
                    """,
                    (report_id,)
                )
                report = cursor.fetchone()

        if not report:
            raise ValueError(f"Report not found: id={report_id}")

        report = dict(report)

        # Validate status
        if report['report_status'] not in ('pending', 'failed'):
            raise ValueError(
                f"Report cannot be regenerated: status={report['report_status']}"
            )

        return report

    def _build_config(self, report: Dict[str, Any]) -> ReportConfig:
        """Build ReportConfig from report record and template."""
        # Load template if available
        template_config = {}
        include_charts = True
        include_summary = True
        include_line_items = True
        logo_path = None
        header_text = None
        footer_text = None

        if report.get('report_template_id'):
            template = self._report_repo.get_template(
                report['report_template_id'],
                report['organization_id']
            )
            if template:
                template_config = template.get('template_config', {})
                include_charts = template.get('include_charts', True)
                include_summary = template.get('include_summary', True)
                include_line_items = template.get('include_line_items', True)
                logo_path = template.get('logo_path')
                header_text = template.get('header_text')
                footer_text = template.get('footer_text')

        return ReportConfig(
            template_id=report.get('report_template_id') or 0,
            report_type=InvoiceReportType(report['report_type']),
            file_format=FileFormat(report['file_format']),
            billing_period_id=report['billing_period_id'],
            organization_id=report['organization_id'],
            contract_id=report.get('contract_id'),
            project_id=report.get('project_id'),
            invoice_direction=report.get('invoice_direction'),
            include_charts=include_charts,
            include_summary=include_summary,
            include_line_items=include_line_items,
            template_config=template_config,
            logo_path=logo_path,
            header_text=header_text,
            footer_text=footer_text,
        )

    def _extract_data(self, config: ReportConfig) -> ExtractedData:
        """Extract data using the appropriate extractor."""
        extractor = get_extractor(config.report_type)

        logger.debug(
            f"Extracting data: type={config.report_type.value}, "
            f"billing_period={config.billing_period_id}"
        )

        return extractor.extract(
            billing_period_id=config.billing_period_id,
            org_id=config.organization_id,
            contract_id=config.contract_id,
            project_id=config.project_id,
            invoice_direction=config.invoice_direction
        )

    def _format_output(
        self,
        extracted_data: ExtractedData,
        config: ReportConfig
    ) -> bytes:
        """Format extracted data using the appropriate formatter."""
        if not is_format_available(config.file_format):
            raise ReportGenerationError(
                f"Format not available: {config.file_format.value}. "
                f"Check that required dependencies are installed."
            )

        formatter = get_formatter(config.file_format)

        # Build template config dict for formatter
        template_config = {
            **config.template_config,
            'include_charts': config.include_charts,
            'include_summary': config.include_summary,
            'include_line_items': config.include_line_items,
            'logo_path': config.logo_path,
            'header_text': config.header_text,
            'footer_text': config.footer_text,
        }

        logger.debug(f"Formatting output: format={config.file_format.value}")

        return formatter.format(extracted_data, template_config)

    def _upload_to_storage(
        self,
        content: bytes,
        config: ReportConfig,
        report_name: str
    ) -> str:
        """Upload report to S3 storage."""
        formatter = get_formatter(config.file_format)
        extension = formatter.get_file_extension()

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = self._sanitize_filename(report_name)
        filename = f"{safe_name}_{timestamp}.{extension}"

        logger.debug(f"Uploading to storage: filename={filename}")

        return self._storage.upload(
            content=content,
            org_id=config.organization_id,
            filename=filename,
            content_type=formatter.get_content_type()
        )

    def _calculate_hash(self, content: bytes) -> str:
        """Calculate SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    def _build_summary(self, extracted_data: ExtractedData) -> Dict[str, Any]:
        """Build summary data for quick display."""
        summary = {
            'record_count': extracted_data.metadata.record_count,
            'contract_names': extracted_data.metadata.contract_names,
        }

        if extracted_data.metadata.total_amount is not None:
            summary['total_amount'] = str(extracted_data.metadata.total_amount)

        if extracted_data.comparison_data:
            summary['comparison'] = {
                'total_variance': str(extracted_data.comparison_data.get('total_variance', 0)),
                'matched_count': extracted_data.comparison_data.get('matched_count', 0),
                'overbilled_count': extracted_data.comparison_data.get('overbilled_count', 0),
                'underbilled_count': extracted_data.comparison_data.get('underbilled_count', 0),
            }

        return summary

    def _update_status(self, report_id: int, status: ReportStatus) -> None:
        """Update report status in database."""
        self._report_repo.update_report_status(
            report_id=report_id,
            status=status.value
        )

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize a string for use as a filename."""
        # Replace spaces and special chars with underscores
        safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')
        result = ''.join(c if c in safe_chars else '_' for c in name)
        # Remove consecutive underscores
        while '__' in result:
            result = result.replace('__', '_')
        return result.strip('_')[:100]  # Limit length
