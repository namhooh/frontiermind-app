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
- `database/diagrams/schema.mermaid.md`

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
- `database/diagrams/schema.mermaid.md` (to be updated)

---
