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
- S3 bucket: `frontiermind-meter`
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

**Reference:** `IMPLEMENTATION_GUIDE_REPORT_GENERATION.md`

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
- **Status:** `report_status` column (uses `report_status` enum - aligned column/enum naming)
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

### v5.4 - 2026-01-26 (Contract Metadata Extraction)

**Description:** Added extraction_metadata JSONB column to contract table and seeded contract_type lookup table for AI-extracted contract metadata.

**Reference:** `IMPLEMENTATION_GUIDE.md` - Contract Metadata Extraction section

**Migrations:**
- `database/migrations/020_contract_extraction_metadata.sql` - Add extraction_metadata column and seed contract_type

**Changes:**

**Enhanced contract table:**
- `extraction_metadata` - JSONB - AI-extracted metadata including:
  - `seller_name` - Extracted seller legal name
  - `buyer_name` - Extracted buyer legal name
  - `counterparty_matched` - Boolean if matched to existing record
  - `counterparty_match_confidence` - Match confidence score (0-1)
  - `contract_type_extracted` - Original extracted type code
  - `contract_type_confidence` - Extraction confidence
  - `extraction_timestamp` - When extraction occurred
  - `extraction_notes` - Notes from extraction process

**New Index:**
- `idx_contract_extraction_metadata` - GIN index for JSONB querying

**Seeded contract_type table:**
| Code | Name | Description |
|------|------|-------------|
| PPA | Power Purchase Agreement | Agreement for purchase of electricity |
| O_M | Operations & Maintenance | Facility O&M services agreement |
| EPC | Engineering Procurement Construction | Facility construction agreement |
| LEASE | Lease Agreement | Land or equipment lease |
| IA | Interconnection Agreement | Grid interconnection with utility |
| ESA | Energy Storage Agreement | Battery/storage services |
| VPPA | Virtual Power Purchase Agreement | Financial PPA |
| TOLLING | Tolling Agreement | Offtaker provides fuel |
| OTHER | Other | Unclassified contract type |

**New Helper Function:**
- `get_contracts_needing_counterparty_review(p_limit)` - Returns contracts where counterparty was extracted but not matched to existing records

**Python Backend Integration:**
- `python-backend/services/prompts/metadata_extraction_prompt.py` - New metadata extraction prompt
- `python-backend/db/lookup_service.py` - Added counterparty matching with rapidfuzz, FK validation
- `python-backend/db/contract_repository.py` - Added `update_contract_metadata()` method
- `python-backend/services/contract_parser.py` - Added metadata extraction step in pipeline
- `python-backend/api/contracts.py` - Added FK validation at upload

**Dependencies:**
- `rapidfuzz>=3.6.0` - Fuzzy string matching for counterparty matching

**Workflow:**
1. Contract uploaded via API
2. FK validation (organization_id, project_id if provided)
3. Document parsed and PII anonymized
4. Metadata extracted (Step 4.5): contract type, parties, dates
5. Counterparty fuzzy matched to existing records
6. Contract record updated with resolved FKs and extraction_metadata
7. Clauses extracted and stored

**Design Notes:**
- Metadata extraction uses truncated text (~15k chars) since metadata is in first sections
- Counterparty matching uses token_set_ratio (handles word order variations)
- Match threshold of 80% required for automatic counterparty resolution
- Unmatched counterparties stored in extraction_metadata for manual review
- FK validation prevents orphan contract records with invalid references

---

### v5.5 - 2026-01-26 (Billing Period Seed Data)

**Description:** Seed billing_period table with default entry required for invoice/report workflow.

**Migrations:**
- `database/migrations/021_seed_billing_period.sql` - Insert default billing period with ID=1

**Changes:**

**Seeded billing_period table:**
- Inserts billing_period with `id=1`, `name='January 2026'`, dates `2026-01-01` to `2026-01-31`
- Uses `ON CONFLICT (id) DO NOTHING` for idempotency
- Resets sequence to prevent ID conflicts

**Design Notes:**
- Required for invoice generation and report workflow which use `billing_period_id: 1` as default
- The invoice save step (`InvoiceGenerationStep.tsx:163`) and report generation (`ReportGenerationStep.tsx:273`) reference this billing period
- Report queries JOIN on billing_period table - missing record causes empty results

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

**New View: v_security_events** *(dropped in migration 024 — security vulnerability)*
- Shows WARNING/ERROR/CRITICAL events with user and org info
- Useful for security monitoring dashboards
- **Removed:** LEFT JOIN on `auth.users` exposed email; SECURITY DEFINER bypassed RLS

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

**Application Integration (v4.1):**
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

### v5.6 - 2026-01-31 (Client Invoice Validation Architecture)

**Description:** Database architecture for client invoice validation. Adds exchange rates, extends clause_tariff with grouping and client metadata, extends meter_aggregate with billing readings, adds AP/AR invoice direction, and enriches invoice line items with tariff and quantity data.

**Reference:** `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md`

**Migrations:**
- `database/migrations/022_exchange_rate_and_invoice_validation.sql` - All schema changes

**Key Changes:**

**New Table: exchange_rate**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id` - BIGINT REFERENCES organization(id)
- `currency_id` - BIGINT REFERENCES currency(id) (the local currency)
- `rate_date` - DATE (effective date)
- `rate` - DECIMAL (1 USD = X local currency units)
- `source` - VARCHAR(100) DEFAULT 'manual' (manual, api, etc.)
- `created_by` - UUID
- `created_at` - TIMESTAMPTZ
- UNIQUE(organization_id, currency_id, rate_date)
- RLS enabled with org member/admin/service policies
- Index: `idx_exchange_rate_lookup` on (organization_id, currency_id, rate_date DESC)

**Convention:** `rate` = how many units of `currency_id` per 1 USD.
- Example: ZAR with `rate = 18.50` means 1 USD = 18.50 ZAR
- To get USD from local: `local_amount / rate`
- Lookup at runtime: pricing calculator reads `clause_tariff.currency_id`, finds nearest rate on or before billing period date

**New Enum: invoice_direction**
- `payable` - Accounts payable (contractor bills us / expected contractor bill)
- `receivable` - Accounts receivable (we bill client / ERP-generated invoice)

**Extended clause_tariff table:**
- `organization_id` - BIGINT REFERENCES organization(id) (multi-tenant FK)
- `tariff_group_key` - VARCHAR(255) (groups same logical tariff line across time periods; adapter maps client IDs here)
- `meter_id` - BIGINT REFERENCES meter(id) (optional link to physical meter)
- `is_active` - BOOLEAN DEFAULT true (whether tariff line is currently active)
- `source_metadata` - JSONB DEFAULT '{}' (all client-specific fields; core reads only generic columns)
- `updated_at` - TIMESTAMPTZ DEFAULT NOW()
- Indexes: `idx_clause_tariff_group_key`, `idx_clause_tariff_org`, `idx_clause_tariff_meter`

**tariff_group_key usage:**
- CBE maps `CONTRACT_LINE_UNIQUE_ID` → `tariff_group_key` (e.g. "CONZIM00-2025-00002-4000")
- Multiple rows with same key = same logical tariff line with price changes over time
- Future clients use their own convention

**source_metadata examples:**
```json
// CBE:
{"external_line_id": "4000", "product_code": "ENER0001", "metered_available": "EMetered"}
// Future client:
{"sap_material_number": "MAT-12345", "billing_plan_id": "BP-001"}
```

**Extended meter_aggregate table:**
- `clause_tariff_id` - BIGINT REFERENCES clause_tariff(id) (links to billable tariff line)
- `opening_reading` - DECIMAL (meter reading at period start)
- `closing_reading` - DECIMAL (meter reading at period end)
- `utilized_reading` - DECIMAL (net consumption)
- `discount_reading` - DECIMAL DEFAULT 0 (discounted/waived quantity)
- `sourced_energy` - DECIMAL DEFAULT 0 (self-sourced energy to deduct)
- `source_metadata` - JSONB DEFAULT '{}' (client-specific reading metadata)
- Index: `idx_meter_aggregate_clause_tariff`
- `total_production` (existing) = final billable quantity. Adapter computes: `utilized_reading - discount_reading - sourced_energy`

**Two usage patterns for meter_aggregate:**
1. Physical meter pipeline (existing): `meter_id` set, `clause_tariff_id` NULL
2. Client billing data (new): `clause_tariff_id` set, `meter_id` optional

**Extended invoice headers:**
- `expected_invoice_header.invoice_direction` - invoice_direction NOT NULL DEFAULT 'payable'
- `received_invoice_header.invoice_direction` - invoice_direction NOT NULL DEFAULT 'payable'
- `invoice_comparison.invoice_direction` - invoice_direction NOT NULL DEFAULT 'payable'

**Extended expected_invoice_line_item:**
- `clause_tariff_id` - BIGINT REFERENCES clause_tariff(id) (pricing source)
- `meter_aggregate_id` - BIGINT REFERENCES meter_aggregate(id) (readings source; NULL for non-metered)
- `quantity` - DECIMAL (billable quantity; from meter_aggregate or contract terms)
- `line_unit_price` - DECIMAL (unit price at calculation time; from clause_tariff.base_rate)

**Extended received_invoice_line_item:**
- `clause_tariff_id` - BIGINT REFERENCES clause_tariff(id)
- `meter_aggregate_id` - BIGINT REFERENCES meter_aggregate(id)
- `quantity` - DECIMAL (quantity as stated on received invoice)
- `line_unit_price` - DECIMAL (unit price as stated on received invoice)

**Extended invoice_comparison_line_item:**
- `clause_tariff_id` - BIGINT REFERENCES clause_tariff(id) (tariff for variance analysis)
- `variance_percent` - DECIMAL (percentage variance)
- `variance_details` - JSONB DEFAULT '{}' (method-specific breakdown, rounding differences)

**Seeded currency table (11 currencies):**
- USD, EUR, GBP, ZAR, GHS, NGN, KES, RWF, SLE, EGP, MZN

**Seeded tariff_type table (14 types):**
- FLAT, TOU, TIERED, INDEXED, METERED_ENERGY, AVAILABLE_ENERGY, DEEMED_ENERGY
- BESS_CAPACITY, MIN_OFFTAKE, EQUIP_RENTAL, OM_FEE, DIESEL, PENALTY, PRICE_CORRECTION

**Design Notes:**
- No `clause_id` FK on clause_tariff — it's a parallel table to clause, not a child
- No `adjusted_reading` on meter_aggregate — use existing `total_production` as final billable quantity
- No `bill_date` on meter_aggregate — billing date captured on invoice_header
- `exchange_rate_feed` deferred — will be added when auto-fetch scheduler is implemented
- Default `invoice_direction = 'payable'` preserves backward compatibility for existing AP flows
- Non-metered tariffs (capacity, O&M, penalties) have NULL `meter_aggregate_id` with quantity/price stored directly on line items

---

### v6.0 - 2026-02-10 (Actionable Ontology — Canonical Field Names)

**Description:** Simplifies obligation_view COALESCE chains to use canonical ontology field names. Part of the Actionable Ontology Design that standardizes extracted clause payload fields across the pipeline.

**Reference:** `contract-digitization/docs/TEMPORARY_PROPOSAL_ACTIONABLE_ONTOLOGY_DESIGN.md`

**Migrations:**
- `database/migrations/023_simplify_obligation_view.sql` - Simplified obligation VIEW with canonical fields

**Changes:**

**Simplified obligation_view:**
- `threshold_value`: Reduced from 6-way COALESCE to 2-way (`threshold` canonical, `threshold_percent` legacy fallback)
- `evaluation_period`: Simplified to prefer `measurement_period` → `invoice_frequency` → `'annual'`
- Added `rate_value`: New column using `base_rate_per_kwh` canonical with `rate` legacy fallback
- Added `DEFAULT` and `TERMINATION` to obligation category filter
- Removed legacy `PERF_GUARANTEE` and `CAPACITY_FACTOR` codes (now unified as `PERFORMANCE_GUARANTEE`)

**Recreated obligation_with_relationships:**
- Same structure, rebuilt due to dependency on obligation_view

**Recreated get_obligation_details():**
- Same signature and behavior, rebuilt due to dependency on obligation_view

**Python Backend Changes (same release):**
- `python-backend/services/prompts/clause_examples.py` — Added `CANONICAL_SCHEMAS`, `CANONICAL_TERMINOLOGY`, `resolve_aliases()`, `get_schema_for_category()`, `get_required_fields()`, `format_schema_for_prompt()`. Updated all examples to use canonical field names.
- `python-backend/services/ontology/payload_validator.py` — **New**: `validate_payload()`, `normalize_payload()` functions
- `python-backend/services/contract_parser.py` — Added payload normalization step (Phase 1.5), contract type profiles (`CONTRACT_TYPE_PROFILES`), structure map builder, contract type profile warnings
- `python-backend/services/prompts/clause_extraction_prompt.py` — Updated all field lists to canonical names with role annotations [T/FI/FD/S/C/R]
- `python-backend/services/prompts/metadata_extraction_prompt.py` — Added SSA and PROJECT_AGREEMENT contract types
- `python-backend/services/prompts/payload_enrichment_prompt.py` — Updated to reference canonical schemas
- `python-backend/config/relationship_patterns.yaml` — Added MAINTENANCE→AVAILABILITY (GOVERNS), SECURITY_PACKAGE→CONDITIONS_PRECEDENT (INPUTS), SSA↔PPA cross-contract patterns
- `lib/workflow/invoiceGenerator.ts` — Simplified rate fallback: `base_rate_per_kwh` → `rate` (2-way instead of 4-way)

**Design Notes:**
- Canonical field names resolve at extraction time via `resolve_aliases()` — no COALESCE chains needed for new extractions
- Legacy fallbacks in VIEW ensure backward compatibility with pre-ontology clauses
- `CONTRACT_TYPE_PROFILES` enables automatic detection of missing mandatory categories per contract type
- Role annotations (T=Threshold, FI=Formula Input, FD=Formula Definition, S=Schedule, C=Configuration, R=Reference) guide extraction prompts

---

### v6.1 - 2026-02-11 (Security Fix: Drop Insecure View)

**Description:** Dropped `v_security_events` view to fix two Supabase security linter findings: "Exposed Auth Users Entity" (LEFT JOIN on `auth.users` exposed email) and "SECURITY DEFINER property" (bypassed RLS, allowing any authenticated user to read all audit events across all organizations).

**Migrations:**
- `database/migrations/024_drop_insecure_security_events_view.sql` - Drop insecure view

**Changes:**

**Dropped view: v_security_events**
- Previously defined in migration 016 (`016_audit_log.sql`)
- LEFT JOINed `auth.users`, exposing `email` to `authenticated` role via PostgREST
- Used `SECURITY DEFINER`, running with superuser permissions and bypassing all RLS on `audit_log`
- Combined effect: any authenticated user could read ALL security events across ALL organizations
- View was unused — zero references in `app/`, `lib/`, `python-backend/`
- Secure alternative already exists: `get_audit_summary()` provides org-scoped audit access with admin authorization check

**Design Notes:**
- Dropping is preferred over fixing (`security_invoker = true`) because the view is dead code
- `get_audit_summary()` (migration 016) remains the correct way to access audit data
- No application code changes required (view had no consumers)

---

### v6.3 - 2026-02-11 (Billing Aggregate Dedup Index)

**Description:** Adds a unique index on meter_aggregate business keys to enable row-level deduplication for monthly billing aggregates. The billing aggregate pipeline uses `ON CONFLICT DO NOTHING` for idempotent inserts.

**Migrations:**
- `database/migrations/026_meter_aggregate_dedup_index.sql` - Business-key unique index

**Changes:**

**New Unique Index: idx_meter_aggregate_billing_dedup**
- Columns: `organization_id`, `COALESCE(billing_period_id, -1)`, `COALESCE(clause_tariff_id, -1)`
- Partial index: `WHERE period_type = 'monthly'`
- `COALESCE` handles NULL FKs (from unresolved tariffs/periods per the "Load with NULLs + warn" strategy)
- Scoped to monthly billing aggregates only — does not affect hourly/daily physical meter aggregates

**Design Notes:**
- No application code changes required — the loader's `ON CONFLICT DO NOTHING` now has a conflict target
- COALESCE ensures NULL FK values are treated as equal for dedup purposes
- Partial index keeps storage minimal (only monthly rows indexed)

---

### v7.0 - 2026-02-14 (CBE Schema Design Review — Tariff Classification & Operational Tables)

**Description:** Implements schema recommendations from CBE-to-FrontierMind mapping review. Adds org-scoped tariff classification lookup tables, customer contacts, and production forecasts/guarantees.

**Reference:** `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md`

**Migrations:**
- `database/migrations/027_tariff_classification_lookup.sql` - Org-scoped lookup tables + clause_tariff FK extensions
- `database/migrations/028_customer_contact.sql` - Customer contact table
- `database/migrations/029_production_forecast_guarantee.sql` - Production forecast and guarantee tables

**Key Changes:**

**New Table: tariff_structure_type**
- `id` - BIGSERIAL PRIMARY KEY
- `code` - VARCHAR(50) NOT NULL
- `name` - VARCHAR(255) NOT NULL
- `description` - TEXT
- `organization_id` - BIGINT REFERENCES organization(id) (NULL = platform-level canonical)
- `is_active` - BOOLEAN DEFAULT true
- UNIQUE(code, organization_id)
- Seeded: FIXED, GRID, GENERATOR (platform-level)

**New Table: energy_sale_type**
- Same structure as tariff_structure_type
- Seeded: FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES (platform-level)

**New Table: escalation_type**
- Same structure as tariff_structure_type
- Seeded: FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, NONE (platform-level)

**Extended clause_tariff table:**
- `tariff_structure_id` - BIGINT REFERENCES tariff_structure_type(id)
- `energy_sale_type_id` - BIGINT REFERENCES energy_sale_type(id)
- `escalation_type_id` - BIGINT REFERENCES escalation_type(id)
- `market_ref_currency_id` - BIGINT REFERENCES currency(id)

**New Table: customer_contact**
- `id` - BIGSERIAL PRIMARY KEY
- `counterparty_id` - BIGINT NOT NULL REFERENCES counterparty(id) ON DELETE CASCADE
- `organization_id` - BIGINT NOT NULL REFERENCES organization(id)
- `role` - VARCHAR(100) (accounting, cfo, operations_manager, etc.)
- `full_name` - VARCHAR(255)
- `email` - VARCHAR(255)
- `phone` - VARCHAR(50)
- `include_in_invoice_email` - BOOLEAN DEFAULT false
- `escalation_only` - BOOLEAN DEFAULT false
- `is_active` - BOOLEAN DEFAULT true
- `source_metadata` - JSONB DEFAULT '{}'
- Partial index on counterparty_id WHERE include_in_invoice_email AND is_active

**New Table: production_forecast**
- `id` - BIGSERIAL PRIMARY KEY
- `project_id` - BIGINT NOT NULL REFERENCES project(id)
- `organization_id` - BIGINT NOT NULL REFERENCES organization(id)
- `billing_period_id` - BIGINT REFERENCES billing_period(id)
- `forecast_month` - DATE NOT NULL
- `operating_year` - INTEGER
- `forecast_energy_kwh` - DECIMAL NOT NULL
- `forecast_ghi_irradiance` - DECIMAL
- `forecast_pr` - DECIMAL(5,4) (Performance Ratio)
- `degradation_factor` - DECIMAL(6,5)
- `forecast_source` - VARCHAR(100) DEFAULT 'p50'
- UNIQUE(project_id, forecast_month)

**New Table: production_guarantee**
- `id` - BIGSERIAL PRIMARY KEY
- `project_id` - BIGINT NOT NULL REFERENCES project(id)
- `organization_id` - BIGINT NOT NULL REFERENCES organization(id)
- `operating_year` - INTEGER NOT NULL
- `year_start_date` - DATE NOT NULL
- `year_end_date` - DATE NOT NULL
- `guaranteed_kwh` - DECIMAL NOT NULL
- `guarantee_pct_of_p50` - DECIMAL(5,4) (e.g., 0.9000 = 90% of P50)
- `p50_annual_kwh` - DECIMAL
- UNIQUE(project_id, operating_year)
- **Note:** Evaluation data (actual_kwh, shortfall_kwh, evaluation_status) removed — year-end guarantee evaluation is modeled via `default_event` + `rule_output` pipeline (migration 000_baseline), which provides audit trail, LD amounts, breach/excuse flags, and clause linkage

**energy_sale_type seed data correction (2026-02-19):**
- Replaced stale seed data (TAKE_OR_PAY, MIN_OFFTAKE, TAKE_AND_PAY, LEASE) with correct codes from migration 027
- Final canonical set aligned with Excel onboarding template: FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES
- escalation_type stale seeds (FIXED, CPI, CUSTOM, NONE, GRID_PASSTHROUGH) also replaced with: FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, NONE
- GH-MOH01 clause_tariff (id=2) classified: energy_sale_type=FIXED_SOLAR, escalation_type=REBASED_MARKET_PRICE

**Design Notes:**
- Lookup tables use `organization_id` scoping: NULL = platform canonical, non-NULL = client-specific
- METERED_AVAILABLE not promoted to column — `tariff_type_id` FK already carries this semantic; original label preserved in `source_metadata`
- `customer_contact` is 1:many from `counterparty` — avoids flattened contact_N columns anti-pattern
- `production_forecast` and `production_guarantee` are project-level, not clause-level — they are operational data, not pricing formula parameters
- Deferred energy calculation deferred to rules engine / pricing calculator — same rationale as production guarantee evaluation: billing compliance calculations belong at runtime, not materialized as DB views
- All new tables have RLS enabled with standard org member/admin/service policies

---

### v7.1 - 2026-02-15 (Schema Alignment — Billing Period Calendar & Report Direction)

**Description:** Second round of schema alignment fixes. Seeds a full billing_period calendar (48 months) to prevent NULL FK collapse, and adds `invoice_direction` column to `generated_report` to complete the direction-filtering pipeline from API request through background report generation.

**Migrations:**
- `database/migrations/030_seed_billing_period_calendar.sql` - Full billing period calendar + UNIQUE constraint
- `database/migrations/031_generated_report_invoice_direction.sql` - Add invoice_direction to generated_report

**Changes:**

**billing_period calendar (migration 030):**
- Added `UNIQUE(start_date, end_date)` constraint on `billing_period`
- Seeded 48 months: January 2024 through December 2027
- Uses `ON CONFLICT (start_date, end_date) DO NOTHING` — preserves existing ID=1 row from migration 021
- Covers historical CBE data (2024), current operations (2025-2026), and forecast periods (2027)
- Fixes: ingestion of non-January data previously got NULL billing_period_id FK, collapsing via COALESCE(-1) dedup index

**generated_report.invoice_direction (migration 031):**
- Added nullable `invoice_direction` column (reuses existing `invoice_direction` enum from migration 022)
- NULL means "all directions" — backward compatible with existing reports
- Enables the report generation pipeline to persist and use direction filtering:
  `GenerateReportRequest` → `create_generated_report()` → DB row → `_load_report()` → `ReportConfig` → `extractor.extract()`

**Code changes (no migration):**
- `models/reports.py`: Added `invoice_direction` to `GenerateReportRequest` and `ReportConfig`
- `db/report_repository.py`: `create_generated_report()` accepts and inserts `invoice_direction`
- `api/reports.py`: Passes `report_request.invoice_direction` to repository
- `services/reports/generator.py`: Reads `invoice_direction` from DB, sets on config, passes to extractor
- `services/reports/extractors/base.py`: Added `invoice_direction` to abstract `extract()` signature
- `services/reports/extractors/invoice_expected.py`: Passes `invoice_direction` to repository
- `services/reports/extractors/invoice_received.py`: Passes `invoice_direction` to repository
- `services/reports/extractors/invoice_comparison.py`: Passes `invoice_direction` to repository
- `services/reports/extractors/invoice_to_client.py`: Accepts param for interface consistency (no-op)

---

### v6.2 - 2026-02-11 (Meter Reading Dedup Index)

**Description:** Adds a unique index on meter_reading business keys to enable row-level deduplication. The existing `ON CONFLICT DO NOTHING` in the loader had no conflict target (PK uses auto-increment `id`), so duplicate readings were never detected.

**Migrations:**
- `database/migrations/025_meter_reading_dedup_index.sql` - Business-key unique index

**Changes:**

**New Unique Index: idx_meter_reading_dedup**
- Columns: `organization_id`, `reading_timestamp`, `COALESCE(external_site_id, '')`, `COALESCE(external_device_id, '')`
- `COALESCE` handles NULLs (PostgreSQL treats NULLs as distinct in unique constraints)
- Includes `reading_timestamp` (the partition key) — required for partitioned table unique indexes
- Existing `ON CONFLICT DO NOTHING` in `meter_reading_loader.py` automatically leverages this index

**Design Notes:**
- No application code changes required — the loader's `ON CONFLICT DO NOTHING` now has a conflict target
- Pre-migration dedup query included in migration comments for environments with existing duplicate rows
- COALESCE ensures NULL site/device IDs are treated as equal for dedup purposes

---

### v8.0 - 2026-02-15 (Email Notification Engine)

**Description:** Automated email notification system with scheduling, template management,
and token-based external submission collection.

**Migrations:**
- `database/migrations/032_email_notification_engine.sql`

**New Enums:**
- `email_schedule_type`: `invoice_reminder`, `invoice_initial`, `compliance_alert`, `custom` (migration 057 removed `invoice_escalation`, `meter_data_missing`, `report_ready`)
- `email_status`: `pending`, `sending`, `delivered`, `bounced`, `failed`, `suppressed`
- `submission_token_status`: `active`, `used`, `expired`, `revoked`

**Extended Enums:**
- `audit_action_type`: Added `EMAIL_SENT`, `EMAIL_FAILED`, `SUBMISSION_RECEIVED`, `SUBMISSION_TOKEN_CREATED`

**New Tables:**

**email_template** - Reusable Jinja2 email templates
- `id`, `organization_id`, `email_schedule_type`, `name`, `description`
- `subject_template`, `body_html`, `body_text` (Jinja2 template strings)
- `available_variables` (JSONB), `is_system`, `is_active`
- Unique index on `(organization_id, name)`

**email_notification_schedule** - When/what/who to email
- `id`, `organization_id`, `email_template_id`, `name`, `email_schedule_type`
- `report_frequency` (reuses `report_frequency` enum), `day_of_month`, `time_of_day`, `timezone`
- `conditions` (JSONB), `max_reminders`, `escalation_after`
- `include_submission_link`, `submission_fields` (JSONB)
- `next_run_at` (calculated by trigger using `calculate_next_run_time()` from migration 018)
- Scoping FKs: `project_id`, `contract_id`, `counterparty_id`

**outbound_message** (formerly `email_log`, renamed in v8.3) - Every email sent
- `id`, `organization_id`, `email_notification_schedule_id`, `email_template_id`
- `recipient_email`, `recipient_name`, `subject`, `email_status`
- `ses_message_id`, `reminder_count`, `invoice_header_id`, `submission_token_id`
- `error_message`, `bounce_type`, `sent_at`, `delivered_at`, `bounced_at`

**submission_token** - Secure tokens for external data collection
- `id`, `organization_id`, `token_hash` (SHA-256, unique indexed)
- `submission_fields` (JSONB), `submission_token_status`, `max_uses`, `use_count`, `expires_at`
- Linked entity FKs: `invoice_header_id`, `counterparty_id`, `outbound_message_id`

**~~submission_response~~** - Replaced by `inbound_message` in v8.3
- Dropped in migration 052 (Phase B)

**Helper Functions:**
- `update_email_template_timestamp()` - Timestamp trigger for email_template
- `update_email_schedule_next_run()` - Reuses `calculate_next_run_time()` from migration 018

**RLS Policies:**
- All 5 tables have RLS enabled
- SELECT: `is_org_member(organization_id)` for authenticated role
- ALL: `is_org_admin(organization_id)` for admin modifications
- Service role: full access on all tables

**Seed Data:**
- 4 system email templates seeded per organization: Invoice Delivery, Payment Reminder, Invoice Escalation, Compliance Alert

---

### v9.0 - 2026-02-17 (Project Onboarding — COD Data Capture, Amendment Versioning & Reference Price)

**Description:** Redesigned migration 033 with amendment versioning, reference price table (renamed from grid_reference_price), and cleanup of dropped tables (project_document, project_onboarding_snapshot). Removes received_invoice_line_item ALTER (charge_type/is_tax/tou_bucket) in favor of invoice_line_item_type seeds. Adds contract amendment tracking with supersedes chains and is_current semantics on clause and clause_tariff.

**Reference:** `database/docs/IMPLEMENTATION_GUIDE_PROJECT_ONBOARDING.md`

**Migrations:**
- `database/migrations/033_project_onboarding.sql` - Combined migration (ALTERs + CREATEs + seeds + RLS + amendment tracking)

**ETL Script:**
- `database/scripts/project-onboarding/onboard_project.sql` - Staged ETL with batch validation and post-load assertions

**Key Changes:**

**A. ALTER Existing Tables**

**Extended project table:**
- `external_project_id` - VARCHAR(50) — Client-defined project identifier
- `sage_id` - VARCHAR(50) — Finance/ERP system reference
- `country` - VARCHAR(100) — Physical site location
- `cod_date` - DATE — Commercial Operations Date
- `installed_dc_capacity_kwp` - DECIMAL — DC capacity in kWp
- `installed_ac_capacity_kw` - DECIMAL — AC capacity in kW
- `installation_location_url` - TEXT — Google Maps URL
- New unique index: `uq_project_org_external(organization_id, external_project_id)`

**Extended contract table:**
- `external_contract_id` - VARCHAR(50) — Client-defined contract identifier
- `contract_term_years` - INTEGER — PPA duration
- `interconnection_voltage_kv` - DECIMAL — Grid interconnection voltage
- `has_amendments` - BOOLEAN DEFAULT false — Whether contract has amendments (replaces `amendments_post_ppa` TEXT)
- `payment_security_required` - BOOLEAN — Whether payment security is required
- `payment_security_details` - TEXT — Payment security details
- `ppa_confirmed_uploaded` - BOOLEAN — Document upload flag
- `agreed_fx_rate_source` - VARCHAR(255) — Contractual FX reference
- **Renamed:** `updated_by` → `created_by` (UUID of auth.users who created the record)
- New unique index: `uq_contract_project_external(project_id, external_contract_id)`

**Extended counterparty table:**
- `registered_name` - VARCHAR(255) — Official registered company name (legally distinct from trading name)
- `registration_number` - VARCHAR(100) — Company registration number
- `tax_pin` - VARCHAR(100) — Tax identification number
- `registered_address` - TEXT — Registered address from Notices clause

**Extended asset table:**
- `capacity` - DECIMAL — Rated capacity
- `capacity_unit` - VARCHAR(20) — Unit: kWp, kW, kWh, kVA
- `quantity` - INTEGER DEFAULT 1 — Count of units

**Extended meter table:**
- `serial_number` - VARCHAR(100) — Billing meter serial number
- `location_description` - TEXT — Installation location
- `metering_type` - VARCHAR(20) — net or export_only (separate dimension from meter_type)

**Extended production_forecast table:**
- `forecast_poa_irradiance` - DECIMAL — POA irradiance from PVSyst
- `forecast_pr_poa` - DECIMAL — Forecast Performance Ratio based on POA irradiance (0-1 range)

**Extended production_guarantee table:**
- `shortfall_cap_usd` - DECIMAL — Annual shortfall payment cap in USD
- `shortfall_cap_fx_rule` - VARCHAR(255) — FX conversion rule for the cap

**Extended clause table (amendment versioning):**
- `contract_amendment_id` - BIGINT REFERENCES contract_amendment(id) — NULL for original clauses
- `supersedes_clause_id` - BIGINT REFERENCES clause(id) — Version chain pointer
- `is_current` - BOOLEAN NOT NULL DEFAULT true — Active version flag
- `change_action` - change_action ENUM — ADDED, MODIFIED, REMOVED (NULL for originals)

**Extended clause_tariff table (amendment versioning):**
- `contract_amendment_id` - BIGINT REFERENCES contract_amendment(id)
- `supersedes_tariff_id` - BIGINT REFERENCES clause_tariff(id)
- `version` - INTEGER NOT NULL DEFAULT 1
- `is_current` - BOOLEAN NOT NULL DEFAULT true
- `change_action` - change_action ENUM

**B. CREATE New Tables**

**New Table: contract_amendment**
- `id` - BIGSERIAL PRIMARY KEY
- `contract_id` - BIGINT NOT NULL REFERENCES contract(id)
- `organization_id` - BIGINT NOT NULL REFERENCES organization(id)
- `amendment_number` - INTEGER NOT NULL
- `amendment_date` - DATE NOT NULL
- `effective_date` - DATE
- `description` - TEXT
- `file_path` - TEXT
- `source_metadata` - JSONB DEFAULT '{}'
- UNIQUE(contract_id, amendment_number)

**New Table: reference_price** (renamed from grid_reference_price)
- `id` - BIGSERIAL PRIMARY KEY
- `project_id` - BIGINT NOT NULL REFERENCES project(id)
- `organization_id` - BIGINT NOT NULL REFERENCES organization(id)
- `operating_year` - INTEGER NOT NULL
- `period_start` - DATE NOT NULL
- `period_end` - DATE NOT NULL
- `calculated_mrp_per_kwh` - DECIMAL — MRP in local currency per kWh *(renamed from `calculated_grp_per_kwh` in v4.3)*
- `currency_id` - BIGINT REFERENCES currency(id)
- `total_variable_charges` - DECIMAL
- `total_kwh_invoiced` - DECIMAL
- `verification_status` - verification_status ENUM — pending, jointly_verified, disputed, estimated
- `verified_at` - TIMESTAMPTZ
- UNIQUE(project_id, operating_year)

**New Table: onboarding_preview** (kept from original)
- Server-side preview state for two-phase onboarding workflow

**Dropped tables** (removed from migration):
- `project_document` — Not needed; document tracking deferred
- `project_onboarding_snapshot` — Not needed; audit trail via contract_amendment

**C. New Enum Types**
- `verification_status` — ('pending', 'jointly_verified', 'disputed', 'estimated')
- `change_action` — ('ADDED', 'MODIFIED', 'REMOVED')

**D. Seed Data**
- **asset_type seeds:** pv_module, inverter, bess, pcs, generator, transformer, ppc, data_logger
- **invoice_line_item_type seeds:** VARIABLE_ENERGY, DEMAND, FIXED, TAX (replaces charge_type/is_tax/tou_bucket columns on received_invoice_line_item)

**E. Triggers**
- `trg_clause_supersede()` — When inserting a clause with supersedes_clause_id, auto-flips prior row is_current=false and sets contract.has_amendments=true
- `trg_clause_tariff_supersede()` — Same pattern for clause_tariff

**F. Views**
- `clause_current_v` — SELECT * FROM clause WHERE is_current = true
- `clause_tariff_current_v` — SELECT * FROM clause_tariff WHERE is_current = true

**G. Unique Indexes**
- `uq_clause_current_per_type_section` — Partial unique on clause(contract_id, clause_type_id, section_ref) WHERE is_current = true
- `uq_clause_tariff_current_group_validity` — Partial unique scoped to is_current = true (replaces non-versioned index)
- `uq_meter_project_serial` — meter(project_id, serial_number) WHERE serial_number IS NOT NULL
- `uq_counterparty_type_name` — counterparty(counterparty_type_id, LOWER(name))
- `uq_invoice_line_item_type_code` — invoice_line_item_type(code)

**H. Python Backend Changes**
- `db/contract_repository.py`: Renamed `updated_by` → `created_by` in contract SELECT
- `db/rules_repository.py`: Added `AND c.is_current = true` filter to evaluable clause query
- `services/calculations/grid_reference_price.py`: Refactored to use `invoice_line_item_type_code` instead of charge_type/is_tax/tou_bucket
- `services/onboarding/onboarding_service.py`: Removed project_document from count, removed document staging
- `models/onboarding.py`: Removed DocumentChecklistItem, removed documents fields
- `services/onboarding/excel_parser.py`: Removed _extract_documents() method + import
- **New:** `services/amendments/__init__.py` — Package init
- **New:** `services/amendments/amendment_diff.py` — Clause/tariff version comparison and amendment summary

**Design Notes:**
- Amendment versioning uses supersedes chains + is_current flags (not separate history tables)
- Triggers enforce cross-contract validation and auto-maintain contract.has_amendments
- metering_type (net/export_only) kept separate from meter_type (REVENUE/PRODUCTION/IRRADIANCE)
- MRP charge classification moved from received_invoice_line_item columns to invoice_line_item_type FK *(originally "GRP"; renamed in v4.3)*
- project_document and project_onboarding_snapshot dropped — not needed for current workflow

---

### v9.1 - 2026-02-19 (Billing Product Capture, Tariff Rate Versioning & Pricing Gap Fixes)

**Description:** Adds billing product reference table for Sage/ERP product codes, contract-product junction for multi-product contracts, tariff rate period table for tracking annual escalation without modifying the original contractual base_rate, payment_terms column on contract, and pricing gap fixes (multi-value extraction, label mismatches, escalation detail fields).

**Migrations:**
- `database/migrations/034_billing_product_and_rate_period.sql` - Three new tables + CBE seed data + RLS + tariff classification cleanup + payment_terms

**Key Changes:**

**New Table: billing_product**
- `id` - BIGSERIAL PRIMARY KEY
- `code` - VARCHAR(50) NOT NULL — Sage/ERP product code (e.g., GHREVS001)
- `name` - VARCHAR(255) — Human-readable name (e.g., "Metered Energy (EMetered)")
- `organization_id` - BIGINT REFERENCES organization(id) — NULL = platform-level canonical
- `is_active` - BOOLEAN DEFAULT true
- Partial unique index `uq_billing_product_canonical(code) WHERE organization_id IS NULL` — prevents duplicate canonical rows (NULL ≠ NULL in standard UNIQUE)
- Partial unique index `uq_billing_product_org(code, organization_id) WHERE organization_id IS NOT NULL` — enforces uniqueness within each organization
- Seeded with ~110 CBE product codes from `dim_finance_product_code.csv`

**New Table: contract_billing_product**
- `id` - BIGSERIAL PRIMARY KEY
- `contract_id` - BIGINT NOT NULL REFERENCES contract(id)
- `billing_product_id` - BIGINT NOT NULL REFERENCES billing_product(id)
- `is_primary` - BOOLEAN DEFAULT false — Marks the main revenue line
- `notes` - TEXT
- UNIQUE(contract_id, billing_product_id)
- Partial unique index `uq_contract_billing_product_primary(contract_id) WHERE is_primary = true` — enforces single primary product per contract
- Cross-tenant validation trigger `trg_contract_billing_product_org_check` — ensures billing_product belongs to same org as contract (or is canonical)

**New Table: tariff_annual_rate** (originally tariff_rate_period, renamed in migration 036)
- `id` - BIGSERIAL PRIMARY KEY
- `clause_tariff_id` - BIGINT NOT NULL REFERENCES clause_tariff(id)
- `contract_year` - INTEGER NOT NULL — Contract operating year (1-based) *(renamed to `operating_year` in migration 066)*
- `period_start` - DATE NOT NULL
- `period_end` - DATE
- `effective_tariff` - DECIMAL NOT NULL — Rate after escalation (renamed from effective_rate in migration 036)
- `final_effective_tariff` - DECIMAL — Final billing rate (added in migration 036)
- `final_effective_tariff_source` - VARCHAR(20) — 'annual', 'monthly', or 'manual' (added in migration 036)
- `currency_id` - BIGINT REFERENCES currency(id)
- `calculation_basis` - TEXT — Human-readable explanation (e.g., "Base 0.1087 + 2.5% CPI")
- `is_current` - BOOLEAN NOT NULL DEFAULT false
- `approved_by` - UUID REFERENCES auth.users(id)
- `approved_at` - TIMESTAMPTZ
- UNIQUE(clause_tariff_id, contract_year)
- CHECK (contract_year >= 1)
- CHECK (effective_rate >= 0)
- CHECK (period_end IS NULL OR period_end >= period_start)
- Unique partial index: `idx_tariff_annual_rate_current(clause_tariff_id) WHERE is_current = true` — enforces single current rate per tariff

**New column on contract table (section G):**
- `payment_terms` - VARCHAR(50) — Payment terms (e.g. "Net 30", "Net 60"). Governs invoice due dates.

**Onboarding Pipeline Changes:**
- `excel_parser.py`: Added "product to be billed" / "product code" / "billing product" label mappings; comma/semicolon splitting in `_normalize_fields()`; multi-value extraction for billing products and service types; fixed label mismatches; new escalation detail labels; product code extraction from "CODE - Description" format
- `models/onboarding.py`: Added `product_to_be_billed`, `product_to_be_billed_list`, `contract_service_types`, `equipment_rental_rate`, `bess_fee`, `loan_repayment_value`, `billing_frequency`, `escalation_frequency`, `escalation_start_date`, `tariff_components_to_adjust`, `ppa_confirmed_uploaded`, `has_amendments` to ExcelOnboardingData; `billing_products`, `payment_terms`, `ppa_confirmed_uploaded`, `has_amendments` to MergedOnboardingData
- `normalizer.py`: Added `normalize_contact_invoice_flag()` for three-state contact invoice parsing (Yes/No/Escalation only → include_in_invoice + escalation_only); added `extract_billing_product_code()` for "CODE - Description" format
- `onboarding_service.py`: Added `stg_billing_products` staging table, population, and billing_products count in preview response; multi-tariff line generation for multi-service-type contracts; escalation detail fields packed into logic_parameters JSONB; payment_terms, ppa_confirmed_uploaded, has_amendments wired through staging; escalation_only added to stg_contacts INSERT
- `onboard_project.sql`: Added `stg_billing_products` staging table; Step 4.10 (contract_billing_product upsert with LATERAL preference for org-scoped over canonical); Step 4.11 (tariff_annual_rate Year 1 initialization); payment_terms, ppa_confirmed_uploaded, has_amendments in contract upsert

**Design Notes:**
- billing_product is contract-level, not clause_tariff-level — product codes describe WHAT is billed; tariff terms describe HOW
- tariff_annual_rate separates operational rate escalation from contract amendments (version/is_current/supersedes on clause_tariff)
- clause_tariff.base_rate stays as the original contractual rate, never modified after onboarding
- Year 1 tariff_annual_rate is auto-created during onboarding (effective_rate = base_rate, final_effective_tariff = base_rate)
- Escalation types: FIXED_INCREASE/PERCENTAGE are deterministic (pre-populate); US_CPI is semi-deterministic; REBASED_MARKET_PRICE is dynamic
- Partial unique indexes on billing_product solve the NULL ≠ NULL problem for canonical rows (PostgreSQL UNIQUE treats NULLs as distinct)
- Cross-tenant trigger on contract_billing_product prevents org A's contract from referencing org B's billing products
- Unique partial index on is_current prevents multiple active rates per clause_tariff (escalation must flip previous row first)
- onboard_project.sql Step 4.10 uses JOIN LATERAL with ORDER BY organization_id NULLS LAST to prefer org-scoped products over canonical when both exist for same code

---

### v9.2 - 2026-02-19 (Seed tariff_type with CBE Service Codes, Restore energy_sale_type)

**Description:** Seeds `tariff_type` with 7 CBE "Contract Service/Product Type" codes (ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE). Drops `tariff_structure_type` (unused, derivable from energy_sale_type). Keeps `energy_sale_type` as a separate classification on `clause_tariff`.

**Migrations:**
- `database/migrations/034_billing_product_and_rate_period.sql` — Sections E & F

**Changes:**

**Inserted into tariff_type (7 new codes):**
- ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE
- These coexist with the 14 existing billing-line-level codes (METERED_ENERGY, AVAILABLE_ENERGY, etc.)

**Dropped column from clause_tariff:**
- `tariff_structure_id` (no corresponding Excel field, derivable from energy_sale_type)

**Dropped table:**
- `tariff_structure_type`

**clause_tariff classification FKs (3 remaining) — _Superseded by migration 059:_**
- `tariff_type_id` → ~~"Contract Service/Product Type"~~ **Post-059: Offtake/Billing Model** (TAKE_OR_PAY, TAKE_AND_PAY, MINIMUM_OFFTAKE, etc.)
- `energy_sale_type_id` → ~~"Energy Sales Tariff Type"~~ **Post-059: Revenue/Product Type** (ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, etc.)
- `escalation_type_id` → "Price Adjustment Type" (FIXED_INCREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, FLOATING_GRID, FLOATING_GENERATOR, etc.)

**Updated onboard_project.sql:**
- `stg_tariff_lines`: added `energy_sale_type_code` column (alongside `tariff_type_code`)
- Pre-flight validation: added energy_sale_type code check
- clause_tariff INSERT: added `energy_sale_type_id` column + JOIN to `energy_sale_type` with org-scoping
- ON CONFLICT DO UPDATE: added `energy_sale_type_id`

**Updated python-backend:**
- `normalizer.py`: added CONTRACT_SERVICE_TYPE_MAP + `normalize_contract_service_type()`
- `excel_parser.py`: added "contract service/product type" labels, normalization in `_normalize_fields()`
- `models/onboarding.py`: added `contract_service_type` field to ExcelOnboardingData
- `onboarding_service.py`: fixed tariff_type_code mapping (was wrong: pointed to energy_sale_type), added energy_sale_type_code to staging table + INSERT
- `entities.py`: added energy_sale_type JOIN + columns to tariffs_data CTE, energy_sale_types_lookup CTE, energy_sale_type_id to TariffPatch, "energy_sale_types" to response lookups
- `amendments/amendment_diff.py`: added `energy_sale_type_id` to TARIFF_DIFF_FIELDS

**Updated frontend:**
- `app/projects/page.tsx`: added energySaleTypeOpts, added "Sale Type" column to tariffColumns
- `app/projects/components/ProjectOverviewTab.tsx`: added energySaleTypeOpts, added "Energy Sale Type" row to tariff FieldGrid

**Updated validate_onboarding_project.sql:**
- Tariff snapshot query: added energy_sale_type JOIN + column

**Design Notes:**
- ~~`tariff_type` = "Contract Service/Product Type"~~ **Superseded by migration 059**: tariff_type is now Offtake/Billing Model
- ~~`energy_sale_type` = pricing mechanism (FIXED_SOLAR, FLOATING_GRID)~~ **Superseded by migration 059**: energy_sale_type is now Revenue/Product Type; FLOATING_* codes moved to escalation_type
- `tariff_structure_type` dropped — no Excel field, structure derivable from escalation_type
- GH-MOH01 after re-onboarding: energy_sale_type_id = ENERGY_SALES, escalation_type_id = FLOATING_GRID (post-059)

---

### v9.3 - 2026-02-20 (Monthly Tariff & FX Support for REBASED_MARKET_PRICE)

**Description:** Renames `tariff_rate_period` → `tariff_annual_rate`, adds `final_effective_tariff` field for authoritative billing rate, creates `tariff_monthly_rate` child table for REBASED_MARKET_PRICE tariffs that require monthly FX-adjusted rates.

**Migrations:**
- `database/migrations/036_monthly_tariff_and_fx.sql`

**Changes:**

**Renamed Table: tariff_rate_period → tariff_annual_rate**
- Table name, indexes, RLS policies all renamed
- `idx_tariff_rate_period_current` → `idx_tariff_annual_rate_current`
- `idx_tariff_rate_period_date_range` → `idx_tariff_annual_rate_date_range`
- Constraint: `tariff_rate_period_clause_tariff_id_contract_year_key` → `tariff_annual_rate_clause_tariff_id_contract_year_key`

**Renamed Column: effective_rate → effective_tariff**
- Aligns vocabulary with `final_effective_tariff` across the tariff schema

**New Columns on tariff_annual_rate:**
- `final_effective_tariff` - DECIMAL — Final effective tariff for invoicing
- `final_effective_tariff_source` - VARCHAR(20) — 'annual' (deterministic), 'monthly' (FX-adjusted), 'manual'

**New Table: tariff_monthly_rate**
- `id` - BIGSERIAL PRIMARY KEY
- `tariff_annual_rate_id` - BIGINT NOT NULL REFERENCES tariff_annual_rate(id) ON DELETE CASCADE
- `exchange_rate_id` - BIGINT REFERENCES exchange_rate(id) — FK to FX system of record
- `billing_month` - DATE NOT NULL — First of month
- `floor_local` - DECIMAL — Floor in local currency (GHS)
- `ceiling_local` - DECIMAL — Ceiling in local currency (GHS)
- `discounted_mrp_local` - DECIMAL — MRP × (1 - discount) in local currency *(renamed from `discounted_grp_local` in v4.3)*
- `effective_tariff_local` - DECIMAL NOT NULL — Final tariff in local currency
- `rate_binding` - VARCHAR(20) NOT NULL — 'floor', 'ceiling', or 'discounted'
- `calculation_basis` - TEXT — Audit trail
- `is_current` - BOOLEAN NOT NULL DEFAULT false
- UNIQUE(tariff_annual_rate_id, billing_month)
- Unique partial index: `idx_tariff_monthly_rate_current(tariff_annual_rate_id) WHERE is_current = true`
- RLS: org_policy (SELECT), admin_modify_policy (ALL), service_policy (ALL)

**New Python Backend:**
- `services/tariff/rebased_market_price_engine.py`: RebasedMarketPriceEngine with formula registry, component escalation, monthly FX calculation
- `api/entities.py`: POST `/api/projects/{project_id}/calculate-rebased-rate`, POST `/api/exchange-rates/bulk`

**Updated Files:**
- `services/tariff/rate_period_generator.py`: All SQL references renamed; final_effective_tariff = effective_tariff for deterministic types
- `api/entities.py`: Dashboard query + PATCH endpoint table references renamed
- `onboard_project.sql`: INSERT + assertion table references renamed; final_effective_tariff columns added to Year 1 initialization
- `validate_onboarding_project.sql`: All query table references renamed
- `GH_MOH01_ONBOARDING_AUDIT.md`: Documentation references renamed

**Design Notes:**
- final_effective_tariff is the authoritative billing rate; effective_tariff remains the annual escalation calculation
- For deterministic types: final_effective_tariff = effective_tariff, source = 'annual'
- For REBASED_MARKET_PRICE: final_effective_tariff = latest monthly effective_tariff_local, source = 'monthly'
- tariff_monthly_rate uses exchange_rate FK for FX audit trail (no data duplication)
- Formula dispatch via logic_parameters.formula_type — extensible without code changes
- Floor/ceiling escalation rules read from logic_parameters.escalation_rules — project-specific

---

### v9.4 - 2026-02-20 (MRP Ingestion — Monthly Observations & File Upload)

**Description:** Extends `reference_price` for monthly granularity (individual utility invoice observations alongside annual aggregates). Extends `submission_token` with `project_id` and `submission_type` to support file-upload-based MRP collection workflow. *(Note: originally documented as "GRP"; renamed to MRP in v4.3.)*

**Migrations:**
- `database/migrations/037_grp_ingestion.sql`

**Key Changes:**

**Extended submission_token table:**
- `project_id` - BIGINT REFERENCES project(id) ON DELETE SET NULL — Project context for MRP and other project-scoped submissions
- `submission_type` - VARCHAR(30) NOT NULL DEFAULT 'form_response' — Type: 'form_response' (default) or 'mrp_upload'
- CHECK constraint: `submission_type IN ('form_response', 'mrp_upload')`
- CHECK constraint: `submission_type != 'mrp_upload' OR project_id IS NOT NULL` — MRP uploads require project context

**Extended reference_price table:**
- Changed unique constraint from `(project_id, operating_year)` to `(project_id, observation_type, period_start)` — allows both monthly and annual rows per operating year without collision
- `observation_type` - VARCHAR(10) NOT NULL DEFAULT 'annual' — 'monthly' for individual invoice observations, 'annual' for aggregate
- CHECK constraint: `observation_type IN ('monthly', 'annual')`
- `source_document_path` - TEXT — S3 path to uploaded utility invoice document
- `source_document_hash` - VARCHAR(64) — SHA-256 hash of source document for deduplication
- `submission_response_id` - BIGINT REFERENCES submission_response(id) — Link to the token submission that created this observation

**Updated Indexes:**
- Replaced `idx_ref_price_project(project_id, operating_year)` with `idx_ref_price_project(project_id, observation_type, period_start)`
- Added `idx_ref_price_project_year(project_id, operating_year)` for year-based queries
- Added `idx_ref_price_document_hash` — partial unique index on `(project_id, source_document_hash) WHERE source_document_hash IS NOT NULL` for duplicate document prevention

**Row Conventions:**
- Monthly observations: `observation_type='monthly'`, `period_start='2025-10-01'`, `period_end='2025-10-31'`
- Annual aggregate: `observation_type='annual'`, `period_start=year_start`, `period_end=year_end`
- `source_metadata` JSONB stores extracted line items and OCR metadata (no new JSONB column needed)

**Python Backend Changes:**
- `services/tariff/rebased_market_price_engine.py`: Updated ON CONFLICT clause from `(project_id, operating_year)` to `(project_id, period_start)`, added `observation_type='annual'` to INSERT
- `services/email/token_service.py`: Added `project_id` and `submission_type` parameters to `generate_token()`
- `db/notification_repository.py`: Updated `create_submission_token()` to include `project_id` and `submission_type`; updated `get_submission_token_by_hash()` to JOIN project for `project_name`
- `models/notifications.py`: Added `project_name` and `submission_type` to `SubmissionFormConfig`; added `MRPCollectionRequest` model *(renamed from `GRPCollectionRequest` in v4.3)*
- `api/submissions.py`: Added `POST /{token}/upload` endpoint for file-based MRP submissions with validation, S3 upload, and synchronous extraction
- `api/notifications.py`: Added `POST /api/notifications/mrp-collection` endpoint for MRP collection token generation
- **New:** `services/mrp/__init__.py` — Package init *(renamed from `services/grp/` in v4.3)*
- **New:** `services/mrp/extraction_service.py` — OCR (LlamaParse) + Claude structured extraction + MRP calculation + reference_price upsert
- **New:** `services/prompts/mrp_extraction_prompt.py` — Claude extraction prompt for utility invoice line items *(renamed from `grp_extraction_prompt.py` in v4.3)*

**Frontend Changes:**
- `app/submit/[token]/page.tsx`: Added file upload field type (`type: 'file'`), month picker (`type: 'month'`), FormData submission for MRP uploads, extraction results display on success, "Upload Another" flow for reusable tokens

**Design Notes:**
- MRP upload tokens use `max_uses=12` (one per month) — client bookmarks the link and returns monthly
- File upload is synchronous (~10-30s): OCR → Claude extraction → MRP calculation → storage
- Extracted line items stored in `source_metadata` JSONB (no separate line_items table)
- `mrp_aggregation_method` convention in `clause_tariff.logic_parameters` JSONB: `"annual_average"` or `"monthly"` (no schema change needed) *(renamed from `grp_aggregation_method` in v4.3)*
- Files uploaded to S3 at `mrp-uploads/{org_id}/{project_id}/{year}/{month}/{filename}` *(renamed from `grp-uploads/` in v4.3)*
- Backward compatible: existing `RebasedMarketPriceEngine` annual observations continue to work with the new `(project_id, period_start)` constraint

---

### v10.0 - 2026-02-21 (Default Rate & Late Payment via `clause` Table)

**Description:** First use of the `clause` table for onboarded data. Seeds a PAYMENT_TERMS clause for GH-MOH01 with default interest rate, FX indemnity, and dispute resolution fields stored in `normalized_payload` JSONB. Adds `clauses` to the project dashboard API response and displays default rate in the Pricing & Tariffs tab. Expands PPA extraction prompt to capture structured default rate data and auto-inserts PAYMENT_TERMS clause during onboarding.

**Migrations:** None (no schema changes — clause table already exists from migration 005/033)

**Changes:**

**PAYMENT_TERMS clause `normalized_payload` JSONB keys:**
- `payment_due_days` - integer
- `default_rate_benchmark` - "SOFR", "LIBOR", "PRIME", "CBR"
- `default_rate_spread_pct` - decimal (e.g. 2.0 for 2%)
- `default_rate_accrual_method` - "PRO_RATA_DAILY", "SIMPLE_ANNUAL"
- `late_payment_fx_indemnity` - boolean
- `dispute_resolution_days` - integer
- `dispute_resolution_clause_ref` - string (e.g. "Clause 26")

**Backend API Changes:**
- `python-backend/api/entities.py`: Added `clauses` to `ProjectDashboardResponse` model and dashboard query (new `clauses_data` CTE joins `clause` with `clause_category`)
- `python-backend/models/onboarding.py`: Added `DefaultRateExtraction` model and `default_rate` field to `PPAContractData`
- `python-backend/services/prompts/onboarding_extraction_prompt.py`: Expanded `default_interest_rate` to structured `default_rate` object (benchmark, spread_pct, accrual_method, fx_indemnity)
- `python-backend/services/onboarding/onboarding_service.py`: Added `_insert_payment_terms_clause()` — auto-inserts a PAYMENT_TERMS clause during onboarding commit when default rate data is available in extraction_metadata

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `clauses` to `ProjectDashboardResponse` TypeScript type
- `app/projects/components/PricingTariffsTab.tsx`: Displays default rate fields (benchmark + spread, accrual method, FX indemnity, dispute resolution) in the Billing Information section when a PAYMENT_TERMS clause exists

**Design Notes:**
- `clause` table used as the canonical home for payment terms / default rate data (not contract columns)
- `normalized_payload` JSONB follows the same pattern as other clause categories
- Dashboard API returns `clauses` as a flat array; frontend filters by `clause_category_code`
- Onboarding clause insertion is non-fatal — failures are logged as warnings
- Legacy `default_interest_rate` in extraction_metadata preserved for backward compatibility

---

### v10.1 - 2026-02-22 (Pipeline Integrity Fixes)

**Description:** Addresses 16 verified pipeline gaps across onboarding, MRP ingestion, and admin APIs. Fixes SQL section execution order, enables pre-flight validation, adds API key auth to admin endpoints, and resolves data type mismatches between parser output and DB constraints.

**Migration:** `database/migrations/039_pipeline_integrity_fixes.sql`

**Schema Changes:**
- **`reference_price`**: Added partial unique index `uq_reference_price_annual_project_year` on `(project_id, operating_year) WHERE observation_type = 'annual'` — prevents duplicate annual aggregation rows
- **`asset_type`**: Seeded 4 missing codes: `tracker`, `meter`, `mounting_structure`, `combiner_box`
- **`meter`**: Expanded `chk_meter_metering_type` CHECK constraint to include `'gross'` and `'bidirectional'`
- **`clause_tariff`**: Idempotent MRP seed for GH-MOH01 using stable `tariff_group_key` lookup (replaces fragile `WHERE id = 2` from migration 037)

**Backend Changes:**
- `python-backend/services/onboarding/onboarding_service.py`: Numeric section sort key (fixes `4.10` executing before `4.2`), pre-flight validation runs before upserts, `formula_type` auto-set for REBASED_MARKET_PRICE tariffs, staging DDL authority comment
- `python-backend/api/entities.py`: Added `require_api_key` dependency to router (was unauthenticated)
- `python-backend/api/mrp.py`: Added `require_api_key` dependency, annual aggregation upsert uses new partial unique index *(renamed from `api/grp.py` in v4.3)*
- `python-backend/services/onboarding/excel_parser.py`: `_map_asset_type()` produces canonical lowercase DB codes (was uppercase)
- `python-backend/services/onboarding/ppa_parser.py`: Path traversal fix (UUID-based temp filenames), populates structured `default_rate` and `available_energy` fields
- `python-backend/services/mrp/extraction_service.py`: Recomputes `operating_year` after billing period reconciliation *(renamed from `services/grp/` in v4.3)*

**Documentation Changes:**
- `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md`: Fixed stale `tariff_structure` reference, updated meter gap status, added 8 new pipeline gap entries (10–17)

---

### v10.2 - 2026-02-22 (Amendment Version History)

**Description:** Populates the amendment versioning infrastructure (from migration 033) for GH-MOH01's First Amendment. Inserts pre-amendment original tariff row, links the existing tariff to the amendment with correct supersedes chain, and surfaces amendment data in the dashboard API and frontend.

**Migration:** `database/migrations/038_moh01_amendment_version_history.sql` (replaces `038_fix_moh01_min_solar_price_escalation.sql`)

**Data Changes:**
- **`clause_tariff`**: Inserted original (pre-amendment) tariff row with `discount_pct=0.21`, `escalation_rules` including `FIXED 2.5%` on `min_solar_price`, `is_current=false`, `version=1`
- **`clause_tariff` (id=2)**: Updated to `version=2`, `contract_amendment_id=1`, `supersedes_tariff_id=<original id>`, `change_action='MODIFIED'`
- Escalation fix (FIXED->NONE on min_solar_price) made idempotent within the same migration
- Version chain verified with assertions (both rows exist, values correct, supersedes linked)

**Backend Changes:**
- `python-backend/api/entities.py`: Added `amendments_data` CTE to dashboard query (joins `contract_amendment` via `contract` scoped to project); added `amendments` field to `ProjectDashboardResponse` Pydantic model and response construction

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `amendments` to `ProjectDashboardResponse` TypeScript interface
- `app/projects/components/ProjectOverviewTab.tsx`: Added "Amendment History" collapsible section after "Contract Terms" — renders amendment header with date badge, description, and before/after diff table from `source_metadata.changes`
- `app/projects/components/PricingTariffsTab.tsx`: Added amber "v2 — Amended" badge on tariff cards when `contract_amendment_id` is non-null (in both Tariff & Rate Schedule and BillingProductCard views)

**Design Notes:**
- Original tariff row has `is_current=false` so `clause_tariff_current_v` view still returns only the amended tariff (id=2)
- `tariff_annual_rate` (id=1, clause_tariff_id=2) remains correct — it tracks the current active tariff
- AFTER INSERT trigger (`trg_clause_tariff_supersede`) does not fire for the original row because `supersedes_tariff_id=NULL`
- Partial unique index `uq_clause_tariff_current_group_validity` does not collide because original has `is_current=false`

---

### v10.3 - 2026-02-23 (Unified Tariff Rate Table)

**Description:** Merges `tariff_annual_rate` + `tariff_monthly_rate` into a single `tariff_rate` table with four-currency representation, JSONB formula-specific intermediaries, full FX audit trail, and calculation lineage. Old tables are migrated then dropped.

**Migration:** `database/migrations/040_merge_tariff_rate_tables.sql`

**New Enums:**
- `rate_granularity` ('annual', 'monthly')
- `calc_status` ('pending', 'computed', 'approved', 'superseded')
- `contract_ccy_role` ('hard', 'local', 'billing')

**New Table: `tariff_rate`**

| Column Group | Columns |
|---|---|
| **Identity** | `clause_tariff_id`, `contract_year`, `rate_granularity`, `billing_month`, `period_start`, `period_end` |
| **Currency FKs** | `hard_currency_id`, `local_currency_id`, `billing_currency_id` |
| **FX Audit Trail** | `fx_rate_hard_id`, `fx_rate_local_id` |
| **Effective Rate** | `effective_rate_contract_ccy`, `effective_rate_hard_ccy`, `effective_rate_local_ccy`, `effective_rate_billing_ccy`, `effective_rate_contract_role` |
| **Formula Detail** | `calc_detail` (JSONB) |
| **Determination** | `rate_binding` |
| **Lineage** | `reference_price_id`, `discount_pct_applied`, `formula_version` |
| **Status** | `calc_status`, `calculation_basis`, `is_current`, `approved_by`, `approved_at` |

**Key Constraints:**
- `chk_granularity_annual`: annual rows must have `billing_month IS NULL`
- `chk_granularity_monthly`: monthly rows must have `billing_month` set, normalized to first-of-month
- `chk_billing_ccy_is_hard_or_local`: billing currency must equal hard or local
- `chk_effective_rate_contract_role`: contract_ccy must equal the designated role's column
- `chk_computed_has_rate`: computed/approved rows must have effective_rate_billing_ccy
- `chk_period_dates`: `period_end IS NULL OR period_end >= period_start`
- `chk_rate_binding_values`: `rate_binding IN ('floor', 'ceiling', 'discounted', 'fixed')`
- Partial unique indexes enforce one current row per granularity per tariff

**Data Migration:**
- `tariff_annual_rate` rows → `rate_granularity = 'annual'`
- `tariff_monthly_rate` rows → `rate_granularity = 'monthly'` with reconstructed `calc_detail` and USD values
- Same-currency backfill: sets `effective_rate_hard_ccy = effective_rate_local_ccy` where `hard_currency_id = local_currency_id`

**Dropped Tables:**
- `tariff_annual_rate` — replaced by `tariff_rate WHERE rate_granularity = 'annual'`
- `tariff_monthly_rate` — replaced by `tariff_rate WHERE rate_granularity = 'monthly'`

**Backend Changes:**
- `python-backend/services/tariff/rebased_market_price_engine.py`: Writes exclusively to `tariff_rate` — computes all four currency columns, builds `calc_detail` JSONB with floor/ceiling/discounted_base in four-currency format, sets `reference_price_id`, `discount_pct_applied`, `formula_version='rebased_v1'`, `effective_rate_contract_role='local'`. Monthly rows link to monthly `reference_price` when available (fallback to annual).
- `python-backend/services/tariff/rate_period_generator.py`: Writes exclusively to `tariff_rate` — same-currency columns, `calc_detail` with `escalation_value`/`years_elapsed`, `formula_version='deterministic_v1'`, `rate_binding='fixed'`
- `python-backend/api/entities.py`: All three CTEs (`rate_periods_data`, `monthly_rates_data`, `tariff_rates_data`) query `tariff_rate` directly in main CTE. PATCH endpoint targets `tariff_rate`. `RatePeriodPatch` field renamed `effective_tariff` → `effective_rate_contract_ccy`.
- `python-backend/api/billing.py`: Reads `tariff_rate` exclusively (month-exact matching); uses `effective_rate_billing_ccy` directly; no old-table fallback.
- `python-backend/api/spreadsheet.py`: Only `tariff_rate` in `_PROJECT_SCOPED_TABLES` (removed `tariff_annual_rate`, `tariff_monthly_rate`). Removed old-table scoping, UPDATE, and DELETE handlers.
- `database/scripts/project-onboarding/onboard_project.sql`: Removed section 4.11 (`tariff_annual_rate` INSERT) and its assertion. Only inserts Year 1 into `tariff_rate`.
- `database/scripts/project-onboarding/validate_onboarding_project.sql`: Replaced `tariff_annual_rate` checks with `tariff_rate WHERE rate_granularity = 'annual'`.

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `tariff_rates` to `ProjectDashboardResponse` interface
- `app/projects/components/PricingTariffsTab.tsx`: Monthly rate linking uses `clause_tariff_id + contract_year` (was `tariff_annual_rate_id`). Rate field renamed `effective_tariff` → `effective_rate_contract_ccy`.
- `app/projects/components/spreadsheet/univerDataConverter.ts`: Removed `tariff_annual_rate_id` from `PROTECTED_COLUMNS`.

---

### v10.4 - 2026-02-24 (Multi-Meter Billing & Plant Performance)

**Description:** Adds per-meter billing breakdown, Available Energy tracking, and plant performance analysis. Models the real-world scenario where projects have multiple physical meters (e.g. PPL1, PPL2, BBM1) each generating separate invoice line items. Includes dedup index fix, contract_line FK resolution, and irradiance unit handling.

**Migration:** `database/migrations/041_multi_meter_billing_and_performance.sql`

**New Enum:**
- `energy_category` ('metered', 'available', 'test')

**Modified Table: `meter`**
- Added `name VARCHAR(100)` — human-readable meter name

**New Table: `contract_line`**

| Column | Type | Description |
|--------|------|-------------|
| `contract_id` | BIGINT FK | Links to contract |
| `billing_product_id` | BIGINT FK | Links to billing_product |
| `meter_id` | BIGINT FK | Links to meter (NULL for project-level lines) |
| `contract_line_number` | INTEGER | CBE line code (1000, 4000, etc.) |
| `product_desc` | VARCHAR(255) | Description (e.g. "Metered Energy - PPL1") |
| `energy_category` | energy_category | metered, available, or test |
| `external_line_id` | VARCHAR(100) | CBE CONTRACT_LINE_UNIQUE_ID |

**Modified Table: `meter_aggregate`**
- Added `available_energy_kwh DECIMAL` — Available Energy per meter per month
- Added `contract_line_id BIGINT FK → contract_line(id)` — links to billable contract line
- Added `ghi_irradiance_wm2 DECIMAL` — monthly GHI irradiance in Wh/m² (divide by 1000 for kWh/m² forecast comparison)
- Added `poa_irradiance_wm2 DECIMAL` — monthly POA irradiance in Wh/m² (divide by 1000 for kWh/m² forecast comparison)

**Replaced Index: idx_meter_aggregate_billing_dedup**
- Old key (migration 026): `(organization_id, COALESCE(billing_period_id, -1), COALESCE(clause_tariff_id, -1))`
- New key: `(organization_id, COALESCE(meter_id, -1), COALESCE(billing_period_id, -1), COALESCE(clause_tariff_id, -1), COALESCE(contract_line_id, -1))`
- Still partial: `WHERE period_type = 'monthly'`
- Prevents multi-meter rows from colliding on same tariff+period

**New Unique Index: uq_contract_line_external_line_id**
- Columns: `(organization_id, external_line_id) WHERE external_line_id IS NOT NULL`
- Enables bulk FK lookup by CBE `CONTRACT_LINE_UNIQUE_ID` during ingestion

**New Table: `plant_performance`**

| Column | Type | Description |
|--------|------|-------------|
| `project_id` | BIGINT FK | Links to project |
| `billing_period_id` | BIGINT FK | Links to billing_period (nullable, resolved on insert) |
| `production_forecast_id` | BIGINT FK | Links to forecast for this month |
| `billing_month` | DATE | Unique per project |
| `operating_year` | INTEGER | Operating year number |
| `actual_pr` | DECIMAL(5,4) | Performance Ratio |
| `actual_availability_pct` | DECIMAL(5,2) | System availability % |
| `energy_comparison` | DECIMAL(6,4) | actual / forecast energy ratio |
| `irr_comparison` | DECIMAL(6,4) | actual / forecast GHI ratio |
| `pr_comparison` | DECIMAL(6,4) | actual / forecast PR ratio |

**Seed Data:**
- MOH01 meter names: PPL1, PPL2, Bottles, BBM1, BBM2 (meter ids 2-6)
- MOH01 contract_line rows: 8 lines mapping meters to billing products (contract_id=7)
- MOH01 external_line_ids: `CONZIM00-2025-00002-{contract_line_number}` backfilled on contract_line rows

**Backend Changes:**

**python-backend/api/billing.py:**
- New `GET /projects/{id}/meter-billing` endpoint for per-meter breakdown
- `get_meter_billing`: Resolves rate per-meter via `contract_line.external_line_id` → `clause_tariff` linkage; falls back to project-level tariff for old data
- `ManualEntryRequest`: Added optional `meter_id` field
- `add_manual_entry`: Uses provided `meter_id` or falls back to first project meter
- `import_monthly_billing`: Parses `meter_id` column from CSV if present

**python-backend/api/performance.py:**
- New file — `GET /projects/{id}/plant-performance`, `POST .../manual`, `POST .../import`
- `irr_comparison`: Converts `actual_ghi` from Wh/m² to kWh/m² (÷1000) before dividing by `forecast_ghi` (kWh/m²)

**python-backend/services/available_energy_calculator.py:** New file — contractual Available Energy formula implementation

**python-backend/main.py:** Registered performance router

**data-ingestion/processing/meter_aggregate_loader.py:**
- Added `contract_line_id`, `available_energy_kwh`, `ghi_irradiance_wm2`, `poa_irradiance_wm2` to COLUMNS
- Changed `ON CONFLICT DO NOTHING` to explicit upsert on new dedup key columns

**data-ingestion/processing/billing_resolver.py:**
- Added `_bulk_resolve_contract_lines(external_line_ids, org_id)` method
- Extended `resolve_batch()` to resolve `contract_line_id` and `meter_id` from `contract_line.external_line_id`
- CBE `CONTRACT_LINE_UNIQUE_ID` = `tariff_group_key` on `clause_tariff` AND `external_line_id` on `contract_line`

**data-ingestion/processing/adapters/cbe_billing_adapter.py:**
- Populates `available_energy_kwh`, `energy_category`, `contract_line_number`

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `MeterBillingResponse`, `PlantPerformanceResponse` types and API methods
- `app/projects/components/MonthlyBillingTab.tsx`: Summary/Meter Breakdown toggle with expandable per-meter detail
- `app/projects/components/PlantPerformanceTab.tsx`: New file — performance table, charts (energy bar, PR line), summary cards
- `app/projects/page.tsx`: Added "Performance" tab between Monthly Billing and Contacts

**Design Notes:**
- `billing_currency_id` = `clause_tariff.currency_id` (per onboarding — this is the billing currency, not hard/contract currency)
- `effective_rate_contract_role` is nullable with no default — engine must set it explicitly
- `calc_detail` JSONB is escalation-type-specific (REBASED_MARKET_PRICE stores floor/ceiling/discounted_base; deterministic stores escalation_value/years_elapsed)
- RLS policies use `DROP POLICY IF EXISTS` for idempotent re-runs

**Design Notes:**
- Per-contract-line billing math in monthly billing summary deferred (requires frontend changes)
- Available energy calculator (`available_energy_calculator.py`) not wired into API yet (standalone feature)
- Full contract_line date-window CHECK constraints deferred (unique indexes are the critical fix)

---

### v10.5 - 2026-02-24 (Phase 10.5 - Invoice Generation & Tax Engine)

**Description:** Invoice generation prerequisites, billing tax rules, expected invoice versioning,
per-meter performance detail, and restructured frontend tabs.

**Migrations:**
- `database/migrations/042_invoice_generation_prerequisites.sql`

**Fixtures:**
- `database/scripts/fixtures/moh01_dec2025.sql` — Dec 2025 golden test data

**New Tables:**
| Table | Description |
|-------|-------------|
| `billing_tax_rule` | Organization/country tax rules with GiST overlap prevention |

**New `invoice_line_item_type` Entries:**
- `AVAILABLE_ENERGY` — Available energy charge
- `LEVY` — Government levy
- `WITHHOLDING` — Withholding tax or VAT deduction

**Modified Tables:**

| Table | Changes |
|-------|---------|
| `contract_line` | Added `clause_tariff_id` FK for per-line tariff resolution |
| `expected_invoice_header` | Added `version_no`, `is_current`, `generated_at`, `idempotency_key`, `source_metadata` |
| `expected_invoice_line_item` | Added `component_code`, `basis_amount`, `rate_pct`, `amount_sign`, `sort_order`, `contract_line_id` |

**New Indexes:**
- `idx_meter_aggregate_billing_dedup` — Replaced COALESCE-based index with clean resolved-only unique index
- `idx_expected_invoice_current` — One current invoice per (project, period, direction)
- `idx_expected_invoice_version` — Version history uniqueness
- `idx_expected_invoice_idempotency` — Idempotency key uniqueness
- `idx_billing_tax_rule_lookup` — Tax rule resolution lookup

**New Constraints:**
- `chk_line_amount_sign` — Sign enforcement on `expected_invoice_line_item`
- `billing_tax_rule_no_overlap` — GiST exclusion to prevent overlapping active date ranges

**Extensions:**
- `btree_gist` — Required for GiST exclusion constraint on `billing_tax_rule`

**Backend Changes:**
- `python-backend/api/billing.py`: New `POST /projects/{pid}/billing/generate-expected-invoice` endpoint; `GET /meter-billing` reads from `expected_invoice_*` tables
- `python-backend/api/performance.py`: Added `MeterPerformanceDetail`, per-meter detail in `PerformanceMonth`, GHI unit normalization (Wh/m² → kWh/m²)
- `data-ingestion/processing/billing_resolver.py`: `resolve_batch()` returns `(resolved, unresolved)` tuple instead of patching NULLs
- `data-ingestion/processing/meter_aggregate_loader.py`: Split insert path — resolved → upsert, unresolved → logged and dropped

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `ExpectedInvoiceLineItem`, `ExpectedInvoiceSummary`, `MeterPerformanceDetail` types; `meters` on `PlantPerformanceResponse`; `expected_invoice` on `MeterBillingMonth`; `generateExpectedInvoice()` method
- `app/projects/utils/formatters.ts`: New shared formatting utilities (formatMonth, fmtNum, fmtCurrency, fmtPct, fmtRatio, compClass, varianceClass)
- `app/projects/components/PlantPerformanceTab.tsx`: Grouped-header workbook table with per-meter columns, sticky month column
- `app/projects/components/MonthlyBillingTab.tsx`: Generic invoice view from persisted line items, grouped by type with section subtotals

**Tax Configuration:**
- Resolution hierarchy: `clause_tariff.logic_parameters.billing_taxes` → `billing_tax_rule` → explicit failure
- Deterministic rounding: line-level rounding, exact subtotals, stored full precision in `source_metadata`
- Configurable `available_energy_line_mode`: `"single"` (aggregate), `"per_meter"`, or `"per_contract_line"`

---

### v10.6 - 2026-02-25 (Billing Engine Gap Analysis Fixes)

**Description:** Correctness fixes from billing engine gap analysis: per-meter available energy, country-scoped tax rules, configurable invoice direction, direction-aware invoice reads, and tighter RLS.

**Migrations:**
- `database/migrations/043_billing_gap_analysis_fixes.sql` — Org-scoped RLS for `billing_tax_rule`

**RLS Changes:**
- `billing_tax_rule_org_read` policy replaced: was `USING(true)`, now org-scoped via `role` table lookup + global rules (`organization_id IS NULL`)

**Backend Changes:**
- `python-backend/api/billing.py`:
  - **F1:** Implemented `per_meter` available energy mode — creates per-line `AVAILABLE_ENERGY` invoice items
  - **F2:** Tax rule fallback maps `project.country` to ISO code in Python and filters by `country_code`
  - **F3:** `GenerateInvoiceRequest.invoice_direction` field (default "payable", supports "receivable")
  - **F4:** `_read_expected_invoice()` filters by `invoice_direction` (default "payable")
  - **F12:** `MonthlyBillingResponse.cod_date` and `ProductColumn.energy_category` exposed to frontend
- `python-backend/api/performance.py`:
  - **F5:** Per-meter `available_kwh` populated from `meter_aggregate.available_energy_kwh`

**Frontend Changes:**
- `lib/api/adminClient.ts`: Added `energy_category` to `MonthlyBillingProductColumn`, `cod_date` to `MonthlyBillingResponse`, `invoice_direction` to `generateExpectedInvoice()` params
- `app/projects/components/MonthlyBillingTab.tsx`:
  - **F12:** Replaced hardcoded `'2025-09'` COD filter with dynamic `data.cod_date`
  - **F12:** `productEnergyCategory()` prefers API-driven `energy_category`, falls back to name heuristic
  - **F13:** Expanded detail rows use persisted invoice line items when available, fall back to `qty * rate`

---

### v10.7 - 2026-02-26 (Customer Summary Cross-Check: Legal Entity & MOH01 Fixes)

**Description:** New `legal_entity` table for CBE SPVs with Sage company codes, `counterparty.industry` column, and MOH01 data corrections from Customer Summary spreadsheet cross-check.

**Migrations:**
- `database/migrations/044_legal_entity_industry_and_moh01_fixes.sql`

**New Tables:**
| Table | Description |
|-------|-------------|
| `legal_entity` | CBE legal entities (SPVs) with Sage company codes, org-scoped with RLS |

**New Columns:**
| Table | Column | Type | Description |
|-------|--------|------|-------------|
| `project` | `legal_entity_id` | BIGINT FK | Links project to its CBE legal entity |
| `counterparty` | `industry` | VARCHAR(100) | Customer industry classification |

**COMMENT Corrections:**
- `project.sage_id`: Updated to "Sage Customer ID (e.g., MOH01, GBL01). Maps to Sage customer identifier."

**Seed Data:**
- Three CBE legal entities: CBCH (Mauritius), EGY0 (Egypt), GHA0 (Ghana)

**Data Fixes (MOH01 → GH 22015):**
- `project.external_project_id`: `MOH01` → `GH 22015`
- `project.name`: `Mohinani` → `Mohinani Group`
- `project.sage_id`: NULL → `MOH01`
- `project.legal_entity_id`: set to GHA0 legal entity
- `clause_tariff.energy_sale_type_id`: `FIXED_SOLAR` → `FLOATING_GRID`
- `counterparty.industry`: NULL → `Consumer Products` (Polytanks Ghana Limited)

**RLS Policies:**
- `legal_entity_select_policy` — org members can read
- `legal_entity_admin_modify_policy` — org admins can modify
- `legal_entity_service_policy` — service role full access

**Backend Changes:**
- `python-backend/api/entities.py`:
  - Added `legal_entity_id` to `ProjectPatch` model
  - Added `legal_entity_name`, `legal_entity_code` to project_data CTE (via LEFT JOIN legal_entity)
  - Added `counterparty_industry` to contracts_data CTE

**Frontend Changes:**
- `app/projects/components/ProjectOverviewTab.tsx`:
  - Renamed `Sage ID` → `Sage Customer ID`
  - Added Legal Entity, Legal Entity Code, and Industry display fields

---

### v10.8 - 2026-02-27 (Relocate Misplaced Contract Columns)

**Description:** Clean up contract table by relocating columns that were added during onboarding (migration 033) but don't belong on the contract table: `interconnection_voltage_kv` (site-level spec → project), `agreed_fx_rate_source` (tariff data → clause_tariff), and `payment_security_*` (clause terms → clause table).

**Migrations:**
- `database/migrations/045_relocate_contract_columns.sql`

**New Columns:**
| Table | Column | Type | Description |
|-------|--------|------|-------------|
| `project` | `technical_specs` | JSONB DEFAULT '{}' | Technical specifications bag (interconnection_voltage_kv, etc.) |
| `clause_tariff` | `agreed_fx_rate_source` | VARCHAR(255) | Agreed FX rate determination method |

**Data Migrations:**
- `contract.interconnection_voltage_kv` → `project.technical_specs` JSONB key
- `contract.agreed_fx_rate_source` → `clause_tariff.agreed_fx_rate_source` (all is_current=true tariffs)
- `contract.payment_security_required` + `payment_security_details` → `clause` records with category `SECURITY_PACKAGE`

**Dropped Columns:**
| Table | Column | Replacement |
|-------|--------|-------------|
| `contract` | `interconnection_voltage_kv` | `project.technical_specs->>'interconnection_voltage_kv'` |
| `contract` | `payment_security_required` | `clause` with `SECURITY_PACKAGE` category |
| `contract` | `payment_security_details` | `clause.normalized_payload->>'details'` |
| `contract` | `agreed_fx_rate_source` | `clause_tariff.agreed_fx_rate_source` |

**Onboarding Script Changes:**
- `database/scripts/project-onboarding/onboard_project.sql`:
  - Step 4.2: Project upsert now writes `technical_specs` JSONB from staging `interconnection_voltage_kv`
  - Step 4.3: Contract upsert no longer writes the 4 relocated columns
  - Step 4.5: Tariff upsert now writes `agreed_fx_rate_source` from staging
  - New Step 4.6b: Inserts `SECURITY_PACKAGE` clause from staging payment security data

**Backend Changes:**
- `python-backend/api/entities.py`:
  - Removed `payment_security_details`, `agreed_fx_rate_source`, `interconnection_voltage_kv` from `ContractPatch`
  - Added `ts_interconnection_voltage_kv` to `ProjectPatch` (JSONB prefix `ts_` → `technical_specs`)
  - Added `agreed_fx_rate_source` to `TariffPatch`
  - Added `"ts_": "technical_specs"` to `_JSONB_PREFIX_MAP`

**Frontend Changes:**
- `app/projects/components/TechnicalTab.tsx`: Reads interconnection voltage from `project.technical_specs` JSONB instead of contract
- `app/projects/components/PricingTariffsTab.tsx`: Reads/edits `agreed_fx_rate_source` from tariff instead of contract

**Validation Changes:**
- `database/scripts/project-onboarding/validate_onboarding_project.sql`: Updated payment security validation to query `clause` table for `SECURITY_PACKAGE` clause

---

### v10.9 - 2026-02-27 (CBE Portfolio Data Population)

**Description:** Populates the database with CBE's full customer contract portfolio: 33 projects from Customer Summary spreadsheet and metadata from 62 contract PDFs. Adds `parent_contract_id` hierarchy for ancillary documents, makes `amendment_date` nullable for unknown signing dates, and seeds all reference data (legal entities, counterparties, contracts, amendments). Deletes placeholder projects (Solar Farm, Travis County). Preserves existing MOH01 data.

**Migration:** `database/migrations/046_populate_portfolio_base_data.sql`

**Reference:** `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md` — Complete mapping reference

**Schema Changes:**

**New Column: contract.parent_contract_id**
- `parent_contract_id` - BIGINT REFERENCES contract(id) — links ancillary documents to their primary contract
- `chk_contract_no_self_parent` CHECK constraint — prevents self-reference
- `idx_contract_parent` — partial index WHERE parent_contract_id IS NOT NULL
- `trg_contract_same_project_parent` trigger — validates parent belongs to same project

**Nullable Column: contract_amendment.amendment_date**
- Was NOT NULL, now nullable — 5 amendments have unknown signing dates (QMM01 RESA 1st/2nd, UNSOS 2nd)

**New Currencies:**
- MGA (Malagasy Ariary), SOS (Somali Shilling), ZWL (Zimbabwean Dollar), CDF (Congolese Franc)

**New Legal Entities (8):**
- KEN0, MAD0, MAD2, NIG0, SL02, SOM0, MOZ0, ZIM0

**Deleted Projects:**
- Solar Farm (org=1) — 1 orphan meter deleted
- Travis County (org=2) — no child data

**Seed Data:**
- ~22 new counterparties (all OFFTAKER type)
- ~32 new projects (MOH01 excluded)
- ~28 primary contracts (parent_contract_id = NULL), with `file_location` set for ~27
- ~13 ancillary contracts (parent_contract_id = primary), with `file_location` set for all
- ~18 new amendments (MOH01 amendment excluded), with `file_path` set for all

**Data Quality Fixes:**
- `project.country` uses physical site location, not legal entity jurisdiction (GC01→Kenya, ZO01→Sierra Leone, TBC→DRC)
- ZO01 now has primary ESA contract + ancillary loan agreement (2 PDFs found)
- Amendment numbering preserves source document numbering (NBL02: #2, UNSOS: #2/#3)
- Normalized Sage IDs tracked via `extraction_metadata.source_sage_customer_id` (GC001→GC01, ZL01→ZO01, XF-AB/BV/L01/SS→XF-AB)

**Backend Changes:**
- `python-backend/api/billing.py` (~line 264): Added `AND c.parent_contract_id IS NULL` to contract JOIN — prevents billing from picking ancillary documents
- `python-backend/api/billing.py` (~line 27-40): Added 8 country codes to `_COUNTRY_NAME_TO_CODE` (EG, MG, SL, SO, MZ, ZW, CD, RW) — resolves all portfolio countries for tax rule lookup
- `python-backend/api/entities.py` (~line 728): Changed ORDER BY to `c.parent_contract_id NULLS FIRST, c.effective_date` — ensures primary contract sorts first for dashboard display

**Exchange Rates (Step 9):**
- 140 rows: 10 currencies × 14 months (Jan 2025 – Feb 2026, 1st of each month)
- Source: xe.com mid-market rates, stored with `source = 'xe.com'`
- Currencies: KES, NGN, SLE, EGP, MGA, RWF, SOS, MZN, ZWL, CDF
- GHS rates (6 rows, `source = 'bog_manual'`) are NOT modified
- ZWL: xe.com renamed to ZWG (Zimbabwe Gold) after Apr 2024 currency reform; ZWG rates used
- All inserts use dynamic currency code lookups (not hardcoded IDs)
- ON CONFLICT upsert ensures idempotency

**Design Notes:**
- Primary contracts have `parent_contract_id = NULL`; ancillary docs reference the primary
- Projects TBC, ZL02 have no contract rows (no PDFs available)
- Contract effective_date set to COD date as proxy where exact signing date unavailable
- `contract.file_location` and `contract_amendment.file_path` store relative paths to PDFs in `CBE_data_extracts/Customer Offtake Agreements/`
- All inserts use code-based lookups (not hardcoded IDs) for FK resolution
- All inserts are idempotent (ON CONFLICT DO NOTHING or DO UPDATE)
- Post-load assertions verify MOH01 integrity and minimum record counts

---

### v10.10 - 2026-02-28 (SAGE Contract IDs & Parent-Child Contract Line Hierarchy)

**Description:** Combined migration with two parts. **Part A** populates `external_contract_id` (SAGE ERP contract number), `payment_terms`, and `end_date` for 27 primary contracts using data from CBE's SAGE ERP contract extract. **Part B** adds `parent_contract_line_id` self-referential FK to `contract_line`, mirroring the `contract.parent_contract_id` pattern, and inserts MOH01 line 1000 as a "mother" site-level contract line linked to per-meter children.

**Migration:** `database/migrations/047_populate_sage_contract_ids.sql`

**Reference:** `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md` Sections 18–19

**Source Data:** `CBE_data_extracts/Data Extracts/FrontierMind Extracts_dim_finance_contract.csv` (DIM_CURRENT_RECORD=1 rows only)

**Part A — Schema Changes:** None — data-only

**Part A — Data Updates (27 contracts):**

| Field | Scope | Pattern |
|-------|-------|---------|
| `contract.external_contract_id` | 26 contracts (MOH01 already set) | SAGE contract number, e.g. `CONCBCH0-2021-00001` |
| `contract.payment_terms` | 26 contracts (MOH01 already set) | SAGE payment term code: 30NET, 30EOM, 60NET, 75EOM, 90NET, 90EOM |
| `contract.end_date` | 27 contracts (including MOH01) | SAGE END_DATE from current contract record |

**Payment Terms Breakdown:**

| Term | Count | Projects |
|------|-------|----------|
| 30NET | 14 | IVL01, AR01, MB01, MF01, MP01, MP02, NC02, NC03, TBM01, ERG, MIR01, UNSOS, CAL01, MOH01 |
| 30EOM | 8 | GC01, KAS01, LOI01, XF-AB, AMP01, TWG01, JAB01, QMM01→75EOM |
| 60NET | 3 | GBL01, NBL01, NBL02 |
| 75EOM | 1 | QMM01 |
| 90NET | 1 | UGL01 |
| 90EOM | 1 | UTK01 |

**Contracts Without SAGE Data (3 — not modified):**
- ABI01 (contract 42) — no SAGE contract record
- BNT01 (contract 43) — no SAGE contract record
- ZO01 (contract 56) — SAGE ZL01 contracts reassigned to ZL02 entity

**Part B — Schema Changes:**
- `contract_line.parent_contract_line_id` — BIGINT FK to `contract_line(id)`, self-referential
- `chk_contract_line_no_self_parent` — CHECK constraint preventing self-parent
- `idx_contract_line_parent` — Partial index on `parent_contract_line_id WHERE IS NOT NULL`
- `trg_contract_line_same_contract_parent` — Trigger enforcing parent belongs to same contract
- **Dropped:** `line_decomposition` table (from prior version)

**Part B — Data Changes (MOH01):**
- Cleared `external_line_id = '11481428495164935368'` from per-meter available lines (was incorrectly set previously)
- Inserted mother line 1000: `energy_category = 'available'`, `meter_id = NULL`, `external_line_id = '11481428495164935368'`
- Linked 5 child lines (4001, 5001, 6001, 7001, 8001) via `parent_contract_line_id`

**Design Notes:**
- Uses `project.sage_id` joins instead of hardcoded `contract.id` — environment-stable across dev/staging/prod
- SAGE contract numbers follow pattern `CON{FACILITY}-{YEAR}-{SEQ}` (e.g., `CONKEN00-2023-00009`)
- XF-AB: SAGE has 4 sub-contracts (XFAB, XFBV, XFL01, XFSS); primary `CONKEN00-2021-00003` (XFAB) used as `external_contract_id`
- TWG01: FM uses `TWG01`, SAGE uses `TWG` — mapping handled via `project.sage_id`
- MOH01: only `end_date` updated (external_contract_id and payment_terms already populated)
- Post-load assertions verify minimum counts and MOH01 integrity

**Code Changes:**
- `data-ingestion/processing/billing_resolver.py` — Pass 2 now detects mother lines (meter_id IS NULL) and resolves via `parent_contract_line_id` children instead of `line_decomposition`
- `python-backend/api/billing.py` — Added `AND cl.parent_contract_line_id IS NULL` filter to exclude mother lines from invoice generation
- `python-backend/evals/conftest.py` — Added `parent_contract_line_id` to `fm_contract_lines` fixture SELECT
- `python-backend/evals/metrics/mapping_metrics.py` — Removed `fm_line_decompositions` parameter; mother line has `external_line_id` set directly
- `python-backend/evals/test_billing_readiness.py` — Excluded mother lines from `meter_id` assertion

**Mapping Doc:** See `CBE_TO_FRONTIERMIND_MAPPING.md` Sections 18–19 for full documentation.

---

### v4.2 - 2026-02-28 (Pilot Project Data Population)

**Description:** Populates contract_line, clause_tariff, meter_aggregate, and contract_billing_product for 3 pilot projects: KAS01 (Ghana), NBL01 (Nigeria), LOI01 (Kenya).

**Migrations:**
- `database/migrations/049_pilot_project_data_population.sql`

**Source Data:**
- `CBE_data_extracts/Data Extracts/FrontierMind Extracts_dim_finance_contract_line.csv` (DIM_CURRENT_RECORD=1)
- `CBE_data_extracts/Data Extracts/FrontierMind Extracts_meter readings.csv`

**Data Changes:**

**Section A — Contract Lines (15 rows):**

| Project | Contract | Lines | Active | Inactive |
|---------|----------|-------|--------|----------|
| KAS01 | CONGHA00-2021-00002 | 1000, 2000, 3000, 4000 | 3 (1000 metered P1, 2000 available, 4000 metered P2) | 1 (3000 Inverter Energy, test) |
| NBL01 | CONNIG00-2021-00002 | 1000, 3000, 4000, 5000, 6000, 7000, 9000, 10000 | 3 (6000 gen metered P1, 7000 gen available, 10000 gen metered P2) | 5 (legacy grid + early operating) |
| LOI01 | CONKEN00-2021-00002 | 1000, 2000, 3000 | 3 (1000 HQ metered, 2000 Camp metered, 3000 BESS capacity test) | 0 |

- All lines have `meter_id = NULL` (meters not yet available)
- `external_line_id` set from CBE `CONTRACT_LINE_UNIQUE_ID`
- `energy_category`: metered/available from METERED_AVAILABLE field; N/A non-energy products → test

**Section B — Clause Tariffs (4 placeholder rows):**

| Project | Tariff Group Key | Currency | Base Rate | Notes |
|---------|-----------------|----------|-----------|-------|
| KAS01 | CONGHA00-2021-00002-MAIN | GHS | NULL | Populated after PPA parsing |
| NBL01 | CONNIG00-2021-00002-MAIN | NGN | NULL | Populated after PPA parsing |
| LOI01 | CONKEN00-2021-00002-MAIN | USD | NULL | Populated after PPA parsing |
| LOI01 | CONKEN00-2021-00002-BESS | USD | NULL | BESS capacity charge |

- Linked to contract_lines via `clause_tariff_id` FK update

**Section C — Meter Aggregates (94 rows):**

| Project | Months | Lines with Readings | Total Rows |
|---------|--------|-------------------|------------|
| KAS01 | Jan-Dec 2025 | 1000, 2000, 3000 (Jan only), 4000 (Feb-Dec) | 36 |
| NBL01 | Jan-Dec 2025 | 6000, 7000 (Mar-Dec), 10000 | 34 |
| LOI01 | Jan-Dec 2025 | 1000, 2000 | 24 |

- `meter_id = NULL`, `contract_line_id` resolved via `external_line_id` join
- `billing_period_id` resolved via `end_date` match
- `source_metadata` contains `external_reading_id` for CBE traceability

**Section D — Contract Billing Products (8 junction rows):**
- KAS01: Metered Energy + Available Energy
- NBL01: Generator (EMetered) + Generator (EAvailable)
- LOI01: Loisaba HQ + Loisaba Camp + BESS Capacity

**Bug Fixes:**
- EXC-004: `cbe_billing_adapter.py` — Removed `n/a`/`N/A` from `AVAILABLE_CATEGORIES`; added `_classify_energy_category()` with product-pattern matching from ontology

**New Scripts:**
- `python-backend/scripts/batch_parse_ppas.py` — Batch PPA parsing for pilot projects

**New Documentation:**
- `CBE_data_extracts/PROJECT_SOURCE_INVENTORY.md` — Project × document matrix for all 32 projects

---

### v4.3 - 2026-03-04 (Rename GRP → MRP — Terminology Change)

**Description:** Renames "Grid Reference Price" (GRP) to "Market Reference Price" (MRP) across the entire application. This is a terminology-only change — no logic changes.

**Migration:** `database/migrations/050_rename_grp_to_mrp.sql`

**Column Renames:**
| Table | Old Column | New Column |
|-------|-----------|------------|
| `reference_price` | `calculated_grp_per_kwh` | `calculated_mrp_per_kwh` |
| `tariff_monthly_rate` | `discounted_grp_local` | `discounted_mrp_local` |

**JSONB Key Updates (`clause_tariff.logic_parameters`):**
- `grp_method` → `mrp_method`
- `grp_included_components` → `mrp_included_components`
- `grp_excluded_components` → `mrp_excluded_components`
- `grp_time_window_start` → `mrp_time_window_start`
- `grp_per_kwh` → `mrp_per_kwh`

**Check Constraint Updates:**
- `submission_token.submission_type`: `'grp_upload'` → `'mrp_upload'`
- Existing rows in `reference_price` and `submission_token` updated

**Comment Updates:**
- `reference_price` table and `calculated_mrp_per_kwh` column
- `tariff_monthly_rate.discounted_mrp_local` column
- `submission_token.project_id` and `submission_token.submission_type` columns
- `tariff_rate.reference_price_id` column

**Backend File Renames:**
- `models/grp.py` → `models/mrp.py`
- `api/grp.py` → `api/mrp.py`
- `services/grp/` → `services/mrp/`
- `services/calculations/grid_reference_price.py` → `market_reference_price.py`
- `services/prompts/grp_extraction_prompt.py` → `mrp_extraction_prompt.py`
- `scripts/populate_grp_from_excel.py` → `populate_mrp_from_excel.py`
- `scripts/patch_kas01_grp_template.py` → `patch_kas01_mrp_template.py`
- `scripts/backfill_grp_method.py` → `backfill_mrp_method.py`

**Backend Content Updates:**
- All class names: `GRP*` → `MRP*` (e.g., `GRPObservation` → `MRPObservation`, `GRPExtractionService` → `MRPExtractionService`)
- All API routes: `/grp-*` → `/mrp-*`
- All function names: `*grp*` → `*mrp*` (e.g., `calculate_grp` → `calculate_mrp`)
- S3 upload path: `grp-uploads/` → `mrp-uploads/`
- Submission type: `'grp_upload'` → `'mrp_upload'`
- Logic parameter keys in prompts, parsers, and onboarding services

**Frontend File Renames:**
- `app/projects/components/GRPSection.tsx` → `MRPSection.tsx`

**Frontend Content Updates:**
- Component: `GRPSection` → `MRPSection`
- All TypeScript interfaces: `GRP*` → `MRP*`
- All admin client methods: `*GRP*` → `*MRP*`
- API route paths in admin client
- UI labels: "Grid Reference Price" → "Market Reference Price"

**Fixture/Script Updates:**
- `database/scripts/project-onboarding/onboard_project.sql`: `grp_method` → `mrp_method`
- `database/scripts/fixtures/kas01_dec2025.sql`: Column names, JSON keys, comments
- `database/scripts/fixtures/moh01_dec2025.sql`: Column names, JSON keys, comments

---

### v8.1 - 2026-03-04 (Organization Email Addresses)

**Description:** Maps organizations to dedicated email addresses on `mail.frontiermind.co` for bidirectional email — outbound notifications and inbound invoice ingestion from a single address per org.

**Migration:** `database/migrations/051_org_email_address.sql`

**New Table: `org_email_address`**
| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `organization_id` | BIGINT | FK → `organization(id)` |
| `email_prefix` | VARCHAR(63) | Local part (e.g., `cbe` → `cbe@mail.frontiermind.co`) |
| `domain` | VARCHAR(255) | Email domain, default `mail.frontiermind.co` |
| `display_name` | VARCHAR(200) | Sender display name in From header (e.g., `CrossBoundary Energy`) |
| `label` | VARCHAR(100) | Purpose label (`default`, `billing`, etc.) |
| `is_active` | BOOLEAN | Default `true` |
| `created_at` | TIMESTAMPTZ | Auto-set |
| `updated_at` | TIMESTAMPTZ | Auto-set via trigger |

**Indexes:**
- `ux_org_email_prefix_domain` — unique on `(email_prefix, domain)`
- `ux_org_email_org_label` — unique on `(organization_id, label)`
- `idx_org_email_prefix_active` — partial index for inbound routing lookup

**RLS Policies:** Follows migration 032 pattern — org members read, org admins manage, service_role full access.

**Seed Data:** CBE organization (id=1) → `cbe@mail.frontiermind.co`, display_name `CrossBoundary Energy`, label `default`.

**Infrastructure Context:**
- AWS SES domain: `mail.frontiermind.co` (verified via DKIM)
- Inbound email: MX → SES → S3 (`frontiermind-email`) + SNS notification
- Outbound sender: `SES_SENDER_EMAIL` secret updated to `cbe@mail.frontiermind.co`
- Task definition env vars: `SES_INGEST_BUCKET`, `SES_SENDER_DOMAIN`

---

### v8.3 - 2026-03-04 (Unified Inbound Message Model — Combined Expand/Contract)

**Description:** Unified `inbound_message` + `inbound_attachment` tables fully replacing `submission_response`. Renames `email_log` → `outbound_message` for symmetric naming. Combined expand/contract migration in two transaction blocks within a single file.

**Migration File:** `database/migrations/052_inbound_message.sql`

**Renamed Table: `email_log` → `outbound_message`**
- Table renamed for symmetric naming with `inbound_message`
- FK column on `submission_token` renamed: `email_log_id` → `outbound_message_id`
- All indexes and RLS policies renamed accordingly

**Phase A (Expand):**

**New Table: `inbound_message`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `organization_id` | BIGINT | FK → `organization(id)` |
| `channel` | VARCHAR(20) | `email`, `token_form`, or `token_upload` |
| `subject` | TEXT | Email subject |
| `body_text` | TEXT | Plain text body |
| `raw_headers` | JSONB | Full parsed email headers |
| `ses_message_id` | VARCHAR(255) | SES Message-ID for threading |
| `in_reply_to` | VARCHAR(255) | In-Reply-To header value |
| `references_chain` | TEXT[] | References header as array |
| `s3_raw_path` | TEXT | S3 path of raw MIME |
| `submission_token_id` | BIGINT | FK → `submission_token(id)` |
| `response_data` | JSONB | Submitted form data |
| `sender_email` | VARCHAR(320) | Sender email (all channels) |
| `sender_name` | VARCHAR(255) | Sender display name |
| `ip_address` | INET | Submitter IP |
| `invoice_header_id` | BIGINT | FK → `invoice_header(id)` |
| `project_id` | BIGINT | FK → `project(id)` |
| `counterparty_id` | BIGINT | FK → `counterparty(id)` |
| `outbound_message_id` | BIGINT | FK → `outbound_message(id)` (threading) |
| `customer_contact_id` | BIGINT | FK → `customer_contact(id)` |
| `attachment_count` | INTEGER | Number of attachments |
| `inbound_message_status` | `inbound_message_status` | ENUM: received, pending_review, approved, rejected, noise, auto_processed, failed |
| `classification_reason` | VARCHAR(255) | Why this status was assigned |
| `failed_reason` | TEXT | Detailed failure info |


**New Table: `inbound_attachment`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `inbound_message_id` | BIGINT | FK → `inbound_message(id)` |
| `filename` | VARCHAR(500) | Original filename |
| `content_type` | VARCHAR(100) | MIME type |
| `size_bytes` | BIGINT | File size |
| `s3_path` | TEXT | S3 storage path |
| `file_hash` | VARCHAR(64) | SHA-256 hash |
| `attachment_processing_status` | `attachment_processing_status` | ENUM: pending, processing, extracted, failed, skipped |
| `extraction_result` | JSONB | Extraction output |
| `reference_price_id` | BIGINT | FK → `reference_price(id)` |

**Modified Table: `reference_price`**
- Added `inbound_message_id` BIGINT FK → `inbound_message(id)` (nullable)
- Added `inbound_attachment_id` BIGINT FK → `inbound_attachment(id)` (nullable)

**Backfill:** All existing `submission_response` rows migrated to `inbound_message` via temporary `legacy_submission_response_id` column. `reference_price.inbound_message_id` backfilled via exact join.

**RLS Policies:** Follows migration 032 pattern — org members read, org admins manage, service_role full access.

**Phase B (Contract):**

- Dropped `inbound_message.legacy_submission_response_id` column
- Dropped `reference_price.submission_response_id` column
- Dropped RLS policies on `submission_response`
- Dropped indexes on `submission_response`
- **Dropped `submission_response` table entirely**

**Verification:** Two DO blocks — Phase A asserts row count parity between `submission_response` and backfilled `inbound_message` rows; Phase B asserts `submission_response` table, `legacy_submission_response_id` column, and `reference_price.submission_response_id` column are all gone.

---

### Migration 053 - Organization-Scoped API Keys (2026-03-06)

**Migration:** `database/migrations/053_org_scoped_credentials.sql`

**Description:** Refactors the API key system from source-scoped (one key per data source) to org-scoped (one key, many data types). Adds indexed key lookup for O(1) authentication.

**Changes to `integration_credential`:**

- `data_source_id` — Made **nullable** (was NOT NULL). NULL = org-scoped key, non-NULL = legacy source-scoped key.
- `allowed_scopes TEXT[]` — New column. NULL = all scopes allowed. Non-null = restricted to listed values (`meter_data`, `fx_rates`, `billing_reads`). CHECK constraint validates values.
- `api_key_hash VARCHAR(64)` — New column. SHA-256 hash of the plaintext API key for indexed O(1) lookup. Partial index on non-NULL values.

**Constraint:** `chk_allowed_scopes_valid` — ensures `allowed_scopes` values are a subset of `{meter_data, fx_rates, billing_reads, invoice_export}`.

**Index:** `idx_credential_api_key_hash` — partial index on `api_key_hash WHERE api_key_hash IS NOT NULL`.

**Backward Compatible:** Existing keys with `data_source_id` set continue to work unchanged.

---

### v10.12 - 2026-03-08 (Sage ID Alias Reversal, Data Fixes, Multi-Phase Support & XF-AB Split)

**Migration:** `database/migrations/054_sage_id_aliases_and_data_fixes.sql`

**Description:** Reverses sage_id aliases to match xlsx source values, applies Step 1 data corrections, adds schema support for multi-phase projects, splits XF-AB into 4 separate projects, and creates ZL02 contracts.

**Sage ID Alias Reversal:**
- `GC01` → `GC001` (Garden City Mall — restores original SAGE customer number)
- `ZO01` → `ZL01` (Zoodlabs Group — restores original SAGE customer number)
- Clears `extraction_metadata.source_sage_customer_id` for these projects (no longer needed)

**Data Fixes:**
- `MOH01.cod_date`: `2025-09-01` → `2025-12-12` (from Customer summary.xlsx)
- `NBL01` counterparty: `CROSSBOUNDARY ENERGY NIGERIA LTD.` → `Heineken` (offtaker, not CBE SPV)

**New Column: `project.additional_external_ids TEXT[]`**
- Stores secondary client-defined project identifiers for multi-phase projects
- Primary ID remains in `external_project_id VARCHAR(50)` (unchanged, used as lookup key)
- Populated: QMM01 `['MG 22452']`, NBL01 `['NG 22051']`

**New Column: `contract_line.phase_cod_date DATE`**
- Phase-specific Commercial Operations Date
- Use when a project has multiple phases with different COD dates (e.g., KAS01 Phase 1 vs Phase 2)

**XF-AB Split (Step 2):**
- Renamed `XF-AB` → `XFAB` (primary project keeps existing contract id=31)
- Updated counterparty name: "XFlora Group" → "Xflora Africa Blooms"
- Created 3 new projects: `XFBV` (Xflora Bloom Valley), `XFL01` (Xpressions Flora), `XFSS` (Sojanmi Spring)
- Each new project has counterparty, primary contract (with external_contract_id, payment_terms, dates), and 2 contract lines (metered + available)
- Ancillary contracts (id=53,54) remain on XFAB
- Total projects: 32 → 35

**ZL02 Contracts (Step 2):**
- Added 4 SAGE contracts under existing ZL02 project: CONCBCH0-2025-00002 (RENTAL/USD), CONCBCH0-2025-00003 (OM/USD), CONCBCH0-2025-00004 (RENTAL/USD), CONSLL02-2025-00003 (OM/SLE)

---

### Migration 055 - Step 4: Billing Product & Tariff Structure (2026-03-08)

**Migration:** `database/migrations/055_step4_billing_product_tariff_structure.sql`

**Description:** CBE Data Population Step 4. Links all 114 contract lines to billing products, creates contract-to-billing-product junctions, and inserts clause_tariff placeholders for all primary contracts.

**Section A — contract_type_id fixes:**
- Fixed NULL `contract_type_id` on 9 contracts: NBL01→PPA, LOI01→ESA, IVL01 OM→OTHER, TWG01 OM→OTHER, XFBV/XFL01/XFSS→PPA, ZL02 contracts→LEASE/OTHER

**Section B — contract_line.billing_product_id:**
- Linked all 114 contract lines to canonical `billing_product` entries using country-specific product codes (GHREVS for Ghana, KEREVS for Kenya, NIREVS for Nigeria, EGREVS for Egypt, ENER for generic, MOREVS for Mozambique, MAREVS003 for BESS)

**Section C — contract_billing_product junction:**
- Inserted 72 new junction records (10 pre-existing from pilot)
- Set `is_primary = true` on 36 contracts (one primary per contract)
- Total: 82 junction records across 36 contracts

**Section D — clause_tariff placeholders:**
- Inserted 36 new `clause_tariff` entries (6 pre-existing from pilot)
- `base_rate = NULL` for all new entries (populated in Step 7/9)
- Energy sale type breakdown: FIXED_SOLAR (20), NOT_ENERGY_SALES (10), FLOATING_GRID (5), FLOATING_GRID_GENERATOR (1), FLOATING_GENERATOR (1), NULL/placeholder (5)
- Escalation rates populated where known from PO Summary

**Verification:** 5/5 gates passed.

---

### Migration 056 - billing_tax_rule Project Scope (2026-03-08)

**Migration:** `database/migrations/056_billing_tax_rule_project_scope.sql`

**Description:** Adds `project_id` column to `billing_tax_rule` for project-specific tax overrides. Resolves Section 9.3 open decision (Option A): `NULL project_id` = country default, non-NULL = project-specific override.

**Modified Table: `billing_tax_rule`**
| Column | Type | Description |
|--------|------|-------------|
| `project_id` | BIGINT FK → `project(id)` | NULL = country default, non-NULL = project-specific override |

**Constraint Changes:**
- Dropped and recreated `billing_tax_rule_no_overlap` GiST exclusion to include `COALESCE(project_id, 0)`, allowing project-specific rules to coexist with country defaults
- Dropped and recreated `idx_billing_tax_rule_lookup` to include `project_id`

**Application Impact:**
- Billing API lookup should check project-specific rule first, then fall back to country default (`project_id IS NULL`)
- Step 8 script populates country defaults + project-specific overrides from invoice PDF extraction

---

### Migration 058 - Sage Business Partner Import + Amendment Date Cleanup (2026-03-14)

**Migration:** `database/migrations/058_sage_bp_import.sql`

**Description:** Adds `sage_bp_code` to counterparty, imports all Sage business partners (offtakers, internal entities, takeon placeholders), and consolidates redundant `amendment_date`/`effective_date` columns on `contract_amendment`.

**Sections 1–6:** Sage BP import (see migration file for details).

**Section 7 — Merge `amendment_date` into `effective_date`:**

Consolidates redundant columns on `contract_amendment`. `amendment_date` held the signing date (17/20 rows populated) while `effective_date` was NULL for 19/20 rows — they represent the same concept.

| Change | Detail |
|--------|--------|
| `effective_date` | Backfilled from `amendment_date` where previously NULL (17 rows) |
| `amendment_date` | **Dropped** — redundant with `effective_date` |

**Application Changes:**
- `python-backend/api/entities.py` — Removed `ca.amendment_date` from amendments CTE
- `app/projects/components/ProjectOverviewTab.tsx` — Changed `a.amendment_date` → `a.effective_date` for amendment date display
- `add_source_workflow_columns.py` — Removed `amendment_date` mapping entry, updated `effective_date` description

**Shared Utility (new):**
- `python-backend/db/lookup_service.py` — Added `get_project_by_sage_id()` and `get_primary_contract_by_sage_id()` methods to `LookupService` for reusable sage_id → project/contract resolution
- `python-backend/scripts/step11_ppa_parsing.py` — Refactored local `get_contract_id_by_sage()` to delegate to `LookupService.get_primary_contract_by_sage_id()`

---

### Migration 059 - Tariff Classification Taxonomy Restructure (2026-03-15)

**Migration:** `database/migrations/059_tariff_taxonomy_restructure.sql`

**Description:** Separates three orthogonal classification dimensions on `clause_tariff` that were previously conflated. All three lookup tables (`tariff_type`, `energy_sale_type`, `escalation_type`) are repurposed with clean semantics. Only `clause_tariff` references these tables (~60 rows).

**Phase 1 — Expand `escalation_type` (Pricing Mechanism + Escalation):**

Flat codes (no `parent_id` hierarchy) — grouped by `IN (...)` in queries when needed:

| Change | Detail |
|--------|--------|
| `FLOATING_GRID` | New flat code — grid utility tariff discount (MRP sub-type) |
| `FLOATING_GENERATOR` | New flat code — diesel/gas generator cost discount (MRP sub-type) |
| `FLOATING_GRID_GENERATOR` | New flat code — combined grid + generator baseline (MRP sub-type) |
| `NOT_ENERGY_SALES` | New code — non-energy arrangements (lease, O&M) |

MRP-family grouping convention: `esc.code IN ('REBASED_MARKET_PRICE', 'FLOATING_GRID', 'FLOATING_GENERATOR', 'FLOATING_GRID_GENERATOR')`

**Phase 2 — Migrate `clause_tariff.escalation_type_id`:**
- Rows with `energy_sale_type` = FLOATING_* moved to corresponding `escalation_type` flat codes (~7 rows)
- Rows with `energy_sale_type` = NOT_ENERGY_SALES moved to `escalation_type` NOT_ENERGY_SALES (~12 rows)

**Phase 3 — Repurpose `energy_sale_type` → Revenue/Product Type (what is being sold):**

Old values (FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, NOT_ENERGY_SALES, ENERGY, CAPACITY) deleted. New values:

| Code | Name |
|------|------|
| ENERGY_SALES | Energy Sales |
| EQUIPMENT_RENTAL_LEASE | Equipment Rental/Lease/Boot |
| LOAN | Loan |
| BESS_LEASE | Battery Lease (BESS) |
| ENERGY_AS_SERVICE | Energy as a Service |
| OTHER_SERVICE | Other |
| NOT_APPLICABLE | N/A |

Source: PO Summary col D "Revenue Type"

**Phase 4 — Repurpose `tariff_type` → Offtake/Billing Model (how the buyer pays):**

Old values (ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, etc.) deleted. New values:

| Code | Name |
|------|------|
| TAKE_OR_PAY | Take or Pay |
| TAKE_AND_PAY | Take and Pay |
| MINIMUM_OFFTAKE | Minimum Offtake |
| FINANCE_LEASE | Finance Lease |
| OPERATING_LEASE | Operating Lease |
| NOT_APPLICABLE | N/A |

Source: PO Summary col E "Energy Sale Type" (offtake model)

**Phase 5 — Fix remaining NULL `escalation_type_id`:** Populated from PO Summary col AD "Indexation Rate/Method".

**Phase 6 — Drop `parent_id`:** Removes `parent_id` column from `escalation_type` if it exists (cleanup from earlier draft).

**Application Changes:**
- `python-backend/services/tariff/tariff_bridge.py` — Merged FLOATING_* codes into `ESCALATION_TYPE_MAP`, removed `ENERGY_SALE_TYPE_MAP` and `TARIFF_TYPE_TO_ENERGY_SALE` constants, `energy_sale_type_id` defaults to ENERGY_SALES for PPA parsing, `tariff_type_id` set to NULL (populated from PO Summary)
- `python-backend/services/tariff/rebased_market_price_engine.py` — Updated `_fetch_tariff()` query to use `esc.code IN ('REBASED_MARKET_PRICE', 'FLOATING_GRID', 'FLOATING_GENERATOR', 'FLOATING_GRID_GENERATOR')` instead of `= 'REBASED_MARKET_PRICE'`
- `app/projects/components/PricingTariffsTab.tsx` — Updated `isRebased` checks to use module-level `REBASED_CODES` Set with all MRP-family codes
- `add_source_workflow_columns.py` — Updated MAPPING and FK_TARGET_POPULATION entries for `tariff_type_id`, `energy_sale_type_id`, `escalation_type_id`, `meter_id`

---

### v10.16 - 2026-03-15 (tariff_rate Schema Cleanup)

**Description:** Schema cleanup for `tariff_rate`: add `billing_period_id` FK (aligns with 6 other tables), drop always-NULL `fx_rate_hard_id`, rename `fx_rate_local_id` → `exchange_rate_id`.

**Migrations:**
- `database/migrations/060_tariff_rate_billing_period.sql`

**tariff_rate changes:**
- **Added:** `billing_period_id` BIGINT FK → `billing_period(id)` — backfilled from `billing_month` for existing monthly rows
- **Added:** Partial index `idx_tariff_rate_billing_period` on `billing_period_id WHERE billing_period_id IS NOT NULL`
- **Dropped:** `fx_rate_hard_id` — always NULL everywhere, hard currency is always USD
- **Renamed:** `fx_rate_local_id` → `exchange_rate_id` — clearer name for the surviving FX column

**Application Changes:**
- `python-backend/scripts/step10b_tariff_rate_population.py` — Added `billing_period_id` to monthly INSERT, renamed `fx_rate_local_id` → `exchange_rate_id`
- `python-backend/services/tariff/rebased_market_price_engine.py` — Added `billing_period_id` to monthly INSERT/UPSERT, removed `fx_rate_hard_id`, renamed `fx_rate_local_id` → `exchange_rate_id` in annual + monthly INSERTs and ON CONFLICT clauses
- `python-backend/api/entities.py` — Renamed JOIN column `tr.fx_rate_local_id` → `tr.exchange_rate_id`
- `python-backend/api/spreadsheet.py` — Updated protected columns list: removed `fx_rate_hard_id`, `fx_rate_local_id`; column already listed as `exchange_rate_id`

---

### v10.17 - 2026-03-15 (Live Data Pipeline & Billing Cycle Services)

**Description:** Application-layer implementation of the live data pipeline: billing cycle orchestrator, compute services, reference price ingestion, and generic billing adapter. No schema migration — all changes are in Python services, API endpoints, and frontend.

**Migrations:** None — application code only.

**New Python Packages/Modules:**
- `python-backend/services/billing/__init__.py` — billing compute services package
- `python-backend/services/billing/tariff_rate_service.py` — dispatches tariff rate generation per escalation type (deterministic → `RatePeriodGenerator`, floating → `RebasedMarketPriceEngine`, CPI → blocked)
- `python-backend/services/billing/performance_service.py` — computes `plant_performance` from existing `meter_aggregate` + `production_forecast` data
- `python-backend/services/billing/invoice_service.py` — extracted invoice generation logic from `api/billing.py`; now single source of truth for expected invoice writes
- `python-backend/services/billing/billing_cycle_orchestrator.py` — models monthly billing as dependency graph: verify inputs → compute (parallel) → generate output
- `python-backend/models/billing_cycle.py` — request/response models (`GenerateTariffRatesRequest`, `ComputePerformanceRequest`, `RunCycleRequest`, `BillingCycleResult`)
- `python-backend/models/reference_price_ingest.py` — canonical model for reference price external ingestion (`ReferencePriceEntry`, `ReferencePriceBatchRequest`)
- `data-ingestion/processing/adapters/generic_billing_adapter.py` — passthrough adapter for non-CBE clients sending canonical meter_aggregate fields

**New API Endpoints:**
- `POST /api/ingest/reference-prices` — external MRP ingestion with API-key auth, `reference_prices` scope; resolves `project_sage_id` → `project_id`, computes `calculated_mrp_per_kwh`, derives `operating_year` from COD, writes `period_end`
- `POST /api/projects/{id}/billing/generate-tariff-rates` — tariff rate generation per billing month
- `POST /api/projects/{id}/billing/run-cycle` — full billing cycle orchestration with step-by-step status
- `POST /api/projects/{id}/plant-performance/compute` — automated performance computation from meter data

**Modified Modules:**
- `python-backend/models/ingestion.py` — added `GENERIC` to `SourceType`, `REFERENCE_PRICES` to `IngestionScope`
- `python-backend/api/billing.py` — added tariff-rate and run-cycle endpoints; existing `generate-expected-invoice` handler refactored to delegate to `InvoiceService` (removed ~500 lines of inline SQL)
- `python-backend/api/performance.py` — added compute endpoint
- `python-backend/api/ingest.py` — added reference-prices endpoint
- `data-ingestion/processing/adapters/__init__.py` — expanded registry with `GenericBillingAdapter`, default fallback changed from CBE to Generic

**Frontend Changes:**
- `app/client-setup/components/GenerateAPIKeyDialog.tsx` — added `reference_prices` and `invoice_export` to available scopes
- `app/client-setup/components/OnboardingSummary.tsx` — added `reference_prices` endpoint to onboarding text

**Documentation Changes:**
- `data-ingestion/sources/snowflake/CLIENT_INSTRUCTIONS.md` — added Sections 3 (FX Rates) and 4 (Reference Prices / MRP) with full JSON schemas, examples, field references
- `CBE_data_extracts/CBE_DATA_POPULATION_WORKFLOW.md` — added Part B (lifecycle categories, dependency graph, API reference, recompute rules, adapter framework, ops actuals data path)
- `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md` — added Section 32 (live pipeline architecture, lifecycle classification, compute services, orchestrator prerequisite logic)
- `data-ingestion/docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md` — added Section 17 (live pipeline, adapter framework, billing cycle orchestrator, reference price endpoint)

**Key Design Decisions:**
- Orchestrator prerequisite gates are **per tariff family**: deterministic tariffs never block on FX/MRP
- `plant_performance` and `expected_invoice` are parallel branches — performance failure does not block invoice
- `actual_availability_pct` is a `plant_performance` column, not `meter_aggregate` — the generic adapter routes it to `source_metadata`
- `InvoiceService` uses `with get_db_connection()` for standalone calls and accepts pre-opened `conn` for transaction sharing

---

### v10.18 - 2026-03-17 (oy_start_date as Canonical OY Anchor)

**Description:** Made `clause_tariff.logic_parameters.oy_start_date` the single canonical source for Operating Year (OY) computation across all 10 code paths. Previously, OY was derived from `project.cod_date` with an optional override from `oy_start_date`; now all paths read `oy_start_date` directly. This fixes LOI01 where OY must be based on Transfer Date (2019-10-31), not COD (2019-03-01).

**No new migration** — data-only population via script + application-layer code changes.

**Population Script:**
- `python-backend/scripts/populate_oy_start_date.py` — sets `oy_start_date = project.cod_date` for all clause_tariff records where it was NULL; skips LOI01 (already set to Transfer Date) and projects without COD (BNT01, XFBV, XFL01, XFSS)
- Result: 36 clause_tariff rows updated, 2 skipped (LOI01)

**Modified Modules (6 — simplified COALESCE to direct read):**
- `python-backend/api/submissions.py` — `_determine_operating_year()`: queries only `oy_start_date`, removed `cod_date` fallback
- `python-backend/api/mrp.py` — bulk upsert OY calculation: same
- `python-backend/api/performance.py` — project metadata query: reads `oy_start_date` as canonical anchor
- `python-backend/services/mrp/extraction_service.py` — `_compute_operating_year()`: same
- `python-backend/services/billing/tariff_rate_service.py` — `_derive_operating_year()`: same
- `python-backend/services/billing/performance_service.py` — inline OY compute: same

**Modified Modules (4 — added oy_start_date read):**
- `python-backend/api/ingest.py` — meter data ingestion: query now JOINs clause_tariff, resolves `oy_start_date` per sage_id
- `python-backend/scripts/extend_forecasts.py` — project query JOINs clause_tariff, passes `oy_start_date` to `_compute_operating_year`
- `python-backend/scripts/populate_mrp_from_excel.py` — `resolve_project()` extracts `oy_anchor` from logic_parameters, `compute_operating_year()` uses it
- `python-backend/scripts/step10b_tariff_rate_population.py` — fetches `oy_start_date` in query, `_resolve_valid_from()` uses it as highest-priority source

**Key Design Decision:**
- `oy_start_date` is now a **required** field for OY computation — all paths return default OY=1 if missing rather than falling back to `cod_date`
- For most projects `oy_start_date == cod_date`; for LOI01 it equals Transfer Date (2019-10-31)
- Projects without COD (and thus no `oy_start_date`) are unaffected — they already defaulted to OY=1

---

### v10.19 - 2026-03-18 (Tariff Formula — Pricing & Tariff Extraction)

**Description:** Added `tariff_formula` table for storing decomposed mathematical formulas from PPA/SSA pricing sections as structured computation graphs. Populated by Step 11P (Pricing & Tariff Extraction Pipeline).

**Migration:**
- `database/migrations/062_tariff_formula.sql`

**New Table: `tariff_formula`**
- `id` BIGSERIAL PRIMARY KEY
- `clause_tariff_id` BIGINT FK → clause_tariff(id) ON DELETE CASCADE
- `organization_id` BIGINT FK → organization(id)
- `formula_name` VARCHAR(255) — human-readable name
- `formula_text` TEXT — mathematical expression
- `formula_type` VARCHAR(50) NOT NULL — e.g. 'MRP_BOUNDED', 'CPI_ESCALATION', 'ENERGY_OUTPUT'
- `variables` JSONB — array of {symbol, role, variable_type, description, unit, maps_to}
- `operations` JSONB — array of operations (MIN, MAX, MULTIPLY, IF, SUM, etc.)
- `conditions` JSONB — array of conditions with if/then/else branching
- `section_ref` VARCHAR(255) — contract section reference
- `extraction_confidence` NUMERIC(3,2)
- `extraction_metadata` JSONB
- `version` INTEGER DEFAULT 1, `is_current` BOOLEAN DEFAULT true
- `created_at` TIMESTAMPTZ

**Indexes:**
- `idx_tariff_formula_clause_tariff` — clause_tariff lookup
- `idx_tariff_formula_org` — organization lookup
- `idx_tariff_formula_type` — formula_type lookup
**Formula Type Taxonomy (14 types across 5 categories):**
- **pricing:** MRP_BOUNDED, MRP_CALCULATION
- **escalation:** PERCENTAGE_ESCALATION, FIXED_ESCALATION, CPI_ESCALATION, FLOOR_CEILING_ESCALATION
- **energy:** ENERGY_OUTPUT, DEEMED_ENERGY, ENERGY_DEGRADATION, ENERGY_GUARANTEE, ENERGY_MULTIPHASE
- **performance:** SHORTFALL_PAYMENT, TAKE_OR_PAY
- **billing:** FX_CONVERSION

**Design Decisions:**
- `formula_type` is VARCHAR, not ENUM — new types can be added without migration
- Validation enforced at Pydantic model layer (`models/pricing.py`)
- Per-project variations: each project gets its own rows with different variables JSONB
- Formula dependencies captured via `maps_to` on variables (e.g., `tariff_formula.DEEMED_ENERGY`)
- No additional FKs beyond `clause_tariff_id` — variable-level `maps_to` captures relationships

**Pipeline Files (Compiler Architecture):**
- `python-backend/services/pricing/resolver_registry.py` — Semantic variable bindings (56 bindings; 12 added for Rwanda wheeling)
- `python-backend/services/pricing/formula_components.py` — Composable formula templates (23 components, 9 compositions; 7 added for RWANDA_WHEELING)
- `python-backend/services/pricing/contract_classifier.py` — Contract type classification (Rwanda wheeling detection added)
- `python-backend/services/pricing/template_resolver.py` — Symbol → binding matching
- `python-backend/services/pricing/formula_compiler.py` — Compile to runtime + display + rates
- `python-backend/services/pricing/strict_validator.py` — Hard-stop validation + quarantine
- `python-backend/services/pricing/pricing_extractor.py` — Claude API raw extraction
- `python-backend/services/prompts/pricing_extraction_prompt.py` — Claude prompt (no DB mapping)
- `python-backend/scripts/step11p_pricing_extraction.py` — Orchestrator

---

### v12.1 - 2026-03-19 (Role Expansion & Team Management)

**Description:** Expanded role system from `admin/staff` to `admin/approver/editor/viewer`, added invite lifecycle fields, enabled RLS on the `role` table, and added audit action types for team management.

**Migration:** `database/migrations/063_role_expansion.sql`

**Changes to `role` table:**
- **Modified constraint:** `role_role_type_check` now allows `admin`, `approver`, `editor`, `viewer` (was `admin`, `staff`)
- **Migrated data:** existing `staff` rows updated to `editor`
- **New columns:** `department VARCHAR`, `job_title VARCHAR`, `status VARCHAR NOT NULL DEFAULT 'active'` (with CHECK: `invited`, `active`, `suspended`, `deactivated`), `invited_by UUID`, `invited_at TIMESTAMPTZ`, `accepted_at TIMESTAMPTZ`, `deactivated_at TIMESTAMPTZ`
- **RLS enabled:** Three policies — `role_self_read` (user reads own row), `role_admin_read` (admin reads org), `role_admin_write` (admin writes org)

**Extended enum: `audit_action_type`**
- `MEMBER_INVITED`, `MEMBER_ROLE_CHANGED`, `MEMBER_DEACTIVATED`, `MEMBER_REACTIVATED`, `INVITE_ACCEPTED`

**New API endpoints:** `python-backend/api/team.py`
- `GET /api/team/me` — current user's membership
- `GET /api/team/members` — list org members (admin only)
- `POST /api/team/invite` — invite new member (admin only)
- `PATCH /api/team/members/{id}` — update member (admin only)
- `POST /api/team/members/{id}/deactivate` — deactivate (admin only)
- `POST /api/team/members/{id}/reactivate` — reactivate (admin only)

**Authorization changes:**
- `require_write_access()` now allows `admin`, `approver`, `editor` (removed stale `owner`)
- New: `require_approve_access()` — `admin`, `approver` only
- New: `require_admin()` — `admin` only
- MRP verify endpoint upgraded from `require_write_access` to `require_approve_access`
- Email ingest approve endpoint now requires `require_approve_access`

**Frontend changes:**
- New page: `/settings/team` — team management UI
- Browser `role` table queries replaced with `/api/team/me` endpoint (3 files)
- `/settings` added to protected paths in middleware

---

### v12.2 - 2026-03-20 (Change Request Workflow)

**Description:** Two-step edit/approval workflow for financially sensitive fields. Editors propose changes → approvers review and apply/reject. Non-designated fields continue with immediate save.

**Migration:** `database/migrations/065_change_request.sql`

**New enum: `change_request_status`**
- `pending`, `conflicted`, `approved`, `rejected`, `cancelled`, `superseded`

**New table: `change_request`**
- Tracks proposed field changes with old/new values (JSONB), requester, assigned approver, reviewer, conflict detection via `base_updated_at`
- Unique index prevents duplicate pending requests for same field
- Immutability trigger on terminal states
- `auto_approved` flag for admin/approver audit trail

**Modified table: `project`**
- Added `default_approver_id UUID` column

**Extended enum: `audit_action_type`**
- `CHANGE_REQUESTED`, `CHANGE_APPROVED`, `CHANGE_REJECTED`

**New backend files:**
- `python-backend/services/approval_config.py` — policy registry defining which fields require approval
- `python-backend/api/change_requests.py` — CRUD + approve/reject/cancel/assign endpoints

**Modified: `python-backend/api/entities.py`**
- `_execute_patch()` gains `auth` parameter and approval-check branch
- Editor edits on designated fields create `change_request` rows instead of applying
- Admin/approver edits auto-approve with audit trail
- All ~10 PATCH endpoints now pass `auth=auth`

---

### v12.3 - 2026-03-20 (Swap E_metered / Energy Output column mappings)

**Description:** Data-only migration swapping `meter_aggregate` column mappings in `tariff_formula.variables` JSONB. E_metered (raw metered) now maps to `energy_kwh`; Energy Output (confirmed billing) now maps to `total_production`.

**Migration:** `database/migrations/066_swap_energy_column_mappings.sql`

**Changes to `tariff_formula.variables` (JSONB data only, no schema change):**
- `monthly_metered_energy` binding: `maps_to` changed from `meter_aggregate.total_production` → `meter_aggregate.energy_kwh`
- `annual_metered_energy` binding: same swap
- `billing_energy_output` binding: `maps_to` changed from `meter_aggregate.energy_kwh` → `meter_aggregate.total_production`
- `annual_billing_energy_output` binding: same swap (purely-annual ENERGY_OUTPUT formulas only)
- PAYMENT_CALCULATION formulas: old `monthly_metered_energy` Energy Output inputs upgraded to `billing_energy_output` binding

**Updated code files:**
- `python-backend/services/pricing/resolver_registry.py` — swapped column in 4 bindings
- `python-backend/services/pricing/formula_components.py` — updated binding_key references in payment and energy output templates
- `contract-digitization/docs/IMPLEMENTATION_GUIDE_PRICING_TARIFF_EXTRACTION.md` — updated all column references and binding table

**Phase 1 designated fields:**
- `exchange_rate.rate`
- `production_guarantee.guaranteed_kwh`, `p50_annual_kwh`

**Frontend:**
- `EditableCell.tsx` handles `outcome: 'submitted'` with amber toast
- New `PendingChangesPanel.tsx` slide-over for reviewing/approving changes
- Dashboard header shows pending badge count, edit toggle hidden for viewers

---

### v12.4 - 2026-03-21 (Approval Phase 3 — Endpoint-Level Approval for Write Paths)

**Description:** Extends the two-step approval workflow from inline field edits (Phase 1-2) to POST endpoints that create/upsert rows. Editors submitting billing entries, performance data, or MRP rates now go through the same approval queue. No schema migration needed — uses existing `change_request` table with `field_name = '*'` convention for full-row proposals and `target_id = 0` for rows that don't exist yet.

**No migration required.** Existing `change_request` table supports this via conventions:
- `field_name = '*'` — full-row proposal (not a single field edit)
- `target_id = 0` — row will be created on approve
- `new_value` — full JSONB payload of the proposed entry
- `old_value = null` — new row, no previous value

**New policies in `approval_config.py`:**
- `billing_entry` — Monthly Billing Entry (`POST /projects/{pid}/monthly-billing/manual`)
- `performance_entry` — Plant Performance Entry (`POST /projects/{pid}/plant-performance/manual`)
- `mrp_manual_entry` — Manual MRP Rate Entry (`POST /projects/{pid}/mrp-manual`)
- `mrp_upload` — MRP Invoice Upload (`POST /projects/{pid}/mrp-upload`)

**New file: `python-backend/services/approval_service.py`**
- `check_approval_required(auth, policy_key)` — returns True if editor + policy exists
- `create_row_change_request(...)` — creates full-row change_request
- `create_auto_approved_row_record(...)` — audit trail for admin/approver

**Modified: `python-backend/api/billing.py`**
- Approval check at top of `add_manual_entry()`
- Core logic extracted to `_apply_billing_entry()` for replay on approve

**Modified: `python-backend/api/performance.py`**
- Approval check at top of `add_performance_manual()`
- Core logic extracted to `_apply_performance_entry()` for replay on approve

**Modified: `python-backend/api/mrp.py`**
- Approval check on both `admin_mrp_upload()` and `manual_mrp_entry()`
- Core logic extracted to `_apply_mrp_upload()` and `_apply_mrp_manual()`
- MRP upload: S3 storage is immediate (not sensitive), only DB write deferred

**Modified: `python-backend/api/change_requests.py`**
- Added `_apply_row_change()` dispatcher for `field_name = '*'` approvals
- Approve endpoint branches: row proposals call dispatcher, single-field changes use existing UPDATE
- Four-eyes check uses `find_policy_by_key()` for endpoint-level policies
- MRP upload approve: downloads file from S3 and re-extracts

**Frontend:**
- `MonthlyBillingTab.tsx` — both inline edit and add-row handlers show amber toast on approval
- `PlantPerformanceTab.tsx` — same pattern for both entry points
- `MRPSection.tsx` — upload and manual entry handlers show amber toast on approval
- `PendingChangesPanel.tsx` — full-row proposals (`field_name = '*'`) render as key-value list instead of old→new diff; subtitle shows "new entry" instead of "ID: 0"

---

### v0.66 - 2026-03-22 (Loan Repayment & Rental/Ancillary Charge Tables)

**Description:** Normalizes loan amortization schedules and rental/BESS/O&M charge data from `project.technical_specs` JSONB into proper relational tables. Parallels the existing `tariff_rate` pattern — new tables record period-level data linked to `clause_tariff` rows. Also renames `tariff_rate.contract_year` → `operating_year` for consistency.

**Migration:** `database/migrations/066_loan_and_recurring_charge.sql`

**Renamed Column: `tariff_rate.contract_year` → `operating_year`**
- Aligns with `operating_year` convention used on `loan_repayment`, `rental_ancillary_charge`, and throughout `logic_parameters` (oy_definition, oy_start_date)
- PostgreSQL RENAME COLUMN auto-updates indexes and constraints
- All backend services, scripts, frontend, and database scripts updated

**New Table: `loan_repayment`**
- Amortization schedule rows per loan `clause_tariff`
- Unified columns: `scheduled_amount` (total repayment), `principal_amount`, `interest_amount`, `closing_balance`
- Unique on `(clause_tariff_id, billing_month)` — follows `tariff_rate` pattern
- Data quality tracking: `data_quality` column (`ok`, `quarantined`, `needs_review`)
- Provenance: `source`, `source_row_ref`, `source_metadata` JSONB

**New Table: `rental_ancillary_charge`**
- Monthly charge rows per non-energy `clause_tariff` (BESS, rental, O&M, lease)
- Primary parent: `clause_tariff_id` (terms), reconciliation parent: `contract_line_id` (billing grain)
- Charge type derived from parent `clause_tariff.energy_sale_type_id` (no separate ENUM — BESS_LEASE, EQUIPMENT_RENTAL_LEASE, OTHER_SERVICE, etc.)
- Unique on `(clause_tariff_id, contract_line_id, billing_month)` — handles projects with multiple same-type charge lines
- `scheduled_amount` records contractual obligation; reconciliation with invoices via `invoice_line_item_id` FK and existing `expected_invoice_line_item.clause_tariff_id` joins

**Loan terms stored as clause_tariff rows:**
- No separate `loan_schedule` table — loan terms (opening_balance, interest_rate, loan_variant) stored in `clause_tariff.logic_parameters` JSONB with `energy_sale_type = LOAN`, `tariff_type = FINANCE_LEASE`
- Population script creates new clause_tariff rows for ZL02, GC001, iSAT01

**clause_tariff backfills:**
- Empty non-energy clause_tariff rows (AMP01 ct#65, LOI01 ct#14, TWG01 ct#31) backfilled with `base_rate` and `logic_parameters` from `technical_specs` values

**Population script:** `python-backend/scripts/step7h_loan_rental_normalize.py`
- Data quality quarantine: ZL02 corrupt date_paid → needs_review, AMP01 placeholder amounts → skipped, AR01 outlier amounts → quarantined
- Report: `python-backend/reports/cbe-population/step7h_YYYY-MM-DD.json`

---

### v12.5 - 2026-03-23 (Invoice Engine Audit & Tax Rule Corrections)

**Description:** Full line-item audit of 29 invoice PDFs against DB records. Fixed critical bugs in the expected invoice generation engine (tax rule resolution, basis calculation) and corrected tax rule data for 7 projects. Added `deduction` enum value to `energy_category` for negative invoice lines (e.g., Sourced Energy on NBL projects). Added `available_energy_discount` config for XFlora projects.

**Modified migration:** `database/migrations/041_multi_meter_billing_and_performance.sql`
- `energy_category` enum: added `'deduction'` value (metered, available, test, **deduction**)
- Comment updated to document all four values

**Engine fixes (`python-backend/services/billing/invoice_service.py`):**

1. **Tax rule resolution query** — was ignoring `project_id`, returning non-deterministic results when multiple rules existed for the same country. Now does two-step lookup: project-specific override first (`project_id = ?`), then country default (`project_id IS NULL`)
2. **`_resolve_basis()`** — added `invoice_total` parameter and `grand_total`/`invoice_total` basis support. Previously any unrecognized basis silently fell back to `energy_subtotal`
3. **Deduction line handling** — new block processes `energy_category = 'deduction'` contract lines, emitting `LD_CREDIT` type items with `amount_sign = -1` and negative quantity/amount
4. **Description precision** — VAT and withholding line descriptions now use `.1f%` format (e.g., "7.5%" instead of "7%")

**Tax rule data corrections (applied directly, no migration file):**

| Action | IDs | Projects | Detail |
|--------|-----|----------|--------|
| Deactivated | 21, 10, 11, 12, 13 | MB01, MP02, NC02, UTK01, XFSS | KE overrides incorrectly removed WHVAT 2%. Now fall back to KE Standard |
| Fixed basis | 19 | MOH01 | WHT `applies_to` → `energy_subtotal`, WHVAT → `subtotal_after_levies` (was `grand_total` for both) |
| Fixed rate+basis | 20 | XFBV | WHVAT rate 1.72% → 2%, basis `grand_total` → `energy_subtotal` |

**Tariff config updates (clause_tariff.logic_parameters):**

| Tariff | Project | Added Key | Value |
|--------|---------|-----------|-------|
| ct#34 | XFAB | `available_energy_discount` | `{threshold_pct: 0.05}` |
| ct#35 | XFBV | `available_energy_discount` | `{threshold_pct: 0.05}` |
| ct#55 | XFL01 | `available_energy_discount` | `{threshold_pct: 0.05}` |
| ct#60 | XFSS | `available_energy_discount` | `{threshold_pct: 0.05}` |

**New data: NBL Sourced Energy deduction lines**

| Project | Meter | Contract Line | energy_category |
|---------|-------|--------------|-----------------|
| NBL01 | meter#109 "Sourced Energy" | cl#295 (line 8000) | `deduction` |
| NBL02 | meter#110 "Sourced Energy" | cl#296 (line 3000) | `deduction` |

When `meter_aggregate` data is ingested for these meters (grid-sourced kWh), the engine emits a negative `LD_CREDIT` line at the tariff rate — matching the "Sourced Energy" deduction on actual invoices.

**Step 8 dual-read transition:** `python-backend/scripts/step8_invoice_calibration.py`
- `_check_loan_rental()` reads normalized tables first, falls back to `technical_specs` JSONB
- `technical_specs` JSONB left intact for backward compatibility

---

### v0.67 - 2026-03-22 (QMM01 Tariff & Billing Cross-Validation Remediation)

**Description:** Fixes gaps found during cross-validation of QMM01 tariff_formula rows against invoice SINQMM012512028 (Dec 2025). Populates `contract_line.clause_tariff_id` for active lines, fixes billing engine tariff resolution (cross-join → lateral join), corrects BESS base rate and metadata, and adds 2 missing payment formulas.

**Migration:** `database/migrations/067_qmm01_tariff_billing_remediation.sql`

**Data fixes:**
- `contract_line.clause_tariff_id` populated for 4 active lines (CL 258,260,261 → ct 32; CL 262 → ct 33)
- `clause_tariff` id=33: base_rate 57,878 → 115,756 (Phase 1+2 combined BESS), unit → 'USD/month', escalation_type_id 23 → 8
- `clause_tariff` id=32: unit → 'USD/kWh'
- `tariff_formula` 266,272: N variable maps_to fixed to derived year offset

**New tariff_formula rows:**
- Available Energy Payment Calculation (PAYMENT_CALCULATION, ct 32) — `Available_Payment = Solar_Tariff × DE`
- BESS Capacity Payment Calculation (PAYMENT_CALCULATION, ct 33) — `BESS_Payment = Charge_N × FX_Rate`

**Code changes:**
- `python-backend/api/billing.py`: Added `MAREVS003` to `FIXED_FEE_PRODUCT_CODES` (BESS is monthly, not kWh-based)
- `python-backend/api/billing.py`: Replaced clause_tariff cross-join with lateral join through `contract_line.clause_tariff_id` for correct product→tariff resolution

---

### v12.4 - 2026-03-24 (Multi-Approver Escalation System)

**Description:** Added multi-step approval chains and threshold-based escalation rules to the change request workflow. Organizations can now define ordered approval chains with multiple steps and configure escalation rules that select the appropriate chain based on conditions (e.g., amount thresholds). The `change_request` table is extended to track progress through multi-step chains.

**Migration:** `database/migrations/067_approval_escalation.sql`

**Renamed column on `change_request`:**
- `policy_key` → `change_type` — clearer naming for the type of change being requested

**New Table: `approval_chain`**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id` - BIGINT (org-scoped)
- `approval_chain_type` - TEXT (chain identifier, grouped with org)
- `step_order` - INTEGER (position in the chain)
- `step_name` - TEXT (human-readable step label)
- `assigned_approver_id` - UUID (specific approver for this step)
- `approver_role_type` - TEXT (role-based assignment alternative)
- `approver_department` - TEXT (department-based assignment alternative)
- `allow_self_approve` - BOOLEAN (four-eyes override per step)
- `is_active` - BOOLEAN
- `created_at` - TIMESTAMPTZ

Each row represents one step in a multi-step approval chain. Steps are grouped by `(organization_id, approval_chain_type)` and ordered by `step_order`.

**New Table: `approval_escalation_rule`**
- `id` - BIGSERIAL PRIMARY KEY
- `organization_id` - BIGINT (org-scoped)
- `change_type` - TEXT (matches `change_request.change_type`)
- `name` - TEXT (human-readable rule name)
- `priority` - INTEGER (evaluation order, lower = higher priority)
- `condition_type` - TEXT (type of condition to evaluate)
- `condition_field` - TEXT (field to inspect)
- `condition_operator` - TEXT (comparison operator)
- `condition_value` - JSONB (threshold or match value)
- `approval_chain_type` - TEXT (chain to use when rule matches)
- `is_active` - BOOLEAN
- `created_at` - TIMESTAMPTZ
- `updated_at` - TIMESTAMPTZ

Rules are evaluated by priority for a given `change_type`. The first matching rule determines which `approval_chain_type` is used for the change request.

**New columns on `change_request`:**
- `approval_chain_type` - TEXT (selected approval chain for this request)
- `current_step_order` - INTEGER DEFAULT 1 (current position in the chain)
- `total_steps` - INTEGER DEFAULT 1 (total steps in the chain)
- `approval_steps` - JSONB (audit log of each step's outcome: approver, timestamp, decision)

---
