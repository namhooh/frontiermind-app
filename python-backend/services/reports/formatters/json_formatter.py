"""
JSON output formatter.

Serializes ExtractedData to JSON format with configurable options.
"""

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any

from models.reports import ExtractedData, FileFormat
from .base import BaseFormatter

logger = logging.getLogger(__name__)


class JSONFormatter(BaseFormatter):
    """
    Formatter that outputs report data as JSON.

    Supports:
    - Pretty printing (configurable indent)
    - Custom datetime serialization
    - Decimal to string conversion
    """

    def get_file_format(self) -> FileFormat:
        """Return JSON file format."""
        return FileFormat.JSON

    def get_content_type(self) -> str:
        """Return JSON MIME type."""
        return "application/json"

    def get_file_extension(self) -> str:
        """Return json extension."""
        return "json"

    def format(
        self,
        extracted_data: ExtractedData,
        template_config: Dict[str, Any]
    ) -> bytes:
        """
        Format extracted data as JSON.

        Args:
            extracted_data: The data to format
            template_config: Configuration options:
                - pretty_print (bool): Enable indented output (default: True)
                - indent (int): Indentation level (default: 2)

        Returns:
            JSON-encoded bytes

        Raises:
            ValueError: If serialization fails
        """
        logger.info(
            f"Formatting {extracted_data.report_type.value} data as JSON"
        )

        # Get config options
        pretty_print = template_config.get('pretty_print', True)
        indent = template_config.get('indent', 2) if pretty_print else None

        # Build output structure
        output = {
            'report_type': extracted_data.report_type.value,
            'generated_at': datetime.utcnow().isoformat(),
            'billing_period': None,
            'metadata': {
                'total_amount': None,
                'record_count': extracted_data.metadata.record_count,
                'contract_names': extracted_data.metadata.contract_names,
            },
            'headers': extracted_data.headers,
            'line_items': extracted_data.line_items,
        }

        # Add billing period if available
        if extracted_data.billing_period:
            output['billing_period'] = {
                'id': extracted_data.billing_period.id,
                'start_date': extracted_data.billing_period.start_date.isoformat()
                    if extracted_data.billing_period.start_date else None,
                'end_date': extracted_data.billing_period.end_date.isoformat()
                    if extracted_data.billing_period.end_date else None,
            }

        # Add total amount if available
        if extracted_data.metadata.total_amount is not None:
            output['metadata']['total_amount'] = str(extracted_data.metadata.total_amount)

        # Add comparison data for invoice_comparison reports
        if extracted_data.comparison_data:
            output['comparison_data'] = self._serialize_comparison_data(
                extracted_data.comparison_data
            )

        try:
            json_str = json.dumps(
                output,
                indent=indent,
                default=self._json_serializer,
                ensure_ascii=False
            )
            return json_str.encode('utf-8')
        except (TypeError, ValueError) as e:
            logger.error(f"JSON serialization failed: {e}")
            raise ValueError(f"Failed to serialize data to JSON: {e}")

    def _json_serializer(self, obj: Any) -> Any:
        """
        Custom JSON serializer for non-standard types.

        Handles:
        - datetime/date objects -> ISO format string
        - Decimal -> string
        - Other -> string representation
        """
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        # Fallback to string representation
        return str(obj)

    def _serialize_comparison_data(self, comparison_data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize comparison data with proper type handling."""
        result = {}
        for key, value in comparison_data.items():
            if isinstance(value, Decimal):
                result[key] = str(value)
            elif isinstance(value, (datetime, date)):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result
