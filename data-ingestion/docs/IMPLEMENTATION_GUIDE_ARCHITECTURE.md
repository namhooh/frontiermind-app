# Data Ingestion & Integration Architecture

## Final Confirmed Architecture for Energy Contract Compliance Platform

---

## 1. Core Philosophy

**"The Database is a Temple. Nothing enters unless it is clean. S3 is the Loading Dock."**

### Backend API Endpoint

The Python backend for data processing is deployed to AWS ECS Fargate:

| Endpoint | URL |
|----------|-----|
| **Backend API** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com` |
| **Ingest API** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/api/ingest` |
| **Health Check** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/health` |

**For full deployment documentation, see `CLAUDE.md` in the project root.**

- All data lands in S3 first as raw files (JSON/CSV/Parquet)
- Validator Lambda checks, cleans, and loads to database
- Invalid files quarantined for review
- Immutable audit trail enables replayability

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                             │
└─────────────────────────────────────────────────────────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ INVERTER APIs │      │    CLIENT     │      │    MANUAL     │
│               │      │  SNOWFLAKE    │      │   UPLOADS     │
│ SolarEdge     │      │               │      │               │
│ Enphase       │      │ COPY INTO     │      │ CSV/Parquet   │
│ SMA           │      │ (client push) │      │ via UI        │
│ GoodWe        │      │               │      │               │
└───────┬───────┘      └───────┬───────┘      └───────┬───────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│   FETCHER     │      │   SNOWFLAKE   │      │  PRESIGNED    │
│   WORKERS     │      │   TASK        │      │  URL UPLOAD   │
│               │      │               │      │               │
│ GitHub Actions│      │ Scheduled     │      │ Direct to S3  │
│ or Lambda     │      │ export to S3  │      │               │
└───────┬───────┘      └───────┬───────┘      └───────┬───────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                               ▼
                ┌─────────────────────────┐
                │        S3 BUCKET        │
                │       (Lake-House)      │
                │                         │
                │  raw/{source}/{org}/    │
                │  validated/             │
                │  quarantine/            │
                │  archive/               │
                └────────────┬────────────┘
                             │
                        S3 Event
                    (ObjectCreated)
                             │
                             ▼
                ┌─────────────────────────┐
                │    VALIDATOR LAMBDA     │
                │                         │
                │  • Schema validation    │
                │  • Data cleaning        │
                │  • Transform to         │
                │    canonical model      │
                │  • Load OR quarantine   │
                └────────────┬────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│    SUPABASE POSTGRES    │   │   AWS ECS FARGATE       │
│                         │   │   (Python Backend)      │
│  meter_reading          │   │                         │
│  meter_aggregate        │   │  Rules engine           │
│  default_event          │   │  Contract parsing       │
│  integration_credential │   │  API endpoints          │
│  integration_site       │   │                         │
└─────────────────────────┘   └─────────────────────────┘
                                        │
                              Backend API URL:
              http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com
```

**AWS Infrastructure:**
- **Region:** us-east-1
- **ECS Cluster:** frontiermind-cluster
- **ECS Service:** frontiermind-backend
- **Load Balancer:** frontiermind-alb

---

## 3. S3 Bucket Structure

```
s3://meter-data-lake/
├── raw/                          ← Landing zone
│   ├── solaredge/{org_id}/{date}/
│   ├── enphase/{org_id}/{date}/
│   ├── snowflake/{org_id}/{date}/
│   └── manual/{org_id}/{date}/
│
├── validated/                    ← Passed validation (retain 30 days)
│   └── {date}/
│
├── quarantine/                   ← Failed validation (retain 14 days)
│   └── {date}/
│
└── archive/                      ← Long-term evidence (optional, Glacier)
    └── evidence/
```

---

## 4. Inverter API Authentication

### 4.1 Authentication Methods by Manufacturer

| Manufacturer | Auth Type | Client Action | Token Refresh |
|--------------|-----------|---------------|---------------|
| SolarEdge | API Key | Paste key into your app | Not needed |
| GoodWe | API Key | Paste key into your app | Not needed |
| Enphase | OAuth 2.0 | Click "Connect", authorize in popup | Automatic |
| SMA | OAuth 2.0 | Click "Connect", authorize in popup | Automatic |

### 4.2 API Key Flow (SolarEdge, GoodWe)

```
CLIENT                          YOUR APP                      INVERTER PORTAL
   │                               │                               │
   │  1. Go to SolarEdge portal    │                               │
   │──────────────────────────────────────────────────────────────▶│
   │                               │                               │
   │  2. Generate API key          │                               │
   │◀──────────────────────────────────────────────────────────────│
   │                               │                               │
   │  3. Paste key into your app   │                               │
   │──────────────────────────────▶│                               │
   │                               │                               │
   │                    4. Encrypt & store                         │
   │                       in Supabase                             │
   │                               │                               │
   │  5. "Connected" confirmation  │                               │
   │◀──────────────────────────────│                               │
```

### 4.3 OAuth 2.0 Flow (Enphase, SMA)

```
CLIENT                    YOUR APP                 MANUFACTURER AUTH
   │                         │                            │
   │  1. Click "Connect      │                            │
   │     Enphase" button     │                            │
   │────────────────────────▶│                            │
   │                         │                            │
   │         2. Redirect to authorization URL             │
   │◀─────────────────────────────────────────────────────│
   │                         │                            │
   │  3. Popup opens,        │                            │
   │     client logs in      │                            │
   │─────────────────────────────────────────────────────▶│
   │                         │                            │
   │  4. Client clicks       │                            │
   │     "Authorize"         │                            │
   │─────────────────────────────────────────────────────▶│
   │                         │                            │
   │         5. Redirect to callback with auth code       │
   │         ─────────────────────────────────────────────│
   │                         │◀───────────────────────────│
   │                         │                            │
   │              6. Exchange code for tokens             │
   │                         │───────────────────────────▶│
   │                         │◀───────────────────────────│
   │                         │                            │
   │              7. Encrypt & store tokens               │
   │                         │                            │
   │  8. Popup closes,       │                            │
   │     "Connected" shown   │                            │
   │◀────────────────────────│                            │
```

### 4.4 OAuth Callback Endpoint

**Recommendation:** Use Supabase Edge Function for the OAuth callback.

**Endpoint:** `https://{project}.supabase.co/functions/v1/oauth-callback`

**Function responsibilities:**
- Receive authorization code from manufacturer
- Exchange code for access token + refresh token
- Encrypt and store tokens in `integration_credential` table
- Return success/close popup

### 4.5 OAuth Security Architecture

**State Parameter (CSRF Protection):**
- Frontend MUST call `POST /api/oauth/state` to get HMAC-signed state
- State includes organization_id, timestamp, and HMAC-SHA256 signature
- Callback validates signature and rejects expired states (>10 min)
- Legacy unsigned states are rejected

**Credential Encryption:**
- All credentials encrypted with AES-256-GCM (authenticated encryption)
- 12-byte random IV per encryption operation
- 16-byte authentication tag prevents tampering
- Same format used by both TypeScript callback and Python fetchers

**Wire Format:**
```
[IV - 12 bytes][Ciphertext][Auth Tag - 16 bytes] → Base64
```

**Implementation Files:**

| Component | File | Operation |
|-----------|------|-----------|
| State Generation | `python-backend/api/oauth.py` | Generate HMAC-signed state |
| State Validation | `data-ingestion/oauth/supabase-callback/index.ts` | Validate on callback |
| Credential Encrypt | `data-ingestion/oauth/supabase-callback/index.ts` | Encrypt tokens |
| Credential Decrypt | `data-ingestion/sources/inverter-api/base_fetcher.py` | Decrypt/re-encrypt |
| Frontend Client | `lib/api/oauthClient.ts` | Request state before redirect |

---

## 5. Credential Storage

### 5.1 integration_credential Table

Stores encrypted API keys and OAuth tokens for each organization's inverter connections.

**Key fields:**
- `organization_id` - Links to organization
- `source_type` - 'solaredge', 'enphase', 'sma', 'goodwe'
- `auth_type` - 'api_key' or 'oauth2'
- `encrypted_credentials` - AES-256-GCM encrypted JSON containing keys/tokens
- `token_expires_at` - For OAuth tokens, when refresh is needed
- `is_active` - Enable/disable integration
- `last_used_at` - Track usage
- `last_error` - Store error messages for troubleshooting

### 5.2 integration_site Table

Maps external inverter sites to your internal projects.

**Key fields:**
- `organization_id` - Links to organization
- `credential_id` - Links to integration_credential
- `project_id` - Links to your internal project
- `source_type` - 'solaredge', 'enphase', etc.
- `external_site_id` - ID in manufacturer's system
- `external_site_name` - Human-readable name
- `is_active` - Enable/disable sync for this site
- `last_sync_at` - When data was last fetched
- `last_sync_status` - 'success', 'error', etc.
- `last_sync_error` - Error message if failed

---

## 6. Fetcher Workers

### 6.1 Overview

| Aspect | Specification |
|--------|---------------|
| **Runtime** | GitHub Actions (preferred) or AWS Lambda scheduled |
| **Frequency** | Hourly (configurable per source) |
| **Trigger** | Cron schedule |
| **Output** | Raw JSON files to S3 `raw/{source}/{org_id}/{date}/` |
| **One worker per** | Source type (solaredge_fetcher, enphase_fetcher, etc.) |

### 6.2 Fetcher Worker Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    FETCHER WORKER EXECUTION                      │
└─────────────────────────────────────────────────────────────────┘

1. TRIGGER: Cron schedule (e.g., every hour)
                │
                ▼
2. QUERY CREDENTIALS:
   - Connect to Supabase
   - Fetch all active credentials for this source type
   - Decrypt credentials
                │
                ▼
3. FOR EACH CREDENTIAL:
   │
   ├── If OAuth: Check token expiry
   │   └── If expired: Refresh token, update in DB
   │
   ├── Fetch sites for this credential
   │
   └── FOR EACH SITE:
       │
       ├── Call inverter API (last 2 hours of data)
       │
       ├── Format as JSON with metadata:
       │   - source
       │   - organization_id
       │   - site_id
       │   - fetched_at
       │   - data_range (start, end)
       │   - readings array
       │
       └── Upload to S3: raw/solaredge/{org_id}/{date}/site_abc_140000.json
                │
                ▼
4. UPDATE STATUS:
   - Update last_sync_at in integration_site
   - Log any errors
                │
                ▼
5. EXIT (ephemeral - no persistent process)
```

### 6.3 GitHub Actions Configuration

Each fetcher runs as a scheduled GitHub Actions workflow:
- Triggered by cron (e.g., `0 * * * *` for hourly)
- Can also be triggered manually (workflow_dispatch)
- Uses repository secrets for credentials (Supabase URL, AWS keys, encryption key)
- Runs Python script, then exits

---

## 7. Validator Lambda

### 7.1 Overview

| Aspect | Specification |
|--------|---------------|
| **Trigger** | S3 Event (ObjectCreated) on `raw/` prefix |
| **Runtime** | AWS Lambda (Python 3.11) |
| **Timeout** | 5 minutes |
| **Memory** | 512MB - 1GB |

### 7.2 Validator Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    VALIDATOR LAMBDA FLOW                         │
└─────────────────────────────────────────────────────────────────┘

1. TRIGGER: S3 ObjectCreated event on raw/{source}/{org_id}/...
                │
                ▼
2. DOWNLOAD & PARSE:
   - Download file from S3
   - Parse JSON/CSV/Parquet
   - Extract metadata (source, org_id, site_id)
                │
                ▼
3. VALIDATE:
   - Check required fields exist
   - Validate data types
   - Check timestamps are reasonable
   - Validate values are within expected ranges
                │
                ▼
4. BRANCH:
   │
   ├── VALID:
   │   ├── Transform to canonical model
   │   ├── Load to meter_reading table (batch insert)
   │   ├── Move file to validated/
   │   └── Emit success metrics
   │
   └── INVALID:
       ├── Move file to quarantine/
       ├── Log validation errors
       └── Emit failure metrics (alert if needed)
                │
                ▼
5. UPDATE METADATA:
   - Record in ingestion_log table:
     - File path
     - Rows processed
     - Rows loaded
     - Validation errors (if any)
```

---

## 8. Canonical Data Model

All sources transform to this unified format before database insertion:

| Field | Type | Description |
|-------|------|-------------|
| `source_system` | string | 'solaredge', 'enphase', 'snowflake', 'manual' |
| `organization_id` | int | Your internal organization ID |
| `external_site_id` | string | Site ID in source system |
| `external_device_id` | string | Device/meter ID in source system |
| `timestamp` | datetime (UTC) | Reading timestamp |
| `reading_interval_seconds` | int | 300, 900, 3600 |
| `energy_wh` | float (nullable) | Energy in Watt-hours |
| `power_w` | float (nullable) | Power in Watts |
| `irradiance_wm2` | float (nullable) | Solar irradiance |
| `temperature_c` | float (nullable) | Temperature |
| `other_metrics` | jsonb | Additional metrics |
| `quality` | enum | 'measured', 'estimated', 'missing' |
| `ingested_at` | datetime | When record was ingested |

---

## 9. Database Schema (Supabase PostgreSQL)

### 9.1 meter_reading Table

**Purpose:** Store raw meter readings

**Partitioning:** By month using native Postgres partitioning (RANGE on timestamp)

**Retention:** 90 days, then drop old partitions

**Key fields:**
- `organization_id`, `project_id`, `meter_id` - Identity
- `timestamp` - Reading time (UTC)
- `reading_interval_seconds` - Interval (e.g., 900 for 15-min)
- `energy_wh`, `power_w`, `irradiance_wm2`, `temperature_c` - Metrics
- `other_metrics` - JSONB for additional data
- `source_system` - Origin of data
- `quality` - Data quality flag
- `ingested_at` - When loaded

### 9.2 meter_aggregate Table

**Purpose:** Store aggregated totals (hourly, daily, monthly)

**Retention:** Forever - this is your financial source of truth

**Key fields:**
- `organization_id`, `project_id`, `meter_id` - Identity
- `period_type` - 'hourly', 'daily', 'monthly'
- `period_start`, `period_end` - Time range
- `energy_wh`, `energy_kwh` - Energy totals
- `hours_available`, `hours_expected` - Availability metrics
- `availability_percent` - Calculated availability
- `reading_count`, `data_completeness_percent` - Data quality

### 9.3 default_event with Evidence

**Purpose:** Preserve breach evidence even after raw data is deleted

**Evidence JSONB structure:**
- `breach_period` - Start and end timestamps
- `meters_involved` - List of meter IDs
- `aggregate_values` - Expected vs actual values, shortfall, availability
- `sample_readings` - Minimal slice of raw readings
- `data_hash` - SHA256 hash of original data
- `snapshot_s3_path` - Optional S3 path to archived evidence file

---

## 10. Client Platform Integration (Snowflake)

### Method: Client Pushes to Your S3

```
┌─────────────────────────────────────────────────────────────────┐
│                    SNOWFLAKE INTEGRATION                         │
└─────────────────────────────────────────────────────────────────┘

CLIENT'S SNOWFLAKE                           YOUR S3 BUCKET
       │                                           │
       │  1. Create external stage                 │
       │     pointing to your S3                   │
       │─────────────────────────────────────────▶│
       │                                           │
       │  2. Scheduled task runs COPY INTO         │
       │     (hourly/daily)                        │
       │─────────────────────────────────────────▶│ raw/snowflake/{org_id}/
       │                                           │
       │                                           │ S3 Event triggers
       │                                           │ Validator Lambda
       │                                           │
```

**What You Provide to Client:**
- S3 bucket path: `s3://meter-data-lake/raw/snowflake/{org_id}/`
- IAM role ARN for cross-account access
- Expected file format specification (Parquet preferred)
- Column mapping requirements

---

## 11. Manual Upload Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    MANUAL UPLOAD FLOW                            │
└─────────────────────────────────────────────────────────────────┘

CLIENT                     YOUR APP                        S3
   │                          │                             │
   │  1. Click "Upload"       │                             │
   │─────────────────────────▶│                             │
   │                          │                             │
   │  2. Return presigned URL │                             │
   │◀─────────────────────────│                             │
   │                          │                             │
   │  3. Upload directly to S3│                             │
   │──────────────────────────────────────────────────────▶│
   │                          │                             │
   │                          │    4. S3 Event triggers     │
   │                          │       Validator Lambda      │
   │                          │                             │
   │  5. Poll for status      │                             │
   │─────────────────────────▶│                             │
   │                          │                             │
   │  6. Return result        │                             │
   │◀─────────────────────────│                             │
```

---

## 12. Implementation Phases

| Phase | Focus | Components | Status |
|-------|-------|------------|--------|
| **Phase 1** | Foundation | S3 bucket, Validator Lambda, DB schema, manual upload | NOT DEPLOYED |
| **Phase 2** | API Key Inverters | SolarEdge + GoodWe fetchers, credential storage | CODE COMPLETE (schedules disabled) |
| **Phase 3** | OAuth Inverters | OAuth callback endpoint, Enphase + SMA fetchers | CODE COMPLETE (schedules disabled) |
| **Phase 4** | Client Platforms | Snowflake integration, documentation for clients | NOT STARTED |
| **Phase 5** | Polish | Monitoring, alerting, credential health checks | NOT STARTED |

> **Note:** Fetcher GitHub Actions workflows are disabled until AWS infrastructure (S3 bucket, Secrets Manager, IAM roles) is deployed. Workflows can still be triggered manually for testing via `workflow_dispatch`.

### Phase Implementation Details

#### Phase 1: Foundation (NOT DEPLOYED)
- [ ] S3 bucket structure (`raw/`, `validated/`, `quarantine/`, `archive/`) - infrastructure not created
- [ ] Validator Lambda with S3 trigger - code exists but not deployed
- [x] Database schema (meter_reading partitioned, meter_aggregate, ingestion_log)
- [x] Integration credential table with encryption
- [x] Integration site table with sync tracking

#### Phase 2: API Key Inverters (CODE COMPLETE - schedules disabled)
- [x] Base fetcher class (`data-ingestion/sources/inverter-api/base_fetcher.py`)
- [x] SolarEdge fetcher (`data-ingestion/sources/inverter-api/solaredge/fetcher.py`)
- [x] GoodWe fetcher (`data-ingestion/sources/inverter-api/goodwe/fetcher.py`)
- [x] GitHub Actions workflows (`fetcher-solaredge.yml`, `fetcher-goodwe.yml`) - schedules disabled
- [x] Credential CRUD API endpoints

#### Phase 3: OAuth Inverters (CODE COMPLETE - schedules disabled)
- [x] OAuth token refresh in base_fetcher.py
- [x] Enphase fetcher (`data-ingestion/sources/inverter-api/enphase/fetcher.py`)
- [x] SMA fetcher (`data-ingestion/sources/inverter-api/sma/fetcher.py`)
- [x] OAuth callback Edge Function (`data-ingestion/oauth/supabase-callback/`)
- [x] GitHub Actions workflows (`fetcher-enphase.yml`, `fetcher-sma.yml`) - schedules disabled
- [x] Config updates for OAuth client credentials

#### Phase 4: Snowflake Integration (NOT STARTED)
- [x] FILE_FORMAT_SPEC.md - Canonical data format documentation (`data-ingestion/sources/file-upload/README.md`)
- [x] SNOWFLAKE_INTEGRATION.md - Client setup guide with SQL templates (`data-ingestion/sources/snowflake/README.md`)
- [x] SNOWFLAKE_ONBOARDING_CHECKLIST.md - Onboarding process (`data-ingestion/sources/snowflake/ONBOARDING_CHECKLIST.md`)
- [ ] Database migration to seed data_source ID 5
- [ ] Status-by-hash API endpoint for Snowflake clients
- [ ] IAM role for cross-account S3 access (Terraform)

#### Phase 5: Monitoring & Health (NOT STARTED)
- [ ] CloudWatch custom metrics (ingestion success rate, processing time)
- [ ] CloudWatch alarms (failure rate, credential errors)
- [ ] Health check endpoints (`/health/full`, `/health/credentials`)
- [ ] Credential expiration alerts (7-day warning)
- [ ] Monitoring dashboard

---

## 13. Project Structure

```
project/
├── data-ingestion/                  # All data ingestion components
│   ├── README.md                    # Overview and links
│   │
│   ├── sources/                     # Data source integrations
│   │   ├── file-upload/
│   │   │   └── README.md            # File format specification
│   │   │
│   │   ├── inverter-api/            # Manufacturer API fetchers
│   │   │   ├── base_fetcher.py      # Base class with common logic
│   │   │   ├── config.py            # Configuration management
│   │   │   ├── requirements.txt     # Python dependencies
│   │   │   ├── solaredge/fetcher.py # SolarEdge API fetcher
│   │   │   ├── enphase/fetcher.py   # Enphase API fetcher (OAuth)
│   │   │   ├── goodwe/fetcher.py    # GoodWe API fetcher
│   │   │   └── sma/fetcher.py       # SMA API fetcher (OAuth)
│   │   │
│   │   └── snowflake/               # Client Snowflake integration
│   │       ├── README.md            # Integration guide
│   │       ├── ONBOARDING_CHECKLIST.md
│   │       └── terraform/           # IAM resources
│   │
│   ├── processing/                  # S3 event processing
│   │   ├── validator-lambda/
│   │   │   ├── handler.py           # Lambda entry point
│   │   │   ├── schema_validator.py  # Schema validation logic
│   │   │   ├── transformer.py       # Transform to canonical model
│   │   │   ├── loader.py            # Load to Supabase
│   │   │   └── template.yaml        # SAM deployment template
│   │   └── infrastructure/          # AWS infrastructure configs
│   │
│   └── oauth/                       # OAuth callback handling
│       └── supabase-callback/
│           └── index.ts             # OAuth callback handler
│
├── .github/
│   └── workflows/
│       ├── fetcher-solaredge.yml
│       ├── fetcher-enphase.yml
│       ├── fetcher-goodwe.yml
│       └── fetcher-sma.yml
│
└── database/
    └── migrations/
        ├── 001_integration_credential.sql
        ├── 002_integration_site.sql
        ├── 003_meter_reading_partitioned.sql
        ├── 004_meter_aggregate.sql
        └── 005_default_event_evidence.sql
```

---

## 14. Cost Estimate

| Component | Monthly Cost |
|-----------|--------------|
| Supabase Pro | $25 |
| S3 storage + requests | $5-15 |
| Lambda executions | $0-5 |
| GitHub Actions | Free (within limits) |
| **Total** | **$30-45/month** |

---

## 15. Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Ingestion strategy | S3-first (Lake-House) | Audit trail, replayability, decoupling |
| Inverter API integration | Custom Fetcher Workers | No pre-built connectors, need credential management |
| Fetcher runtime | GitHub Actions | Free, ephemeral, simple |
| Client platform integration | Client pushes to S3 | Simpler than pulling, client controls schedule |
| Validation | Lambda triggered by S3 | Serverless, event-driven |
| Time-series storage | Native Postgres partitioning | Simpler than TimescaleDB, sufficient for scale |
| Raw data retention | 90 days | Balance storage cost vs debugging needs |
| Evidence preservation | JSONB in default_event | Proof survives raw data deletion |
| OAuth callback | Supabase Edge Function | Stays in ecosystem, serverless |

---

## 16. What Was Removed (and Why)

| Removed | Reason |
|---------|--------|
| **Airbyte** | Overkill for ~5 inverter APIs; unnecessary infrastructure cost/maintenance |
| **Always-on FastAPI server** | No need for 24/7 server just for cron jobs; prefer ephemeral execution |
| **TimescaleDB** | Native Postgres partitioning is sufficient; less lock-in |
| **Custom Snowflake connector** | Let client push via COPY INTO; simpler, client controls schedule |

---

*This document provides complete context for implementing the data ingestion and integration system.*
