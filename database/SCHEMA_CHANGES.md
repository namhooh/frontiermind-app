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

### v2.0 - TBD (Phase 2 - Contract Parsing)

**Description:** Added contract parsing infrastructure with PII protection.

**Schema File:** `database/versions/v2.0_phase2_parsing.sql` (not yet created)

**Migrations:**
- `database/migrations/002_add_contract_pii_mapping.sql` - Encrypted PII storage
- `database/migrations/003_add_contract_parsing_fields.sql` - Contract parsing status tracking
- `database/migrations/004_enhance_clause_table.sql` - AI extraction fields
- `database/migrations/005_add_audit_trails.sql` - Audit logging

**Planned Changes:**
- New table: contract_pii_mapping
- contract table: parsing_status, pii_detected_count, clauses_extracted_count
- clause table: summary, beneficiary_party, confidence_score
- Enhanced audit trails for contract processing

**Diagrams:**
- `database/diagrams/entity_diagram_v2.0.drawio` (to be created)
- `database/diagrams/schema.mermaid.md` (auto-updated)

---
