# Database Schema Change Log

This document tracks major schema versions and their associated changes.

## Version History

### v1.0 - 2025-01-XX (Baseline)

**Description:** Initial database schema with 50+ tables for contract compliance system.

**Schema File:** `database/versions/v1.0_baseline.sql`

**Key Tables:**
- contract, clause, clause_type, clause_category
- meter_reading, meter_aggregate
- default_event, rule_output
- invoice_header, invoice_line_item
- organization, project, counterparty

---

### v1.1 - 2026-01-XX (Phase 1 - Authentication)

**Description:** Added authentication support with Supabase Auth integration.

**Schema File:** `database/versions/v1.1_phase1_auth.sql`

**Migrations:**
- `database/migrations/001_migrate_role_to_auth.sql`

**Changes:**
- Added user_id UUID to role table
- Added role_type ('admin', 'staff')
- Added is_active, updated_at fields
- Linked role table to auth.users

**Diagrams:**
- `database/diagrams/entity_diagram_v1.1.drawio`

---

### v2.0 - 2026-01-11 (Phase 2 - Contract Parsing)

**Description:** Added contract parsing infrastructure with PII protection and AI extraction tracking.

**Schema File:** `database/versions/v2.0_phase2_parsing.sql`

**Migrations:**
- ✅ `database/migrations/002_add_contract_pii_mapping.sql` - Encrypted PII storage
- ✅ `database/migrations/003_add_contract_parsing_fields.sql` - Contract parsing status tracking
- ✅ `database/migrations/004_enhance_clause_table.sql` - AI extraction fields
- ⏳ `database/migrations/005_add_audit_trails.sql` - Audit logging (future)

**Implemented Changes:**

**New Table: contract_pii_mapping**
- `id` - BIGSERIAL PRIMARY KEY
- `contract_id` - BIGINT REFERENCES contract(id)
- `encrypted_mapping` - BYTEA (AES-256-GCM encrypted JSON)
- `pii_entities_count` - INTEGER
- `encryption_method` - VARCHAR(50)
- `created_at`, `created_by`, `accessed_at`, `accessed_by`, `access_count`
- Row Level Security (RLS) enabled - admin-only access
- Helper functions: `log_pii_access()`, `get_contract_pii_count()`

**Enhanced contract table:**
- `parsing_status` - VARCHAR(50) [pending, processing, completed, failed]
- `parsing_started_at` - TIMESTAMPTZ
- `parsing_completed_at` - TIMESTAMPTZ
- `parsing_error` - TEXT
- `pii_detected_count` - INTEGER
- `clauses_extracted_count` - INTEGER
- `processing_time_seconds` - NUMERIC(10,2)
- Helper functions: `update_contract_parsing_status()`, `get_parsing_statistics()`

**Enhanced clause table:**
- `summary` - TEXT (AI-generated clause summary)
- `beneficiary_party` - VARCHAR(255) (who benefits from clause)
- `confidence_score` - NUMERIC(4,3) (AI confidence 0.0-1.0)
- Helper functions: `get_clauses_needing_review()`, `get_contract_clause_stats()`

**Security Features:**
- PII encrypted using application-level keys (not stored in DB)
- Row Level Security on PII mappings (admin-only)
- Access logging for PII decryption
- pgcrypto extension enabled

**Diagrams:**
- `database/diagrams/entity_diagram_v2.0.drawio` (to be created)

---

### v2.1 - 2026-01-15 (Clause Category Restructure)

**Description:** Restructured clause categories to a flat 13-category system for contract extraction.

**Migrations:**
- `database/migrations/005_update_clause_categories.sql` - Truncate and reseed clause_category

**Changes:**

**Restructured clause_category table:**
- Truncated existing data for clean start
- Reseeded with 13 standardized categories:
  1. CONDITIONS_PRECEDENT - Contract effectiveness requirements
  2. AVAILABILITY - Uptime, meter accuracy, curtailment
  3. PERFORMANCE_GUARANTEE - Output, capacity factor, degradation
  4. LIQUIDATED_DAMAGES - Penalties for breaches
  5. PRICING - Rates, escalation, adjustments
  6. PAYMENT_TERMS - Billing, take-or-pay obligations
  7. DEFAULT - Events of default, cure periods, remedies
  8. FORCE_MAJEURE - Excused events
  9. TERMINATION - End provisions, purchase options, FMV
  10. MAINTENANCE - O&M, SLAs, outages
  11. COMPLIANCE - Regulatory, environmental requirements
  12. SECURITY_PACKAGE - LCs, bonds, guarantees
  13. GENERAL - Governing law, disputes, notices, confidentiality

**Design Notes:**
- Flat hierarchy (no sub-categories)
- Added `key_terms` array for extraction matching
- UNIDENTIFIED clauses use `clause_category_id = NULL`
- Reference: `python-backend/CONTRACT_EXTRACTION_RECOMMENDATIONS_20260115.md`

---

### v3.0 - 2026-01-16 (Data Ingestion Lake-House)

**Description:** Lake-house architecture for multi-source meter data ingestion.

**Reference:** `DATA_INGESTION_ARCHITECTURE.md`

**Migrations:**
- `database/migrations/006_meter_reading_v2.sql` - Partitioned meter_reading with canonical model
- `database/migrations/007_meter_aggregate_enhance.sql` - Enhanced aggregation fields
- `database/migrations/008_default_event_evidence.sql` - Evidence JSONB for audit trail
- `database/migrations/009_integration_credential.sql` - API key/OAuth token storage
- `database/migrations/010_integration_site.sql` - External site mapping
- `database/migrations/011_ingestion_log.sql` - Ingestion audit trail

**Key Changes:**

**Restructured meter_reading table (BREAKING - no existing data):**
- Dropped old single-value structure
- New columns: `source_system`, `reading_interval` (uses `updated_frequency` enum), `energy_wh`, `power_w`, `irradiance_wm2`, `temperature_c`, `other_metrics`, `quality`, `ingested_at`
- Added external identifiers: `external_site_id`, `external_device_id`
- Monthly partitioning (PARTITION BY RANGE on reading_timestamp)
- 90-day retention policy
- Helper function: `create_meter_reading_partition(date)`
- **pg_cron job**: `meter-reading-partition-maintenance` runs monthly to auto-create partitions 3 months ahead

**Enhanced meter_aggregate table:**
- Added: `organization_id`, `period_type`, `period_start`, `period_end`
- Added: `energy_wh`, `energy_kwh` for standardized values
- Added: `hours_available`, `hours_expected`, `availability_percent`
- Added: `reading_count`, `data_completeness_percent`
- Added: `source_system`, `aggregated_at`
- Helper function: `calculate_availability_percent(hours_available, hours_expected)`

**Enhanced default_event table:**
- Added: `evidence` JSONB for preserved audit trail
- Added: `evidence_archived_at`, `evidence_s3_path` for Glacier archival
- Helper functions: `validate_default_event_evidence()`, `preserve_default_event_evidence()`

**New Table: integration_credential**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id` - BIGINT REFERENCES organization(id)
- `data_source_id` - BIGINT REFERENCES data_source(id)
- `auth_type` - VARCHAR(20): 'api_key', 'oauth2'
- `encrypted_credentials` - BYTEA (Fernet-encrypted JSON)
- `token_expires_at` - TIMESTAMPTZ for OAuth refresh
- `is_active`, `last_used_at`, `last_error`, `error_count`
- Row Level Security enabled
- Helper functions: `integration_credential_needs_refresh()`, `integration_credential_record_success()`, `integration_credential_record_error()`

**New Table: integration_site**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id`, `integration_credential_id`, `project_id`, `meter_id`
- `data_source_id` - BIGINT REFERENCES data_source(id)
- `external_site_id`, `external_site_name`, `external_metadata`
- `sync_enabled`, `sync_interval_minutes`
- `last_sync_at`, `last_sync_status`, `last_sync_error`
- Row Level Security enabled
- Helper functions: `get_sites_ready_for_sync(p_data_source_id)`, `update_site_sync_status()`

**New Enum Types:**
- `ingestion_status` - ('processing', 'success', 'quarantined', 'skipped', 'error')
- `ingestion_stage` - ('validating', 'transforming', 'loading', 'moving', 'complete')

**New Table: ingestion_log**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id`, `integration_site_id`
- `data_source_id` - BIGINT REFERENCES data_source(id)
- `ingestion_status` - ingestion_status enum (processing, success, quarantined, skipped, error)
- `ingestion_stage` - ingestion_stage enum (validating, transforming, loading, moving, complete)
- `file_path`, `file_size_bytes`, `file_format`, `file_hash`
- `rows_in_file`, `rows_valid`, `rows_loaded`, `rows_skipped`, `rows_failed`
- `validation_errors` - JSONB array of errors
- `processing_time_ms`
- Row Level Security enabled
- Helper functions: `start_ingestion_log(p_data_source_id)`, `complete_ingestion_log_success()`, `complete_ingestion_log_quarantine()`, `get_ingestion_stats()`

**Infrastructure:**
- S3 bucket: `frontiermind-meter-data`
- Validator Lambda for S3-triggered ingestion
- GitHub Actions for scheduled fetchers (future phases)

**Design Notes:**
- S3-first lake-house pattern: all data lands in S3 before database
- Validator Lambda processes S3 events: raw/ → validated/ or quarantine/
- Multi-source support: SolarEdge, Enphase, SMA, GoodWe, Snowflake, Manual
- 90-day raw data retention, aggregates kept forever
- Evidence preserved in default_event before raw data deletion

---

### v3.1 - 2026-01-17 (Audit Column Standardization)

**Description:** Standardized audit columns (created_by, updated_by) from VARCHAR to UUID with FK reference to auth.users(id) for consistency with Supabase Auth.

**Migrations:**
- `database/migrations/012_audit_columns_uuid.sql` - Audit column type migration

**Changes:**

**Migrated columns to UUID REFERENCES auth.users(id):**

| Table | Column | Previous Type |
|-------|--------|---------------|
| contract | updated_by | VARCHAR |
| clause | updated_by | VARCHAR |
| event | created_by | VARCHAR |
| event | updated_by | VARCHAR |
| default_event | created_by | VARCHAR |
| default_event | updated_by | VARCHAR |
| rule_output | created_by | VARCHAR |
| rule_output | updated_by | VARCHAR |

**Design Notes:**
- Aligns with Supabase Auth integration pattern from migration 001
- Matches newer tables (integration_credential, integration_site, etc.)
- Enables FK constraint enforcement for user references
- Existing VARCHAR data dropped (not migratable without user mapping)

---
