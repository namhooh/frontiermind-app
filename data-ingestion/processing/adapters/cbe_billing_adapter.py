"""
CBE Billing Adapter — CrossBoundary Energy-specific billing aggregate mapping.

Maps CBE Snowflake field names to canonical meter_aggregate columns.
Other clients will have their own adapter with different field mappings.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import ValidationResult

logger = logging.getLogger(__name__)


class CBEBillingAdapter:
    """CBE-specific adapter for billing aggregate ingestion.

    Maps CBE Snowflake field names to canonical meter_aggregate columns.
    Other clients will have their own adapter with different field mappings.
    """

    # CBE field names → canonical meter_aggregate columns
    FIELD_MAP = {
        'BILL_DATE': 'bill_date',
        'CONTRACT_LINE_UNIQUE_ID': 'contract_line_unique_id',
        'OPENING_READING': 'opening_reading',
        'CLOSING_READING': 'closing_reading',
        'UTILIZED_READING': 'utilized_reading',
        'DISCOUNT_READING': 'discount_reading',
        'SOURCED_ENERGY': 'sourced_energy',
        'CUSTOMER_NUMBER': 'site_id',
        'FACILITY': 'device_id',
        'PRODUCT_DESC': 'product_desc',
        'METERED_AVAILABLE': 'metered_available',
        'QUANTITY_UNIT': 'quantity_unit',
        'CONTRACT_NUMBER': 'contract_number',
        'CONTRACT_LINE': 'contract_line',
        'CONTRACT_CURRENCY': 'currency',
        'TAX_RULE': 'tax_rule',
        'PAYMENT_TERMS': 'payment_terms',
        'METER_READING_UNIQUE_ID': 'external_reading_id',
    }

    # CBE-specific required fields (accept both SCREAMING_SNAKE and snake_case)
    REQUIRED_FIELDS = {'BILL_DATE', 'bill_date'}

    # CBE-specific: fields that go into source_metadata (not canonical columns)
    METADATA_FIELDS = {
        'product_desc', 'metered_available', 'contract_number',
        'contract_line', 'currency', 'tax_rule', 'payment_terms',
        'external_reading_id', 'quantity_unit',
    }

    def validate(self, records: List[Dict[str, Any]]) -> ValidationResult:
        """Validate CBE billing records.

        Checks:
        - BILL_DATE (or bill_date) is present
        - At least one of: UTILIZED_READING, or both OPENING_READING + CLOSING_READING
        - Numeric reading fields are actually numeric
        """
        errors = []
        for idx, record in enumerate(records):
            row_errors = []

            # Check BILL_DATE present
            has_bill_date = any(
                record.get(f) for f in ('BILL_DATE', 'bill_date')
            )
            if not has_bill_date:
                row_errors.append({
                    "row": idx,
                    "field": "BILL_DATE",
                    "error": "Missing required field BILL_DATE",
                })

            # Check reading fields
            has_utilized = self._has_numeric(record, 'UTILIZED_READING', 'utilized_reading')
            has_opening = self._has_numeric(record, 'OPENING_READING', 'opening_reading')
            has_closing = self._has_numeric(record, 'CLOSING_READING', 'closing_reading')

            if not has_utilized and not (has_opening and has_closing):
                row_errors.append({
                    "row": idx,
                    "field": "readings",
                    "error": "Need UTILIZED_READING or both OPENING_READING + CLOSING_READING",
                })

            # Validate numeric fields
            for cbe_field, canon_field in [
                ('OPENING_READING', 'opening_reading'),
                ('CLOSING_READING', 'closing_reading'),
                ('UTILIZED_READING', 'utilized_reading'),
                ('DISCOUNT_READING', 'discount_reading'),
                ('SOURCED_ENERGY', 'sourced_energy'),
            ]:
                val = record.get(cbe_field) or record.get(canon_field)
                if val is not None and val != '':
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        row_errors.append({
                            "row": idx,
                            "field": cbe_field,
                            "error": f"Non-numeric value: {val!r}",
                        })

            errors.extend(row_errors)

        if errors:
            return ValidationResult(
                is_valid=False,
                errors=errors[:10],
                error_message=f"Validation failed: {len(errors)} error(s) in {len(records)} records",
                rows_with_errors=len({e["row"] for e in errors}),
            )

        return ValidationResult(is_valid=True)

    def transform(
        self,
        records: List[Dict[str, Any]],
        organization_id: int,
        resolver: Any,
    ) -> List[Dict[str, Any]]:
        """Transform CBE records to canonical meter_aggregate dicts.

        Steps:
        1. Map CBE SCREAMING_SNAKE_CASE → canonical snake_case
        2. Compute total_production
        3. Resolve FKs via BillingResolver
        4. Pack CBE-specific fields into source_metadata
        """
        canonical_records = []
        now = datetime.now(timezone.utc)

        for record in records:
            mapped = self._map_fields(record)

            # Parse numeric values
            opening = self._to_float(mapped.get('opening_reading'))
            closing = self._to_float(mapped.get('closing_reading'))
            utilized = self._to_float(mapped.get('utilized_reading'))
            discount = self._to_float(mapped.get('discount_reading')) or 0.0
            sourced = self._to_float(mapped.get('sourced_energy')) or 0.0

            # Compute total_production
            if utilized is not None:
                total_production = utilized - discount - sourced
            elif opening is not None and closing is not None:
                total_production = (closing - opening) - discount - sourced
            else:
                total_production = 0.0

            # Parse bill_date for period_start/period_end
            bill_date = mapped.get('bill_date')
            period_start, period_end = self._parse_bill_date(bill_date)

            # Build source_metadata from CBE-specific fields
            source_metadata = {}
            for field in self.METADATA_FIELDS:
                val = mapped.get(field)
                if val is not None and val != '':
                    source_metadata[field] = val

            # Build canonical record
            canonical = {
                'organization_id': organization_id,
                'project_id': None,
                'meter_id': None,
                'period_type': 'monthly',
                'period_start': period_start,
                'period_end': period_end,
                'energy_kwh': total_production,
                'energy_wh': total_production * 1000 if total_production else None,
                'total_production': total_production,
                'opening_reading': opening,
                'closing_reading': closing,
                'utilized_reading': utilized,
                'discount_reading': discount,
                'sourced_energy': sourced,
                'source_system': 'snowflake',
                'source_metadata': source_metadata if source_metadata else None,
                'aggregated_at': now,
                # Fields for FK resolution (consumed by resolver, not inserted directly)
                'tariff_group_key': mapped.get('contract_line_unique_id'),
                'bill_date': bill_date,
            }

            canonical_records.append(canonical)

        # Resolve FKs in bulk
        if resolver:
            canonical_records = resolver.resolve_batch(
                canonical_records, organization_id
            )

        return canonical_records

    def _map_fields(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Map CBE SCREAMING_SNAKE_CASE fields to canonical snake_case."""
        mapped = {}
        for key, value in record.items():
            canon_key = self.FIELD_MAP.get(key, key.lower())
            mapped[canon_key] = value
        return mapped

    @staticmethod
    def _has_numeric(
        record: Dict[str, Any], cbe_key: str, canon_key: str
    ) -> bool:
        """Check if record has a non-empty numeric value for field."""
        val = record.get(cbe_key) or record.get(canon_key)
        if val is None or val == '':
            return False
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """Convert value to float, returning None if not possible."""
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_bill_date(bill_date: Any) -> tuple:
        """Parse CBE bill_date string into (period_start, period_end).

        CBE sends dates like '2025/01/31' or '2025-01-31'.
        The bill_date is the period end; period_start is first day of that month.
        """
        if not bill_date:
            return None, None

        date_str = str(bill_date).strip()
        for fmt in ('%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                dt = datetime.strptime(date_str, fmt)
                period_end = dt.date()
                period_start = period_end.replace(day=1)
                return period_start, period_end
            except ValueError:
                continue

        logger.warning("Could not parse bill_date: %s", bill_date)
        return None, None
