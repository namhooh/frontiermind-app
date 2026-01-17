# Snowflake Integration Guide

This guide explains how to push meter data from your Snowflake data warehouse to FrontierMind using Snowflake's `COPY INTO` command.

## Architecture Overview

```
┌─────────────────────┐     COPY INTO       ┌─────────────────────┐
│                     │ ─────────────────►  │                     │
│  Your Snowflake     │                     │  FrontierMind S3    │
│  Data Warehouse     │                     │  (raw/snowflake/)   │
│                     │                     │                     │
└─────────────────────┘                     └──────────┬──────────┘
                                                       │
                                                       │ S3 Event Trigger
                                                       ▼
                                            ┌─────────────────────┐
                                            │  Validator Lambda   │
                                            │  - Schema validation│
                                            │  - Deduplication    │
                                            │  - Transformation   │
                                            └──────────┬──────────┘
                                                       │
                                                       ▼
                                            ┌─────────────────────┐
                                            │  FrontierMind DB    │
                                            │  (meter_reading)    │
                                            └─────────────────────┘
```

**Key Benefits:**
- Push data on your schedule (no polling from FrontierMind)
- Use Snowflake's native Parquet export for best performance
- Automatic validation and transformation
- Full audit trail in `ingestion_log`

---

## Prerequisites

Before starting, obtain the following from your FrontierMind contact:

| Item | Description | Example |
|------|-------------|---------|
| Organization ID | Your FrontierMind org ID | `42` |
| IAM Role ARN | FrontierMind's cross-account role | `arn:aws:iam::123456789012:role/frontiermind-snowflake-access` |
| External ID | Unique ID for your integration | `fm_org_42_snowflake` |
| S3 Bucket | Target bucket name | `frontiermind-meter-data` |
| S3 Path Prefix | Your designated upload path | `raw/snowflake/42/` |

---

## Step 1: Create Storage Integration

Create a storage integration in Snowflake to enable cross-account S3 access.

```sql
-- Run as ACCOUNTADMIN
CREATE OR REPLACE STORAGE INTEGRATION frontiermind_integration
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::FRONTIERMIND_ACCOUNT:role/frontiermind-snowflake-access'
  STORAGE_ALLOWED_LOCATIONS = ('s3://frontiermind-meter-data/raw/snowflake/YOUR_ORG_ID/');

-- Grant usage to the role that will run COPY INTO
GRANT USAGE ON INTEGRATION frontiermind_integration TO ROLE DATA_ENGINEER;
```

After creating the integration, retrieve the Snowflake IAM user ARN:

```sql
DESC STORAGE INTEGRATION frontiermind_integration;
```

Note the `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID` values. Provide these to your FrontierMind contact to complete the IAM trust relationship.

---

## Step 2: Create External Stage

Create a stage pointing to your FrontierMind S3 path:

```sql
CREATE OR REPLACE STAGE frontiermind_stage
  URL = 's3://frontiermind-meter-data/raw/snowflake/YOUR_ORG_ID/'
  STORAGE_INTEGRATION = frontiermind_integration
  FILE_FORMAT = (TYPE = PARQUET);
```

Replace `YOUR_ORG_ID` with your assigned organization ID.

---

## Step 3: Create File Format

Parquet is the recommended format for best performance:

```sql
CREATE OR REPLACE FILE FORMAT frontiermind_parquet
  TYPE = PARQUET
  COMPRESSION = SNAPPY;
```

For JSON (alternative):

```sql
CREATE OR REPLACE FILE FORMAT frontiermind_json
  TYPE = JSON
  COMPRESSION = GZIP
  STRIP_OUTER_ARRAY = TRUE;
```

---

## Step 4: Export Data with COPY INTO

### Basic Export

```sql
COPY INTO @frontiermind_stage/2026-01-17/readings.parquet
FROM (
  SELECT
    reading_timestamp AS timestamp,
    site_id,
    device_id,
    energy_wh,
    power_w,
    irradiance_wm2,
    temperature_c
  FROM your_meter_readings_table
  WHERE reading_timestamp >= '2026-01-17T00:00:00Z'
    AND reading_timestamp < '2026-01-18T00:00:00Z'
)
FILE_FORMAT = frontiermind_parquet
OVERWRITE = FALSE
HEADER = TRUE;
```

### Best Practices for Export

```sql
-- Use date partitioning in file paths
SET export_date = CURRENT_DATE()::VARCHAR;

COPY INTO @frontiermind_stage/$export_date/readings_${export_date}.parquet
FROM (
  SELECT
    -- Required: UTC timestamp
    CONVERT_TIMEZONE('UTC', reading_timestamp) AS timestamp,

    -- Recommended: site/device identification
    site_id,
    device_id,

    -- Energy in Watt-hours (NOT kWh)
    energy_kwh * 1000 AS energy_wh,

    -- Power in Watts (NOT kW)
    power_kw * 1000 AS power_w,

    -- Optional environmental data
    irradiance_wm2,
    temperature_c
  FROM your_meter_readings_table
  WHERE reading_timestamp >= DATEADD(day, -1, CURRENT_DATE())
    AND reading_timestamp < CURRENT_DATE()
)
FILE_FORMAT = frontiermind_parquet
SINGLE = TRUE  -- Produce one file for simpler tracking
MAX_FILE_SIZE = 500000000;  -- 500 MB max
```

### Incremental Exports

For incremental exports, track the last exported timestamp:

```sql
-- Create tracking table
CREATE TABLE IF NOT EXISTS frontiermind_export_log (
  export_id NUMBER AUTOINCREMENT,
  export_timestamp TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  last_reading_timestamp TIMESTAMP_TZ,
  rows_exported NUMBER,
  file_path VARCHAR
);

-- Export only new data
SET last_export = (
  SELECT COALESCE(MAX(last_reading_timestamp), '1970-01-01'::TIMESTAMP_TZ)
  FROM frontiermind_export_log
);

COPY INTO @frontiermind_stage/${CURRENT_DATE()}/readings_incremental.parquet
FROM (
  SELECT
    CONVERT_TIMEZONE('UTC', reading_timestamp) AS timestamp,
    site_id,
    device_id,
    energy_wh,
    power_w
  FROM your_meter_readings_table
  WHERE reading_timestamp > $last_export
  ORDER BY reading_timestamp
)
FILE_FORMAT = frontiermind_parquet;

-- Log the export
INSERT INTO frontiermind_export_log (last_reading_timestamp, rows_exported, file_path)
SELECT MAX(reading_timestamp), COUNT(*), '@frontiermind_stage/' || CURRENT_DATE() || '/readings_incremental.parquet'
FROM your_meter_readings_table
WHERE reading_timestamp > $last_export;
```

---

## Step 5: Schedule Automated Exports (Optional)

Create a Snowflake Task for automated daily exports:

```sql
CREATE OR REPLACE TASK frontiermind_daily_export
  WAREHOUSE = YOUR_WAREHOUSE
  SCHEDULE = 'USING CRON 0 2 * * * UTC'  -- 2 AM UTC daily
AS
BEGIN
  -- Set date variables
  LET export_date VARCHAR := TO_VARCHAR(CURRENT_DATE() - INTERVAL '1 day', 'YYYY-MM-DD');
  LET start_ts TIMESTAMP_TZ := CURRENT_DATE() - INTERVAL '1 day';
  LET end_ts TIMESTAMP_TZ := CURRENT_DATE();

  -- Export yesterday's data
  COPY INTO @frontiermind_stage/:export_date/daily_readings.parquet
  FROM (
    SELECT
      CONVERT_TIMEZONE('UTC', reading_timestamp) AS timestamp,
      site_id,
      device_id,
      energy_wh,
      power_w,
      irradiance_wm2,
      temperature_c
    FROM your_meter_readings_table
    WHERE reading_timestamp >= :start_ts
      AND reading_timestamp < :end_ts
  )
  FILE_FORMAT = frontiermind_parquet
  SINGLE = TRUE;
END;

-- Enable the task
ALTER TASK frontiermind_daily_export RESUME;
```

---

## Step 6: Check Ingestion Status

After uploading files, you can check their processing status using the FrontierMind API.

### Get Status by File Hash

Calculate the SHA256 hash of your exported file and query the status endpoint:

```bash
# Calculate file hash (example using Python in Snowflake)
# Or use: openssl dgst -sha256 your_file.parquet

curl -X GET \
  "https://api.frontiermind.com/api/ingest/status/by-hash/{file_hash}?organization_id=YOUR_ORG_ID" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response

```json
{
  "file_id": "abc123def456...",
  "status": "success",
  "rows_loaded": 1500,
  "validation_errors": [],
  "processing_time_ms": 450,
  "created_at": "2026-01-17T10:00:00Z",
  "completed_at": "2026-01-17T10:00:01Z"
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `processing` | File received, validation in progress |
| `success` | File validated and data loaded |
| `quarantined` | Validation failed, file moved to quarantine |
| `skipped` | Duplicate file (same hash already processed) |
| `error` | Processing error occurred |

---

## Troubleshooting

### Integration Not Working

```sql
-- Check integration status
DESCRIBE STORAGE INTEGRATION frontiermind_integration;

-- Verify IAM role trust relationship is configured
-- Contact FrontierMind if STORAGE_AWS_IAM_USER_ARN is not trusted
```

### Access Denied Errors

1. Verify the S3 path matches your assigned prefix
2. Confirm the IAM trust relationship is established
3. Check that `STORAGE_ALLOWED_LOCATIONS` includes your path

### Validation Errors

Check the FrontierMind status API for specific validation errors:

| Error | Solution |
|-------|----------|
| `invalid_timestamp` | Ensure timestamps are UTC and ISO 8601 format |
| `missing_required_field` | Include `timestamp` field in all records |
| `value_out_of_range` | Check units (Wh not kWh, W not kW) |
| `malformed_file` | Verify Parquet file is not corrupted |

### Files Not Processing

1. Verify the file landed in the correct S3 path
2. Check file extension matches format (`.parquet`, `.json`)
3. Confirm file size is under limits (500 MB for Parquet)

---

## Data Format Reference

See [FILE_FORMAT_SPEC.md](./FILE_FORMAT_SPEC.md) for complete field definitions, data types, and validation rules.

### Quick Reference

```sql
-- Required columns
timestamp         -- TIMESTAMP_TZ (UTC)

-- Recommended columns
site_id           -- VARCHAR
device_id         -- VARCHAR
energy_wh         -- NUMBER (Watt-hours, NOT kWh)
power_w           -- NUMBER (Watts, NOT kW)

-- Optional columns
irradiance_wm2    -- NUMBER (W/m²)
temperature_c     -- NUMBER (Celsius)
quality           -- VARCHAR ('measured', 'estimated', 'missing')
```

---

## Security Considerations

1. **Least Privilege**: The FrontierMind IAM role only has `s3:PutObject` and `s3:ListBucket` permissions on your specific path
2. **Encryption**: All data is encrypted at rest (S3 SSE) and in transit (TLS)
3. **Audit Trail**: All uploads are logged in `ingestion_log` with file hash for integrity verification
4. **External ID**: Prevents confused deputy attacks in cross-account access

---

## Support

For integration assistance:
- Email: integrations@frontiermind.com
- Documentation: https://docs.frontiermind.com/snowflake

Include your Organization ID in all support requests.
