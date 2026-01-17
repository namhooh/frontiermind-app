# FrontierMind Meter Data File Format Specification

This document defines the canonical file formats accepted by FrontierMind's data ingestion pipeline.

## Overview

FrontierMind accepts meter data in three formats:
- **JSON** - Recommended for API integrations and small datasets
- **CSV** - Supported for legacy systems and spreadsheet exports
- **Parquet** - Recommended for Snowflake and large datasets (best performance)

All timestamps must be in **UTC**.

---

## Field Definitions

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 string or Unix timestamp | Reading timestamp in UTC |

### Optional Fields

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `energy_wh` | Numeric | Wh | Cumulative energy reading in watt-hours |
| `power_w` | Numeric | W | Instantaneous power in watts |
| `site_id` | String | - | External site/system identifier |
| `device_id` | String | - | External device/inverter identifier |
| `irradiance_wm2` | Numeric | W/m² | Solar irradiance measurement |
| `temperature_c` | Numeric | °C | Temperature measurement |

### Metadata Fields (Optional)

| Field | Type | Description |
|-------|------|-------------|
| `quality` | String | Data quality flag: `measured`, `estimated`, `missing` |
| `interval_seconds` | Integer | Reading interval in seconds (default: 900) |

---

## Unit Requirements

| Measurement | Required Unit | Notes |
|-------------|---------------|-------|
| Energy | Watt-hours (Wh) | Not kWh or MWh |
| Power | Watts (W) | Not kW or MW |
| Irradiance | W/m² | |
| Temperature | Celsius (°C) | Not Fahrenheit |

---

## Timestamp Formats

### Supported Formats

```
# ISO 8601 (Recommended)
2026-01-17T14:30:00Z
2026-01-17T14:30:00.000Z
2026-01-17T14:30:00+00:00

# ISO 8601 Date + Time
2026-01-17 14:30:00

# Unix Timestamp (seconds)
1737124200

# Unix Timestamp (milliseconds)
1737124200000
```

### Important Notes

- All timestamps must be in **UTC**
- Local timestamps without timezone info will be assumed UTC
- Timestamps with timezone offsets will be converted to UTC

---

## JSON Format

### Single Record

```json
{
  "timestamp": "2026-01-17T14:30:00Z",
  "site_id": "site_001",
  "device_id": "inv_001",
  "energy_wh": 125000,
  "power_w": 4500,
  "irradiance_wm2": 850,
  "temperature_c": 28.5
}
```

### Multiple Records (Array)

```json
[
  {
    "timestamp": "2026-01-17T14:15:00Z",
    "site_id": "site_001",
    "energy_wh": 124500,
    "power_w": 4200
  },
  {
    "timestamp": "2026-01-17T14:30:00Z",
    "site_id": "site_001",
    "energy_wh": 125000,
    "power_w": 4500
  }
]
```

### NDJSON (Newline-Delimited JSON)

```json
{"timestamp": "2026-01-17T14:15:00Z", "site_id": "site_001", "energy_wh": 124500}
{"timestamp": "2026-01-17T14:30:00Z", "site_id": "site_001", "energy_wh": 125000}
```

---

## CSV Format

### Structure

- First row must be header row
- UTF-8 encoding required
- Comma delimiter (`,`)
- Double quotes for strings containing commas

### Example

```csv
timestamp,site_id,device_id,energy_wh,power_w,irradiance_wm2,temperature_c
2026-01-17T14:15:00Z,site_001,inv_001,124500,4200,800,27.5
2026-01-17T14:30:00Z,site_001,inv_001,125000,4500,850,28.5
2026-01-17T14:45:00Z,site_001,inv_001,125600,4800,900,29.0
```

### Column Name Mapping

The following alternative column names are accepted:

| Canonical | Alternatives |
|-----------|--------------|
| `timestamp` | `reading_timestamp`, `time`, `datetime`, `date_time` |
| `energy_wh` | `energy`, `cumulative_energy`, `total_energy` |
| `power_w` | `power`, `ac_power`, `active_power` |
| `site_id` | `site`, `system_id`, `plant_id` |
| `device_id` | `device`, `inverter_id`, `serial_number` |

---

## Parquet Format

Parquet is the recommended format for large datasets and Snowflake integration.

### Schema Definition

```
message meter_reading {
  required int64 timestamp (TIMESTAMP(MILLIS, true));  -- UTC timestamp
  optional binary site_id (STRING);
  optional binary device_id (STRING);
  optional double energy_wh;
  optional double power_w;
  optional double irradiance_wm2;
  optional double temperature_c;
  optional binary quality (STRING);
}
```

### Recommended Settings

- Compression: SNAPPY (default) or GZIP
- Row group size: 128 MB
- Page size: 1 MB

### Snowflake Example

```sql
-- Create file format
CREATE FILE FORMAT frontiermind_parquet
  TYPE = PARQUET
  COMPRESSION = SNAPPY;

-- Export to Parquet
COPY INTO @frontiermind_stage/readings.parquet
FROM (
  SELECT
    reading_timestamp AS timestamp,
    site_id,
    device_id,
    energy_wh,
    power_w
  FROM meter_readings
  WHERE reading_timestamp >= '2026-01-01'
)
FILE_FORMAT = frontiermind_parquet;
```

---

## Data Quality Expectations

### Validation Rules

1. **Timestamp** - Must be valid, not in the future, not more than 10 years in the past
2. **Energy** - Must be non-negative
3. **Power** - Must be non-negative
4. **Temperature** - Must be between -50°C and 100°C
5. **Irradiance** - Must be between 0 and 1500 W/m²

### Deduplication

Files are deduplicated by SHA-256 hash. Uploading the same file twice will skip processing.

### Quarantine

Files failing validation are moved to quarantine. Common issues:
- Invalid timestamp format
- Missing required fields
- Values outside valid ranges
- Malformed JSON/CSV/Parquet

---

## File Size Limits

| Format | Max File Size | Max Records |
|--------|---------------|-------------|
| JSON | 100 MB | 1,000,000 |
| CSV | 100 MB | 1,000,000 |
| Parquet | 500 MB | 10,000,000 |

For larger datasets, split into multiple files.

---

## S3 Path Convention

Files uploaded via presigned URL follow this path structure:

```
s3://frontiermind-meter-data/raw/{source}/{org_id}/{date}/{file_id}_{filename}
```

Example:
```
s3://frontiermind-meter-data/raw/snowflake/1/2026-01-17/abc123_readings.parquet
```

---

## Content Types

| Format | Content-Type |
|--------|--------------|
| JSON | `application/json` |
| CSV | `text/csv` |
| Parquet | `application/octet-stream` |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-17 | Initial specification |
