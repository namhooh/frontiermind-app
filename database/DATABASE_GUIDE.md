# Database Management Guide
**Energy Contract Compliance & Invoicing System**

Quick links: [Directory Structure](#directory-structure) | [Workflows](#common-workflows) | [Scripts](#scripts-reference) | [Troubleshooting](#troubleshooting)

Last updated: 2026-02-26

---

## Overview

This guide provides comprehensive documentation for managing the database infrastructure of the Energy Contract Compliance & Invoicing System.

### Technology Stack

- **Database**: Supabase PostgreSQL (cloud-hosted)
- **Frontend**: Next.js 16.0.8 + React + TypeScript
- **Backend**: Next.js API Routes (TypeScript), Python services (planned)
- **Authentication**: Supabase Auth with Row-Level Security (RLS)
- **Deployment**: Vercel (frontend), Cloud Run (planned for Python)

### Versioning Philosophy

- **Migrations as Source of Truth**: Sequential migration files capture all incremental changes
- **Periodic Snapshots**: Full schema snapshots created after completing each development phase
- **Manual Diagrams**: Manual draw.io diagrams for design

### Key Principles

1. **Never modify existing migrations** - Always create new migration files
2. **Test locally before deploying** - Run migrations on local database first
3. **Migrations run once** - Each migration should be idempotent where possible
4. **Snapshots are read-only** - Reference points, not source of truth
5. **Document all changes** - Update SCHEMA_CHANGES.md after each phase

---

## Directory Structure

Complete database directory tree with inline explanations:

```
database/
├── migrations/                            # All schema files (SOURCE OF TRUTH)
│   ├── 000_baseline.sql                   # Initial 50+ table schema
│   ├── 001_migrate_role_to_auth.sql       # Phase 1: Authentication
│   ├── 002_add_contract_pii_mapping.sql   # Phase 2: PII protection
│   ├── 003_add_contract_parsing_fields.sql
│   ├── 004_enhance_clause_table.sql
│   ├── 005_update_clause_categories.sql
│   ├── 006_meter_reading_v2.sql           # Phase 3: Lake-house partitioned table + pg_cron
│   ├── 007_meter_aggregate_enhance.sql    # Phase 3: Enhanced aggregation
│   ├── 008_default_event_evidence.sql     # Phase 3: Evidence JSONB
│   ├── 009_integration_credential.sql     # Phase 3: API key/OAuth storage
│   ├── 010_integration_site.sql           # Phase 3: External site mapping
│   ├── 011_ingestion_log.sql              # Phase 3: Ingestion audit trail
│   ├── 012_audit_columns_uuid.sql         # Phase 3.1: Audit column standardization
│   ├── 014_clause_relationship.sql        # Phase 4: Ontology relationships + event enhancements
│   ├── 015_obligation_view.sql            # Phase 4: Obligation VIEW and helpers
│   ├── 016_audit_log.sql                  # Phase 4.1: Comprehensive security audit logging
│   ├── 017_core_table_rls.sql             # Phase 4.1: RLS policies for core tables
│   ├── 018_export_and_reports_schema.sql  # Phase 5: Export and report generation
│   ├── 019_invoice_comparison_final_amount.sql  # Phase 5.2: Invoice reconciliation columns
│   ├── 020_contract_extraction_metadata.sql     # Phase 5.4: Contract metadata extraction
│   ├── 021_seed_billing_period.sql              # Phase 5.5: Billing period seed data
│   ├── 022_exchange_rate_and_invoice_validation.sql  # Phase 5.6: Exchange rates, invoice validation architecture
│   ├── 023_simplify_obligation_view.sql              # Phase 6.0: Canonical ontology field names in obligation VIEW
│   ├── 024_drop_insecure_security_events_view.sql    # Phase 6.1: Security fix - drop insecure v_security_events view
│   ├── 025_meter_reading_dedup_index.sql              # Phase 6.2: Business-key dedup index for meter_reading
│   ├── 026_meter_aggregate_dedup_index.sql            # Phase 6.3: Billing aggregate dedup index for meter_aggregate
│   ├── 027_tariff_classification_lookup.sql           # Phase 7.0: Org-scoped tariff classification lookup tables
│   ├── 028_customer_contact.sql                       # Phase 7.0: Customer contact table (1:many from counterparty)
│   ├── 029_production_forecast_guarantee.sql          # Phase 7.0: Production forecast (monthly) and guarantee (annual)
│   ├── 030_seed_billing_period_calendar.sql           # Phase 7.1: Full billing period calendar (Jan 2024 - Dec 2027)
│   ├── 031_generated_report_invoice_direction.sql     # Phase 7.1: Add invoice_direction to generated_report
│   ├── 032_email_notification_engine.sql              # Phase 8.0: Email notifications, scheduling, submission tokens
│   ├── 033_project_onboarding.sql                     # Phase 9.0: COD data capture, amendment versioning, reference_price, contract_amendment, upsert indexes, preview table, forecast_pr_poa
│   ├── 034_billing_product_and_rate_period.sql         # Phase 9: billing_product, contract_billing_product, tariff_annual_rate (was tariff_rate_period), CBE seed data, tariff classification cleanup, payment_terms
│   ├── 036_monthly_tariff_and_fx.sql                  # Phase 9.1: Rename tariff_rate_period→tariff_annual_rate, final_effective_tariff, tariff_monthly_rate
│   ├── 037_grp_ingestion.sql                          # Phase 9.3: MRP ingestion — monthly observations, file upload, submission_token extensions
│   ├── 038_moh01_amendment_version_history.sql         # Phase 10.2: Amendment version chain for MOH01 (original tariff row + supersedes linkage)
│   ├── 039_pipeline_integrity_fixes.sql               # Phase 10.1: Annual ref_price partial unique index, asset_type seeds, metering_type CHECK, idempotent MRP seed
│   ├── 040_merge_tariff_rate_tables.sql               # Phase 10.3: Unified tariff_rate table (merges + drops tariff_annual_rate + tariff_monthly_rate), four-currency, JSONB calc_detail, FX audit trail, integrity constraints
│   ├── 041_multi_meter_billing_and_performance.sql    # Phase 10.4: contract_line, plant_performance, meter_aggregate enhancements, meter names, dedup index fix, external_line_id unique index
│   ├── 042_invoice_generation_prerequisites.sql       # Phase 10.5: clean dedup index, billing_tax_rule (GiST), invoice header versioning, line item audit/sign, new line item types
│   ├── 043_billing_gap_analysis_fixes.sql              # Phase 10.6: org-scoped billing_tax_rule RLS
│   ├── 044_legal_entity_industry_and_moh01_fixes.sql  # Phase 10.7: legal_entity table, counterparty.industry, MOH01 data fixes
│   ├── 045_relocate_contract_columns.sql              # Phase 10.8: Relocate interconnection_voltage_kv, agreed_fx_rate_source, payment_security to proper homes
│   ├── 046_populate_portfolio_base_data.sql           # Phase 10.9: CBE portfolio population — parent_contract_id, legal entities, counterparties, 33 projects, contracts, amendments, exchange rates (10 currencies × 14 months from xe.com)
│   ├── 047_populate_sage_contract_ids.sql             # Phase 10.10: SAGE contract IDs + parent_contract_line_id hierarchy + MOH01 mother line 1000
│   ├── 049_pilot_project_data_population.sql          # Phase 10.11: Pilot data — contract_lines, clause_tariffs, meter_aggregates for KAS01, NBL01, LOI01
│   ├── 050_rename_grp_to_mrp.sql                      # Phase 10.13: Rename GRP (Grid Reference Price) → MRP (Market Reference Price) — terminology only
│   ├── 051_org_email_address.sql                      # Phase 8.1: Org → email address mapping for bidirectional email on mail.frontiermind.co
│   ├── 052_inbound_message.sql                       # Phase 8.3: Unified inbound_message + inbound_attachment (combined expand/contract, drops submission_response)
│   ├── 053_org_scoped_credentials.sql                # Org-scoped API keys: nullable data_source_id, allowed_scopes, api_key_hash
│   ├── 054_sage_id_aliases_and_data_fixes.sql        # Sage ID reversal, data fixes, additional_external_ids, phase_cod_date, XF-AB→XFAB split (4 projects), ZL02 contracts
│   ├── 055_step4_billing_product_tariff_structure.sql # Step 4: billing_product linking, contract_billing_product junction, clause_tariff placeholders
│   ├── 056_billing_tax_rule_project_scope.sql        # Step 8: Add project_id to billing_tax_rule for project-specific overrides
│   ├── 058_sage_bp_import.sql                        # SAGE BP import data
│   ├── 059_tariff_taxonomy_restructure.sql           # Tariff classification taxonomy restructure: tariff_type→offtake model, energy_sale_type→revenue type, escalation_type→expanded with FLOATING_* flat codes
│   ├── 060_tariff_rate_billing_period.sql            # tariff_rate cleanup: add billing_period_id FK, drop fx_rate_hard_id, rename fx_rate_local_id → exchange_rate_id
│   ├── 062_tariff_formula.sql                       # Tariff formula decomposition: computation graphs from PPA pricing sections (Step 11P)
│   ├── snapshot_v2.0.sql                  # (Optional) Schema snapshot after Phase 2
│   └── README.md
│
├── diagrams/                              # Entity relationship diagrams
│   ├── entity_diagram_v1.0.drawio         # Manual draw.io diagrams
│   ├── entity_diagram_v1.1.drawio
│   ├── exports/                           # Exported images (optional)
│   │   ├── entity_diagram_v1.0.png
│   │   └── entity_diagram_v2.0.png
│   └── README.md
│
├── seed/                                  # Data insertion files
│   ├── reference/                         # Production lookup data
│   │   └── 00_reference_data.sql          # Currencies, countries, types
│   ├── fixtures/                          # Test data only
│   │   ├── 01_test_organizations.sql      # Sample organizations
│   │   ├── 02_test_project.sql            # Test projects
│   │   ├── 03_default_event_scenario.sql  # Test events
│   │   └── 05_auth_seed.sql               # Test users
│   └── README.md
│
├── scripts/                               # Database management scripts
│   ├── apply_schema.sh                    # Apply all migrations
│   ├── create-phase-snapshot.sh           # Create schema snapshot
│   ├── load_test_data.sh                  # Load seed data
│   ├── fixtures/                          # Project-specific fixture data
│   │   └── moh01_dec2025.sql             # MOH01 Dec 2025 golden test data
│   └── project-onboarding/               # Project onboarding scripts
│       ├── onboard_project.sql           # Staged ETL for COD project onboarding
│       ├── validate_onboarding_project.sql # Validation query pack
│       └── audits/                       # Per-project audit trails
│
├── functions/                             # PostgreSQL functions (future)
├── views/                                 # Database views (future)
└── SCHEMA_CHANGES.md                      # Version changelog
```

---

## Versioning Strategy

### Migrations (Source of Truth)

**Format**: `001_description.sql`, `002_description.sql`, `003_description.sql`

**Characteristics**:
- Always incremental (additive changes)
- Numbered sequentially
- Never modified after creation
- Run once per environment
- Contains DDL statements (CREATE, ALTER, DROP)

**Example**:
```sql
-- File: database/migrations/002_add_contract_pii_mapping.sql

CREATE TABLE contract_pii_mapping (
  id BIGSERIAL PRIMARY KEY,
  contract_id BIGINT REFERENCES contract(id) ON DELETE CASCADE,
  encrypted_mapping BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_contract_pii_contract_id ON contract_pii_mapping(contract_id);
```

### Snapshots (Reference Points)

**Format**: `snapshot_v2.0.sql`, `snapshot_v3.0.sql` (stored in `migrations/`)

**Characteristics**:
- Full schema dump at a specific point in time
- Created after completing a development phase
- Combines multiple migrations
- Used for quick database recreation
- Read-only (DO NOT EDIT)
- Stored in `migrations/` but prefixed with `snapshot_` to differentiate

**When to Create**:
- After completing a major phase
- After several related migrations
- Before major refactoring
- When you want a clean restore point

### Version Numbering

- **v1.0** - Baseline (initial schema)
- **v1.x** - Minor changes within a phase (v1.1, v1.2)
- **v2.0** - Major phase completion (Phase 2)
- **v2.x** - Minor changes within Phase 2

---

## Scripts Reference

### 1. `apply_schema.sh`

**Purpose**: Apply all migrations to a fresh database

**Usage**:
```bash
./database/scripts/apply_schema.sh
```

**When to use**:
- Setting up a new development environment
- Recreating database from scratch
- After running `reset_database.sh`

**What it does**:
1. Applies all migrations from `database/migrations/` in numeric order
2. Skips `_UP.sql` reversal files
3. Stops on first error

**Prerequisites**: `SUPABASE_DB_URL` environment variable set

---

### 2. `backup_database.sh`

**Purpose**: Create a backup of the database

**Usage**:
```bash
./database/scripts/backup_database.sh
```

**When to use**:
- Before running major migrations
- Before destructive operations
- Weekly backups (recommended)

**What it does**:
1. Creates timestamped backup file
2. Saves to `backups/` directory
3. Includes both schema and data

**Output**: `backups/backup_YYYY-MM-DD_HH-MM-SS.sql`

---

### 3. `reset_database.sh`

**Purpose**: Drop and recreate database (DESTRUCTIVE)

**Usage**:
```bash
./database/scripts/reset_database.sh
```

**When to use**:
- Development only (never in production)
- When database state is corrupted
- When starting fresh

**What it does**:
1. Drops all tables in public schema
2. Recreates public schema
3. Ready for `apply_schema.sh`

**Warning**: All data will be lost!

---

### 4. `load_test_data.sh`

**Purpose**: Load reference data + test fixtures

**Usage**:
```bash
./database/scripts/load_test_data.sh
```

**When to use**:
- After running `apply_schema.sh`
- After resetting database
- When you need test data

**What it does**:
1. Loads reference data (production lookup tables)
2. Loads test fixtures (sample organizations, projects, etc.)

**Output**:
```
Loading reference data...
✅ Reference data loaded

Loading test fixtures...
✅ Test fixtures loaded
```

---

### 5. `document-migration.sh`

**Purpose**: Analyze a migration file to assist with diagram updates

**Usage**:
```bash
./database/scripts/document-migration.sh database/migrations/002_add_contract_pii_mapping.sql
```

**When to use**:
- Before updating draw.io diagrams
- To understand what changed in a migration
- For code review

**What it does**:
1. Parses SQL statements in migration
2. Extracts new tables, columns, relationships
3. Displays human-readable summary

**Example output**:
```
📋 Migration Summary: 002_add_contract_pii_mapping.sql
================================

🆕 New Tables:
  - contract_pii_mapping

✏️  Modified Tables:
  (none)

➕ New Columns:
  - encrypted_mapping BYTEA NOT NULL
  - pii_entities_count INTEGER

🔗 New Relationships:
  - contract(id) ← contract_pii_mapping.contract_id

💡 Update draw.io diagram with these changes
```

---

### 6. `create-phase-snapshot.sh`

**Purpose**: Create a version snapshot after completing a phase

**Usage**:
```bash
./database/scripts/create-phase-snapshot.sh v2.0 "Phase 2 - Contract Parsing"
```

**When to use**:
- After completing several related migrations
- At the end of a development phase
- Before major releases

**What it does**:
1. Exports full schema from Supabase using `pg_dump`
2. Adds version header with metadata
3. Saves to `database/migrations/snapshot_v2.0.sql`
4. Updates `database/SCHEMA_CHANGES.md` changelog

**Example output**:
```
📸 Creating schema snapshot: v2.0
✅ Snapshot saved to database/migrations/snapshot_v2.0.sql
✅ Changelog updated in database/SCHEMA_CHANGES.md

📌 Next steps:
  1. Update database/diagrams/entity_diagram_v2.0.drawio
  2. Commit changes
```

---

## Data Management

### Seed Data

#### Reference Data (`database/seed/reference/`)

**Purpose**: Production lookup data required for application to function

**Files**: `00_reference_data.sql`

**Contents**:
- Currency codes (USD, EUR, GBP)
- Country lists
- Lookup table values (contract types, statuses, etc.)
- Configuration data

**Deployment**: **GOES TO PRODUCTION**

**Loading**:
```bash
# Production-safe loading (reference data only)
psql $SUPABASE_DB_URL -f database/seed/reference/00_reference_data.sql
```

**Best practices**:
- Keep idempotent (safe to run multiple times)
- Use `INSERT ... ON CONFLICT DO NOTHING` or `WHERE NOT EXISTS`
- Never include sensitive data
- Version control with schema

---

#### Fixture Data (`database/seed/fixtures/`)

**Purpose**: Test and development data for local testing

**Files**:
- `01_test_organizations.sql` - Sample organizations
- `02_test_project.sql` - Test projects
- `03_default_event_scenario.sql` - Test events
- `05_auth_seed.sql` - Test users

**Deployment**: **NEVER GOES TO PRODUCTION**

**Loading**:
```bash
# Load all fixtures (development only)
for file in database/seed/fixtures/*.sql; do
  psql $SUPABASE_DB_URL -f "$file"
done

# Or use helper script
./database/scripts/load_test_data.sh
```

**Best practices**:
- Keep small (only essential test data)
- Document dependencies (numbered prefixes)
- Never commit real user data
- Reset frequently during development

---

## Diagram Management

### Manual Diagrams (draw.io)

**Location**: `database/diagrams/entity_diagram_vX.X.drawio`

**Tool**: [https://app.diagrams.net](https://app.diagrams.net)

**Workflow**:

1. **After creating a migration**, run the documentation helper:
   ```bash
   ./database/scripts/document-migration.sh database/migrations/002_add_contract_pii_mapping.sql
   ```

2. **Review the summary** to understand what changed:
   - New tables
   - Modified tables
   - New columns
   - New relationships

3. **Open the appropriate version** in draw.io:
   - Open `database/diagrams/entity_diagram_v2.0.drawio`
   - Or use web version: https://app.diagrams.net

4. **Add/modify based on migration summary**:
   - Add new tables as entities
   - Add relationships (foreign keys)
   - Update existing tables with new columns

5. **Export (optional)**:
   - File → Export As → PNG or SVG
   - Save to `database/diagrams/exports/`

---

## Common Workflows

### Workflow 1: Creating a Migration

```bash
# 1. Create migration file with sequential number
vi database/migrations/002_add_contract_pii_mapping.sql

# 2. Write SQL (CREATE TABLE, ALTER TABLE, etc.)
# Keep it idempotent where possible:
# - Use IF NOT EXISTS for CREATE TABLE
# - Use IF EXISTS for DROP TABLE
# - Check for existing columns before ALTER TABLE

# 3. Test locally
psql $SUPABASE_DB_URL -f database/migrations/002_add_contract_pii_mapping.sql

# 4. Document changes for diagram update
./database/scripts/document-migration.sh database/migrations/002_add_contract_pii_mapping.sql

# 5. Update draw.io diagram
# Open database/diagrams/entity_diagram_v2.0.drawio
# Add new tables/relationships based on migration summary

# 6. Commit changes
git add database/migrations/002_add_contract_pii_mapping.sql
git add database/diagrams/entity_diagram_v2.0.drawio
git commit -m "Add contract_pii_mapping table for PII protection"
git push
```

---

### Workflow 2: Creating a Phase Snapshot

**When**: After completing multiple migrations in a development phase

```bash
# 1. Generate snapshot (combines all migrations)
./database/scripts/create-phase-snapshot.sh v2.0 "Phase 2 - Contract Parsing"

# Output:
# 📸 Creating schema snapshot: v2.0
# ✅ Snapshot saved to database/migrations/snapshot_v2.0.sql
# ✅ Changelog updated in database/SCHEMA_CHANGES.md

# 2. Review generated files
cat database/migrations/snapshot_v2.0.sql | head -20
cat database/SCHEMA_CHANGES.md

# 3. Update final diagram for this version
# Open database/diagrams/entity_diagram_v2.0.drawio
# Ensure all Phase 2 changes are reflected

# 4. Commit everything
git add database/migrations/snapshot_v2.0.sql \
        database/SCHEMA_CHANGES.md \
        database/diagrams/entity_diagram_v2.0.drawio

git commit -m "Schema snapshot v2.0: Phase 2 Contract Parsing Complete"
git push
```

---

### Workflow 3: Loading Test Data

**Scenario**: Fresh database setup or after reset

```bash
# Load all data (reference + fixtures)
./database/scripts/load_test_data.sh

# Or load selectively:

# Load only reference (production-safe)
psql $SUPABASE_DB_URL -f database/seed/reference/00_reference_data.sql

# Load only specific fixture
psql $SUPABASE_DB_URL -f database/seed/fixtures/01_test_organizations.sql
```

---

### Workflow 4: Verifying Database State

**Scenario**: Check database state after migrations

```bash
# List all tables
psql $SUPABASE_DB_URL -c "\dt"

# Check row counts
psql $SUPABASE_DB_URL -c "SELECT COUNT(*) FROM organization;"

# Interactive query session
psql $SUPABASE_DB_URL
```

---

### Workflow 5: Setting Up New Environment

**Scenario**: New team member or new development machine

```bash
# 1. Clone repository
git clone <repo-url>
cd frontiermind-app

# 2. Create .env.local
cp .env.example .env.local

# 3. Set database connection
echo "SUPABASE_DB_URL=postgresql://user:pass@host:5432/db" >> .env.local

# 4. Apply schema (baseline + migrations)
./database/scripts/apply_schema.sh

# 5. Load test data
./database/scripts/load_test_data.sh

# 6. Verify
psql $SUPABASE_DB_URL -c "SELECT COUNT(*) FROM organization;"
psql $SUPABASE_DB_URL -c "\dt"  # List all tables
```

---

## Team Onboarding

### Prerequisites

- **PostgreSQL client** (`psql`) - [Download](https://www.postgresql.org/download/)
- **draw.io** - Desktop app or web access at [https://app.diagrams.net](https://app.diagrams.net)
- **Git** - [Download](https://git-scm.com/downloads)
- **Node.js 18+** (for Next.js) - [Download](https://nodejs.org/)

### Environment Setup

**Step 1: Clone repository**
```bash
git clone <repo-url>
cd frontiermind-app
```

**Step 2: Create environment file**
```bash
cp .env.example .env.local
```

**Step 3: Get database credentials**
- Contact team lead for Supabase credentials
- Or create your own Supabase project at [https://supabase.com](https://supabase.com)

**Step 4: Set database connection**
```bash
echo "SUPABASE_DB_URL=postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres" >> .env.local
```

**Step 5: Install Python dependencies (optional)**
```bash
pip install psycopg2-binary
```

**Step 6: Load initial schema and data**
```bash
# Apply baseline schema
./database/scripts/apply_schema.sh

# Load test data
./database/scripts/load_test_data.sh
```

**Step 7: Verify setup**
```bash
# Count organizations (should be > 0)
psql $SUPABASE_DB_URL -c "SELECT COUNT(*) FROM organization;"

# List all tables (should see 50+)
psql $SUPABASE_DB_URL -c "\dt"
```

---

### Daily Development

**Morning routine**:
```bash
# 1. Pull latest changes
git pull

# 2. Check for new migrations
ls database/migrations/

# 3. Apply new migrations if any
psql $SUPABASE_DB_URL -f database/migrations/00X_*.sql

# 4. Reload test data if schema changed
./database/scripts/load_test_data.sh
```

**Before creating a pull request**:
```bash
# 1. Ensure all migrations are documented
./database/scripts/document-migration.sh database/migrations/00X_*.sql

# 2. Update draw.io diagram if needed

# 3. Verify database state
psql $SUPABASE_DB_URL -c "\dt"

# 4. Commit with descriptive message
git add database/migrations/00X_*.sql
git commit -m "feat(db): Add contract_pii_mapping table"
git push
```

---

## Troubleshooting

### Issue 1: Database Connection Failed

**Symptoms**:
```
psql: error: connection to server failed
```

**Diagnosis**:
```bash
# Check connection string
echo $SUPABASE_DB_URL

# Test connection
psql $SUPABASE_DB_URL -c "SELECT 1;"
```

**Common causes**:
- Missing `.env.local` file → Create from `.env.example`
- Incorrect credentials → Verify with Supabase dashboard
- Firewall blocking port 5432 → Check network settings
- VPN required → Connect to VPN

**Solution**:
```bash
# Fix .env.local
vi .env.local
# Add: SUPABASE_DB_URL=postgresql://...

# Source environment
source .env.local

# Test again
psql $SUPABASE_DB_URL -c "SELECT 1;"
```

---

### Issue 2: Migration Already Exists Error

**Symptoms**:
```
ERROR: relation "contract_pii_mapping" already exists
```

**Diagnosis**:
```sql
-- Check if table exists
\dt contract_pii_mapping

-- Check table structure
\d contract_pii_mapping
```

**Cause**: Migration has already been run on this database

**Solutions**:

**Option 1**: Skip migration (if already applied)
```bash
# No action needed - migration already applied
```

**Option 2**: Make migration idempotent
```sql
-- Use IF NOT EXISTS
CREATE TABLE IF NOT EXISTS contract_pii_mapping (
  id BIGSERIAL PRIMARY KEY,
  ...
);
```

**Option 3**: Reset database (development only)
```bash
./database/scripts/reset_database.sh
./database/scripts/apply_schema.sh
./database/scripts/load_test_data.sh
```

---

### Issue 3: Test Data Load Failed

**Symptoms**:
```
ERROR: insert or update on table violates foreign key constraint
```

**Diagnosis**:
```bash
# Check if reference data loaded
psql $SUPABASE_DB_URL -c "SELECT COUNT(*) FROM organization;"
```

**Cause**: Foreign key dependencies not met (load order matters)

**Solution**:
```bash
# 1. Load reference data first
psql $SUPABASE_DB_URL -f database/seed/reference/00_reference_data.sql

# 2. Then load fixtures in order
psql $SUPABASE_DB_URL -f database/seed/fixtures/01_test_organizations.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/02_test_project.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/03_default_event_scenario.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/05_auth_seed.sql

# Or use helper script (handles order)
./database/scripts/load_test_data.sh
```

**Common issues**:
- Missing reference data → Load reference first
- Duplicate primary keys → Reset database or use ON CONFLICT
- Wrong file order → Follow numbered prefixes (01, 02, 03, ...)

---

### Issue 4: Permission Denied on Scripts

**Symptoms**:
```
permission denied: ./database/scripts/apply_schema.sh
```

**Cause**: Scripts not executable

**Solution**:
```bash
# Make scripts executable
chmod +x scripts/*.sh
chmod +x scripts/*.py

# Verify
ls -l scripts/
```

---

### Issue 5: pg_cron Permission Denied

**Symptoms**:
```
ERROR: permission denied for schema cron
```

**Cause**: pg_cron extension not enabled in Supabase

**Solution**:
1. Go to Supabase Dashboard → **Database** → **Extensions**
2. Search for `pg_cron`
3. Click **Enable**
4. Re-run the migration

**Verify pg_cron is working**:
```sql
-- Check scheduled jobs
SELECT * FROM cron.job;

-- Check job run history
SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;

-- Manually trigger partition creation
SELECT create_meter_reading_partition('2026-05-01'::DATE);
```

---

### Issue 6: Partition Does Not Exist

**Symptoms**:
```
ERROR: no partition of relation "meter_reading" found for row
```

**Cause**: Trying to insert data for a month without a partition

**Solution**:
```sql
-- Create missing partition manually
SELECT create_meter_reading_partition('2026-06-01'::DATE);

-- Verify partition exists
SELECT c.relname FROM pg_inherits i
JOIN pg_class c ON i.inhrelid = c.oid
WHERE i.inhparent = 'meter_reading'::regclass
ORDER BY c.relname;
```

**Prevention**: Ensure pg_cron job is running (creates partitions 3 months ahead)

---

## Quick Reference

### One-Liner Commands

```bash
# Apply latest migration only
psql $SUPABASE_DB_URL -f $(ls database/migrations/[0-9]*.sql | grep -v "_UP.sql" | tail -1)

# Count tables in database
psql $SUPABASE_DB_URL -c "\dt" | wc -l

# Show baseline schema header
head -5 database/migrations/000_baseline.sql

# Reset and reload everything (DESTRUCTIVE)
./database/scripts/reset_database.sh && ./database/scripts/apply_schema.sh && ./database/scripts/load_test_data.sh

# List all migrations
ls -1 database/migrations/

# Check migration status (compare files to database)
psql $SUPABASE_DB_URL -c "\dt" > /tmp/tables.txt && cat /tmp/tables.txt

# Quick database backup
pg_dump $SUPABASE_DB_URL > backup_$(date +%Y%m%d).sql
```

---

### File Paths Quick Reference

```
database/
├── migrations/000_baseline.sql             # Initial schema (baseline)
├── migrations/001_migrate_role.sql         # First migration (auth)
├── migrations/016_audit_log.sql            # Security audit logging
├── migrations/017_core_table_rls.sql       # RLS for core tables
├── migrations/018_export_and_reports_schema.sql  # Export and reports
├── migrations/019_invoice_comparison_final_amount.sql  # Invoice reconciliation
├── migrations/020_contract_extraction_metadata.sql     # Contract metadata extraction
├── diagrams/entity_diagram_v1.0.drawio     # Manual diagram v1.0
├── seed/reference/00_reference.sql         # Production lookup data
├── seed/fixtures/01_test_orgs.sql          # Test organizations
└── SCHEMA_CHANGES.md                       # Version history log
```

---

### Version History at a Glance

**v1.0 (Baseline)** - Initial schema
- 50+ tables for contract compliance system
- Core entities: organization, project, contract, clause
- Metering: meter_reading, meter_aggregate
- Invoicing: invoice_header, invoice_line_item
- Events: default_event, rule_output

**v1.1 (Phase 1 - Authentication)** - Completed
- Migration: `001_migrate_role_to_auth.sql`
- Added: `role.user_id`, `role.role_type`, `role.is_active`
- Integration with Supabase Auth

**v2.0 (Phase 2 - Contract Parsing)** - Completed
- Migrations: `002-005_*.sql`
- New: `contract_pii_mapping` table
- Enhanced: `contract` parsing fields
- Enhanced: `clause` AI extraction fields

**v3.0 (Phase 3 - Data Ingestion Lake-House)** - Completed
- Migrations: `006-011_*.sql`
- Restructured: `meter_reading` → partitioned table with canonical model
- New: `integration_credential`, `integration_site`, `ingestion_log` tables
- Enhanced: `meter_aggregate` with availability metrics
- Enhanced: `default_event` with evidence JSONB
- **pg_cron**: Automatic partition management (monthly job)
- Reference: `DATA_INGESTION_ARCHITECTURE.md`

**v3.1 (Audit Column Standardization)** - Completed
- Migration: `012_audit_columns_uuid.sql`
- Standardized audit columns (`created_by`, `updated_by`) from VARCHAR to UUID
- FK references to `auth.users(id)` for Supabase Auth consistency

**v4.0 (Phase 4 - Power Purchase Ontology Framework)** - Completed
- Migrations: `014_clause_relationship.sql`, `015_obligation_view.sql`
- New: `clause_relationship` table (TRIGGERS, EXCUSES, GOVERNS, INPUTS relationships)
- New: `obligation_view` VIEW (exposes "Must A" obligations)
- New: `obligation_with_relationships` VIEW (obligations with relationship aggregates)
- Enhanced: `event` table with verification columns (`verified`, `verified_by`, `verified_at`, `contract_id`)
- Seeded: New event types (`FORCE_MAJEURE`, `SCHEDULED_MAINT`, `GRID_CURTAIL`, etc.)
- Helper functions: `get_excuses_for_clause()`, `get_triggers_for_clause()`, `get_contract_relationship_graph()`
- Reference: `contract-digitization/docs/ONTOLOGY_GUIDE.md`

**v4.1 (Security Hardening)** - Completed
- Migrations: `016_audit_log.sql`, `017_core_table_rls.sql`
- New: `audit_log` table with 50+ action types (auth, data access, PII, exports, admin)
- New: `audit_action_type` and `audit_severity` enums
- New: `v_security_events` VIEW for security monitoring (**removed in migration 024** — security vulnerability)
- New: RLS policies on 15+ core tables (organization, project, contract, clause, event, etc.)
- Helper functions: `log_audit_event()`, `log_pii_access_event()`, `get_audit_summary()`
- Security: Organization isolation, admin-only PII access, service role policies
- Reference: `SECURITY_PRIVACY_ASSESSMENT.md` Appendix E

**v5.1 (Simplified Export & Reports - Invoice-Focused)** - Pending
- Migration: `018_export_and_reports_schema.sql`
- New tables: `report_template`, `scheduled_report`, `generated_report`
- New enums: `invoice_report_type`, `export_file_format`, `report_frequency`, `report_status`, `generation_source`
- Pre-seeded: 4 invoice-focused report templates per organization
- Helper functions: `get_latest_completed_billing_period()`, `calculate_next_run_time()`, `get_report_statistics()`
- **Billing Period Integration:** Reports reference `billing_period_id` FK instead of date ranges
- **Simplified workflow:** No approval process, on-demand vs scheduled generation only
- **Implementation Guide:** `IMPLEMENTATION_GUIDE_REPORT_GENERATION.md`

**v5.2 (Invoice Reconciliation Columns)** - Completed
- Migration: `019_invoice_comparison_final_amount.sql`
- Enhanced: `invoice_comparison` table with `final_amount` and `adjustment_amount` columns
- New index: `idx_invoice_comparison_final_amount` (partial index for reconciled invoices)
- **Workflow:** Track final reconciled payment amount after variance review

**v5.4 (Contract Metadata Extraction)** - Completed
- Migration: `020_contract_extraction_metadata.sql`
- New column: `contract.extraction_metadata` JSONB for AI-extracted metadata
- New index: `idx_contract_extraction_metadata` GIN index for JSONB querying
- Seeded: `contract_type` lookup table with 9 energy contract types (PPA, O&M, EPC, LEASE, IA, ESA, VPPA, TOLLING, OTHER)
- New function: `get_contracts_needing_counterparty_review()` - Find contracts needing manual counterparty assignment
- **Features:**
  - AI extracts contract type, party names, dates from uploaded contracts
  - Counterparty fuzzy matching with `rapidfuzz` library (80% threshold)
  - FK validation for `organization_id`, `project_id` at upload time
  - Extraction metadata stored for audit trail
- **Python Backend:**
  - `services/prompts/metadata_extraction_prompt.py` - New Claude prompt
  - `db/lookup_service.py` - Counterparty matching, FK validation
  - `db/contract_repository.py` - `update_contract_metadata()` method
  - `services/contract_parser.py` - Step 4.5 metadata extraction
  - `api/contracts.py` - FK validation at upload
- Reference: `contract-digitization/docs/IMPLEMENTATION_GUIDE.md`

**v5.6 (Client Invoice Validation Architecture)** - Completed
- Migration: `022_exchange_rate_and_invoice_validation.sql`
- New: `exchange_rate` table (per org/currency/date, rate to USD)
- New enum: `invoice_direction` ('payable', 'receivable')
- Extended: `clause_tariff` with `tariff_group_key`, `meter_id`, `source_metadata`, `is_active`
- Extended: `meter_aggregate` with billing readings (`opening_reading`, `closing_reading`, `utilized_reading`, etc.)
- Extended: Invoice headers and line items with `invoice_direction`, `clause_tariff_id`, `quantity`, `line_unit_price`
- Extended: `invoice_comparison_line_item` with `variance_percent`, `variance_details`
- Seeded: 11 currencies (USD, EUR, GBP, ZAR, GHS, NGN, KES, RWF, SLE, EGP, MZN)
- Seeded: 14 tariff types (FLAT, TOU, TIERED, METERED_ENERGY, etc.)
- Reference: `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md`

**v6.2 (Meter Reading Dedup Index)** - Completed
- Migration: `025_meter_reading_dedup_index.sql`
- New unique index: `idx_meter_reading_dedup` on (organization_id, reading_timestamp, COALESCE(external_site_id), COALESCE(external_device_id))
- Enables row-level dedup via existing `ON CONFLICT DO NOTHING` in loader

**v6.3 (Billing Aggregate Dedup Index)** - Completed
- Migration: `026_meter_aggregate_dedup_index.sql`
- New unique index: `idx_meter_aggregate_billing_dedup` on (organization_id, COALESCE(billing_period_id, -1), COALESCE(clause_tariff_id, -1)) WHERE period_type = 'monthly'
- Enables row-level dedup for monthly billing aggregates via `ON CONFLICT DO NOTHING`

**v7.0 (CBE Schema Design Review)** - Completed
- Migrations: `027-029_*.sql`
- New: `energy_sale_type`, `escalation_type` — org-scoped lookup tables (repurposed in migration 059; `tariff_structure_type` dropped in migration 034)
- New: `customer_contact` — 1:many contacts per counterparty with role, invoice email, escalation flags
- New: `production_forecast` — monthly time-series per project (forecast energy, GHI, PR, degradation)
- New: `production_guarantee` — annual per project (guaranteed kWh, P50 %, actual/shortfall tracking)
- Extended: `clause_tariff` with `energy_sale_type_id`, `escalation_type_id`, `market_ref_currency_id` (`tariff_structure_id` dropped in 034)
- Deferred energy calculation deferred to pricing calculator / rules engine (not a DB view)
- Reference: `CBE_data_extracts/CBE_TO_FRONTIERMIND_MAPPING.md`

**v8.0 (Email Notification Engine)** - Completed
- Migration: `032_email_notification_engine.sql`
- New: `email_template` — Jinja2 email templates per org (system + custom); uses `email_schedule_type` column
- New: `email_notification_schedule` — Scheduling rules with conditions, escalation, submission links; uses `email_schedule_type` column
- New: `email_log` (renamed to `outbound_message` in v8.3) — Full email delivery audit trail (SES integration)
- New: `submission_token` — Secure SHA-256 hashed tokens for external data collection
- New enums: `email_schedule_type`, `email_status`, `submission_token_status`
- Note: `submission_response` was created in v8.0 but fully replaced by `inbound_message` in v8.3 (migration 052)
- Note: `email_log` was renamed to `outbound_message` in v8.3 for symmetric naming with `inbound_message`
- Extended: `audit_action_type` with EMAIL_SENT, EMAIL_FAILED, SUBMISSION_RECEIVED, SUBMISSION_TOKEN_CREATED
- Reuses `calculate_next_run_time()` from migration 018 for schedule timing
- Reuses `customer_contact` from migration 028 for recipient resolution
- Backend: APScheduler in-process, AWS SES for delivery, Jinja2 templates
- Frontend: `/notifications` page, `/submit/[token]` public submission page

**v9.0 (Project Onboarding — COD Data Capture, Amendment Versioning)** - Completed
- Migration: `033_project_onboarding.sql`
- Extended: `project`, `contract`, `counterparty`, `asset`, `meter`, `production_forecast` (forecast_poa_irradiance, forecast_pr_poa), `production_guarantee`, `clause`, `clause_tariff`
- New tables: `contract_amendment`, `reference_price`, `onboarding_preview`
- New enums: `verification_status`, `change_action`
- Amendment tracking: `is_current`, `supersedes_clause_id`, `contract_amendment_id` on clause/clause_tariff
- Triggers: `trg_clause_supersede()`, `trg_clause_tariff_supersede()` for version chain integrity
- Views: `clause_current_v`, `clause_tariff_current_v`
- Renamed: `contract.updated_by` → `contract.created_by`
- Dropped: `project_document`, `project_onboarding_snapshot`, `received_invoice_line_item` ALTERs (charge_type/is_tax/tou_bucket)
- Seeded: `asset_type` (8 codes), `invoice_line_item_type` (4 MRP charge types)
- ETL script: `database/scripts/project-onboarding/onboard_project.sql`
- Python: Amendment diff service, MRP calculator refactored for invoice_line_item_type_code
- Reference: `database/docs/IMPLEMENTATION_GUIDE_PROJECT_ONBOARDING.md`

**v10.0 (Default Rate & Late Payment via clause Table)** - Completed
- No migration required — clause table already exists; records created via onboarding pipeline
- First use of the `clause` table for onboarded project data
- Seeded PAYMENT_TERMS clause for GH-MOH01 with default interest rate (SOFR + 2%), FX indemnity, dispute resolution
- Dashboard API now returns `clauses` array alongside contracts, tariffs, etc.
- PPA extraction prompt expanded to capture structured `default_rate` object
- Onboarding service auto-inserts PAYMENT_TERMS clause when default rate data is available
- Frontend displays default rate in Billing Information section of Pricing & Tariffs tab

**v10.3 (Unified Tariff Rate Table)** - Complete
- Migration: `040_merge_tariff_rate_tables.sql`
- New table: `tariff_rate` — merges `tariff_annual_rate` + `tariff_monthly_rate`
- Dropped tables: `tariff_annual_rate`, `tariff_monthly_rate`
- New enums: `rate_granularity` (annual/monthly), `calc_status` (pending/computed/approved/superseded), `contract_ccy_role` (hard/local/billing)
- Four-currency effective rate: `effective_rate_contract_ccy`, `_hard_ccy`, `_local_ccy`, `_billing_ccy` with `contract_role` role designator
- JSONB `calc_detail` for formula-specific intermediaries (floor/ceiling/discounted_base for REBASED_MARKET_PRICE; escalation_value/years_elapsed for deterministic)
- `billing_period_id` FK for monthly rows (added in migration 060)
- FX audit trail: `exchange_rate_id` (renamed from `fx_rate_local_id` in migration 060; `fx_rate_hard_id` dropped — always NULL)
- Calculation lineage: `reference_price_id`, `discount_pct_applied`, `formula_version`
- All engines and APIs write/read exclusively from `tariff_rate`

**v10.4 (Multi-Meter Billing & Plant Performance)** - Complete
- Migration: `041_multi_meter_billing_and_performance.sql`
- Modified table: `meter` — added `name` column
- New table: `contract_line` — links contracts to meters and billing products
- Modified table: `meter_aggregate` — added `available_energy_kwh`, `contract_line_id`, `ghi_irradiance_wm2`, `poa_irradiance_wm2`
- New table: `plant_performance` — monthly project-level performance metrics (includes `billing_period_id` FK for consistency with other monthly-scoped tables)
- New enum: `energy_category` (metered/available/test)
- New API: `GET /projects/{id}/meter-billing`, `GET /projects/{id}/plant-performance` with manual entry and import
- New frontend: Performance tab with table/chart views, MonthlyBillingTab meter breakdown toggle
- Seed data: MOH01 meter names and contract_line rows

**v10.5 (Invoice Generation & Tax Engine)** - Complete
- Migration: `042_invoice_generation_prerequisites.sql`
- New table: `billing_tax_rule` — org/country tax rules with GiST overlap prevention (`btree_gist` extension)
- Modified table: `contract_line` — added `clause_tariff_id` FK
- Modified table: `expected_invoice_header` — versioning (`version_no`, `is_current`), idempotency, `source_metadata`
- Modified table: `expected_invoice_line_item` — audit fields (`component_code`, `basis_amount`, `rate_pct`, `amount_sign`, `sort_order`, `contract_line_id`)
- New line item types: `AVAILABLE_ENERGY`, `LEVY`, `WITHHOLDING`
- New API: `POST /projects/{id}/billing/generate-expected-invoice` — full tax chain (levies, VAT, withholdings)
- Ingestion fix: billing_resolver returns `(resolved, unresolved)` tuple; loader drops unresolved rows with diagnostic logging
- Clean dedup index: `idx_meter_aggregate_billing_dedup` excludes NULL FKs (replaces COALESCE hack)
- Performance API: per-meter detail + GHI unit normalization (Wh/m² → kWh/m²)
- Frontend: workbook-style performance table, generic invoice view from persisted line items
- Fixtures: `database/scripts/fixtures/moh01_dec2025.sql`

**v10.6 (Billing Engine Gap Analysis Fixes)** - Complete
- Migration: `043_billing_gap_analysis_fixes.sql` — org-scoped RLS for `billing_tax_rule`
- Billing API: per-meter available energy mode, country-scoped tax rules, configurable invoice direction, direction-aware reads
- Performance API: per-meter `available_kwh` populated
- Frontend: dynamic COD filtering, API-driven energy_category, persisted invoice amounts in expanded rows

**v10.7 (Legal Entity & Industry)** - Complete
- Migration: `044_legal_entity_industry_and_moh01_fixes.sql` — legal_entity table, counterparty.industry

**v10.8 (Contract Column Relocation)** - Complete
- Migration: `045_relocate_contract_columns.sql` — moved interconnection_voltage_kv, agreed_fx_rate_source, payment_security to proper tables

**v10.9 (CBE Portfolio Data Population)** - Complete
- Migration: `046_populate_portfolio_base_data.sql` — parent_contract_id hierarchy, 33 projects, contracts, amendments, exchange rates

**v10.10 (SAGE Contract IDs & Parent-Child Hierarchy)** - Complete
- Migration: `047_populate_sage_contract_ids.sql` — Part A: SAGE ERP contract numbers, payment terms, end dates for 27 contracts; Part B: `parent_contract_line_id` FK + MOH01 mother line 1000
- Self-referential hierarchy mirrors `contract.parent_contract_id` pattern
- Billing resolver detects mother lines (meter_id IS NULL) and resolves via child lines

**v10.11 (Pilot Project Data Population)** - Complete
- Migration: `049_pilot_project_data_population.sql` — Contract lines, clause tariffs, meter aggregates for 3 pilot projects (KAS01, NBL01, LOI01)
- 15 contract_line rows, 4 clause_tariff placeholders, 94 meter_aggregate rows, 8 contract_billing_product junction rows
- All `meter_id = NULL` (meters back-filled when actual meter data available)
- Bug fix: EXC-004 resolved — `cbe_billing_adapter.py` N/A misclassification fixed with product-pattern matching

**v10.17 (Live Data Pipeline & Billing Cycle Services)** - Complete
- No new migration — application-layer services and API endpoints only
- New package: `python-backend/services/billing/` with 4 services:
  - `tariff_rate_service.py` — dispatches deterministic (`RatePeriodGenerator`) and floating (`RebasedMarketPriceEngine`) tariff generation
  - `performance_service.py` — computes `plant_performance` from `meter_aggregate` + `production_forecast`
  - `invoice_service.py` — extracted from `api/billing.py` inline SQL; single source of truth for invoice generation
  - `billing_cycle_orchestrator.py` — dependency-graph runner (verify inputs → compute → generate)
- New models: `models/billing_cycle.py`, `models/reference_price_ingest.py`
- New adapter: `data-ingestion/processing/adapters/generic_billing_adapter.py` — passthrough for non-CBE clients
- New enum values: `SourceType.GENERIC`, `IngestionScope.REFERENCE_PRICES`
- New API endpoints:
  - `POST /api/ingest/reference-prices` — external MRP ingestion with API-key auth
  - `POST /api/projects/{id}/billing/generate-tariff-rates` — tariff rate generation
  - `POST /api/projects/{id}/billing/run-cycle` — full billing cycle orchestration
  - `POST /api/projects/{id}/plant-performance/compute` — automated performance computation
- Existing `POST /api/projects/{id}/billing/generate-expected-invoice` now delegates to `InvoiceService`
- Adapter registry expanded: `generic` source type falls through to `GenericBillingAdapter`
- Frontend: `GenerateAPIKeyDialog.tsx` and `OnboardingSummary.tsx` updated with `reference_prices` scope
- Client docs: `CLIENT_INSTRUCTIONS.md` updated with Sections 3 (FX Rates) and 4 (Reference Prices)

**v10.18 (oy_start_date as Canonical OY Anchor)** - Complete
- No new migration — data population script + application-layer code changes
- `clause_tariff.logic_parameters.oy_start_date` is now the single canonical OY anchor for all 10 computation paths
- Population script: `python-backend/scripts/populate_oy_start_date.py` — set `oy_start_date = cod_date` for 36 clause_tariff rows; LOI01 kept at Transfer Date (2019-10-31)
- All 10 OY code paths updated to read `oy_start_date` directly instead of falling back to `project.cod_date`

---

## Best Practices

### 1. Migration Best Practices

- **Never modify existing migrations** - Create new ones to fix issues
- **Test migrations locally** before pushing to remote
- **Use idempotent SQL** where possible:
  ```sql
  CREATE TABLE IF NOT EXISTS ...
  ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...
  ```
- **Document breaking changes** in commit messages
- **Keep migrations focused** - One logical change per migration
- **Number migrations sequentially** - No gaps in numbering

---

### 2. Data Management Best Practices

- **Keep fixtures small** - Only essential test data
- **Never commit real user data** - Use synthetic/anonymized data
- **Use semantic naming** - Descriptive file names
- **Document dependencies** - Use numbered prefixes for load order
- **Separate reference from fixtures** - Production vs. test data

---

### 3. Diagram Best Practices

- **Update diagrams after migrations** - Don't let them fall out of sync
- **Use document-migration.sh** - Assists with manual updates
- **Version diagrams** - Match diagram versions to schema versions
- **Export for presentations** - Save PNG/SVG to exports/

---

### 4. Git Commit Best Practices

Use semantic commit messages:

```bash
# Features
git commit -m "feat(db): Add contract_pii_mapping table"

# Fixes
git commit -m "fix(db): Correct foreign key constraint on clause table"

# Documentation
git commit -m "docs(db): Update schema diagram for v2.0"

# Migrations
git commit -m "migration(db): Add parsing status fields to contract"

# Snapshots
git commit -m "snapshot(db): v2.0 Phase 2 Contract Parsing Complete"
```

---

### 5. Backup Best Practices

- **Backup before major changes** - Use `backup_database.sh`
- **Weekly backups** (recommended for production)
- **Store backups securely** - Encrypt and store off-site
- **Test restore process** - Verify backups work

---

### 6. Team Collaboration

- **Coordinate migrations** - Avoid conflicts on numbered files
- **Review SCHEMA_CHANGES.md** after phase completion
- **Communicate breaking changes** - Notify team before deploying
- **Code review migrations** - Have another team member review DDL
- **Use feature branches** - Don't push migrations directly to main

---

## Links & Resources

### Official Documentation
- [Supabase Documentation](https://supabase.com/docs) - Database, Auth, Storage
- [PostgreSQL Documentation](https://www.postgresql.org/docs/) - SQL reference
- [Next.js Documentation](https://nextjs.org/docs) - Frontend framework

### Diagram Tools
- [Draw.io](https://app.diagrams.net) - Manual entity diagrams

### Project Files
- [SCHEMA_CHANGES.md](database/SCHEMA_CHANGES.md) - Version changelog
- [Contract Digitization Guide](contract-digitization/docs/IMPLEMENTATION_GUIDE.md) - Phase 2 plan
- [Data Ingestion Architecture](data-ingestion/docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md) - Phase 3 lake-house design
- [Ontology Framework Guide](contract-digitization/docs/ONTOLOGY_GUIDE.md) - Phase 4 clause relationships
- [Export & Reports Guide](IMPLEMENTATION_GUIDE_REPORT_GENERATION.md) - Phase 5 export/report workflows
- [Security Assessment](SECURITY_PRIVACY_ASSESSMENT.md) - Security controls and implementation status
- [Database Seed README](database/seed/README.md) - Data loading guide
- [Migrations README](database/migrations/README.md) - Migration guidelines

### GitHub
- [Repository](https://github.com/<org>/<repo>) - Source code
- [Actions](https://github.com/<org>/<repo>/actions) - CI/CD workflows
- [Issues](https://github.com/<org>/<repo>/issues) - Bug tracking

---

## Document Maintenance

**Update this guide**:
- After major schema changes
- When adding new scripts or workflows
- After team feedback
- Quarterly review for accuracy

**Keep current**:
- Troubleshooting section (add common issues)
- Scripts reference (document new scripts)
- Workflows (add new patterns)
- Best practices (refine as team learns)

**Version control**:
- Track changes in git
- Update "Last updated" date at top
- Reference specific schema versions

---

## Feedback & Questions

**Questions or improvements?**
- Contact the database team
- Create an issue on GitHub
- Submit a pull request with improvements
- Add to team retrospectives

**Contributing to this guide**:
1. Fork or create feature branch
2. Make improvements
3. Test changes with team
4. Submit pull request
5. Update "Last updated" date

---

**End of Database Management Guide**
