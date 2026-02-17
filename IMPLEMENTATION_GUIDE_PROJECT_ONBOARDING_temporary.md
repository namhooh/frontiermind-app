# Implementation Guide: Project Onboarding (COD Data Capture)

## Overview

This guide documents the schema changes, formula parameter storage design, calculator architecture, and ETL pipeline for capturing Commercial Operations Date (COD) data and supporting contractual tariff terms (Exhibit A / Annexure H).

**Migration:** `database/migrations/033_project_onboarding.sql`
**ETL Script:** `database/scripts/onboard_project.sql`

---

## 1. Gap Analysis Summary

The client captures project data at COD across 9 sections (Project Info, Pricing, Contacts, Installation, Documentation, Billing, VCOM, O&M, Guarantees). Cross-referencing against contractual tariff terms and the existing data architecture identified these gap categories:

| Gap Category | Examples | Resolution |
|---|---|---|
| **Missing typed columns** | Project capacity, contract term, counterparty registration | ALTER existing tables (migration 033 Section A) |
| **Missing unique constraints** | clause_tariff, customer_contact (no upsert support) | Add partial unique indexes (migration 033 Section B) |
| **Missing tables** | Grid Reference Price, documentation checklist, onboarding snapshots | CREATE new tables (migration 033 Section C) |
| **Missing charge taxonomy** | GRP requires variable/demand/tax classification on invoice lines | ALTER received_invoice_line_item (migration 033 Section A8) |
| **Rules engine bug** | `PERF_GUARANTEE` mapping vs `PERFORMANCE_GUARANTEE` in schema | Fix RULE_CLASSES dict (rules_engine.py) |
| **Missing formula parameters** | Available energy method, shortfall formula type | Extend CANONICAL_SCHEMAS (clause_examples.py) |
| **Missing calculators** | Available energy, GRP, production guarantee, shortfall, pricing | New Python calculator classes (Phase 3) |

---

## 2. Schema Changes (Migration 033)

### A. ALTER Existing Tables

| Table | New Columns | Purpose |
|---|---|---|
| `project` | external_project_id, sage_id, country, cod_date, installed_dc_capacity_kwp, installed_ac_capacity_kw, installation_location_url | Physical site identifiers and capacity |
| `contract` | external_contract_id, contract_term_years, interconnection_voltage_kv, amendments_post_ppa, payment_security_required, payment_security_details, ppa_confirmed_uploaded, agreed_fx_rate_source | PPA-specific terms |
| `counterparty` | registered_name, registration_number, tax_pin, registered_address | Legal registration |
| `asset` | capacity, capacity_unit, quantity | Equipment specifications |
| `meter` | serial_number, location_description, metering_type | Billing meter config |
| `production_forecast` | forecast_poa_irradiance | PVSyst completeness |
| `production_guarantee` | shortfall_cap_usd, shortfall_cap_fx_rule | Annual shortfall cap |
| `received_invoice_line_item` | charge_type, is_tax, tou_bucket | GRP charge taxonomy |

### B. New Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `grid_reference_price` | Annual calculated GRP per project | calculated_grp_per_kwh, total_variable_charges, total_kwh_invoiced, verification_status |
| `project_document` | Documentation checklist (Y/N + file path) | document_type, is_received, file_path |
| `project_onboarding_snapshot` | Versioned COD data snapshots | snapshot_version, effective_from, snapshot_data (JSONB) |

### C. Unique Constraints for Upsert Support

```sql
-- Project natural key
uq_project_org_external ON project(organization_id, external_project_id)

-- Contract natural key
uq_contract_project_external ON contract(project_id, external_contract_id)

-- Clause tariff composite key (was only non-unique index)
uq_clause_tariff_contract_group_validity ON clause_tariff(contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'))

-- Customer contact dedup
uq_customer_contact_email_role ON customer_contact(counterparty_id, LOWER(email), role) WHERE is_active = true
```

### D. Security: Credential Routing

PPC and data logger credentials (admin passwords, network access) must NOT be stored in `asset.description`. Route to `integration_credential` table (`009_integration_credential.sql`) with `auth_type = 'api_key'`. Store only model/label in `asset`.

---

## 3. Formula Parameter Storage

Two JSONB columns store formula parameters, split by domain:

| Column | Table | Domain | Used By |
|---|---|---|---|
| `normalized_payload` | `clause` | **Obligations** — what must be met | Rules engine (`rules_repository.get_evaluable_clauses`) |
| `logic_parameters` | `clause_tariff` | **Pricing** — how to calculate billing amounts | Billing engine (PricingRule) |

### Parameter Placement

| Parameter | Storage Location | Rationale |
|---|---|---|
| Performance guarantee variant/threshold/degradation | `clause.normalized_payload` (PERFORMANCE_GUARANTEE) | Obligation — rules engine evaluates compliance |
| Shortfall formula type + exceptions | `clause.normalized_payload` (PERFORMANCE_GUARANTEE) | Obligation — contractual consequence of breach |
| Available energy method + params | `clause.normalized_payload` (AVAILABILITY) | Obligation — defines "available energy" for curtailment |
| Solar discount, floor/ceiling rates | `clause_tariff.logic_parameters` | Pricing — per-tariff-line billing parameters |
| GRP construction rules | `clause_tariff.logic_parameters` | Pricing — defines how GRID reference price is derived |
| Escalation rate/base year/index | `clause_tariff.logic_parameters` | Pricing — per-tariff-line rate escalation |

---

## 4. Named Calculator Registry (Strategy Pattern)

Each formula variant is a separate Python calculator class, dispatched via a registry dict. The formula TYPE is stored as a code in JSONB; PARAMETERS are stored alongside.

### Calculator Domains

| Domain | Registry Dict | Type Code Location | Calculator File |
|---|---|---|---|
| Available Energy | `AVAILABLE_ENERGY_CALCULATORS` | `clause.normalized_payload.available_energy_method` | `services/calculations/available_energy.py` |
| Grid Reference Price | `GRP_CALCULATORS` | `clause_tariff.logic_parameters.grp_method` | `services/calculations/grid_reference_price.py` |
| Production Guarantee | (Rule class) | `clause.normalized_payload.variant` | `services/rules/production_guarantee_rule.py` |
| Shortfall Payment | (Standalone) | `clause.normalized_payload.shortfall_formula_type` | `services/rules/shortfall_payment.py` |
| Tariff Pricing | (Rule class) | `tariff_structure_type.code` + `logic_parameters` | `services/rules/pricing_rule.py` |

### Available Energy Methods

| Code | Class | Formula | Used By |
|---|---|---|---|
| `irradiance_interval_adjusted` | `IrradianceIntervalAdjustedCalculator` | E(x) = (E_hist/Irr_hist) × (1/Intervals) × Irr(x) | Ghana GRID contracts |
| `monthly_average_irradiance` | `MonthlyAverageIrradianceCalculator` | E = E_avg × (Irr_actual/Irr_ref) | Kenya FIXED contracts |
| `fixed_deemed` | `FixedDeemedCalculator` | E = deemed_rate × curtailed_intervals | Simple deemed contracts |

### Adding a New Formula Variant

| Step | What Changes |
|---|---|
| 1. New formula appears in contract | Write new Python calculator class |
| 2. Register in calculator registry | Add entry to `CALCULATORS` dict |
| 3. Extend `CANONICAL_SCHEMAS` | Add formula type code + required parameters |
| 4. Store parameters in JSONB | Onboarding SQL populates normalized_payload |
| 5. No schema migration needed | JSONB handles new parameters |

---

## 5. ETL Pipeline Architecture

```
staging tables (with batch_id)
  → pre-flight validation (fail fast on missing required FKs)
  → upserts in FK dependency order
  → post-load assertions
  → COMMIT (or ROLLBACK on any assertion failure)
```

### FK Dependency Order

1. `counterparty` (no FK dependencies)
2. `project` (→ organization)
3. `contract` (→ project, counterparty, contract_type, contract_status)
4. `asset` (→ project, asset_type)
5. `meter` (→ project)
6. `clause_tariff` (→ contract, tariff_structure_type, energy_sale_type, escalation_type, currency)
7. `customer_contact` (→ counterparty, organization)
8. `production_forecast` (→ project, organization)
9. `production_guarantee` (→ project, organization)
10. `project_document` (→ project, organization)
11. `project_onboarding_snapshot` (→ project, organization)

### Data Loading Methods

| Method | Command | Use Case |
|---|---|---|
| psql client-side | `\copy stg_project_core FROM 'file.csv' WITH (FORMAT csv, HEADER true)` | Bulk CSV import |
| Direct INSERT | `INSERT INTO stg_project_core VALUES (...)` | Scripted loads |
| Backend API | Future `/api/onboard/project` endpoint | Automated pipeline |

**Important:** Use `\copy` (client-side), NOT `COPY FROM` (requires superuser and won't work in hosted Supabase).

### Post-Load Assertions

- Forecast count matches staging
- Guarantee count matches staging
- Meter count matches staging
- Contract exists for project
- guaranteed_kwh positive
- Guarantee monotonically declining (warning only)
- discount_pct between 0 and 1
- floor_rate <= ceiling_rate

---

## 6. Files Modified/Created

| File | Action | Description |
|---|---|---|
| `database/migrations/033_project_onboarding.sql` | **Created** | Combined migration (ALTERs + CREATEs + RLS + seeds + CHECKs) |
| `database/scripts/onboard_project.sql` | **Created** | Staged ETL script |
| `database/SCHEMA_CHANGES.md` | **Updated** | v9.0 entry |
| `database/DATABASE_GUIDE.md` | **Updated** | Directory structure |
| `IMPLEMENTATION_GUIDE_PROJECT_ONBOARDING.md` | **Created** | This guide |
| `python-backend/services/rules_engine.py` | **Modified** | Fixed PERFORMANCE_GUARANTEE mapping |
| `python-backend/services/prompts/clause_examples.py` | **Modified** | Extended CANONICAL_SCHEMAS |
| `python-backend/services/calculations/__init__.py` | **Created** | Package init |
| `python-backend/services/calculations/available_energy.py` | **Created** | Available energy calculators |
| `python-backend/services/calculations/grid_reference_price.py` | **Created** | GRP calculators |
| `python-backend/services/rules/production_guarantee_rule.py` | **Created** | Production guarantee rule |
| `python-backend/services/rules/shortfall_payment.py` | **Created** | Shortfall payment calculator |
| `python-backend/services/rules/pricing_rule.py` | **Created** | GRID tariff pricing rule |
| `database/migrations/033_project_onboarding.sql` | **Modified** | Added sections G & H: upsert indexes + onboarding_preview table |
| `python-backend/api/onboarding.py` | **Created** | FastAPI endpoints (preview + commit) |
| `python-backend/models/onboarding.py` | **Created** | Pydantic models for onboarding data |
| `python-backend/services/onboarding/__init__.py` | **Created** | Package init |
| `python-backend/services/onboarding/onboarding_service.py` | **Created** | Two-phase orchestration service |
| `python-backend/services/onboarding/excel_parser.py` | **Created** | Label-anchored Excel parser |
| `python-backend/services/onboarding/ppa_parser.py` | **Created** | PPA PDF hybrid extractor (regex + LLM) |
| `python-backend/services/onboarding/normalizer.py` | **Created** | Code normalization for lookup tables |

---

## 7. Python Onboarding Service

### Architecture Overview

The onboarding service implements a **two-phase preview/commit workflow**:

```
Phase A (Preview): Upload files → Parse → Cross-validate → Store preview state → Return preview
Phase B (Commit):  Load preview → Apply overrides → SQL upserts → Return counts + IDs
```

This design ensures no production database writes occur until the user explicitly approves the previewed data.

### API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/onboard/preview` | API Key | Parse Excel + optional PPA PDF, return preview data |
| `POST` | `/api/onboard/commit` | API Key | Apply previewed data to production tables |

**Preview Request** (multipart form):
- `external_project_id` (required) — Client project identifier
- `external_contract_id` (required) — Client contract identifier
- `excel_file` (required) — COD onboarding Excel template
- `ppa_pdf_file` (optional) — PPA contract PDF for cross-validation

**Preview Response:**
- `preview_id` — UUID, valid for 1 hour
- `parsed_data` — Merged data from all sources
- `discrepancy_report` — Cross-validation findings
- `counts` — Row counts per entity type

**Commit Request** (JSON):
- `preview_id` — UUID from preview response
- `overrides` — Optional field overrides (e.g., corrected values)

**Commit Response:**
- `success` — Boolean
- `project_id`, `contract_id` — Created/updated entity IDs
- `warnings` — Non-fatal issues
- `counts` — Final row counts per table

### File Listing

| File | Purpose |
|------|---------|
| `api/onboarding.py` | FastAPI router with `preview` and `commit` endpoints |
| `models/onboarding.py` | Pydantic models: `ExcelOnboardingData`, `PPAContractData`, `MergedOnboardingData`, `OnboardingPreviewResponse`, `OnboardingCommitResponse`, etc. |
| `services/onboarding/onboarding_service.py` | Orchestration: parse → cross-validate → merge → store preview → commit via SQL upserts |
| `services/onboarding/excel_parser.py` | Label-anchored parser: finds labels in Excel cells and reads adjacent values |
| `services/onboarding/ppa_parser.py` | Hybrid extractor: regex patterns for structured fields, Claude LLM for complex clauses (guarantee tables, escalation rules) |
| `services/onboarding/normalizer.py` | Maps free-text values to lookup table codes (e.g., "Fixed" → `FIXED`, "KES" → `KES`) |

### Excel Parser Design

The Excel parser uses a **label-anchored** approach rather than fixed cell positions:

1. Scan all cells for known label patterns (e.g., "Project Name", "COD Date", "Installed Capacity")
2. Read the value from the adjacent cell (right or below)
3. Normalize values (dates, numbers, booleans)
4. Extract tabular sections (contacts, meters, assets) by detecting header rows

### PPA Hybrid Extraction

The PPA parser combines two strategies:

- **Regex patterns**: For structured fields (contract term, effective date, party names)
- **Claude LLM**: For complex contractual provisions (guarantee tables, escalation rules, payment security terms)

Confidence scores are tracked per field to flag low-confidence extractions in the discrepancy report.

### Cross-Validation and Discrepancy Reporting

When both Excel and PPA PDF are provided, the service cross-validates:

- Contract term (years)
- Solar discount percentage
- Floor/ceiling rates
- Capacity vs guarantee alignment

Discrepancies are reported with severity (`warning`/`error`), recommended values, and recommended source (`excel`/`pdf`).

### Source Priority Rules

Data merge uses: **Override > PPA (contractual terms) > Excel (operational data)**

| Data Domain | Primary Source | Rationale |
|-------------|---------------|-----------|
| Project info (name, capacity, COD) | Excel | Operational data |
| Contractual terms (term, discount, floor/ceiling) | PPA PDF | Legally binding |
| Guarantee schedule | PPA PDF | Contractual obligation |
| Contacts, meters, assets | Excel | Operational data |
| Payment security | PPA PDF | Contractual term |
| FX rate source | PPA PDF | Contractual definition |

---

## 8. SQL Script Fixes Applied (Migration 033 Sections G & H)

### 8A. Meter Upsert Support

- Created `stg_meters` staging table in `onboard_project.sql`
- Added Step 4.10: Meter INSERT with `ON CONFLICT (project_id, serial_number) DO UPDATE`
- Added meter count assertion in Step 5
- **Requires:** `uq_meter_project_serial` unique index (migration 033 section G1)

### 8B. Counterparty Conflict Key Fixed

- Changed counterparty INSERT from bare INSERT (no ON CONFLICT) to:
  `ON CONFLICT (counterparty_type_id, LOWER(name)) DO UPDATE SET registered_name, registration_number, tax_pin, registered_address`
- **Requires:** `uq_counterparty_type_name` unique index (migration 033 section G2)

### 8C. Onboarding Preview Table

- Moved `CREATE TABLE IF NOT EXISTS onboarding_preview` from runtime Python code to migration 033 section H
- Added RLS (service_role only) and expiry index
- Removed runtime DDL from `onboarding_service.py._store_preview()`

### 8D. Snapshot JSON Fixed

- Changed `row_to_json(spc.*)` to `to_jsonb(spc)` for proper JSONB storage in `project_onboarding_snapshot.snapshot_data`

### 8E. Source Hash from Python

- `stg_batch.source_file_hash` populated by Python service from SHA-256 of uploaded files
- Snapshot INSERT reads hash from `stg_batch` rather than computing in SQL
