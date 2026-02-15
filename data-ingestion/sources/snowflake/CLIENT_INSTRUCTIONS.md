# Snowflake Data Ingestion — Client Instructions

This guide covers everything you need to export data from your Snowflake data warehouse to FrontierMind. There are two ingestion endpoints — one for raw meter readings and one for monthly billing aggregates.

---

## What You'll Receive From FrontierMind

Before starting, we'll provide you with:

| Item | Description |
|------|-------------|
| **Organization ID** | Your unique identifier in our system |
| **API Key** | Bearer token for authenticating API requests |
| **API Endpoint** | The base URL for the ingestion API |

---

## Quick Reference — Which Endpoint to Use?

| Endpoint | Path | Use When | Units |
|----------|------|----------|-------|
| **Raw Meter Readings** | `/api/ingest/meter-data` | Sending 15-min or hourly interval readings from inverters/meters | Wh (Watt-hours) |
| **Monthly Billing Aggregates** | `/api/ingest/billing-reads` | Sending monthly billing data with opening/closing/utilized readings tied to contract tariff lines | kWh (kilowatt-hours) |

> **Rule of thumb:** If your data has a `BILL_DATE` and comes from your ERP billing system, use `billing-reads`. If it has granular timestamps from monitoring equipment, use `meter-data`.

---

## 1. Raw Meter Readings (meter-data)

Push granular meter data directly to our REST API.

### Endpoint

```
POST {API_ENDPOINT}/api/ingest/meter-data
Authorization: Bearer {YOUR_API_KEY}
Content-Type: application/json
```

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["readings"],
  "properties": {
    "readings": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5000,
      "items": {
        "type": "object",
        "required": ["timestamp"],
        "properties": {
          "timestamp":        { "type": "string", "description": "ISO 8601 or Unix timestamp (UTC)" },
          "site_id":          { "type": "string", "description": "External site identifier" },
          "device_id":        { "type": "string", "description": "External device identifier" },
          "energy_wh":        { "type": "number", "description": "Energy in Watt-hours" },
          "power_w":          { "type": "number", "description": "Power in Watts" },
          "irradiance_wm2":   { "type": "number", "description": "Solar irradiance in W/m²" },
          "temperature_c":    { "type": "number", "description": "Temperature in Celsius" },
          "quality":          { "type": "string", "enum": ["measured", "estimated", "missing"] },
          "interval_seconds": { "type": "integer", "description": "Reading interval in seconds" }
        }
      }
    },
    "source_type": {
      "type": "string",
      "enum": ["snowflake"],
      "default": "snowflake"
    },
    "metadata": {
      "type": "object",
      "description": "Optional metadata (project_id, meter_id, etc.)"
    }
  }
}
```

> **Note:** `source_type` is locked to `"snowflake"` because your API key is scoped to this data source.

### Example Payload

```json
{
  "readings": [
    {
      "timestamp": "2026-01-15T14:00:00Z",
      "site_id": "SITE-001",
      "device_id": "INV-A",
      "energy_wh": 15230.5,
      "power_w": 4500.0,
      "irradiance_wm2": 850.2,
      "temperature_c": 28.3,
      "quality": "measured"
    }
  ],
  "source_type": "snowflake",
  "metadata": {
    "project_id": 1,
    "meter_id": 5
  }
}
```

### Field Reference

| Field | Required? | Unit | Notes |
|-------|-----------|------|-------|
| `timestamp` | **Yes** | UTC | ISO 8601 string or Unix timestamp |
| `site_id` | Recommended | — | Your site or system identifier |
| `device_id` | Recommended | — | Your device or inverter identifier |
| `energy_wh` | Recommended | **Watt-hours** | Must be Wh, not kWh — multiply by 1000 if needed |
| `power_w` | Recommended | **Watts** | Must be W, not kW — multiply by 1000 if needed |
| `irradiance_wm2` | Optional | W/m² | Solar irradiance |
| `temperature_c` | Optional | °C | Must be Celsius |
| `quality` | Optional | — | One of: `measured`, `estimated`, `missing` |
| `interval_seconds` | Optional | seconds | Reading interval (default: 3600) |

### Batch Limits

- **Max 5,000 readings per request**
- **Rate limit: 30 requests per minute**
- For larger datasets, split into multiple batches

### Response

```json
{
  "ingestion_id": 42,
  "status": "success",
  "rows_accepted": 96,
  "rows_rejected": 0,
  "errors": null,
  "processing_time_ms": 234,
  "data_start": "2026-01-15T00:00:00Z",
  "data_end": "2026-01-15T23:45:00Z",
  "message": null
}
```

| Status | Meaning |
|--------|---------|
| `success` | All readings validated and loaded |
| `quarantined` | Validation failed — check `errors` array for details |
| `skipped` | Duplicate payload (same SHA256 hash already processed) |
| `error` | Processing error — check `message` |

### Snowflake Implementation

Create a Snowflake External Network Rule and API Integration, then use a stored procedure:

**Step 1: Create a network rule allowing HTTPS to our API**

Use the hostname from your API endpoint URL.

**Step 2: Create a stored procedure**

Write a stored procedure that:
1. Queries your meter data table for the previous day
2. Batches results into groups of 5,000
3. Calls the API endpoint with each batch using `SNOWFLAKE.CORTEX.COMPLETE` or an external function

**Step 3: Schedule with a Snowflake Task**

```sql
CREATE OR REPLACE TASK meter_data_export
  WAREHOUSE = YOUR_WAREHOUSE
  SCHEDULE = 'USING CRON 0 2 * * * UTC'
AS
  CALL export_meter_data_to_frontiermind();
```

### Key Rules

- All timestamps must be **UTC**
- Energy in **Wh** (not kWh), power in **W** (not kW)
- Duplicate payloads are automatically detected and skipped
- Responses are **synchronous** — no need to poll a status endpoint
- Your API key is **scoped to the Snowflake data source** — always use `"source_type": "snowflake"`. Using a different source type will return a 403 Forbidden error.

---

## 2. Monthly Billing Aggregates (billing-reads)

For **monthly billing aggregates** — opening/closing/utilized readings tied to contract tariff lines — use the dedicated billing reads endpoint.

> **Note:** The billing-reads schema below is currently tailored to CBE (CrossBoundary Energy) field mappings. If your organization uses different billing fields, contact the FrontierMind team for adapter configuration.

### Endpoint

```
POST {API_ENDPOINT}/api/ingest/billing-reads
Authorization: Bearer {YOUR_API_KEY}
Content-Type: application/json
```

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["readings"],
  "properties": {
    "readings": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5000,
      "items": {
        "type": "object",
        "required": ["BILL_DATE"],
        "properties": {
          "BILL_DATE":                  { "type": "string", "description": "Billing period end date (YYYY/MM/DD or YYYY-MM-DD)" },
          "CONTRACT_LINE_UNIQUE_ID":    { "type": "string", "description": "Unique tariff line identifier" },
          "OPENING_READING":            { "type": "number", "description": "Meter reading at period start (kWh)" },
          "CLOSING_READING":            { "type": "number", "description": "Meter reading at period end (kWh)" },
          "UTILIZED_READING":           { "type": "number", "description": "Net consumption (kWh)" },
          "DISCOUNT_READING":           { "type": "number", "description": "Discounted/waived quantity (kWh)" },
          "SOURCED_ENERGY":             { "type": "number", "description": "Self-sourced energy to deduct (kWh)" },
          "CUSTOMER_NUMBER":            { "type": "string", "description": "Customer/site identifier" },
          "FACILITY":                   { "type": "string", "description": "Facility/device identifier" },
          "PRODUCT_DESC":               { "type": "string", "description": "Product description" },
          "METERED_AVAILABLE":          { "type": "string", "description": "Metered availability flag" },
          "QUANTITY_UNIT":              { "type": "string", "description": "Unit of measure (e.g. KWH)" },
          "CONTRACT_NUMBER":            { "type": "string", "description": "ERP contract number" },
          "CONTRACT_LINE":              { "type": "string", "description": "ERP contract line number" },
          "CONTRACT_CURRENCY":          { "type": "string", "description": "Currency code (e.g. KES)" },
          "TAX_RULE":                   { "type": "string", "description": "Tax rule identifier" },
          "PAYMENT_TERMS":              { "type": "string", "description": "Payment terms" },
          "METER_READING_UNIQUE_ID":    { "type": "string", "description": "Unique reading identifier in source system" }
        }
      }
    },
    "source_type": {
      "type": "string",
      "enum": ["snowflake"],
      "default": "snowflake"
    },
    "metadata": {
      "type": "object",
      "description": "Optional metadata"
    }
  }
}
```

### Example Payload

```json
{
  "readings": [
    {
      "BILL_DATE": "2025/01/31",
      "CONTRACT_LINE_UNIQUE_ID": "7911848012608655937",
      "OPENING_READING": 73419.84,
      "CLOSING_READING": 108861.84,
      "UTILIZED_READING": 35442.0,
      "DISCOUNT_READING": 0,
      "SOURCED_ENERGY": 0,
      "CUSTOMER_NUMBER": "10023",
      "FACILITY": "FAC-001",
      "PRODUCT_DESC": "Solar Energy Metered",
      "METERED_AVAILABLE": "EMetered",
      "QUANTITY_UNIT": "KWH",
      "CONTRACT_NUMBER": "CONKEN00-2023-00011",
      "CONTRACT_LINE": "4000",
      "CONTRACT_CURRENCY": "KES",
      "TAX_RULE": "O-VATKEN",
      "PAYMENT_TERMS": "ZB30",
      "METER_READING_UNIQUE_ID": "8070404068085149697"
    }
  ],
  "source_type": "snowflake"
}
```

### Field Reference

| Field | Required? | Unit | Notes |
|-------|-----------|------|-------|
| `BILL_DATE` | **Yes** | — | Period end date (YYYY/MM/DD or YYYY-MM-DD). Used to match the billing period. |
| `CONTRACT_LINE_UNIQUE_ID` | Recommended | — | Unique tariff line identifier. Used to match the contract tariff. |
| `OPENING_READING` | Conditional | kWh | Required if `UTILIZED_READING` not provided |
| `CLOSING_READING` | Conditional | kWh | Required if `UTILIZED_READING` not provided |
| `UTILIZED_READING` | Conditional | kWh | Net consumption. Required if opening/closing not provided. |
| `DISCOUNT_READING` | Optional | kWh | Discounted quantity (default: 0) |
| `SOURCED_ENERGY` | Optional | kWh | Self-sourced energy (default: 0) |
| `CUSTOMER_NUMBER` | Optional | — | Site identifier |
| `FACILITY` | Optional | — | Device/facility identifier |
| `PRODUCT_DESC` | Optional | — | Stored as supplementary metadata |
| `METERED_AVAILABLE` | Optional | — | Stored as supplementary metadata |
| `QUANTITY_UNIT` | Optional | — | Stored as supplementary metadata |
| `CONTRACT_NUMBER` | Optional | — | Stored as supplementary metadata |
| `CONTRACT_LINE` | Optional | — | Stored as supplementary metadata |
| `CONTRACT_CURRENCY` | Optional | — | Stored as supplementary metadata |
| `TAX_RULE` | Optional | — | Stored as supplementary metadata |
| `PAYMENT_TERMS` | Optional | — | Stored as supplementary metadata |
| `METER_READING_UNIQUE_ID` | Optional | — | Stored as supplementary metadata |

### Bill Date & Tariff Resolution

`BILL_DATE` is matched to the billing period whose end date equals the provided date. If no matching billing period exists, the row is still loaded with `billing_period_id` set to NULL. Check application logs for unresolved billing-period warnings.

Similarly, `CONTRACT_LINE_UNIQUE_ID` is matched to the corresponding contract tariff line. Unmatched values are loaded with the tariff FK set to NULL.

### Total Production Calculation

```
total_production = UTILIZED_READING - DISCOUNT_READING - SOURCED_ENERGY
```

If `UTILIZED_READING` is not provided, it is computed from `CLOSING_READING - OPENING_READING`.

### Response

Same format as the meter-data endpoint:

```json
{
  "ingestion_id": 58,
  "status": "success",
  "rows_accepted": 30,
  "rows_rejected": 0,
  "errors": null,
  "processing_time_ms": 187,
  "data_start": "2025-01-01",
  "data_end": "2025-01-31",
  "message": null
}
```

### Snowflake Implementation

Follow the same pattern as Section 1 (network rule, stored procedure, scheduled task):

1. Query your billing data table for the target month
2. Batch results into groups of 5,000
3. Call `/api/ingest/billing-reads` with each batch
4. Schedule with a Snowflake Task (e.g., run on the 2nd of each month)

```sql
CREATE OR REPLACE TASK billing_data_export
  WAREHOUSE = YOUR_WAREHOUSE
  SCHEDULE = 'USING CRON 0 6 2 * * UTC'
AS
  CALL export_billing_data_to_frontiermind();
```

### Key Rules

- `BILL_DATE` is required for every reading — rows without it are quarantined
- Energy values are in **kWh** (not Wh) — this differs from the meter-data endpoint
- Provide either `UTILIZED_READING` or both `OPENING_READING` and `CLOSING_READING`
- Duplicate payloads are automatically detected and skipped
- Responses are **synchronous** — no need to poll a status endpoint
- Your API key is **scoped to the Snowflake data source** — always use `"source_type": "snowflake"`

---

## Checking Ingestion Status

> These endpoints work for both `meter-data` and `billing-reads` ingestions.

All status endpoints require the same `Authorization: Bearer` header as the ingestion endpoint. The organization is derived from your API key — no `organization_id` query parameter is needed.

### Ingestion History

```
GET {API_ENDPOINT}/api/ingest/history
Authorization: Bearer {YOUR_API_KEY}
```

Optional query parameters: `data_source_id`, `status`, `page`, `page_size`

### Status by File Hash

```
GET {API_ENDPOINT}/api/ingest/status/by-hash/{FILE_HASH}
Authorization: Bearer {YOUR_API_KEY}
```

### Ingestion Statistics

```
GET {API_ENDPOINT}/api/ingest/stats?days=30
Authorization: Bearer {YOUR_API_KEY}
```

---

## Retry & Error Handling

### Which Errors to Retry

| HTTP Status | Meaning | Retry? | Action |
|-------------|---------|--------|--------|
| **200** | Success | No | Proceed normally |
| **401** | Invalid API key | **No** | Check your API key — do not retry |
| **403** | Wrong source type | **No** | Ensure `source_type` is `"snowflake"` |
| **429** | Rate limited | **Yes** | Back off and retry |
| **5xx** | Server error | **Yes** | Back off and retry |
| Quarantined | Validation failed | **No** | Fix the data — check `errors` array |

### Exponential Backoff

Use exponential backoff with jitter for retryable errors:

| Attempt | Wait Time |
|---------|-----------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |
| 4 | 8 seconds |
| 5 | 16 seconds (max) |

After 5 failed attempts, log the error and alert your team.

---

## Idempotency

The ingestion pipeline computes a SHA256 hash of each payload. If you re-send the exact same payload, the API returns `"status": "skipped"` instead of inserting duplicate data. This applies to both `meter-data` and `billing-reads` endpoints.

This means:
- **Retrying a failed HTTP request is always safe** — if the server received and processed it before the timeout, the retry will be skipped
- **Re-running your export task is safe** — identical data won't be duplicated

In addition to payload-level deduplication, row-level deduplication prevents duplicates even across different payloads:

- **Meter readings:** A unique index on `(organization, timestamp, site, device)` prevents duplicate readings
- **Billing aggregates:** A unique index on `(organization, billing period, tariff)` prevents duplicate billing rows

---

## API Key Storage

Store your FrontierMind API key securely using Snowflake's secret management:

```sql
-- Create a secret for the API key
CREATE OR REPLACE SECRET frontiermind_api_key
  TYPE = GENERIC_STRING
  SECRET_STRING = 'your-api-key-here';

-- Reference in stored procedures
DECLARE
  api_key VARCHAR := SYSTEM$GET_SECRET('frontiermind_api_key');
```

**Do not** hardcode API keys in stored procedures, worksheets, or version control.

---

## Common Issues

| Problem | Likely Cause | Resolution |
|---------|-------------|------------|
| **401 Unauthorized** | Missing or invalid API key | Check `Authorization: Bearer <key>` header |
| **403 Forbidden** | API key scoped to wrong source type | Ensure `"source_type": "snowflake"` |
| **429 Too Many Requests** | Rate limit exceeded | Implement exponential backoff, reduce to < 30 requests/minute |
| **Quarantined meter readings** | Timestamps not UTC, energy in kWh instead of Wh, or missing `timestamp` | Check `errors` array in response |
| **Quarantined billing reads** | Missing `BILL_DATE`, or missing both `UTILIZED_READING` and `OPENING_READING`/`CLOSING_READING` | Ensure every billing row has `BILL_DATE` and at least one reading value |
| **Billing period not matched** | `BILL_DATE` doesn't match any configured billing period end date | Verify the date format (YYYY/MM/DD or YYYY-MM-DD) and confirm the billing period exists in FrontierMind |
| **Tariff not matched** | `CONTRACT_LINE_UNIQUE_ID` doesn't match any configured tariff | Confirm the tariff line identifier with your FrontierMind contact |
| **Skipped** | Same payload already processed | Expected for reruns — no action needed |
| **413 Request Too Large** | > 5,000 readings in batch | Split into smaller batches |
