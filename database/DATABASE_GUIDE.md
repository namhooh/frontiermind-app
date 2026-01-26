# Database Management Guide
**Energy Contract Compliance & Invoicing System**

Quick links: [Directory Structure](#directory-structure) | [Workflows](#common-workflows) | [Scripts](#scripts-reference) | [Troubleshooting](#troubleshooting)

Last updated: 2026-01-26

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
│   └── load_test_data.sh                  # Load seed data
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
- New: `v_security_events` VIEW for security monitoring
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
- **Implementation Guide:** `IMPLEMENTATION_GUIDE_REPORTS.md`

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
- [Export & Reports Guide](database/IMPLEMENTATION_GUIDE_REPORTS.md) - Phase 5 export/report workflows
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
