"""
Data Transformer for Meter Data

Transforms source-specific formats to canonical meter_reading model.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class Transformer:
    """Transforms meter data to canonical model."""

    # Field mappings for each source type
    SOURCE_MAPPINGS = {
        'solaredge': {
            'timestamp': ['date', 'timestamp', 'datetime'],
            'energy_wh': ['energy', 'value'],  # SolarEdge typically returns Wh
            'power_w': ['power'],
            'external_site_id': ['siteId', 'site_id'],
            'external_device_id': ['serialNumber', 'deviceId', 'device_id'],
        },
        'enphase': {
            'timestamp': ['end_at', 'timestamp'],
            'energy_wh': ['enwh', 'energy'],  # Energy in Wh
            'power_w': ['powr', 'power'],
            'external_site_id': ['system_id'],
            'external_device_id': ['serial_number'],
        },
        'sma': {
            'timestamp': ['timestamp', 'time'],
            'energy_wh': ['total_yield', 'energy'],  # May need conversion
            'power_w': ['power', 'pac'],
            'external_site_id': ['plant_id'],
            'external_device_id': ['device_id'],
        },
        'goodwe': {
            'timestamp': ['time', 'timestamp'],
            'energy_wh': ['e_day'],  # Daily energy in Wh (may need verification)
            'power_w': ['pac', 'power'],
            'external_site_id': ['powerstation_id'],
            'external_device_id': ['sn'],
        },
        'snowflake': {
            'timestamp': ['timestamp', 'reading_timestamp'],
            'energy_wh': ['energy_wh', 'energy'],
            'power_w': ['power_w', 'power'],
            'external_site_id': ['site_id'],
            'external_device_id': ['device_id'],
        },
        'manual': {
            'timestamp': ['timestamp', 'reading_timestamp', 'datetime', 'date_time', 'time'],
            'energy_wh': ['energy_wh', 'energy', 'production', 'generation', 'value'],
            'power_w': ['power_w', 'power'],
            'irradiance_wm2': ['irradiance_wm2', 'irradiance', 'ghi', 'poa'],
            'temperature_c': ['temperature_c', 'temperature', 'temp', 'ambient_temp', 'module_temp'],
            'external_site_id': ['site_id', 'external_site_id'],
            'external_device_id': ['device_id', 'meter_id', 'external_device_id'],
        },
    }

    # Default reading interval by source (in seconds)
    DEFAULT_INTERVALS = {
        'solaredge': 900,   # 15 minutes
        'enphase': 900,     # 15 minutes
        'sma': 900,         # 15 minutes
        'goodwe': 900,      # 15 minutes
        'snowflake': 3600,  # 1 hour (typically aggregated)
        'manual': 3600,     # 1 hour (default)
    }

    def transform(
        self,
        data: Union[List[Dict], Dict],
        source_type: str,
        organization_id: int,
        metadata: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Transform data to canonical meter_reading model.

        Args:
            data: Source data (list of records or wrapper dict)
            source_type: Source type (solaredge, enphase, etc.)
            organization_id: Organization ID
            metadata: Additional metadata from S3 key

        Returns:
            List of canonical records ready for database insertion
        """
        # Normalize to list
        if isinstance(data, dict):
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

        mapping = self.SOURCE_MAPPINGS.get(source_type, self.SOURCE_MAPPINGS['manual'])
        default_interval = self.DEFAULT_INTERVALS.get(source_type, 3600)

        canonical_records = []
        ingested_at = datetime.now(timezone.utc)

        for record in records:
            try:
                canonical = self._transform_record(
                    record=record,
                    mapping=mapping,
                    source_type=source_type,
                    organization_id=organization_id,
                    default_interval=default_interval,
                    ingested_at=ingested_at,
                    metadata=metadata
                )
                if canonical:
                    canonical_records.append(canonical)
            except Exception as e:
                logger.warning(f"Failed to transform record: {e}")
                continue

        logger.info(f"Transformed {len(canonical_records)} of {len(records)} records")
        return canonical_records

    def _transform_record(
        self,
        record: Dict,
        mapping: Dict,
        source_type: str,
        organization_id: int,
        default_interval: int,
        ingested_at: datetime,
        metadata: Optional[Dict]
    ) -> Optional[Dict]:
        """Transform a single record to canonical model."""

        # Extract timestamp (required)
        timestamp = self._extract_timestamp(record, mapping['timestamp'])
        if not timestamp:
            return None

        # Build canonical record
        canonical = {
            'organization_id': organization_id,
            'project_id': metadata.get('project_id') if metadata else None,
            'meter_id': metadata.get('meter_id') if metadata else None,
            'source_system': source_type,
            'reading_timestamp': timestamp,
            'reading_interval_seconds': record.get('interval', default_interval),
            'quality': 'measured',  # Default, can be overridden
            'ingested_at': ingested_at,
        }

        # Extract optional fields
        canonical['energy_wh'] = self._extract_numeric(record, mapping.get('energy_wh', []))
        canonical['power_w'] = self._extract_numeric(record, mapping.get('power_w', []))
        canonical['irradiance_wm2'] = self._extract_numeric(record, mapping.get('irradiance_wm2', []))
        canonical['temperature_c'] = self._extract_numeric(record, mapping.get('temperature_c', []))

        # Handle energy unit conversion if needed
        if canonical['energy_wh'] is not None:
            # Check if source provides kWh instead of Wh
            if self._is_likely_kwh(record, source_type):
                canonical['energy_wh'] = canonical['energy_wh'] * 1000

        # Extract external identifiers
        canonical['external_site_id'] = self._extract_string(record, mapping.get('external_site_id', []))
        canonical['external_device_id'] = self._extract_string(record, mapping.get('external_device_id', []))

        # Collect other metrics into JSONB
        other_metrics = {}
        known_fields = set()
        for field_list in mapping.values():
            if isinstance(field_list, list):
                known_fields.update(field_list)

        for key, value in record.items():
            if key not in known_fields and value is not None:
                # Only include simple types
                if isinstance(value, (str, int, float, bool)):
                    other_metrics[key] = value

        if other_metrics:
            canonical['other_metrics'] = other_metrics

        # Handle quality flag
        if 'quality' in record:
            quality = str(record['quality']).lower()
            if quality in ('estimated', 'interpolated'):
                canonical['quality'] = 'estimated'
            elif quality in ('missing', 'null', 'none'):
                canonical['quality'] = 'missing'

        return canonical

    def _extract_timestamp(self, record: Dict, field_aliases: List[str]) -> Optional[datetime]:
        """Extract and parse timestamp from record."""
        for alias in field_aliases:
            if alias in record and record[alias] is not None:
                value = record[alias]

                # Already a datetime
                if isinstance(value, datetime):
                    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

                # Unix timestamp
                if isinstance(value, (int, float)):
                    # Check if milliseconds
                    if value > 1e12:
                        value = value / 1000
                    return datetime.fromtimestamp(value, tz=timezone.utc)

                # String timestamp
                if isinstance(value, str):
                    # Try ISO format
                    try:
                        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                    except:
                        pass

                    # Try common formats
                    formats = [
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%dT%H:%M:%S',
                        '%Y/%m/%d %H:%M:%S',
                        '%m/%d/%Y %H:%M:%S',
                        '%Y-%m-%d',
                    ]
                    for fmt in formats:
                        try:
                            dt = datetime.strptime(value, fmt)
                            return dt.replace(tzinfo=timezone.utc)
                        except:
                            continue

        return None

    def _extract_numeric(self, record: Dict, field_aliases: List[str]) -> Optional[Decimal]:
        """Extract numeric value from record."""
        for alias in field_aliases:
            if alias in record and record[alias] is not None:
                value = record[alias]

                if isinstance(value, (int, float)):
                    return Decimal(str(value))

                if isinstance(value, str):
                    try:
                        # Handle comma as thousands separator
                        cleaned = value.replace(',', '')
                        return Decimal(cleaned)
                    except:
                        continue

        return None

    def _extract_string(self, record: Dict, field_aliases: List[str]) -> Optional[str]:
        """Extract string value from record."""
        for alias in field_aliases:
            if alias in record and record[alias] is not None:
                return str(record[alias])
        return None

    def _is_likely_kwh(self, record: Dict, source_type: str) -> bool:
        """
        Determine if energy values are likely in kWh instead of Wh.

        Heuristic: If values are < 1000 and source typically provides kWh,
        assume it's kWh.
        """
        # Sources known to provide kWh
        kwh_sources = ['snowflake', 'manual']

        if source_type in kwh_sources:
            # Check if there's a unit field
            unit = record.get('unit', '').lower()
            if 'kwh' in unit:
                return True
            if 'wh' in unit and 'k' not in unit:
                return False

            # If no unit, assume kWh for these sources
            return True

        return False
