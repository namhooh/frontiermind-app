"""
Schema Validator for Meter Data

Validates incoming meter data against expected schemas for each source type.
Returns validation results with detailed error messages.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a single validation error."""
    field: str
    error: str
    sample_value: Any = None
    row_index: Optional[int] = None


@dataclass
class ValidationResult:
    """Result of schema validation."""
    is_valid: bool
    errors: List[Dict] = field(default_factory=list)
    error_message: Optional[str] = None
    rows_validated: int = 0
    rows_with_errors: int = 0


class SchemaValidator:
    """Validates meter data against expected schemas."""

    # Required fields for canonical model
    REQUIRED_FIELDS = {
        'timestamp',  # or reading_timestamp, datetime, etc.
    }

    # Field aliases for different sources
    FIELD_ALIASES = {
        'timestamp': ['timestamp', 'reading_timestamp', 'datetime', 'date_time', 'time'],
        'energy_wh': ['energy_wh', 'energy', 'production', 'generation', 'kwh', 'wh'],
        'power_w': ['power_w', 'power', 'watts', 'w'],
    }

    # Source-specific schemas
    SOURCE_SCHEMAS = {
        'solaredge': {
            'required': ['timestamp'],
            'optional': ['energy', 'power', 'site_id', 'device_id'],
            'timestamp_formats': ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'],
        },
        'enphase': {
            'required': ['end_at'],
            'optional': ['enwh', 'devices_reporting'],
            'timestamp_formats': ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'],
        },
        'sma': {
            'required': ['timestamp'],
            'optional': ['total_yield', 'power'],
            'timestamp_formats': ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S'],
        },
        'goodwe': {
            'required': ['time'],
            'optional': ['pac', 'e_day', 'e_total'],
            'timestamp_formats': ['%Y-%m-%d %H:%M:%S'],
        },
        'snowflake': {
            'required': ['timestamp'],
            'optional': ['energy_wh', 'power_w', 'site_id'],
            'timestamp_formats': ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'],
        },
        'manual': {
            'required': ['timestamp'],
            'optional': ['energy_wh', 'power_w', 'energy_kwh', 'value'],
            'timestamp_formats': [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y/%m/%d %H:%M:%S',
                '%m/%d/%Y %H:%M:%S',
                '%Y-%m-%d',
            ],
        },
    }

    def validate(
        self,
        data: Union[List[Dict], Dict],
        source_type: str
    ) -> ValidationResult:
        """
        Validate data against schema for source type.

        Args:
            data: List of records or single record (will be converted to list)
            source_type: Source type (solaredge, enphase, etc.)

        Returns:
            ValidationResult with validation status and errors
        """
        # Normalize to list
        if isinstance(data, dict):
            # Check if it's a wrapper with 'readings' or 'data' key
            if 'readings' in data:
                records = data['readings']
            elif 'data' in data:
                records = data['data']
            elif 'values' in data:
                records = data['values']
            else:
                records = [data]
        else:
            records = data

        if not records:
            return ValidationResult(
                is_valid=False,
                error_message="No records found in data",
                errors=[{'field': 'data', 'error': 'Empty dataset'}]
            )

        # Get schema for source type
        schema = self.SOURCE_SCHEMAS.get(source_type, self.SOURCE_SCHEMAS['manual'])

        errors = []
        rows_with_errors = 0

        for i, record in enumerate(records):
            record_errors = self._validate_record(record, schema, i)
            if record_errors:
                errors.extend(record_errors)
                rows_with_errors += 1

            # Limit total errors to prevent memory issues
            if len(errors) >= 100:
                errors.append({
                    'field': '_truncated',
                    'error': f'Error limit reached, {len(records) - i - 1} more records not validated'
                })
                break

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=[e if isinstance(e, dict) else e.__dict__ for e in errors],
            error_message=f"Validation failed: {len(errors)} errors in {rows_with_errors} rows" if not is_valid else None,
            rows_validated=len(records),
            rows_with_errors=rows_with_errors
        )

    def _validate_record(
        self,
        record: Dict,
        schema: Dict,
        row_index: int
    ) -> List[ValidationError]:
        """Validate a single record against schema."""
        errors = []

        # Check required fields
        for required_field in schema['required']:
            if not self._has_field(record, required_field):
                errors.append(ValidationError(
                    field=required_field,
                    error=f"Missing required field",
                    row_index=row_index
                ))

        # Validate timestamp
        timestamp_field = self._find_field(record, self.FIELD_ALIASES['timestamp'])
        if timestamp_field:
            timestamp_value = record.get(timestamp_field)
            if timestamp_value:
                if not self._is_valid_timestamp(timestamp_value, schema['timestamp_formats']):
                    errors.append(ValidationError(
                        field=timestamp_field,
                        error="Invalid timestamp format",
                        sample_value=str(timestamp_value)[:50],
                        row_index=row_index
                    ))

        # Validate numeric fields
        for numeric_field in ['energy_wh', 'power_w']:
            field_name = self._find_field(record, self.FIELD_ALIASES.get(numeric_field, [numeric_field]))
            if field_name and record.get(field_name) is not None:
                value = record[field_name]
                if not self._is_valid_numeric(value):
                    errors.append(ValidationError(
                        field=field_name,
                        error="Invalid numeric value",
                        sample_value=str(value)[:50],
                        row_index=row_index
                    ))

        return errors

    def _has_field(self, record: Dict, field_name: str) -> bool:
        """Check if record has field (considering aliases)."""
        aliases = self.FIELD_ALIASES.get(field_name, [field_name])
        return any(alias in record for alias in aliases)

    def _find_field(self, record: Dict, aliases: List[str]) -> Optional[str]:
        """Find which alias exists in record."""
        for alias in aliases:
            if alias in record:
                return alias
        return None

    def _is_valid_timestamp(self, value: Any, formats: List[str]) -> bool:
        """Check if value is a valid timestamp."""
        if value is None:
            return False

        # Already a datetime
        if isinstance(value, datetime):
            return True

        # Unix timestamp (integer or float)
        if isinstance(value, (int, float)):
            try:
                # Check if it's a reasonable timestamp (between year 2000 and 2100)
                if 946684800 < value < 4102444800:
                    return True
                # Might be milliseconds
                if 946684800000 < value < 4102444800000:
                    return True
            except:
                pass
            return False

        # String timestamp
        if isinstance(value, str):
            for fmt in formats:
                try:
                    datetime.strptime(value, fmt)
                    return True
                except ValueError:
                    continue

            # Try ISO format
            try:
                datetime.fromisoformat(value.replace('Z', '+00:00'))
                return True
            except:
                pass

        return False

    def _is_valid_numeric(self, value: Any) -> bool:
        """Check if value is a valid numeric value."""
        if value is None:
            return True  # NULL is valid

        if isinstance(value, (int, float)):
            return True

        if isinstance(value, str):
            try:
                float(value.replace(',', ''))
                return True
            except ValueError:
                return False

        return False
