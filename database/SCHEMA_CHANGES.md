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
- `email_schedule_type`: `invoice_reminder`, `invoice_initial`, `invoice_escalation`, `compliance_alert`, `meter_data_missing`, `report_ready`, `custom`
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

**email_log** - Every email sent
- `id`, `organization_id`, `email_notification_schedule_id`, `email_template_id`
- `recipient_email`, `recipient_name`, `subject`, `email_status`
- `ses_message_id`, `reminder_count`, `invoice_header_id`, `submission_token_id`
- `error_message`, `bounce_type`, `sent_at`, `delivered_at`, `bounced_at`

**submission_token** - Secure tokens for external data collection
- `id`, `organization_id`, `token_hash` (SHA-256, unique indexed)
- `submission_fields` (JSONB), `submission_token_status`, `max_uses`, `use_count`, `expires_at`
- Linked entity FKs: `invoice_header_id`, `counterparty_id`, `email_log_id`

**submission_response** - Data submitted by counterparties
- `id`, `organization_id`, `submission_token_id`
- `response_data` (JSONB), `submitted_by_email`, `ip_address`, `invoice_header_id`

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
- `calculated_grp_per_kwh` - DECIMAL — GRP in local currency per kWh
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
- GRP charge classification moved from received_invoice_line_item columns to invoice_line_item_type FK
- project_document and project_onboarding_snapshot dropped — not needed for current workflow

---

### v9.1 - 2026-02-19 (Billing Product Capture & Tariff Rate Versioning)

**Description:** Adds billing product reference table for Sage/ERP product codes, contract-product junction for multi-product contracts, and tariff rate period table for tracking annual escalation without modifying the original contractual base_rate.

**Migrations:**
- `database/migrations/034_billing_product_and_rate_period.sql` - Three new tables + CBE seed data + RLS

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

**New Table: tariff_rate_period**
- `id` - BIGSERIAL PRIMARY KEY
- `clause_tariff_id` - BIGINT NOT NULL REFERENCES clause_tariff(id)
- `contract_year` - INTEGER NOT NULL — Contract operating year (1-based)
- `period_start` - DATE NOT NULL
- `period_end` - DATE
- `effective_rate` - DECIMAL NOT NULL — Rate after escalation
- `currency_id` - BIGINT REFERENCES currency(id)
- `calculation_basis` - TEXT — Human-readable explanation (e.g., "Base 0.1087 + 2.5% CPI")
- `is_current` - BOOLEAN NOT NULL DEFAULT false
- `approved_by` - UUID REFERENCES auth.users(id)
- `approved_at` - TIMESTAMPTZ
- UNIQUE(clause_tariff_id, contract_year)
- CHECK (contract_year >= 1)
- CHECK (effective_rate >= 0)
- CHECK (period_end IS NULL OR period_end >= period_start)
- Unique partial index: `idx_tariff_rate_period_current(clause_tariff_id) WHERE is_current = true` — enforces single current rate per tariff

**Onboarding Pipeline Changes:**
- `excel_parser.py`: Added "product to be billed" / "product code" / "billing product" label mappings; comma/semicolon splitting in `_normalize_fields()`
- `models/onboarding.py`: Added `product_to_be_billed`, `product_to_be_billed_list` to ExcelOnboardingData; `billing_products` to MergedOnboardingData
- `onboarding_service.py`: Added `stg_billing_products` staging table, population, and billing_products count in preview response
- `onboard_project.sql`: Added `stg_billing_products` staging table; Step 4.10 (contract_billing_product upsert with LATERAL preference for org-scoped over canonical); Step 4.11 (tariff_rate_period Year 1 initialization)

**Design Notes:**
- billing_product is contract-level, not clause_tariff-level — product codes describe WHAT is billed; tariff terms describe HOW
- tariff_rate_period separates operational rate escalation from contract amendments (version/is_current/supersedes on clause_tariff)
- clause_tariff.base_rate stays as the original contractual rate, never modified after onboarding
- Year 1 tariff_rate_period is auto-created during onboarding (effective_rate = base_rate)
- Escalation types: FIXED_INCREASE/PERCENTAGE are deterministic (pre-populate); US_CPI is semi-deterministic; REBASED_MARKET_PRICE is dynamic
- Partial unique indexes on billing_product solve the NULL ≠ NULL problem for canonical rows (PostgreSQL UNIQUE treats NULLs as distinct)
- Cross-tenant trigger on contract_billing_product prevents org A's contract from referencing org B's billing products
- Unique partial index on is_current prevents multiple active rates per clause_tariff (escalation must flip previous row first)
- onboard_project.sql Step 4.10 uses JOIN LATERAL with ORDER BY organization_id NULLS LAST to prefer org-scoped products over canonical when both exist for same code

---

### v9.2 - 2026-02-19 (Seed tariff_type with CBE Service Codes, Restore energy_sale_type)

**Description:** Seeds `tariff_type` with 7 CBE "Contract Service/Product Type" codes (ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE). Drops `tariff_structure_type` (unused, derivable from energy_sale_type). Keeps `energy_sale_type` as a separate classification on `clause_tariff`.

**Migrations:**
- `database/migrations/034_billing_product_and_rate_period.sql` — Sections E & F (merged from former 035)

**Changes:**

**Inserted into tariff_type (7 new codes):**
- ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE
- These coexist with the 14 existing billing-line-level codes (METERED_ENERGY, AVAILABLE_ENERGY, etc.)

**Dropped column from clause_tariff:**
- `tariff_structure_id` (no corresponding Excel field, derivable from energy_sale_type)

**Dropped table:**
- `tariff_structure_type`

**clause_tariff classification FKs (3 remaining):**
- `tariff_type_id` → "Contract Service/Product Type" (ENERGY_SALES, LOAN, etc.)
- `energy_sale_type_id` → "Energy Sales Tariff Type" (FIXED_SOLAR, FLOATING_GRID, etc.)
- `escalation_type_id` → "Price Adjustment Type" (FIXED_INCREASE, PERCENTAGE, US_CPI, etc.)

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
- `tariff_type` = "Contract Service/Product Type" — classifies WHAT the contract is for
- `energy_sale_type` = pricing mechanism within energy sales (FIXED_SOLAR, FLOATING_GRID, etc.)
- `tariff_structure_type` dropped — no Excel field, structure derivable from energy_sale_type
- GH-MOH01 after re-onboarding: tariff_type_id = ENERGY_SALES, energy_sale_type_id = FIXED_SOLAR

---
