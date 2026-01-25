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

### v4.0 - 2026-01-19 (Power Purchase Ontology Framework)

**Description:** Implements semantic ontology layer for explicit clause relationships. Enables relationship-based excuse detection in rules engine and obligation tracking.

**Reference:** `contract-digitization/docs/ONTOLOGY_GUIDE.md`

**Migrations:**
- `database/migrations/014_clause_relationship.sql` - Clause relationship table and event enhancements
- `database/migrations/015_obligation_view.sql` - Obligation VIEW and helper functions

**Key Changes:**

**New Enum Type: relationship_type**
- `TRIGGERS` - Source breach triggers target consequence (e.g., availability → LD)
- `EXCUSES` - Source event excuses target obligation (e.g., FM → availability)
- `GOVERNS` - Source sets context for target (e.g., CP → all obligations)
- `INPUTS` - Source provides data to target (e.g., pricing → payment)

**New Table: clause_relationship**
- `id` - BIGSERIAL PRIMARY KEY
- `source_clause_id` - BIGINT REFERENCES clause(id) ON DELETE CASCADE
- `target_clause_id` - BIGINT REFERENCES clause(id) ON DELETE CASCADE
- `relationship_type` - relationship_type enum
- `is_cross_contract` - BOOLEAN (for PPA ↔ O&M relationships)
- `parameters` - JSONB (relationship-specific parameters)
- `is_inferred` - BOOLEAN (auto-detected vs explicit)
- `confidence` - NUMERIC(4,3) (0.000-1.000 for inferred relationships)
- `inferred_by` - VARCHAR(100) ('pattern_matcher', 'claude_extraction', 'human')
- `created_at`, `created_by`
- Unique constraint on (source_clause_id, target_clause_id, relationship_type)
- Indexes on source_clause_id, target_clause_id, relationship_type, is_cross_contract

**New View: obligation_view**
- Exposes "Must A" obligations only (AVAILABILITY, PERFORMANCE_GUARANTEE, PAYMENT_TERMS, etc.)
- Extracts metric, threshold_value, comparison_operator, evaluation_period from normalized_payload
- Includes responsible_party, beneficiary_party
- Does NOT include LD parameters (consequences come from TRIGGERS relationships per ontology design)
- Read-only VIEW on clause table (not a duplicate table)

**New View: obligation_with_relationships**
- Extends obligation_view with relationship counts
- Aggregates excuse_categories, triggered_categories arrays
- Includes `ld_parameters` JSONB - extracted from triggered LIQUIDATED_DAMAGES clause via clause_relationship
- Useful for UI dashboards

**Enhanced event table:**
- Added: `contract_id` - BIGINT REFERENCES contract(id) (optional contract link)
- Added: `verified` - BOOLEAN (for excuse verification)
- Added: `verified_by` - UUID
- Added: `verified_at` - TIMESTAMPTZ

**New event_type seeds:**
- `FORCE_MAJEURE` - Act of God, war, natural disaster
- `SCHEDULED_MAINT` - Planned maintenance outage
- `GRID_CURTAIL` - Utility-ordered output reduction
- `UNSCHED_MAINT` - Emergency repairs
- `WEATHER` - Extreme weather affecting performance
- `PERMIT_DELAY` - Regulatory delay
- `EQUIP_FAILURE` - Equipment malfunction
- `GRID_OUTAGE` - Grid unavailability

**Helper Functions:**
- `get_excuses_for_clause(clause_id)` - Returns clauses that excuse given clause
- `get_triggers_for_clause(clause_id)` - Returns consequences triggered by clause
- `get_contract_relationship_graph(contract_id)` - Returns full relationship graph
- `get_obligation_details(clause_id)` - Returns obligation with all relationships and `ld_parameters` JSONB from triggered LIQUIDATED_DAMAGES clause

**Python Backend Integration:**
- `python-backend/services/ontology/` - New ontology service package
- `python-backend/db/ontology_repository.py` - Repository for relationship CRUD
- `python-backend/api/ontology.py` - REST API endpoints
- `python-backend/config/relationship_patterns.yaml` - Pattern definitions for auto-detection

**API Endpoints:**
- `GET /api/ontology/contracts/{id}/obligations` - List obligations
- `GET /api/ontology/clauses/{id}/relationships` - Get clause relationships
- `GET /api/ontology/clauses/{id}/triggers` - Get triggered consequences
- `GET /api/ontology/clauses/{id}/excuses` - Get excuse clauses
- `POST /api/ontology/contracts/{id}/detect-relationships` - Auto-detect relationships
- `GET /api/ontology/contracts/{id}/relationship-graph` - Get full graph

**Rules Engine Integration:**
- `BaseRule._get_excused_types_from_relationships()` - Queries EXCUSES relationships
- `_calculate_excused_hours()` now combines legacy + relationship-based excuses
- Auto-detection runs after contract parsing (Step 8 in pipeline)

**Design Notes:**
- VIEW-based obligation exposure (not table) per ontology framework recommendation
- Single source of truth: clause table remains master, VIEW derives from it
- Backward compatible: legacy `excused_events` in normalized_payload still works
- Relationship detection uses configurable patterns in YAML
- Cross-contract relationships supported (PPA ↔ O&M)

---

### v5.1 - 2026-01-24 (Simplified Export & Reports - Invoice-Focused)

**Description:** Simplified report generation schema focused on invoice workflows. Removed approval workflow, consolidated workflows into on-demand vs scheduled generation, integrated with billing_period table.

**Reference:** `IMPLEMENTATION_GUIDE_REPORTS.md`

**Migrations:**
- `database/migrations/018_export_and_reports_schema.sql` - Simplified report generation tables

**Key Changes from v5.0:**
- **Removed:** `export_request` table (merged into simplified workflow)
- **Removed:** Approval workflow (no `requires_approval`, `approved_by`, etc.)
- **Removed:** `check_export_requires_approval()` function
- **Simplified:** Status lifecycle from 7 states to 4 (pending, processing, completed, failed)
- **Simplified:** Report types from 8 generic to 4 invoice-focused
- **Added:** `billing_period_id` FK instead of date ranges
- **Added:** `generation_source` enum for audit trail (on_demand vs scheduled)

**New Enum Types:**
- `report_type` - (invoice_to_client, invoice_expected, invoice_received, invoice_comparison)
- `file_format` - (csv, xlsx, json, pdf)
- `report_frequency` - (monthly, quarterly, annual, on_demand)
- `report_status` - (pending, processing, completed, failed)
- `generation_source` - (on_demand, scheduled)
- `delivery_method` - (email, s3, both)

**Invoice Report Types (4 focused types):**
| Type | Description | Source Tables |
|------|-------------|---------------|
| `invoice_to_client` | Generated invoice to issue to paying client | invoice_header, invoice_line_item |
| `invoice_expected` | Expected invoice from contractor | expected_invoice_header |
| `invoice_received` | Received invoice from contractor | received_invoice_header |
| `invoice_comparison` | Variance analysis (expected vs received) | invoice_comparison, invoice_comparison_line_item |

**Table: report_template (simplified)**
- Reusable report configurations with organization/project scoping
- `report_type` uses new `report_type` enum
- Template-specific settings: `include_charts`, `include_summary`, `include_line_items`
- Default scope: `default_contract_id`
- Branding: logo, header, footer text
- Unique constraint via partial indexes (PG14 compatible)

**Table: scheduled_report (simplified)**
- Automated report scheduling linked to report_template
- Frequency: monthly, quarterly, annual (removed daily, weekly - aligned with billing periods)
- **Billing period integration:** `billing_period_id` FK
  - `NULL` = auto-select most recent completed billing period at run time
  - Set = always use specific billing period (for historical reruns)
- Email delivery with recipients JSONB array
- S3 automated storage option
- CHECK constraint: `chk_frequency_requires_day` - Ensures day_of_month is set for scheduled frequencies

**Table: generated_report (simplified)**
- Historical report archive
- **Traceability:** `report_template_id`, `scheduled_report_id`, `generation_source`
- **Billing period:** `billing_period_id` FK (replaces period_start/period_end)
- File details: path, size, hash
- Processing metrics: started_at, completed_at, time_ms, error
- Summary data JSONB for quick dashboard display
- Download tracking and archival

**Helper Functions:**
- `get_latest_completed_billing_period()` - Returns most recent billing period where end_date < CURRENT_DATE (STABLE)
- `calculate_next_run_time()` - Computes next scheduled run for monthly/quarterly/annual (STABLE)
  - Null parameter validation: raises exception if day_of_month NULL for scheduled frequencies
  - Timezone-aware arithmetic
- `get_report_statistics()` - Report metrics by organization (STABLE SECURITY DEFINER)

**Pre-seeded Templates (4 invoice-focused):**
- Invoice to Client Report
- Expected Invoice Report
- Received Invoice Report
- Invoice Comparison Report

**Triggers:**
- `report_template_updated_at` - Auto-update timestamp on modification
- `scheduled_report_next_run` - Auto-calculate next_run_at when schedule changes
- `generated_report_timestamps` - Auto-update processing timestamps on status change

**Performance Indexes:**
- `idx_generated_report_billing_period` - Billing period lookup
- `idx_generated_report_pending` - Partial index for processing queue
- `idx_generated_report_created` - Organization + created_at DESC for listing
- `idx_scheduled_report_active_next_run` - Composite for scheduler queries
- `idx_report_template_config` - GIN index for JSONB template_config

**Security:**
- RLS enabled on all tables
- Org members can view, admins can modify
- Service role bypass for background processing
- REVOKE FROM PUBLIC on all helper functions

---

### v5.2 - 2026-01-24 (Invoice Reconciliation Columns)

**Description:** Added final reconciliation columns to `invoice_comparison` table to track the reconciled payment amount after variance review.

**Migrations:**
- `database/migrations/019_invoice_comparison_final_amount.sql` - Add final_amount and adjustment_amount columns

**Changes:**

**Enhanced invoice_comparison table:**
- `final_amount` - NUMERIC(15,2) - Final reconciled amount to pay contractor (may differ from received amount after negotiation)
- `adjustment_amount` - NUMERIC(15,2) DEFAULT 0 - Adjustment made during reconciliation (final_amount - received_amount)

**New Index:**
- `idx_invoice_comparison_final_amount` - Partial index on final_amount WHERE final_amount IS NOT NULL

**Workflow:**
1. Comparison created → `final_amount` = NULL (not yet reconciled)
2. User reviews variance → Updates `status` (matched/underbilled/overbilled)
3. User reconciles → Sets `final_amount` (and optionally `adjustment_amount`)
4. Reports → Query `final_amount` for payment reports

**Design Notes:**
- Columns added to existing table (no new table required)
- `final_amount` nullable to distinguish unreconciled comparisons
- `adjustment_amount` defaults to 0 for backward compatibility
- Partial index optimizes queries for reconciled invoices only

---

### v5.3 - 2026-01-25 (Enum Name Cleanup)

**Description:** Simplify enum names where context is unambiguous to improve consistency between enum names and column names.

**Migrations:**
- `database/migrations/020_rename_report_enums.sql` - Rename enums to simpler names

**Enum Renames:**

| Old Name | New Name | Reason |
|----------|----------|--------|
| `invoice_report_type` | `report_type` | Clearly scoped to reports, no conflict |
| `export_file_format` | `file_format` | No conflict in schema |
| `report_delivery_method` | `delivery_method` | No conflict in schema |

**Enums Kept Unchanged:**

| Enum | Reason |
|------|--------|
| `report_frequency` | Differentiates from meter data frequency |
| `report_status` | Differentiates from contract/invoice status |
| `generation_source` | Already clean, no prefix |

**Design Notes:**
- PostgreSQL `ALTER TYPE ... RENAME TO` automatically updates all columns referencing the enum
- No application code changes required (column names unchanged)
- Comments added to new enum types for documentation

---

### v4.1 - 2026-01-20 (Security Hardening)

**Description:** Comprehensive security hardening based on Security & Privacy Assessment cross-reference analysis. Implements audit logging, enhanced RLS, and access controls.

**Reference:** `SECURITY_PRIVACY_ASSESSMENT.md` Appendix E

**Migrations:**
- `database/migrations/016_audit_log.sql` - Comprehensive audit logging
- `database/migrations/017_core_table_rls.sql` - RLS policies for core tables

**Key Changes:**

**New Enum: audit_action_type**
- 50+ action types covering: authentication, authorization, data events, PII access, contract events, integration events, administrative events, security events

**New Enum: audit_severity**
- `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**New Enum: data_classification_level**
- `public` - Safe for public access (API health, version info)
- `internal` - Internal use only, minimal harm if exposed (general events)
- `confidential` - Sensitive business data, requires protection (pricing, terms)
- `restricted` - PII, credentials, security - strictest controls, may trigger legal notification (GDPR, CCPA)

**New Table: audit_log**
- `id` - BIGSERIAL PRIMARY KEY
- `timestamp` - TIMESTAMPTZ (when event occurred)
- `user_id` - UUID REFERENCES auth.users (actor)
- `organization_id` - BIGINT REFERENCES organization (tenant)
- `session_id` - TEXT
- `action` - audit_action_type
- `severity` - audit_severity
- `resource_type` - TEXT (e.g., 'contract', 'clause')
- `resource_id` - TEXT
- `resource_name` - TEXT
- `ip_address` - INET
- `user_agent` - TEXT
- `details` - JSONB (flexible event data)
- `success` - BOOLEAN
- `error_message` - TEXT
- `duration_ms` - INTEGER
- `records_affected` - INTEGER
- `compliance_relevant` - BOOLEAN
- `data_classification` - data_classification_level ENUM (DEFAULT 'internal')
- Indexes: timestamp, user_id, organization_id, action, resource, severity, compliance

**Immutability Enforcement:**
- `prevent_audit_log_modification()` - Trigger function that blocks UPDATE/DELETE
- `audit_log_immutability` - BEFORE UPDATE OR DELETE trigger on audit_log
- Ensures forensic integrity and compliance with data protection regulations

**New Helper Functions:**
- `log_audit_event()` - Main audit logging function (SECURITY DEFINER)
  - Validates organization_id and user_id exist before INSERT
  - Only callable by service_role (PUBLIC revoked)
- `log_pii_access_event()` - Convenience wrapper for PII access logging
  - Validates contract_id exists (BIGINT to match contract.id BIGSERIAL)
  - Auto-classifies as 'restricted'
  - Only callable by service_role (PUBLIC revoked)
- `get_audit_summary()` - Audit statistics by organization
  - Requires caller to be admin of the specified organization (authorization check)
  - Service role bypass: backend can call without admin check
  - Granted to both authenticated and service_role
- `prevent_audit_log_modification()` - Immutability trigger function
  - PUBLIC execution revoked for security

**New View: v_security_events**
- Shows WARNING/ERROR/CRITICAL events with user and org info
- Useful for security monitoring dashboards

**RLS Helper Functions (migration 017):**
- `is_org_member(p_org_id)` - Check if current user is a member of org (SECURITY DEFINER)
- `is_org_admin(p_org_id)` - Check if current user is an admin of org (SECURITY DEFINER)
- `get_project_org_id(p_project_id)` - Get organization_id for a project
- `get_contract_org_id(p_contract_id)` - Get organization_id for a contract (via project)
- `get_asset_org_id(p_asset_id)` - Get organization_id for an asset (via project)
- `get_meter_org_id(p_meter_id)` - Get organization_id for a meter (via asset -> project)
- All helper functions: PUBLIC revoked, granted to authenticated and service_role

**RLS Performance Indexes (migration 017):**
- `idx_role_user_org_active` - Composite index on role(user_id, organization_id, is_active)
- `idx_role_admin_check` - Partial index for admin checks
- `idx_project_id_org` - Project org lookup
- `idx_contract_project` - Contract to project mapping
- `idx_asset_project` - Asset to project mapping
- `idx_meter_asset` - Meter to asset mapping

**RLS Policies Added:**

Tables with new RLS:
- `organization` - Users see only their organization
- `project` - Organization-scoped
- `contract` - Organization-scoped via project
- `clause` - Organization-scoped via contract
- `event` - Organization-scoped via contract
- `default_event` - Organization-scoped via contract
- `counterparty` - Organization-scoped
- `invoice_header` - Organization-scoped via contract
- `received_invoice_header` - Organization-scoped via contract
- `asset` - Organization-scoped via project
- `meter` - Organization-scoped via asset
- `meter_reading` - Organization-scoped via meter
- `audit_log` - Admins see org logs, users see own activity

Policy Pattern (applied to all):
- `{table}_org_policy` - SELECT: Uses `is_org_member()` helper
- `{table}_admin_modify_policy` - ALL: Uses `is_org_admin()` helper
- `{table}_service_policy` - ALL: Service role full access
- All policies idempotent: `DROP POLICY IF EXISTS` before `CREATE POLICY`

**Security Features:**
- All audit log entries have organization isolation
- PII access always logged with COMPLIANCE_RELEVANT=true
- Admin-only approval for bulk exports (via Python service)
- Service role policies enable backend operations
- Audit log immutability enforced via trigger (no UPDATE/DELETE)
- Input validation on all SECURITY DEFINER functions
- Authorization check on `get_audit_summary()` (admin-only)
- Service role bypass for `get_audit_summary()` (trusted backend)
- Data classification ENUM ensures only valid values
- Explicit REVOKE FROM PUBLIC on all SECURITY DEFINER functions

**Operational Procedures:**
- Immutability trigger bypass procedure documented in migration comments
- For GDPR right-to-erasure or court orders: use ALTER TABLE DISABLE/ENABLE TRIGGER
- All bypass operations must be logged manually and go through change management

**Application Integration:**
- `python-backend/middleware/rate_limiter.py` - FastAPI rate limiting
- `python-backend/services/export_controls.py` - Dual approval for bulk exports
- `lib/auth/helpers.ts` - MFA enforcement
- `lib/supabase/middleware.ts` - Session timeout tracking

**Configuration:**
- `REQUIRE_MFA=true` - Enable MFA enforcement
- `SESSION_IDLE_TIMEOUT=1800` - 30 minute idle timeout
- `SESSION_ABSOLUTE_TIMEOUT=86400` - 24 hour absolute timeout
- `RATE_LIMIT_DEFAULT=100/minute` - API rate limiting
- `EXPORT_BULK_THRESHOLD=20` - Bulk export approval threshold

---
