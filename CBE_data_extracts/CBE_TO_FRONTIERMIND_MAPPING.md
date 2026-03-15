# CBE to FrontierMind Data Mapping

This document maps CBE's data architecture to FrontierMind's canonical schema and documents the complete pipeline from source documents through extraction, validation, staging, and dashboard display. CBE is the first client adapter; the mapping demonstrates how client-specific data fits into the platform's generic tables.

**Sources:** AM Onboarding Template (Excel), PPA Contract PDFs, Utility Invoices (GRP — Grid Reference Price), Snowflake data warehouse, Operations Plant Performance Workbook, Operating Revenue Masterfile.

**Schema version:** v10.16 (migration 060)
**Latest population step:** Step 11 — Forecast Extension to Contract End (2026-03-09)
**Latest architecture update:** Section 32 — Live Data Pipeline & Billing Cycle (2026-03-15)

**Companion documentation:**
- [`contract-digitization/docs/IMPLEMENTATION_GUIDE.md`](../contract-digitization/docs/IMPLEMENTATION_GUIDE.md) — Full contract digitization pipeline (OCR, PII, clause extraction, ontology)
- [`contract-digitization/docs/POWER_PURCHASE_ONTOLOGY_FRAMEWORK.md`](../contract-digitization/docs/POWER_PURCHASE_ONTOLOGY_FRAMEWORK.md) — Ontology concepts, clause categories, relationship types
- [`database/scripts/project-onboarding/audits/`](../database/scripts/project-onboarding/audits/) — Per-project onboarding audit trail
- [`database/migrations/046_populate_portfolio_base_data.sql`](../database/migrations/046_populate_portfolio_base_data.sql) — Full portfolio population (Section 17)
- [`database/migrations/047_populate_sage_contract_ids.sql`](../database/migrations/047_populate_sage_contract_ids.sql) — SAGE contract IDs, payment terms, end dates (Section 18) + parent-child contract line hierarchy (Section 19)
- [`database/migrations/049_pilot_project_data_population.sql`](../database/migrations/049_pilot_project_data_population.sql) — Pilot data: contract lines, tariffs, meter aggregates for KAS01, NBL01, LOI01 (Section 20)
- [`CBE_data_extracts/CBE_DATA_POPULATION_WORKFLOW.md`](./CBE_DATA_POPULATION_WORKFLOW.md) — End-to-end CBE data population workflow (11-step pipeline, field authority matrix, discrepancy tracking)
- [`python-backend/reports/cbe-population/step1_2026-03-07.json`](../python-backend/reports/cbe-population/step1_2026-03-07.json) — Step 1 dry-run report (23 discrepancies, 5/5 gates passed)
- [`database/migrations/055_step4_billing_product_tariff_structure.sql`](../database/migrations/055_step4_billing_product_tariff_structure.sql) — Step 4: billing product linking, contract_billing_product junction, clause_tariff placeholders
- [`python-backend/reports/cbe-population/step4_2026-03-08.json`](../python-backend/reports/cbe-population/step4_2026-03-08.json) — Step 4 report (5/5 gates passed)
- [`database/migrations/056_billing_tax_rule_project_scope.sql`](../database/migrations/056_billing_tax_rule_project_scope.sql) — Migration 056: project_id column on billing_tax_rule (Section 28)
- [`python-backend/scripts/step9_mrp_and_meter_population.py`](../python-backend/scripts/step9_mrp_and_meter_population.py) — Step 9 & 10: MRP formula OCR, meter readings, plant performance (Section 29)
- [`python-backend/reports/cbe-population/step9_2026-03-09.json`](../python-backend/reports/cbe-population/step9_2026-03-09.json) — Step 9 run report
- [`python-backend/reports/cbe-population/step8_2026-03-08.json`](../python-backend/reports/cbe-population/step8_2026-03-08.json) — Step 8 report: invoice calibration & tax rule extraction
- [`python-backend/scripts/step10b_tariff_rate_population.py`](../python-backend/scripts/step10b_tariff_rate_population.py) — Step 10b: Tariff rate population (Section 30)
- [`python-backend/scripts/extend_forecasts.py`](../python-backend/scripts/extend_forecasts.py) — Step 11: Forecast extension engine (Section 31)
- [`python-backend/reports/cbe-population/extend_forecasts_2026-03-09.json`](../python-backend/reports/cbe-population/extend_forecasts_2026-03-09.json) — Step 11 report

---

## 1. Architecture Philosophy

FrontierMind is a **power purchase ontology, contract compliance, and financial verification platform**. It owns the canonical data model — the domain-level definitions of what a contract, tariff line, meter reading, and invoice are. Clients bring their own data warehouses and source systems; FrontierMind does not replace them.

### Client Data Warehouse vs FrontierMind Platform

```
Client Source Systems (ERP, Billing, SCADA, Monitoring)
        |
Client Data Warehouse (e.g. CBE Snowflake)
        |  Client retains ownership for their own
        |  analytics, BI, finance reporting, audit history
        |
   Client Adapter (maps client schema to FrontierMind canonical model)
        |
        v
+-------------------------------------------------------+
| FrontierMind Canonical Model                          |
|                                                       |
|  Ontology Layer                                       |
|    tariff_type, clause_category, clause_type,         |
|    energy_sale_type, escalation_type                  |
|    (org-scoped lookup tables)                         |
|    (FrontierMind defines the domain vocabulary)       |
|                                                       |
|  Core Tables                                          |
|    contract, clause_tariff, contract_line,            |
|    meter_aggregate, tariff_rate,                      |
|    exchange_rate, invoice tables, price_index,        |
|    production_forecast, production_guarantee,         |
|    plant_performance, customer_contact                |
|    (generic — no client-specific columns)             |
|                                                       |
|  Engines                                              |
|    Pricing Calculator, Comparison Engine,             |
|    Contract Parser, Compliance Rules,                 |
|    Performance Tracker                                |
|    (operate on generic columns only)                  |
+-------------------------------------------------------+
```

### Why this separation

1. **FrontierMind owns the ontology, not the client's raw data.** Clients like CBE have data warehouses with their own conventions (SCD2 dimensional modeling, ERP-specific product codes, internal identifiers). FrontierMind defines what METERED_ENERGY, AVAILABLE_ENERGY, and EQUIP_RENTAL mean at the domain level. Client adapters translate between the two.

2. **The client keeps their warehouse.** CBE's Snowflake serves their finance team, auditors, and BI dashboards — use cases outside FrontierMind's scope. FrontierMind does not need to replicate SCD2 history or serve general-purpose analytics. The platform stores current-state operational data and its own audit trail.

3. **Multi-client by design.** A second client will have a completely different source schema (different ERP, different column names, different product codes). Only the adapter changes — the canonical model, ontology, and engines remain the same.

4. **Each layer solves its own data quality problems.** CBE's SCD2 pipeline may create duplicate versions when no business data changed — that is CBE's ETL concern to fix. FrontierMind's adapter filters to current-state records and applies its own change detection before writing to the canonical model.

---

## 2. Principles

1. **No client-specific columns on core tables** — CBE identifiers live in `source_metadata` JSONB
2. **Adapter writes, core reads** — The CBE adapter ingests data and maps to generic columns; the pricing calculator and comparison engine operate on generic columns only
3. **`tariff_group_key`** groups the same logical tariff line across time periods
4. **`total_production`** on `meter_aggregate` is the final billable quantity
5. **Tariff selection logic is generic** — FIXED/GRID/GENERATOR structures are platform-level concepts, not CBE-specific

---

## 3. Document Input Specifications

### 3.1 AM Onboarding Template (Excel)

**Parser:** `python-backend/services/onboarding/excel_parser.py` — label-anchored, resilient to row shifts

The Excel template has a **3-sheet structure**:

| Sheet | Role | Key Data Extracted |
|-------|------|--------------------|
| **Pricing & Payment Info** | Project, customer, contract, tariff | IDs, names, COD date, capacity, tariff rates, escalation rules, contacts |
| **Technical Information** | Equipment and metering | Meter serial numbers (comma-separated), asset table (PV modules, inverters, transformers) |
| **Yield Report** | Production forecasts | Monthly energy (kWh), GHI, POA, PR, degradation factors |

**Label maps** (case-insensitive, position-independent):

| Map | Fields | Examples |
|-----|--------|---------|
| `PROJECT_INFO_LABELS` (13) | `external_project_id`, `project_name`, `country`, `customer_name`, `sage_id`, `cod_date`, `installed_dc_capacity_kwp`, `installed_ac_capacity_kw`, `installation_location_url` | "project id", "cod date", "installed dc capacity" |
| `CUSTOMER_INFO_LABELS` (8) | `registered_name`, `registration_number`, `tax_pin`, `registered_address`, `customer_email`, `customer_country` | "registered name", "tax pin" |
| `CONTRACT_INFO_LABELS` (16) | `contract_name`, `contract_type_code`, `contract_term_years`, `effective_date`, `end_date`, `interconnection_voltage_kv`, `payment_security_required/details`, `agreed_fx_rate_source`, `ppa_confirmed_uploaded`, `has_amendments` | "contract term", "payment security" |
| `TARIFF_INFO_LABELS` (40+) | `contract_service_type`, `energy_sale_type`, `escalation_type`, `billing_currency`, `base_rate`, `discount_pct`, `floor_rate`, `ceiling_rate`, `grp_method`, `payment_terms`, `product_to_be_billed`, `equipment_rental_rate`, `bess_fee` | "floor tariff per kwh", "billing frequency" |

**Multi-value handling:**
- **Billing products**: Multiple "Product to be billed" rows → `product_to_be_billed_list` (sorted by row position)
- **Service types**: Multiple "Contract Service/Product Type" rows → `contract_service_types` list (creates one `clause_tariff` per type)

**Layout detection**: Detects structured layout (DESCRIPTION/DETAILS columns) vs legacy (value-right-of-label). Filters placeholder text ("select from dropdown", "am to input").

### 3.2 PPA Contract PDF

Two pipelines share LlamaParse OCR but diverge in extraction strategy:

#### 3.2a Full Contract Digitization (clause extraction + compliance)

Reference: `contract-digitization/docs/IMPLEMENTATION_GUIDE.md`

The full pipeline for parsing any PPA contract into clauses, relationships, and obligations:

```
Step 1: Document Upload (PDF/DOCX)
Step 2: OCR — LlamaParse API (do_not_cache=True, ~$0.30/100 pages)
         Extracts text from scanned/native PDFs, preserves tables/headers/sections
Step 3: PII Detection — Presidio (LOCAL, no external APIs)
         Detects: emails, SSNs, phone numbers, names, contract IDs, addresses
         Custom recognizers: CONTRACT_ID (PPA-NNNN-NNNNNN), STREET_ADDRESS
         Person denylist: "Force Majeure", "Commercial Operation Date", etc.
         Section-aware: restricts NER to PII-heavy sections (notices, signature blocks)
Step 4: PII Anonymization — Presidio (LOCAL)
         Replaces PII with <EMAIL_REDACTED>, <NAME_REDACTED>, etc.
         Stores encrypted re-identification mapping in DB
         ORGANIZATION entities kept (needed for context)
Step 4.5: Contract Metadata Extraction — Claude API (~$0.05/contract)
         Type classification (PPA, O&M, EPC, ESA, VPPA, SSA)
         Counterparty fuzzy matching (rapidfuzz token_set_ratio ≥80%)
         Effective date, term years → extraction_metadata JSONB
Step 5: Clause Extraction — Claude API (anonymized text only, ~$0.50-1.00/contract)
         Extraction modes: single_pass, two_pass, or hybrid
         Extracts: availability, LD, pricing, payment, force majeure, termination, etc.
         Returns normalized_payload JSONB per clause
         Uses canonical schemas (POWER_PURCHASE_ONTOLOGY_FRAMEWORK.md)
Step 5.5: Cross-Verification
         Validates clause_type + clause_category against DB lookup tables (13 categories)
         Unmatched codes → preserved in normalized_payload as _unmatched_*
         FK set to NULL for unresolved codes
Step 6: Database Storage
         contract, clause, contract_pii_mapping tables
Step 7: Post-Processing
         Targeted extraction for missing mandatory categories
         Payload normalization using canonical ontology schemas
         Payload enrichment via Claude with gold-standard examples
Step 8: Relationship Detection (Ontology)
         Auto-detects: TRIGGERS (breach→LD), EXCUSES (FM→availability),
         GOVERNS (CP→obligations), INPUTS (pricing→payment)
         Stores in clause_relationship table with confidence scores (min 0.70)
         Supports cross-contract relationships (O&M MAINTENANCE → PPA AVAILABILITY)
         Marked is_inferred=True, inferred_by='pattern_matcher'
```

**Key files:** `python-backend/services/contract_parser.py`, `python-backend/services/pii_detector.py`, `python-backend/db/lookup_service.py`, `python-backend/services/ontology/relationship_detector.py`

**Contract type profiles** (`CONTRACT_TYPE_PROFILES`): Maps each contract type to mandatory and optional clause categories for completeness validation.

#### 3.2b Onboarding PPA Extraction (tariff parameters + guarantee tables)

**Parser:** `python-backend/services/onboarding/ppa_parser.py`
**Prompt:** `python-backend/services/prompts/onboarding_extraction_prompt.py`
**Model:** `claude-sonnet-4-5-20250929` (max 8192 tokens, max 150K input chars)
**Output:** `PPAContractData` (in `python-backend/models/onboarding.py`)

Specialized pipeline for extracting onboarding-specific data from PPA contracts:

```
Phase 1 (Deterministic regex — confidence 1.0):
  Guarantee table:
    - 20-year markdown tables: | Year N | number | number |
    - Alt: whitespace-separated rows (N   number   number)
    - Requires ≥10 matching rows
  Pricing parameters (regex near keywords):
    - Discount percentage (near "discount")
    - Floor rate (near "floor")
    - Ceiling rate (near "ceiling")

Phase 2 (Claude LLM — variable confidence):
  Part I — Key Terms:
    - Contract term (initial + extensions), effective date, payment security
  Annexure A — Definitions:
    - Agreed Exchange Rate definition
  Annexure C — Tariff/Pricing:
    - Pricing formula, per-component escalation rules
    - GRP parameters (exclude VAT/demand/savings, time window, due days, verification deadline)
    - Payment terms, default interest rate (benchmark, spread, accrual method)
  Annexure E — Available Energy:
    - Method (irradiance_interval_adjusted / monthly_average / fixed_deemed)
    - Formula text, variable definitions (symbol/definition/unit)
    - Irradiance threshold (W/m²), measurement interval (minutes)
  Annexure H — Production Guarantee / Shortfall:
    - Formula type, annual cap, FX rule, excused events
  Early Termination:
    - Termination payment schedule

Merge (regex values override LLM at confidence 1.0):
  → TariffExtraction (discount, floor, ceiling, EscalationRule list)
  → GRPExtraction (exclude flags, time window, due days)
  → ShortfallExtraction (formula type, cap, excused events)
  → PPAContractData with confidence_scores (9 scored fields)
```

**Confidence scoring:** 9 fields scored: `contract_term_years`, `solar_discount_pct`, `floor_rate`, `ceiling_rate`, `shortfall_formula`, `excused_events`, `payment_terms`, `available_energy_method`, `grp_parameters`.

### 3.3 Utility Invoices — Grid Reference Price (GRP)

**Parser:** `python-backend/services/grp/extraction_service.py`
**Prompt:** `python-backend/services/prompts/grp_extraction_prompt.py`
**Model:** `claude-sonnet-4-20250514`

Pipeline: Validate → Hash → S3 → OCR (LlamaParse) → Claude structured extraction → GRP calculation → `reference_price` upsert

**Line item classification:**

| Type Code | Description | Used in GRP Calc |
|-----------|-------------|-----------------|
| `VARIABLE_ENERGY` | Per-kWh energy consumption charges | Yes |
| `DEMAND` | Per-kW/kVA demand charges | No |
| `FIXED` | Monthly fixed charges | No |
| `TAX` | Taxes, levies, surcharges (VAT, NHIL, GETFUND, ESLA) | No |

**Time-of-use periods:** `peak` (6pm-10pm), `off_peak` (10pm-6am), `standard` (6am-6pm), `flat` (no TOU)

**Extraction output:** `ExtractionResult` with `invoice_metadata` (number, date, billing period, utility, account, total), `line_items[]`, `extraction_confidence` (high/medium/low).

### 3.4 Plant Performance Workbook

Operational data — see [Section 6.2 (Meter Readings)](#2-cbe-meter-readings--meter_aggregate) for `meter_aggregate` mapping and [Section 6.2b (Plant Performance)](#2b-plant-performance--plant_performance) for `plant_performance` mapping.

**Import endpoint:** `POST /api/projects/{project_id}/plant-performance/import` — parses the Operations workbook Excel format, populates per-meter `meter_aggregate` rows (energy_kwh, available_energy_kwh, opening/closing readings, ghi/poa irradiance) and derived `plant_performance` rows (actual_pr, comparisons).

**Manual entry:** `POST /api/projects/{project_id}/plant-performance/manual` — single-month per-meter entry with automatic performance metric computation.

### 3.5 Operating Revenue Masterfile

Tariff logic reference — `Inp_Proj` row mappings referenced throughout [Section 6.1 (Contract Lines)](#1-cbe-contract-lines--clause_tariff).

---

## 4. Extraction & Normalization Pipeline

### 4.1 Normalizer Mappings

**File:** `python-backend/services/onboarding/normalizer.py`

Converts free-text Excel values to database enum codes via case-insensitive lookup:

| Map | Entries | Output Codes |
|-----|---------|-------------|
| `ESCALATION_TYPE_MAP` | 12 | `FIXED_INCREASE`, `FIXED_DECREASE`, `PERCENTAGE`, `US_CPI`, `REBASED_MARKET_PRICE`, `NONE` |
| `ENERGY_SALE_TYPE_MAP` | 13 | `FIXED_SOLAR`, `FLOATING_GRID`, `FLOATING_GENERATOR`, `FLOATING_GRID_GENERATOR`, `NOT_ENERGY_SALES` |
| `CONTRACT_SERVICE_TYPE_MAP` | 14 | `ENERGY_SALES`, `EQUIPMENT_RENTAL_LEASE`, `LOAN`, `BESS_LEASE`, `ENERGY_AS_SERVICE`, `OTHER_SERVICE`, `NOT_APPLICABLE` |
| `PAYMENT_TERMS_MAP` | 7 | `NET_30`, `NET_60`, `NET_15` |
| `METERING_TYPE_MAP` | 6 | `export_only`, `net`, `gross`, `bidirectional` |

**Special functions:**

| Function | Behavior |
|----------|----------|
| `normalize_percentage(value)` | `21` → `0.21`, `"21%"` → `0.21`, `0.21` → `0.21` |
| `normalize_boolean(value)` | `Y/Yes/True/1` → `True`, handles prefixed forms like `"Yes - details"` |
| `normalize_contact_invoice_flag(value)` | Three-state: `"Yes"` → `(True, False)`, `"Escalation only"` → `(True, True)`, `"No"` → `(False, False)` |
| `extract_billing_product_code(value)` | `"ENER002 - Metered Energy"` → `"ENER002"` |
| `normalize_currency(value)` | Uppercases + aliases: `"US$"` → `"USD"`, `"CEDI"` → `"GHS"` |

### 4.2 Cross-Validation

**Method:** `OnboardingService._cross_validate()` in `python-backend/services/onboarding/onboarding_service.py`

| Check | Severity | Details |
|-------|----------|---------|
| Critical field completeness | `error` | 6 fields: `cod_date`, `customer_name`, `contract_term_years`, `installed_dc_capacity_kwp`, `billing_currency`, `base_rate` |
| Empty collections | `warning` | contacts, meters |
| Data sparseness | `error` | If <50% of 15 key fields populated |
| Excel vs PPA comparison | `warning` | `contract_term_years`, `solar_discount_pct`, `floor_rate`, `ceiling_rate` |
| Guarantee completeness | `warning` | Missing operating years |
| COD vs effective_date coherence | `warning` | `effective_date` should not be after COD |
| Low-confidence LLM extractions | `warning` | Fields with confidence < 0.7 |

**Real-world example (MOH01 audit):** Excel had `contract_term_years = 25`, PPA had `20 + 2×5yr extensions`. Resolution: PPA's 20 chosen (extensions stored in `extraction_metadata`). Excel had blank pricing fields; PPA populated `discount_pct`, `floor_rate`, `ceiling_rate`. See `database/scripts/project-onboarding/audits/GH_MOH01_ONBOARDING_AUDIT.md` Section 2.1.

### 4.3 Merge Priority

**Priority order: Override > PPA (contractual terms) > Excel (operational data)**

| Field Group | Priority | Rationale |
|-------------|----------|-----------|
| `external_project_id`, `external_contract_id` | Override > Excel | Required identifiers |
| `contract_term_years` | PPA `initial_term_years` > PPA `contract_term_years` > Excel | Legal contract authoritative |
| `discount_pct`, `floor_rate`, `ceiling_rate` | PPA tariff > Excel | Contractual pricing |
| `payment_security` | PPA enriches Excel | PPA has structured details |
| `agreed_fx_rate_source` | PPA > Excel | Contractual term |
| `payment_terms` | PPA > Excel | Contractual term |
| Guarantees | PPA only | 20-year table from contract |
| Contacts, meters, assets, forecasts | Excel only | Operational data |
| Tariff lines | Excel base + PPA enrichment | PPA adds `logic_parameters_extra` |

**Multi-service-type tariff lines:** When `len(contract_service_types) > 1`, additional tariff lines are created:
- `EQUIPMENT_RENTAL_LEASE` → uses `excel.equipment_rental_rate`
- `BESS_LEASE` → uses `excel.bess_fee`
- `LOAN` → uses `excel.loan_repayment_value`

---

## 5. Two-Phase Onboarding Workflow

### 5.1 Phase A: Preview

**Endpoint:** `POST /api/onboard/preview` (`python-backend/api/onboarding.py`)
**Auth:** API key → `organization_id`
**Input:** `excel_file` (required, multipart) + `ppa_pdf_file` (optional) + `external_project_id` + `external_contract_id`

```
Parse Excel (ExcelParser) ──→ Parse PPA PDF (PPAOnboardingExtractor, optional)
        │                              │
        └──────── Cross-validate ──────┘
                       │
                    Merge (Override > PPA > Excel)
                       │
               SHA-256 file hash
                       │
          Store in onboarding_preview (1hr expiry)
                       │
                       ▼
    OnboardingPreviewResponse {preview_id, parsed_data, discrepancy_report, counts}
```

### 5.2 Phase B: Commit

**Endpoint:** `POST /api/onboard/commit` (`python-backend/api/onboarding.py`)
**Auth:** API key → `organization_id`
**Input:** `preview_id` (UUID) + `overrides` (dict)
**Orchestrator:** `python-backend/services/onboarding/onboarding_service.py`

```
Load preview (validate not expired) ──→ Apply user overrides
        │
Create 9 staging temp tables (ON COMMIT DROP)
        │
Populate staging from MergedOnboardingData
        │
Execute SQL upserts (onboard_project.sql sections 4.1-4.11)
        │
Insert PAYMENT_TERMS clause (non-fatal)
        │
Generate rate periods (RatePeriodGenerator, non-fatal)
        │
Delete preview state
        │
        ▼
OnboardingCommitResponse {success, project_id, contract_id, warnings, counts}
```

### 5.3 Staging Tables

9 temporary staging tables from `database/scripts/project-onboarding/onboard_project.sql` Step 1:

| Staging Table | Production Table(s) | Key Columns |
|---|---|---|
| `stg_batch` | (audit) | `batch_id` (UUID), `source_file`, `source_file_hash`, `loaded_at` |
| `stg_project_core` | `project`, `counterparty`, `contract` | `organization_id`, `external_project_id`, `customer_name`, `cod_date`, `installed_dc_capacity_kwp`, `contract_term_years`, `payment_security_required/details`, `agreed_fx_rate_source`, `payment_terms`, `extraction_metadata` (JSONB) |
| `stg_tariff_lines` | `clause_tariff` | `tariff_group_key`, `tariff_type_code`, `energy_sale_type_code`, `escalation_type_code`, `billing_currency_code`, `base_rate`, `discount_pct`, `floor_rate`, `ceiling_rate`, `escalation_value`, `grp_method`, `logic_parameters_extra` (JSONB) |
| `stg_contacts` | `customer_contact` | `role`, `full_name`, `email`, `phone`, `include_in_invoice`, `escalation_only` |
| `stg_forecast_monthly` | `production_forecast` | `forecast_month` (DATE), `operating_year`, `forecast_energy_kwh`, `forecast_ghi`, `forecast_poa`, `forecast_pr`, `degradation_factor`, `source_metadata` (JSONB) |
| `stg_guarantee_yearly` | `production_guarantee` | `operating_year`, `year_start_date`, `year_end_date`, `guaranteed_kwh`, `guarantee_pct_of_p50`, `p50_annual_kwh`, `shortfall_cap_usd`, `shortfall_cap_fx_rule` |
| `stg_installation` | `asset` | `asset_type_code`, `asset_name`, `model`, `serial_code`, `capacity`, `capacity_unit`, `quantity` |
| `stg_meters` | `meter` | `serial_number`, `location_description`, `metering_type`, `is_billing_meter` |
| `stg_billing_products` | `contract_billing_product` | `product_code`, `is_primary` |

### 5.4 Pre-Flight Validation (Step 3)

8 checks that abort the transaction on failure:

1. Organization exists (`LEFT JOIN organization`)
2. Tariff type codes resolve (`LEFT JOIN tariff_type`)
3. Energy sale type codes resolve (`LEFT JOIN energy_sale_type`)
4. Currency codes resolve (`LEFT JOIN currency`)
5. Asset type codes resolve (`LEFT JOIN asset_type`)
6. Billing product codes resolve (org-scoped + canonical)
7. COD date is present (`NOT NULL`)
8. `guaranteed_kwh` is positive (`> 0`)

### 5.5 Upsert Order (Step 4)

11 upserts in FK dependency order:

| Step | Target Table | Conflict Key | Conflict Behavior |
|------|-------------|-------------|-------------------|
| 4.1 | `counterparty` | `(counterparty_type_id, LOWER(name))` | UPDATE registered_name, registration_number, tax_pin, registered_address |
| 4.2 | `project` | `(organization_id, external_project_id)` | UPDATE cod_date, capacities, sage_id, country, location_url |
| 4.3 | `contract` | `(project_id, external_contract_id)` | UPDATE counterparty_id, name, dates, term_years, voltage, payment_security, fx_source, payment_terms, metadata |
| 4.4 | `asset` | — | `ON CONFLICT DO NOTHING` |
| 4.5 | `clause_tariff` | `(contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'))` | UPDATE base_rate, logic_parameters, tariff_type_id, energy_sale_type_id, escalation_type_id |
| 4.6 | `customer_contact` | `(counterparty_id, LOWER(email), role)` | UPDATE full_name, phone |
| 4.7 | `production_forecast` | `(project_id, forecast_month)` | UPDATE forecast_energy_kwh, GHI, POA, PR, degradation_factor |
| 4.8 | `production_guarantee` | `(project_id, operating_year)` | UPDATE year dates, guaranteed_kwh, pct_of_p50, p50_annual_kwh, shortfall_cap, fx_rule |
| 4.9 | `meter` | `(project_id, serial_number)` | UPDATE location_description, metering_type |
| 4.10 | `contract_billing_product` | `(contract_id, billing_product_id)` | UPDATE is_primary. Uses `LATERAL` subquery: `ORDER BY organization_id NULLS LAST LIMIT 1` (prefers org-scoped over canonical) |
| 4.11 | `tariff_rate` | `(clause_tariff_id, contract_year) WHERE rate_granularity = 'annual'` | `DO NOTHING`. Creates Year 1 where `effective_rate_billing_ccy = base_rate` |

**Step 4.5 detail:** `logic_parameters` JSONB is built from `discount_pct`, `floor_rate`, `ceiling_rate`, `escalation_value`, `grp_method` merged with `logic_parameters_extra`.

### 5.6 Post-Load Assertions (Step 5)

8 checks after all upserts:

| Check | Severity |
|-------|----------|
| Project exists after upsert | EXCEPTION |
| Forecast row count ≥ staging count | EXCEPTION |
| Guarantee row count ≥ staging count | EXCEPTION |
| Meter row count ≥ staging count | EXCEPTION |
| Contract exists for the project | EXCEPTION |
| Billing product count ≥ staging count AND exactly 1 primary per contract | EXCEPTION |
| Tariff rate (annual) count ≥ number of active tariffs with base_rate | EXCEPTION |
| Data quality: `guaranteed_kwh > 0`, guarantee monotonically declining (WARNING only), `discount_pct ∈ [0,1]`, `floor_rate ≤ ceiling_rate` | EXCEPTION (except declining = WARNING) |

The entire script runs inside `BEGIN` ... `COMMIT` — any exception triggers full rollback.

### 5.7 Post-Commit: Rate Period Generation

**File:** `python-backend/services/tariff/rate_period_generator.py`

Creates `tariff_rate` rows (rate_granularity='annual') for Years 1..N based on escalation type:

| Escalation Type | Formula | Example |
|----------------|---------|---------|
| `NONE` | Flat rate, no change | `0.1087` every year |
| `FIXED_INCREASE` | `base_rate + escalation_value × (year - 1)` | Linear |
| `FIXED_DECREASE` | `max(0, base_rate - escalation_value × (year - 1))` | Linear, floored at 0 |
| `PERCENTAGE` | `base_rate × (1 + escalation_value)^(year - 1)` | Compound |

**Non-deterministic types skipped** (require external data): `US_CPI`, `REBASED_MARKET_PRICE`

**Period calculation:** Year 1 starts at `valid_from`. Year 2 can start at `escalation_start_date` (from `logic_parameters`) if provided. `is_current = true` set on period containing today's date (enforced by unique partial index).

**Database behavior:** Year 1 row updated (set `period_end`, `is_current`, `effective_rate_billing_ccy`). Years 2..N inserted with `ON CONFLICT DO NOTHING` (idempotent). `calc_status = 'computed'` for deterministic types.

### 5.8 Per-Project Audit Format

After each onboarding, create audit doc in `database/scripts/project-onboarding/audits/`.

**Standard sections:**
1. Entity extraction summary (all staging data)
2. Entity count summary (rows per table)
3. Cross-source discrepancies (Excel vs PPA)
4. Pipeline regressions (vs expected output)
5. Open items

**Template:** `GH_MOH01_ONBOARDING_AUDIT.md`

---

## 6. Table Mappings

### 1. CBE Contract Lines → `clause_tariff`

CBE provides contract line data from `dim_finance_contract_line` (Snowflake/CSV) and commercial parameters from the AM Onboarding Template and Operating Revenue Masterfile (`Inp_Proj` tabs).

#### Base Fields (from Snowflake)

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CONTRACT_LINE_UNIQUE_ID` | `tariff_group_key` | Stable key grouping all versions of the same line across periods (e.g. `CONZIM00-2025-00002-4000`) |
| `CONTRACT_NUMBER` | `contract_id` (FK) | Resolved via contract lookup by external reference |
| `LINE_NUMBER` | `source_metadata.external_line_id` | e.g. "4000" |
| `PRODUCT_CODE` | `source_metadata.product_code` | e.g. "ENER0001" |
| `METERED_AVAILABLE` | `source_metadata.metered_available` | "EMetered" or "EAvailable" |
| `UNIT_PRICE` | `base_rate` | The per-unit tariff rate |
| `CURRENCY_CODE` | `currency_id` (FK) | Resolved via `currency.code` lookup |
| `VALID_FROM` | `valid_from` | Tariff effective start date |
| `VALID_TO` | `valid_to` | Tariff effective end date |
| `METER_ID` (if metered) | `meter_id` (FK) | Resolved via meter lookup |
| (derived from PRODUCT_CODE) | `energy_sale_type_id` (FK) | Post-059: adapter maps product codes to energy_sale_type (revenue/product type) |
| Full original record | `source_metadata.original_record` | Preserved for audit |

#### Tariff Structure Fields (from Onboarding Template / `Inp_Proj`)

These fields define HOW the tariff is calculated, not just the base rate. They come from the AM Onboarding Template (one-time at COD) and the `Inp_Proj` tabs in the Operating Revenue Masterfile.

**Classification FKs** — Three classification axes on `clause_tariff` (after migration 034 dropped `tariff_structure_type`):

> **Multi-value service types:** The onboarding parser now supports Contract Service/Product Type 1 and Type 2 from the template. When a contract has multiple service types (e.g., "Energy Sales" + "Equipment Rental/Lease/BOOT"), the system creates one `clause_tariff` row per service type, each with its own rate (base_rate for energy, equipment_rental_rate for rental, bess_fee for BESS, etc.).

| Source Field | FrontierMind Column | Storage | Notes |
|---|---|---|---|
| PO Summary col E "Energy Sale Type" | `tariff_type_id` | FK → `tariff_type` | **Post-059: Offtake/Billing Model.** Resolves to TAKE_OR_PAY, TAKE_AND_PAY, MINIMUM_OFFTAKE, FINANCE_LEASE, OPERATING_LEASE, NOT_APPLICABLE |
| PO Summary col D "Revenue Type" / Onboarding "Contract Service/Product Type" | `energy_sale_type_id` | FK → `energy_sale_type` | **Post-059: Revenue/Product Type.** Resolves to ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE |
| Onboarding "Price Adjustment type" / `Inp_Proj` row 108 / PO Summary col AD | `escalation_type_id` | FK → `escalation_type` | **Post-059: Expanded.** Resolves to NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES |
| (from MRP currency) | `market_ref_currency_id` | FK → `currency` | MRP currency (often differs from billing currency) |

**Pricing formula parameters** — These are stored in `clause_tariff.logic_parameters` JSONB, not as standalone columns. The Pricing Calculator reads them at invoice generation time.


| Source Field | `logic_parameters` key | Notes |
|---|---|---|
| Onboarding "Floor tariff per kWh" / `Inp_Proj` row 174 | `floor_rate` | Floor price in USD/kWh |
| Onboarding "Ceiling tariff per kWh" / `Inp_Proj` row 168 | `ceiling_rate` | Ceiling price in USD/kWh |
| `Inp_Proj` row 162 "Grid cost discount %" | `discount_pct` | e.g. 0.192 for Kasapreko 19.2% |
| `Inp_Proj` rows 119-159 "Grid/Gen cost base rate" | `market_ref_price` | Grid or generator MRP (local currency) |
| `Inp_Proj` row 108 "PPA fixed tariff escalation %" | `escalation_rate` | e.g. 0.025 for 2.5% p.a. |
| `Inp_Proj` row 109 "escalation month" | `escalation_month` | 1-12, month when escalation applies |
| Onboarding "Price adjustment start date" | `escalation_start_date` | Auto-calculated as COD + 1 year |
| `Inp_Proj` row 175 "Floor price escalation %" | `floor_escalation_rate` | Separate from tariff escalation |
| `Inp_Proj` row 176 "Floor escalation month" | `floor_escalation_month` | |
| `Inp_Proj` row 169 "Ceiling price escalation %" | `ceiling_escalation_rate` | |
| `Inp_Proj` row 170 "Ceiling escalation month" | `ceiling_escalation_month` | |
| `Inp_Proj` row 2 "Annual degradation factor" | `degradation_rate` | e.g. 0.007 for 0.7% |
| Plant Performance formula (Y col) | `min_offtake_pct` | e.g. 0.80 for 80% (Min Offtake contracts only) |
| Onboarding "Billing frequency" (row 30) | `billing_frequency` | "Monthly", "Quarterly" — determines period granularity |
| Onboarding "Price adjustment frequency" (row 43) | `escalation_frequency` | "Annually", "Biannually" — escalation cadence |
| Onboarding "Energy Sales Tariff to be adjusted" (row 47) | `tariff_components_to_adjust` | Which components get escalated (e.g. "Solar Tarrif + Floor Tarrif") |

#### Product → Revenue Type Mapping (post-059: `energy_sale_type`)

| CBE Product Code | CBE Description | FrontierMind `energy_sale_type` |
|-----------------|-----------------|--------------------------|
| ENER0001 | Metered Energy | ENERGY_SALES |
| ENER0002 | Available Energy | ENERGY_SALES |
| ENER0003 | Deemed Energy | ENERGY_SALES |
| BESS0001 | BESS Capacity | BESS_LEASE |
| RENT0001 | Equipment Rental | EQUIPMENT_RENTAL_LEASE |
| OMFE0001 | O&M Fee | OTHER_SERVICE |
| DIES0001 | Diesel | OTHER_SERVICE |
| PNLT0001 | Penalty | OTHER_SERVICE |

#### Tariff Structure Types

| Structure | Description | CBE Examples | Applicable Tariff Formula |
|-----------|-------------|-------------|--------------------------|
| `FIXED` | Fixed solar tariff, escalated annually | Garden City, Loisaba, XFlora, Maisha/Devki, QMM, UNSOS, Caledonia | `base_rate * (1 + escalation_rate)^years` or `base_rate * (CPI_now / CPI_base)` |
| `GRID` | Discounted grid utility price with floor/ceiling bounds | Unilever Ghana, Kasapreko, Jabi Lake, Guinness Ghana, ekaterra Tea | `MAX(floor, MIN(grid_price * (1 - discount), ceiling))` |
| `GENERATOR` | Discounted generator cost with floor/ceiling bounds | Nigerian Breweries Ibadan/Ama | `MAX(floor, MIN(gen_price * (1 - discount), ceiling))` |

#### Energy Sale Types

| Type | Description | Billing Rule | CBE Examples |
|------|-------------|-------------|-------------|
| `TAKE_OR_PAY` | Customer pays for all produced energy | Invoice = Metered + Available | Most CBE projects |
| `MIN_OFFTAKE` | Customer pays for at least X% of production | Invoice = MAX(Metered, X% * Total) | Maisha/Devki Group (80%) |
| `TAKE_AND_PAY` | Customer pays only for consumed energy | Invoice = Metered only | UNSOS |
| `LEASE` | Fixed equipment rental, not energy-based | Invoice = Fixed monthly fee | Arijiju, Balama |

#### Escalation Types

Canonical `escalation_type.code` values (from migrations 027 + 059). CBE-specific detail (rate, index name) lives in `clause_tariff.logic_parameters`. Post-059: FLOATING_* sub-types added as flat codes; MRP-family queried with `IN ('REBASED_MARKET_PRICE', 'FLOATING_GRID', 'FLOATING_GENERATOR', 'FLOATING_GRID_GENERATOR')`.

| Canonical Code | CBE Label | Description | Formula | logic_parameters keys | CBE Examples |
|------|------|-------------|---------|------|-------------|
| `NONE` | NONE | Fixed price, no adjustment | `base` | — | QMM01 |
| `FIXED_INCREASE` | FIXED_AMT | Fixed amount increase annually | `base + amount * years` | `escalation_rate` | — |
| `FIXED_DECREASE` | FIXED_DEC | Fixed amount decrease annually | `base - amount * years` | `escalation_rate` | — |
| `PERCENTAGE` | FIXED_PCT | Fixed annual percentage increase | `base * (1 + pct)^years` | `escalation_rate`, `escalation_month` | MF01 (1%), MB01, AMP01, TBM01 |
| `US_CPI` | US_CPI | Indexed to US CPI | `base * (CPI_current / CPI_base)` | `price_index_name` = 'US_CPI_U' | Garden City, Loisaba, Caledonia, XFlora |
| `REBASED_MARKET_PRICE` | REBASED_MKT | Rebased to market reference (generic) | `market_price * (1 - discount)` | `market_ref_price`, `discount_pct` | MOH01 |
| `FLOATING_GRID` | FLOAT_GRID | Discounted grid utility tariff (MRP sub-type) | `MAX(floor, MIN(grid * (1-d), ceiling))` | `discount_pct`, `floor_rate`, `ceiling_rate` | KAS01, GBL01, UGL01, MOH01 |
| `FLOATING_GENERATOR` | FLOAT_GEN | Discounted diesel/gas generator cost (MRP sub-type) | `MAX(floor, MIN(gen * (1-d), ceiling))` | `discount_pct`, `floor_rate`, `ceiling_rate` | NBL02 |
| `FLOATING_GRID_GENERATOR` | FLOAT_GRID_GEN | Combined grid + generator baseline (MRP sub-type) | `MAX(floor, MIN(combined * (1-d), ceiling))` | `discount_pct`, `floor_rate`, `ceiling_rate` | JAB01 |
| `NOT_ENERGY_SALES` | N/A | Non-energy arrangement (lease, O&M, etc.) | — | — | AR01, TWG01, ZL01/ZL02 |

#### source_metadata example (CBE)

```json
{
  "external_line_id": "4000",
  "external_line_key": "CBE-CONZIM00-2025-00002-4000",
  "product_code": "ENER0001",
  "metered_available": "EMetered",
  "sage_id": "GH 22015",
  "original_record": {
    "CONTRACT_LINE_UNIQUE_ID": "CONZIM00-2025-00002-4000",
    "LINE_NUMBER": 4000,
    "PRODUCT_CODE": "ENER0001",
    "DESCRIPTION": "Metered Energy Phase 2",
    "UNIT_PRICE": 0.12,
    "CURRENCY": "ZAR"
  }
}
```

---

### 2. CBE Meter Readings → `meter_aggregate`

CBE provides monthly meter readings from two sources:
- **Snowflake** (billing reads from Sage/vCOM)
- **Operations Plant Performance Workbook** (vCOM extracts with performance data)

#### Billing Fields (from Snowflake)

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| (from tariff line) | `clause_tariff_id` (FK) | Links to the billable tariff line |
| `METER_ID` | `meter_id` (FK) | Physical meter reference |
| `BILLING_PERIOD` | `billing_period_id` (FK) | Resolved via billing_period lookup |
| `OPENING_READING` | `opening_reading` | Meter reading at period start |
| `CLOSING_READING` | `closing_reading` | Meter reading at period end |
| `UTILIZED_READING` | `utilized_reading` | Net consumption (closing - opening) |
| `DISCOUNT_READING` | `discount_reading` | Discounted/waived quantity |
| `SOURCED_ENERGY` | `sourced_energy` | Self-sourced energy to deduct |
| (calculated) | `total_production` | Final billable qty = utilized - discount - sourced |
| `SOURCE_SYSTEM` | `source_system` | 'snowflake' (generic; adapter sets this in transformer.py) |
| Full original record | `source_metadata` | Preserved for audit |

#### Performance Fields (from Plant Performance Workbook / vCOM)

Migration 041 added dedicated columns for performance data on `meter_aggregate` and a new `plant_performance` table for derived metrics.

**Per-meter performance data** (on `meter_aggregate`, migration 041):

| Workbook Column | Storage | Column | Notes |
|---|---|---|---|
| Per-meter available energy | Column | `available_energy_kwh` | Available Energy per meter per month (kWh). Total Available = SUM across all meters. |
| Col AA "Actual GHI Irradiance" | Column | `ghi_irradiance_wm2` | Monthly GHI irradiance (Wh/m2) for pyranometer/irradiance meters |
| (if available) | Column | `poa_irradiance_wm2` | Monthly POA irradiance (Wh/m2) — plane-of-array irradiance |
| Contract line link | Column | `contract_line_id` | FK to `contract_line` — links aggregate to billable contract line |
| Col AC "Availability %" | Column | `availability_percent` | System availability from monitoring (migration 007) |
| Capacity factor | `source_metadata` | `capacity_factor` | `total_energy / (capacity * days * 24)` |

**Project-level derived metrics** (on `plant_performance`, migration 041):

| Workbook Column | Storage | Column | Notes |
|---|---|---|---|
| Col AB "Actual PR" | Column | `actual_pr` | DECIMAL(5,4). Formula: `total_energy × 1000 / (actual_ghi × capacity_kwp)` |
| Col AC "Availability %" | Column | `actual_availability_pct` | DECIMAL(5,2). System availability percentage |
| Energy comparison | Column | `energy_comparison` | Ratio: total actual energy / forecast energy |
| Irradiance comparison | Column | `irr_comparison` | Ratio: actual GHI / forecast GHI |
| PR comparison | Column | `pr_comparison` | Ratio: actual PR / forecast PR |
| Operating year | Column | `operating_year` | INTEGER. `INT((date - COD) / 365 + 1)` |
| (FK) | Column | `production_forecast_id` | Links to forecast for this month |
| (FK) | Column | `billing_period_id` | Links to billing_period for this month |

Raw energy totals (total_metered_kwh, total_available_kwh, total_energy_kwh, actual_ghi_irradiance) are computed on-the-fly from `meter_aggregate` rows, not stored in `plant_performance`.

**Billable quantity calculation:**
```
total_production = utilized_reading - discount_reading - sourced_energy
                 = 783942.656 - 0 - 0
                 = 783942.656 kWh
```

**Meter continuity validation:**
Each month's `opening_reading` must equal the previous month's `closing_reading`. A break signals a meter reset or data error.

**Data sources by project (from Data Integrity Checklist):**

| Data Type | Primary Sources |
|-----------|----------------|
| Metered Energy | vCOM (majority), AMMP (Garden City, Miro), SMA Sunny Portal (XFlora), Encombi (UGL01), Dhybrid (ERG, QMM, NBL02) |
| Available Energy | vCOM (majority), manual calculation (some), N/A (Garden City, Miro, Baidoa) |
| Irradiance | vCOM (majority), AMMP (Garden City, Miro), SMA Sunny Portal (XFlora) |
| Availability | vCOM (majority), Not Available (Garden City, Miro) |

---

### 2b. Contract Lines → `contract_line`

Migration 041. Bridge between CBE Snowflake contract line data and the FrontierMind billing engine. Links contracts to specific meters and energy product categories.

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CONTRACT_NUMBER` | `contract_id` (FK) | Resolved via contract lookup |
| `LINE_NUMBER` | `contract_line_number` | CBE line code: 1000, 4000, 5000, etc. |
| `CONTRACT_LINE_UNIQUE_ID` | `external_line_id` | CBE unique identifier |
| `METER_ID` | `meter_id` (FK) | Physical meter reference (NULL for project-level lines) |
| `PRODUCT_CODE` | `billing_product_id` (FK) | Resolved via billing_product lookup |
| `DESCRIPTION` | `product_desc` | e.g. "Metered Energy (EMetered) - PPL1" |
| `METERED_AVAILABLE` | `energy_category` | Enum: `metered`, `available`, `test` |
| — | `organization_id` (FK) | NOT NULL, for RLS |
| — | `is_active` | BOOLEAN, defaults true |

**Unique constraint:** `(contract_id, contract_line_number)`

**Energy routing:** The CBE billing adapter uses `energy_category` to route readings:
- `metered` → `meter_aggregate.energy_kwh`
- `available` → `meter_aggregate.available_energy_kwh`

**MOH01 seed data** (contract_id=7, 12 lines): 5 metered lines (PPL1, PPL2, Bottles, BBM1, BBM2 at line codes 4000-8000) + 1 mother available energy line (line 1000, site-level, `meter_id = NULL`, `external_line_id = '11481428495164935368'`) + 5 child available energy lines (PPL1, PPL2, Bottles, BBM1, BBM2 at line codes 4001, 5001, 6001, 7001, 8001, linked via `parent_contract_line_id`) + 1 test energy line (3000). See Section 19 for the parent-child contract line hierarchy pattern.

---

### 2c. Plant Performance → `plant_performance`

Migration 041. Monthly project-level performance analysis. Raw data lives in `meter_aggregate` (per-meter energy + actual irradiance) and `production_forecast` (forecast energy/irradiance/PR). This table stores only derived performance metrics and comparisons.

| Source | FrontierMind Column | Notes |
|--------|-------------------|-------|
| Computed from meter_aggregate | `actual_pr` | DECIMAL(5,4). `total_energy × 1000 / (actual_ghi × capacity_kwp)` |
| From monitoring | `actual_availability_pct` | DECIMAL(5,2). System availability % |
| Computed | `energy_comparison` | `total actual energy / forecast energy` |
| Computed | `irr_comparison` | `actual GHI / forecast GHI` |
| Computed | `pr_comparison` | `actual PR / forecast PR` |
| From COD date | `operating_year` | INTEGER, 1-based |
| (FK) | `project_id` | NOT NULL |
| (FK) | `organization_id` | NOT NULL |
| (FK) | `production_forecast_id` | Links to forecast for comparison |
| (FK) | `billing_period_id` | Resolved from billing_month |
| First of month | `billing_month` | DATE, part of UNIQUE(project_id, billing_month) |

**Performance formulas (from Operations Workbook):**

| Metric | Formula |
|--------|---------|
| Total Available Energy | `SUM(available_energy_kwh)` across all meters |
| Total Energy (kWh) | `SUM(metered per meter) + total_available` |
| Actual PR (%) | `total_energy × 1000 / (actual_ghi × capacity_kwp)` |
| Energy Comparison | `total_energy / forecast_energy` |
| Irr Comparison | `actual_ghi / forecast_ghi` |
| PR Comparison | `actual_pr / forecast_pr` |

**Available Energy calculation** (`python-backend/services/available_energy_calculator.py`):

Contractual formula per 15-minute interval during System Event or Curtailed Operation:
```
E_Available(x) = (E_hist / Irr_hist) × (1 / Intervals) × Irr(x)
```
Manual/import values take precedence over auto-calculation. Stored in `meter_aggregate.available_energy_kwh`.

**API endpoints:**
- `GET /api/projects/{id}/plant-performance` — returns monthly performance with raw data computed on-the-fly from meter_aggregate + production_forecast
- `POST /api/projects/{id}/plant-performance/manual` — per-month manual entry
- `POST /api/projects/{id}/plant-performance/import` — Operations workbook Excel import

---

### 3. CBE Contracts → `contract`

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CONTRACT_NUMBER` | External reference stored in `extraction_metadata` | e.g. "CONZIM00-2025-00002" |
| `CONTRACT_NAME` | `name` | |
| `CUSTOMER_NUMBER` | Resolved to `counterparty_id` (FK) | Via customer lookup |
| `START_DATE` | `effective_date` | Schema column is `effective_date`, not `start_date` |
| `END_DATE` | `end_date` | |
| `CURRENCY_CODE` | `currency_id` (FK) | Contract default currency |

**Onboarding-sourced contract fields** (from AM Onboarding Template):

| Onboarding Field | FrontierMind Column | Notes |
|---|---|---|
| "Payment Terms" (row 48) | `payment_terms` | VARCHAR(50), e.g. "Net 30" (migration 034) |
| "Confirmation signed PPA uploaded" (row 50) | `ppa_confirmed_uploaded` | BOOLEAN (migration 033) |
| "Any amendments post PPA" (row 51) | `has_amendments` | BOOLEAN (migration 033, auto-maintained by trigger) |
| "Is Payment Security required?" (row 53) | `payment_security_required` | BOOLEAN (migration 033) |
| "If yes, please include details" (row 54) | `payment_security_details` | TEXT (migration 033) |
| "Agreed source of exchange rate" (row 49) | `agreed_fx_rate_source` | TEXT (migration 033) |

---

### 4. CBE Customers → `counterparty`

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CUSTOMER_NUMBER` | External reference in counterparty metadata | |
| `CUSTOMER_NAME` | `name` | |
| (derived) | Organization tenancy via RLS | `counterparty` has no `organization_id` column; tenancy is inferred via contract → project → organization through RLS policies (017) |

---

### 5. CBE Customer Contacts → `customer_contact`

From the AM Onboarding Template "Key Customer Contacts" section. Each counterparty has up to 7 contact roles.

| Onboarding Field | FrontierMind Column | Notes |
|---|---|---|
| Contact role | `role` | 'accounting', 'cfo', 'financial_manager', 'general_manager', 'operations_manager' |
| Full Name | `full_name` | |
| Email | `email` | |
| Invoice selection (column B) | `include_in_invoice_email` + `escalation_only` | Three-state flag — see mapping below |
| (FK) | `counterparty_id` | Links to customer |

**Three-state invoice flag mapping:** The template column B is a single selection (Yes / No / Only contact for escalation) that maps to two boolean columns:

| Template Value | `include_in_invoice_email` | `escalation_only` | Notification Behavior |
|---|---|---|---|
| **Yes** | `true` | `false` | Gets all invoice emails |
| **Only contact for escalation** | `true` | `true` | Only gets escalation emails (overdue/disputes) |
| **No** | `false` | `false` | Gets nothing |

Parser: `normalize_contact_invoice_flag()` in `normalizer.py` detects "escalation" substring for the middle state, falls back to `normalize_boolean()` for Yes/No. Notification query in `notification_repository.py` filters `include_in_invoice_email = true` then optionally excludes `escalation_only = true` for routine sends.

---

### 6. Exchange Rates → `exchange_rate`

CBE operates across **multiple currencies** depending on project country. The Invoiced SAGE tab tracks both spot and rolling average rates.

| Currency | Countries | Source |
|----------|-----------|--------|
| GHS | Ghana (Kasapreko, Unilever, ABI, Guinness, Mohinani) | Central Bank of Ghana |
| KES | Kenya (Maisha/Devki, ekaterra Tea, TeePee, Loisaba) | CBE treasury |
| NGN | Nigeria (Nigerian Breweries, Jabi Lake) | CBE treasury |
| USD | Sierra Leone, Madagascar, Somalia, Zimbabwe, Egypt, Mauritius | Direct billing |
| ZAR | South Africa (Indorama/XFlora) | CBE treasury |
| MGA | Madagascar (QMM) | CBE treasury |
| SLE | Sierra Leone (Miro, Zoodlabs) | CBE treasury |

| Input | FrontierMind Column | Notes |
|-------|-------------------|-------|
| Currency code | `currency_id` (FK) | Resolved from `currency.code` |
| Rate date | `rate_date` | Monthly (closing spot or rolling average) |
| Rate | `rate` | 1 USD = X local currency |
| Source type | `source` | 'manual', 'central_bank', future: 'xe_api' |

**Exchange rate application rules (from Operating Revenue Masterfile):**
- Invoiced SAGE rows 61-63: Monthly closing spot rates (GHS, KES, NGN)
- Invoiced SAGE rows 65-67: Annual rolling average rates (for reporting)
- Onboarding Template: Some contracts specify custom FX source (e.g. "Central Bank of Ghana selling rate for USD at 12:00pm + 1%")

---

### 7. CBE Sage Invoices → `received_invoice_header` / `received_invoice_line_item`

Sage-generated invoices imported from Snowflake for comparison.

| CBE/Sage Field | FrontierMind Column | Notes |
|---------------|-------------------|-------|
| Invoice Number | `invoice_number` | Sage invoice reference |
| Invoice Date | `invoice_date` | |
| (set by adapter) | `invoice_direction` | `'receivable'` (AR — what ERP generated) |
| Line tariff reference | `clause_tariff_id` (FK) | Matched via `tariff_group_key` |
| Line quantity | `quantity` | As stated on Sage invoice |
| Line unit price | `line_unit_price` | As stated on Sage invoice |
| Line total | `line_total_amount` | As stated on Sage invoice |

---

### 8. Production Forecast → `production_forecast`

From the Plant Performance Workbook yield model (PVSyst-based) and the AM Onboarding Template Yield Report tab. One row per project per billing period. Schema: migration 029.

| Source | FrontierMind Column | Storage | Notes |
|--------|-------------------|---------|-------|
| Yield Report "E_Grid" adjusted | `forecast_energy_kwh` | Column | PVSyst output * total adjustment factor |
| Yield Report GHI (adjusted) | `forecast_ghi_irradiance` | Column | kWh/m2 (monthly total), uncertainty-adjusted |
| (calculated) | `forecast_pr` | Column | Performance Ratio: `forecast_energy / (GHI * capacity)` (both in kWh) |
| `Inp_Proj` row 2 | `degradation_factor` | Column | Cumulative: `(1 - degradation_rate)^(OY-1)` |
| (FK) | `project_id` | Column | NOT NULL |
| (FK) | `organization_id` | Column | NOT NULL |
| (FK) | `billing_period_id` | Column | |
| First day of month | `forecast_month` | Column | DATE, part of UNIQUE(project_id, forecast_month) |
| Operating year | `operating_year` | Column | `INT((date - COD) / 365 + 1)` |
| 'pvsyst' or 'manual' | `forecast_source` | Column | DEFAULT 'p50' |
| Yield Report POA (adjusted) | `source_metadata.forecast_poa_irradiance` | JSONB | kWh/m2 (monthly total), uncertainty-adjusted |
| (calculated) | `source_metadata.forecast_pr_poa` | JSONB | `forecast_energy / (POA * capacity)` (both in kWh) |
| Yield Report row 30 | `source_metadata.adjustment_factor` | JSONB | `(1 - irr_uncertainty) * system_avail * grid_avail * (1 - curtailment)` |

**Forecast degradation formula (from Plant Performance Workbook):**
```
forecast_energy_OY2 = forecast_energy_OY1 * (1 - degradation_rate)
```
Compounding year-over-year from year 1 baseline.

**Multi-array projects:** Forecast is capacity-weighted across sub-arrays:
```
forecast = (cap_A * yield_A * monthly_pct_A) + (cap_B * yield_B * monthly_pct_B)
```

---

### 9. Production Guarantees → `production_guarantee` + `default_event` / `rule_output`

From AM Onboarding Template Section 9 "Guarantees". Schema: migration 029. One row per project per operating year. UNIQUE(project_id, operating_year).

**Guarantee definition** (static contract terms) → `production_guarantee`:

| Source | FrontierMind Column | Storage | Notes |
|--------|-------------------|---------|-------|
| Onboarding "Production guarantee" | `guaranteed_kwh` | Column | e.g. 3,280,333 kWh (Year 1) |
| Onboarding "% of model production" | `guarantee_pct_of_p50` | Column | DECIMAL(5,4), e.g. 0.9000 |
| Yield Report "Net Energy Sold" | `p50_annual_kwh` | Column | PVSyst P50 annual output |
| (FK) | `project_id` | Column | NOT NULL. Contract relationship is via project. |
| (FK) | `organization_id` | Column | NOT NULL |
| | `operating_year` | Column | INTEGER, 1-based from COD year |
| OY start/end dates | `year_start_date`, `year_end_date` | Column | DATE, NOT NULL |
| `Inp_Proj` row 2 | `source_metadata.degradation_rate` | JSONB | Applied to pro-rate future year guarantees |

**Year-end evaluation** (mutable event data) → `default_event` + `rule_output` pipeline:

| Data | Pipeline Location | Notes |
|------|-------------------|-------|
| Actual annual kWh | Calculated from `SUM(meter_aggregate.total_production)` at evaluation time | Not stored on guarantee row |
| Shortfall kWh | `rule_output.details` JSONB | `GREATEST(0, guaranteed_kwh - actual_kwh)` |
| Evaluation outcome | `default_event.status` + `rule_output.breach` | breach=true if shortfall > 0 |
| LD amount | `rule_output.ld_amount` | If applicable per contract terms |
| Excuse flags | `rule_output.excuse` | Force majeure, curtailment, etc. |
| Clause linkage | `rule_output.clause_id` | Links to guarantee clause |
| Event type | `default_event_type.code = 'GUARANTEE_EVALUATION'` | Seeded when feature is built |

**Guarantee pro-rating formula (from Onboarding Template):**
```
guaranteed_kwh = base_guarantee * (actual_capacity / design_capacity)
               = 3,249,363 * (2616.705 / 2592)
               = 3,280,333 kWh
```

---

### 10. Deferred Energy — Runtime Calculation (Pricing Calculator / Rules Engine)

For Minimum Offtake contracts only. From the Plant Performance Workbook columns AL/AM. **Calculated at runtime** by the pricing calculator or rules engine — not materialized as a database view. All source data exists in `meter_aggregate`, `expected_invoice_line_item`, and `clause_tariff`.

The calculation identifies Minimum Offtake contracts via `tariff_type.code = 'MINIMUM_OFFTAKE'` (post-059: offtake model), reads `min_offtake_pct` from `clause_tariff.logic_parameters` JSONB, and joins through `meter_aggregate` and `expected_invoice_line_item` to compute monthly variance and cumulative deferred kWh.

| Source | Output | Derivation |
|--------|--------|------------|
| `meter_aggregate.total_production` | `total_energy_kwh` | Combined across sub-arrays |
| Calculated | `min_offtake_threshold_kwh` | `total_energy_kwh * min_offtake_pct` |
| `expected_invoice_line_item.quantity` | `invoiced_energy_kwh` | What was actually billed |
| Calculated | `monthly_variance_kwh` | `GREATEST(0, min_offtake_threshold_kwh - invoiced_energy_kwh)` |
| Cumulative | `cumulative_deferred_kwh` | `SUM(monthly_variance_kwh)` within operating year, reset at OY boundary |
| `clause_tariff.logic_parameters->>'min_offtake_pct'` | `min_offtake_pct` | e.g. 0.80 for 80% |

**Deferred revenue at year-end:**
```
deferred_revenue = cumulative_deferred_kwh * tariff_rate
```

**Implementation approach:** Pricing calculator computes `min_offtake_threshold = total_production * min_offtake_pct` at invoice generation time. Monthly variance and cumulative tracking across an operating year are handled by the backend service. Results can be stored via `default_event` + `rule_output` if compliance tracking is needed, or calculated on-the-fly for reports.

---

### 11. Price Index → `price_index`

From the Operating Revenue Masterfile "US CPI" tab (BLS CPI-U All Urban Consumers, CUUR0000SA0).

| Source | FrontierMind Column | Notes |
|--------|-------------------|-------|
| BLS series ID | `index_name` | 'US_CPI_U' |
| Monthly date | `period_date` | 2010-01 through current |
| CPI value | `value` | Base period 1982-84 = 100 |
| 'BLS' or 'manual' | `source` | |

**CPI escalation formula (from Revenue Masterfile):**
```
escalated_tariff = base_tariff * (CPI_current_month / CPI_base_month)
```

Future: Support for country-specific CPI indices (GH CPI, KE CPI, etc.) using the same table.

---

### 12. Loan Schedules → `loan_schedule` / `loan_payment`

From the Operating Revenue Masterfile "Loans" tab. CBE currently has 3 active loans.

**`loan_schedule`:**

| Source | FrontierMind Column | Notes |
|--------|-------------------|-------|
| Loan name | `loan_name` | e.g. "Zoodlabs Loan 1" |
| Opening balance | `opening_balance` | e.g. $1,857,005.50 |
| Monthly payment | `monthly_payment` | e.g. $15,436 (may step up) |
| Interest rate | `interest_rate` | Implied from amortization |
| Term | `term_months` | e.g. 180 (15 years) |
| Start date | `start_date` | |
| (FK) | `project_id`, `contract_id`, `counterparty_id` | |

**`loan_payment`:**

| Source | FrontierMind Column | Notes |
|--------|-------------------|-------|
| Month # | `month_number` | Sequential from loan start |
| Principal | `principal` | |
| Interest | `interest` | |
| Payment | `payment` | principal + interest |
| Closing balance | `closing_balance` | |
| | `notice_sent_at` | Tracks when repayment notice was sent |
| (FK) | `loan_schedule_id`, `billing_period_id` | |

---

### 13. GRP Observations → `reference_price`

From utility invoice extraction ([Section 7](#7-grp-ingestion-flow)). One row per project per month (monthly) or per year (annual aggregation).

| Source | FrontierMind Column | Notes |
|--------|-------------------|-------|
| Extraction pipeline | `observation_type` | `'monthly'` (from invoice) or `'annual'` (aggregated) |
| `SUM(VARIABLE_ENERGY amounts) / SUM(VARIABLE_ENERGY kWh)` | `calculated_grp_per_kwh` | Weighted average of variable energy charges |
| `SUM(VARIABLE_ENERGY amounts)` | `total_variable_charges` | In local currency |
| `SUM(VARIABLE_ENERGY kWh)` | `total_kwh_invoiced` | Total consumption from invoice |
| S3 path | `source_document_path` | `grp-uploads/{org_id}/{project_id}/{year}/{month}/{hash}{ext}` |
| SHA-256 | `source_document_hash` | Deduplication key |
| Token consumption | `submission_response_id` (FK) | Links to `submission_response` |
| Line items + metadata | `source_metadata` (JSONB) | Full extraction result for audit |
| Lifecycle | `verification_status` | `'pending'` → `'jointly_verified'` / `'disputed'` / `'estimated'` |

**Conflict key:** `(project_id, observation_type, period_start)` — upserts replace existing observations for the same period.

---

### 14. Billing Products → `billing_product` + `contract_billing_product`

Org-scoped ERP product codes. Migration 034.

**`billing_product`:**

| Field | Notes |
|-------|-------|
| `code` | e.g. "GHREVS001", "GHREVS002" |
| `name` | e.g. "Metered Energy", "Available Energy" |
| `organization_id` | FK (nullable — NULL = canonical/platform-wide) |

**`contract_billing_product`** (junction):

| Field | Notes |
|-------|-------|
| `contract_id` (FK) | |
| `billing_product_id` (FK) | Resolved via `LATERAL` subquery: `ORDER BY organization_id NULLS LAST LIMIT 1` (org-scoped preferred over canonical) |
| `is_primary` | BOOLEAN — exactly 1 primary per contract (enforced by post-load assertion) |

---

### 15. Rate Versioning → `tariff_rate`

Migration 040 merged `tariff_annual_rate` + `tariff_monthly_rate` into a unified `tariff_rate` table with four-currency representation.

**`tariff_rate`** (unified):

| Field | Notes |
|-------|-------|
| `clause_tariff_id` (FK) | Parent tariff |
| `contract_year` | INTEGER, 1-based from COD |
| `rate_granularity` | Enum: `'annual'` or `'monthly'` |
| `billing_month` | DATE (first of month) for monthly rows; NULL for annual |
| `period_start`, `period_end` | DATE range for this period |
| `hard_currency_id` (FK) | International reference currency (USD, EUR) |
| `local_currency_id` (FK) | Local market currency where project operates |
| `billing_currency_id` (FK) | Currency on invoices (must equal hard or local) |
| `billing_period_id` (FK) | FK to `billing_period` for monthly rows; NULL for annual |
| `exchange_rate_id` (FK) | FK to `exchange_rate` for local→USD conversion; NULL for USD-denominated or annual rows |
| `effective_rate_contract_ccy` | Effective rate in the contractual source-of-truth currency |
| `effective_rate_hard_ccy` | Effective rate in hard/international currency |
| `effective_rate_local_ccy` | Effective rate in local market currency |
| `effective_rate_billing_ccy` | Effective rate in billing/invoice currency |
| `effective_rate_contract_role` | Enum: `'hard'`, `'local'`, or `'billing'` — which is source of truth |
| `calc_detail` | JSONB with escalation-type-specific intermediary variables in four-currency format |
| `rate_binding` | `'floor'`, `'ceiling'`, `'discounted'`, or `'fixed'` |
| `reference_price_id` (FK) | Links to GRP observation (NULL for deterministic tariffs) |
| `discount_pct_applied` | Discount percentage applied (e.g. 0.2200) |
| `formula_version` | Engine version identifier (e.g. `rebased_v1`) |
| `calc_status` | Enum: `'pending'` → `'computed'` → `'approved'` → `'superseded'` |
| `is_current` | BOOLEAN, separate unique index per granularity (annual/monthly) |

**Key constraints:**
- Annual rows: one per `(clause_tariff_id, contract_year)`, `billing_month` must be NULL
- Monthly rows: one per `(clause_tariff_id, billing_month)`, `period_start = billing_month`
- `billing_currency_id` must equal `hard_currency_id` or `local_currency_id`

---

## 7. GRP (Grid Reference Price) Ingestion Flow

### 7.1 Token-Based Submission

Admin generates a reusable GRP upload token for a project:

```
POST /api/notifications/grp-collection
  → Validates project/counterparty ownership
  → Generates 64-byte secrets.token_urlsafe() token
  → Stores SHA-256 hash in submission_token (raw token never persisted)
  → Sets submission_type = 'grp_upload', stores project_id and operating_year
  → Builds URL: {APP_BASE_URL}/submit/{token}
  → Returns GRPCollectionResponse {token_id, submission_url}
```

Counterparty receives the URL and uploads their utility invoice.

**Token lifecycle:** Active → Used (when `use_count >= max_uses`) or Revoked (admin action) or Expired (`expires_at` default 168 hours / 7 days). Stale tokens batch-expired by `expire_stale_tokens()`.

### 7.2 Extraction Pipeline

```
POST /api/submit/{token}/upload (unauthenticated, rate limited 5/min)
  │
  ├─ Validate token (must be grp_upload with project_id)
  ├─ Validate billing_month (default: current month)
  ├─ Validate file (max 20 MB, PDF/PNG/JPG only)
  ├─ SHA-256 hash → check reference_price for duplicate
  ├─ Upload to S3: grp-uploads/{org_id}/{project_id}/{year}/{month}/{hash}{ext}
  ├─ Determine operating_year from token fields or COD date
  ├─ Validate billing_month >= COD date
  │
  ▼ GRPExtractionService.extract_and_store() (synchronous, 10-30s)
  │
  ├─ Stage 1: OCR via LlamaParse (markdown output)
  ├─ Stage 2: Claude structured extraction (claude-sonnet-4-20250514)
  │    → ExtractionResult {invoice_metadata, line_items[], confidence}
  ├─ Stage 3: Billing period reconciliation (extracted vs user-provided)
  ├─ Stage 4: GRP calculation
  │    → Fetch logic_parameters from clause_tariff (REBASED_MARKET_PRICE)
  │    → Filter VARIABLE_ENERGY items only
  │    → GRP = SUM(amounts) / SUM(kWh)
  ├─ Stage 5: Upsert reference_price (monthly observation)
  │    → Conflict key: (project_id, 'monthly', period_start)
  │
  ▼ Consume token AFTER successful extraction (retry-safe)
    Link submission_response to reference_price observation
```

### 7.3 Monthly → Annual Aggregation

```
POST /api/projects/{id}/grp-aggregate
  → AggregateGRPRequest {operating_year, include_pending}
  → Fetches all monthly observations for the operating year
  → Filters by verification_status (exclude pending unless include_pending=true)
  → Weighted average: SUM(total_variable_charges) / SUM(total_kwh_invoiced)
  → Upserts reference_price with observation_type='annual'
  → Returns AggregateGRPResponse {annual_grp_per_kwh, months_included/excluded}
```

### 7.4 Verification Lifecycle

```
pending ──→ jointly_verified (both parties confirm)
       ──→ disputed (counterparty challenges)
       ──→ estimated (admin marks as estimate)
```

**Endpoint:** `PATCH /api/projects/{id}/grp-observations/{obsId}` with `VerifyObservationRequest {verification_status, notes}`.

### 7.5 Rebased Market Price Engine

**File:** `python-backend/services/tariff/rebased_market_price_engine.py`

**Core formula (GRID_DISCOUNT_BOUNDED):**
```
effective = MAX(floor_local, MIN(GRP × (1 - discount), ceiling_local))
```

**Currency model:**
- GRP is always in GHS (local currency, system of record)
- Floor and ceiling stored in USD, converted to GHS monthly using that month's FX rate
- Floor/ceiling in GHS vary month-to-month even though USD values are constant for a year

**Component escalation** (`_escalate_component`):
- `FIXED`: compound percentage per year
- `ABSOLUTE`: flat amount per year
- `NONE`: no escalation
- Applied to floor (`min_solar_price`) and ceiling (`max_solar_price`) from configurable `start_year`

**Monthly calculation loop:** For each billing month:
1. Convert escalated floor/ceiling from USD to GHS using that month's FX rate
2. Apply formula: `MAX(floor_ghs, MIN(GRP × (1 - discount), ceiling_ghs))`
3. Record `rate_binding` (`floor` / `ceiling` / `discounted`)

**Database writes (single transaction):**
- `exchange_rate`: 1 row per month (upsert on org+currency+date)
- `reference_price`: Annual GRP observation (upsert on project+type+period)
- `tariff_rate` (annual): Annual anchor row, `effective_rate_billing_ccy` = latest month's effective rate
- `tariff_rate` (monthly): Up to 12 rows, one per billing month with four-currency representation

---

## 8. Amendment Tracking

**Version chain:** `clause_tariff.supersedes_clause_tariff_id` + `is_current` boolean.

When a tariff is amended:
1. New `clause_tariff` row created with `supersedes_clause_tariff_id` pointing to the previous version
2. Previous version's `is_current` set to `false`
3. New version's `is_current` set to `true`

**Table:** `contract_amendment` (migration 033) tracks amendment metadata.

**Views:** `clause_tariff_current_v` filters to `is_current = true` for downstream consumers.

---

## 9. Dashboard Display Mapping

### 9.1 API Data Flow

```
GET /api/projects/{projectId}/dashboard (adminClient.getProjectDashboard)
  → ProjectDashboardResponse {
      project, contracts, tariffs, assets, meters,
      forecasts, guarantees, contacts, documents,
      billing_products, rate_periods, monthly_rates,
      clauses, lookups
    }
```

**Frontend:** `app/projects/page.tsx` — 7-tab Radix UI layout with global edit mode (Overview, Pricing & Tariffs, Technical, Forecasts & Guarantees, Monthly Billing, Performance, Contacts).

### 9.2 Overview Tab

**Component:** `app/projects/components/ProjectOverviewTab.tsx`

| Section | Data Source |
|---------|------------|
| Project Information | `project` (IDs, name, country, customer details) |
| Contract Terms | `contracts` (COD, term years, effective/end dates) |
| Payment Terms & Default Rate | `clauses` (PAYMENT_TERMS clause `normalized_payload`: benchmark, spread, accrual method, FX indemnity) |
| Contracts Table | `contracts[]` (name, type, status, counterparty, dates) |

### 9.3 Pricing & Tariffs Tab

**Component:** `app/projects/components/PricingTariffsTab.tsx` (1574 lines, most complex tab)

| Section | Data Source |
|---------|------------|
| Tariff & Rate Schedule | `rate_periods` per tariff (year, period, rate, currency, current indicator) |
| Billing Information | `tariffs` + `contracts` (frequency, currency, payment terms, FX source) |
| Service & Product Classification | `tariffs` (tariff_type badges, energy_sale_type) |
| Products to be Billed | `billing_products` + `tariffs` grouped by product (expandable cards with tariff detail panels) |
| Escalation Rules | `tariffs.logic_parameters` (type, frequency, start date, components to adjust, escalation rules table, computed floor/ceiling rate schedule) |
| Grid Reference Price (GRP) | `reference_price` via `listGRPObservations` (parameters, token management, annual/monthly observations, verify/dispute actions) |
| Shortfall Formula | `tariffs.logic_parameters` or `clauses` (formula type, text, variables, cap) |
| Non-Energy Service Lines | `tariffs` filtered to non-energy types (rental, BESS, loan) |

**GRP sub-section actions:** Generate Token, Upload Invoice, Aggregate Year, Refresh, Verify/Dispute observations, Manage collection links (active/expired/revoked tokens).

### 9.4 Technical Tab

**Component:** `app/projects/components/TechnicalTab.tsx`

| Section | Data Source |
|---------|------------|
| Technical Summary | `project` + `assets` + `meters` (DC/AC capacity, PV modules model/qty, inverter model/qty, location with Google Maps link, interconnection voltage, billing meter details) |
| Assets Table | `assets[]` (type, name, model, serial, capacity, unit, qty) |
| Meters Table | `meters[]` (type, model, serial, location, metering type) |

### 9.5 Forecasts & Guarantees Tab

**Component:** `app/projects/components/ForecastsGuaranteesTab.tsx`

| Section | Data Source |
|---------|------------|
| Production Forecasts | `forecasts[]` (monthly: energy kWh, GHI/POA irradiance, PR, source; annual sum/avg footer) |
| Production Guarantees | `guarantees[]` (operating year, P50, guarantee %, guaranteed kWh, shortfall cap, FX rule) |

### 9.6 Monthly Billing Tab

**Component:** `app/projects/components/MonthlyBillingTab.tsx`

| Section | Data Source |
|---------|------------|
| Summary view | `adminClient.getMonthlyBilling()` — aggregate monthly totals (energy kWh, rate, amount, currency) |
| Meter Breakdown view | `adminClient.getMeterBilling()` — per-meter detail per month |
| Per-meter detail (expandable) | `meter_id`, `meter_name`, `opening_reading`, `closing_reading`, `metered_kwh`, `available_kwh`, `rate`, `amount` |
| Import | Excel import of billing data |
| Manual entry | Single-month manual row |
| Export | Download billing data |

**Toggle:** Summary vs Meter Breakdown view. Meter Breakdown shows expandable rows per month with per-meter detail on expand.

**Total Available Energy** = SUM(available_energy_kwh) across all meters (shown as separate line in breakdown).

### 9.7 Performance Tab

**Component:** `app/projects/components/PlantPerformanceTab.tsx`

| Section | Data Source |
|---------|------------|
| Summary cards | `project` (installed capacity, degradation rate) + latest `plant_performance` row (PR, availability) |
| Performance table | `adminClient.getPlantPerformance()` — monthly rows: month, OY, total energy, forecast, GHI, PR, availability, energy/irr/PR comparisons |
| Charts | Recharts bar chart (energy actual vs forecast) + line chart (PR trend) |
| Import | Operations workbook Excel upload (`adminClient.importPlantPerformance()`) |
| Manual entry | Single-month row with per-meter readings (`adminClient.addPlantPerformanceEntry()`) |

**Table/Chart toggle:** Switch between tabular and chart visualization.

### 9.8 Contacts Tab

**Component:** Generic `ProjectTableTab` in `app/projects/page.tsx`

| Section | Data Source |
|---------|------------|
| Customer Contacts | `contacts[]` (role, full name, email, phone, include in invoice, escalation only) |
| Add/Remove actions | `adminClient.addContact()` / `adminClient.removeContact()` |

---

## 10. Data Flow Diagrams

### Onboarding Pipeline

```
┌──────────────────┐     ┌──────────────────┐
│ AM Onboarding    │     │ PPA Contract     │
│ Template (Excel) │     │ (PDF)            │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
    ExcelParser              PPAOnboardingExtractor
    (label-anchored)         (regex + Claude LLM)
         │                        │
         ▼                        ▼
    ExcelOnboardingData      PPAContractData
         │                        │
         └──────── Merge ─────────┘
                (Override > PPA > Excel)
                     │
              Cross-Validate
              (completeness, coherence,
               confidence thresholds)
                     │
                     ▼
             MergedOnboardingData
                     │
            ┌────────┴────────┐
            │  Preview Phase  │
            │  (store 1hr)    │
            └────────┬────────┘
                     │ User confirms
                     ▼
            ┌────────────────┐
            │  Commit Phase  │
            └────────┬───────┘
                     │
         Populate 9 staging tables
                     │
         Pre-flight validation (8 checks)
                     │
         11 upserts in FK order
                     │
         Post-load assertions (8 checks)
                     │
         ┌───────────┴───────────┐
         │                       │
    Rate Period              Audit Doc
    Generator                (per-project)
    (Years 1..N)
         │
         ▼
    Dashboard
    (7-tab display)
```

### GRP Pipeline

```
┌──────────────────┐
│ Admin generates  │
│ submission token │
│ (POST /api/      │
│  notifications/  │
│  grp-collection) │
└────────┬─────────┘
         │ URL: {base}/submit/{token}
         ▼
┌──────────────────┐
│ Counterparty     │
│ uploads utility  │
│ invoice (PDF)    │
│ (POST /api/      │
│  submit/{token}/ │
│  upload)         │
└────────┬─────────┘
         │
    Validate → Hash → S3 upload
         │
    OCR (LlamaParse)
         │
    Claude extraction
    (line items + metadata)
         │
    GRP calculation
    (VARIABLE_ENERGY only)
         │
    reference_price upsert
    (monthly observation)
         │
    Consume token
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│ Monthly          │────→│ Annual           │
│ Observations     │     │ Aggregation      │
│ (verify/dispute) │     │ (weighted avg)   │
└──────────────────┘     └────────┬─────────┘
                                  │
                           Rebased Market
                           Price Engine
                                  │
                              │
                        tariff_rate
                     (annual anchor row +
                      12 monthly rows/year,
                      four-currency repr.)
                              │
                        Dashboard
                        (Pricing & Tariffs tab)
```

### Complete Monthly Billing Pipeline

```
                        AM Onboarding Template (one-time at COD)
                                    |
                    Sets: tariff classification (tariff_type, energy_sale_type, escalation_type),
                          floor/ceiling, escalation rules, meters, production guarantee, contacts
                                    |
                                    v
+-----------------------------------------------------------------------+
| 1. clause_tariff                                                      |
|    tariff_group_key = "CONZIM00-2025-00002-4000"                      |
|    tariff_type_id -> TAKE_OR_PAY (FK to tariff_type — offtake model) |
|    energy_sale_type_id -> ENERGY_SALES (FK to energy_sale_type — revenue type) |
|    escalation_type_id -> PERCENTAGE (FK to escalation_type)          |
|    base_rate = 0.12 ZAR                                               |
|    logic_parameters = {escalation_rate: 0.01, ...}                    |
|    source_metadata = {external_line_id: "4000", ...}                  |
+-----------------------------------------------------------------------+
        |
        v   vCOM extract on WD1 (monthly)
+-----------------------------------------------------------------------+
| 2. meter_aggregate (per meter per month)                              |
|    clause_tariff_id -> tariff line                                     |
|    contract_line_id -> contract_line (migration 041)                  |
|    opening_reading = 11333714.94                                      |
|    closing_reading = 12117657.60                                      |
|    utilized_reading = 783942.656                                      |
|    total_production = 783942.656 (final billable)                     |
|    energy_kwh = metered energy (for metered lines)                    |
|    available_energy_kwh = available energy (for available lines)      |
|    ghi_irradiance_wm2 = 158200 Wh/m2 (pyranometer meter)             |
|    poa_irradiance_wm2 = POA irradiance if available                  |
|    availability_pct = 0.985                                           |
|    source_system = 'snowflake'                                        |
+-----------------------------------------------------------------------+
        |
        v   Look up forecast for comparison
+-----------------------------------------------------------------------+
| 2b. production_forecast                                               |
|     forecast_energy_kwh = 810500                                      |
|     forecast_ghi_irradiance = 165000 Wh/m2                            |
|     forecast_pr = 0.813                                               |
|     Comparison:                                                       |
|       energy_ratio = 783942.656 / 810500 = 0.967 (3.3% under)        |
|       irradiance_ratio = 158200 / 165000 = 0.959 (4.1% under)        |
|       pr_ratio = 0.798 / 0.813 = 0.982 (1.8% under)                  |
+-----------------------------------------------------------------------+
        |
        v   Escalation + FX lookup
+-----------------------------------------------------------------------+
| 3. Pricing Calculator                                                 |
|                                                                       |
|    For FIXED tariff:                                                   |
|      years_since_escalation = 2                                       |
|      escalated_rate = 0.12 * (1 + 0.01)^2 = 0.12241 ZAR              |
|                                                                       |
|    For GRID tariff (hypothetical):                                     |
|      grid_price = market_ref * (1 - discount_pct) = 1.554 * 0.808     |
|      floor = floor_rate * (1 + floor_esc)^years                        |
|      ceiling = ceiling_rate * (1 + ceil_esc)^years                     |
|      applicable = MAX(floor, MIN(grid_price, ceiling))                |
|                                                                       |
|    For CPI-indexed (hypothetical):                                    |
|      CPI_base = price_index[escalation_start_date]                     |
|      CPI_now = price_index[billing_date]                               |
|      escalated_rate = base_rate * (CPI_now / CPI_base)                 |
|                                                                       |
|    exchange_rate: ZAR -> USD at rate_date                              |
+-----------------------------------------------------------------------+
        |
        v
+-----------------------------------------------------------------------+
| 4. expected_invoice_header (invoice_direction = 'receivable')         |
|                                                                       |
|    expected_invoice_line_item                                          |
|      clause_tariff_id -> pricing                                      |
|      meter_aggregate_id -> readings                                   |
|      quantity = 783942.656                                            |
|      line_unit_price = 0.12241 ZAR (escalated)                        |
|      line_total_amount = 95,966.13 ZAR                                |
+-----------------------------------------------------------------------+
        |
        v   Import Sage invoice from Snowflake
+-----------------------------------------------------------------------+
| 5. received_invoice_header (invoice_direction = 'receivable')         |
|                                                                       |
|    received_invoice_line_item                                          |
|      clause_tariff_id -> same tariff line                              |
|      quantity = 783942.656                                            |
|      line_unit_price = 0.12241                                        |
|      line_total_amount = 95,966.10                                    |
+-----------------------------------------------------------------------+
        |
        v   Compare
+-----------------------------------------------------------------------+
| 6. invoice_comparison                                                 |
|    invoice_direction = 'receivable'                                   |
|    variance_amount = 0.03                                             |
|                                                                       |
|    invoice_comparison_line_item                                        |
|      variance_amount = 0.03                                           |
|      variance_percent = 0.00003                                       |
|      variance_details = {                                             |
|        "tariff_used": 0.12241,                                        |
|        "tariff_expected": 0.12241,                                     |
|        "tariff_variance": 0.00,                                        |
|        "quantity_variance": 0.00,                                      |
|        "rounding_difference": 0.03                                     |
|      }                                                                |
+-----------------------------------------------------------------------+
        |
        v   For Min Offtake contracts only (runtime calculation)
+-----------------------------------------------------------------------+
| 7. Deferred Energy (pricing calculator / rules engine)               |
|    total_energy_kwh = 783942                                         |
|    min_offtake_threshold_kwh = 783942 * 0.80 = 627154                |
|    invoiced_energy_kwh = 783942                                      |
|    monthly_variance_kwh = 0 (invoiced > threshold)                   |
|    cumulative_deferred_kwh = 0                                       |
+-----------------------------------------------------------------------+
```

---

## 11. Non-Metered Tariff Lines

CBE has tariff lines that are not meter-based (capacity charges, O&M fees, equipment rental, diesel, penalties). These follow a different pattern:

| Aspect | Metered Line | Non-Metered Line |
|--------|-------------|------------------|
| `clause_tariff.energy_sale_type` | ENERGY_SALES | EQUIPMENT_RENTAL_LEASE, OTHER_SERVICE, BESS_LEASE |
| `clause_tariff.meter_id` | SET (physical meter) | NULL |
| `meter_aggregate` row | YES (with readings) | NO |
| `line_item.meter_aggregate_id` | SET (links to readings) | NULL |
| `line_item.quantity` source | `meter_aggregate.total_production` | From contract terms (e.g. 1 unit/month) |
| `line_item.line_unit_price` source | `clause_tariff.base_rate` (may be escalated) | `clause_tariff.base_rate` (may be escalated) |

---

## 12. Pricing Calculator: Tariff Selection Logic

The core business logic that the Operating Revenue Masterfile encodes. This is what the Pricing Calculator engine must implement.

### FIXED Tariff

```python
def calculate_fixed_tariff(tariff, billing_date, price_index_data):
    years = years_since(tariff.escalation_start_date, billing_date)

    if tariff.escalation_type == 'PERCENTAGE':  # post-059 canonical code
        rate = tariff.logic_parameters['escalation_rate']
        return tariff.base_rate * (1 + rate) ** years

    elif tariff.escalation_type == 'US_CPI':  # post-059 canonical code
        index_name = tariff.logic_parameters.get('price_index_name', 'US_CPI_U')
        cpi_base = price_index_data.get(index_name, tariff.escalation_start_date)
        cpi_now = price_index_data.get(index_name, billing_date)
        return tariff.base_rate * (cpi_now / cpi_base)

    elif tariff.escalation_type == 'REBASED_MARKET_PRICE':  # post-059 canonical code
        # Re-priced to current market; adapter provides updated base_rate
        return tariff.base_rate

    else:  # 'NONE'
        return tariff.base_rate
```

### GRID Tariff

```python
def calculate_grid_tariff(tariff, billing_date, current_grid_price):
    years_floor = years_since_month(tariff.floor_escalation_month, billing_date)
    years_ceil = years_since_month(tariff.ceiling_escalation_month, billing_date)

    solar_tariff = current_grid_price * (1 - tariff.discount_pct)
    floor = tariff.floor_rate * (1 + tariff.floor_escalation_rate) ** years_floor
    ceiling = tariff.ceiling_rate * (1 + tariff.ceiling_escalation_rate) ** years_ceil

    return max(floor, min(solar_tariff, ceiling))
```

### GENERATOR Tariff

Same structure as GRID but with generator cost as the market reference price instead of grid utility price.

### Pain Point: Incorrect Rate Selection

The client's #1 pain point: "The system often has trouble selecting the correct rate on floating tariffs and will continue to charge the discounted MRP even when it is below the floor or above the ceiling."

This is exactly the `MAX(floor, MIN(grid_price * (1 - discount), ceiling))` formula. Sage applies a static discount without checking floor/ceiling bounds. The Pricing Calculator must enforce this bounds check on every invoice.

---

## 13. CBE Portfolio Summary

From the PO Summary tab of the Operating Revenue Masterfile.

| Project | Country | Revenue Type | Sale Type | Tariff Structure | Tariff (USD) | Floor | Ceiling | Escalation |
|---------|---------|-------------|-----------|-----------------|-------------|-------|---------|-----------|
| GC001 | Kenya | Loan - Energy Output | Finance Lease | FIXED | $0.26 | - | - | US CPI |
| UGL01 | Ghana | Energy Sales | Take or Pay | GRID | discounted | $0.1199 | - | 2.0% |
| KAS01 | Ghana | Energy Sales | Take or Pay | GRID | discounted | $0.0874 | $0.30 | 2.5% |
| MOH01 | Ghana | Energy Sales | Take or Pay | FIXED | $0.1087 | - | - | Rebased MKT |
| NBL01/02 | Nigeria | Energy Sales | Take or Pay | GENERATOR | discounted | varies | varies | 2.5% |
| XF* | South Africa | Energy Sales | Take or Pay | FIXED | varies | - | - | US CPI |
| MF01 | Kenya | Energy Sales | Min Offtake | FIXED | $0.0654 | - | - | 1.0% |
| MB01 | Kenya | Energy Sales | Min Offtake | FIXED | $0.0674 | - | - | 1.0% |
| QMM01 | Madagascar | Energy Sales + BESS | Take or Pay | FIXED | $0.2193 | - | - | US CPI |
| LOI01 | Kenya | Energy Sales + BESS | Take or Pay | FIXED | $0.28 | - | - | US CPI |
| CAL01 | Zimbabwe | Energy Sales | Take or Pay | FIXED | $0.1059 | - | - | US CPI |
| UNSOS | Somalia | Energy Sales | Take and Pay | FIXED | $0.1750 | - | - | 2.5% |

~30 operational projects across 10+ countries.

---

## 14. Source Files

The CBE data extracts used for mapping are in this directory:

| File | Contents |
|------|----------|
| `FrontierMind Extracts_dim_finance_contract.csv` | Contract header data |
| `FrontierMind Extracts_dim_finance_contract_line.csv` | Contract line/tariff data |
| `FrontierMind Extracts_dim_finance_customer.csv` | Customer/counterparty data |
| `FrontierMind Extracts_meter readings.csv` | Monthly meter readings |
| `Invoice_Validation_App.py` | CBE's original validation script (reference) |
| `AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx` | COD onboarding template (pricing, technical, yield, contacts) |
| `Operations Plant Performance Workbook.xlsx` | Monthly plant performance tracking (51 tabs, ~30 projects) |
| `CBE Asset Management Operating Revenue Masterfile - new.xlsb` | Revenue management (tariff logic, invoicing, loans, CPI, Sage reconciliation) |

---

## 15. Schema Implementation Status

Tracks which tables/views referenced in this mapping doc have concrete migrations.

| Table/View | Migration | Status |
|------------|-----------|--------|
| `clause_tariff` (base) | 000_baseline + 022 | Implemented |
| `clause_tariff` classification FKs (`tariff_type_id`, `energy_sale_type_id`, `escalation_type_id`, `market_ref_currency_id`) | 027 + 034 + 059 | Implemented. Post-059: `tariff_type` = offtake model, `energy_sale_type` = revenue type, `escalation_type` = pricing mechanism |
| `energy_sale_type` lookup (Revenue/Product Type) | 027 → repurposed 059 | Implemented (059: ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE) |
| `escalation_type` lookup (Pricing Mechanism) | 027 + 059 | Implemented (059: NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES — flat codes, no parent_id) |
| `meter_aggregate` | 000_baseline + 007 + 022 + 026 | Implemented |
| `customer_contact` | 028 | Implemented |
| `production_forecast` | 029 | Implemented |
| `production_guarantee` | 029 | Implemented |
| Deferred energy calculation | — | Deferred to pricing calculator / rules engine — no DB view |
| `exchange_rate` | 022 | Implemented |
| `currency` (seeded) | 022 | Implemented (11 currencies) |
| `tariff_type` (Offtake/Billing Model) | 022 → repurposed 059 | Implemented (059: TAKE_OR_PAY, TAKE_AND_PAY, MINIMUM_OFFTAKE, FINANCE_LEASE, OPERATING_LEASE, NOT_APPLICABLE) |
| `billing_period` (calendar) | 021 + 033 | Implemented (48 months: Jan 2024 – Dec 2027, UNIQUE on dates) |
| `generated_report.invoice_direction` | 034 | Implemented (nullable enum, wired through report pipeline) |
| `contract.payment_terms` | 034 | Implemented (VARCHAR(50), parsed from onboarding template) |
| `contract.ppa_confirmed_uploaded`, `has_amendments` | 033 | Implemented (BOOLEAN, now wired through parser) |
| Multi-value billing products (Product 1/2/3) | — | Implemented in parser (extracts all numbered "Product to be billed" rows) |
| Multi-value service types (Type 1/2) | — | Implemented in parser + merge (creates one `clause_tariff` per service type) |
| `project.external_project_id`, `sage_id`, `country`, `cod_date`, capacities | 033 | Implemented |
| `contract.external_contract_id`, `contract_term_years`, `interconnection_voltage_kv` | 033 | Implemented |
| `contract.payment_security_required/details`, `agreed_fx_rate_source` | 033 | Implemented |
| `reference_price` | 033 | Implemented |
| `contract_amendment` | 033 | Implemented |
| `onboarding_preview` | 033 | Implemented |
| `billing_product` + `contract_billing_product` | 034 | Implemented |
| `tariff_rate` (unified from `tariff_annual_rate` + `tariff_monthly_rate`) | 040 | Implemented (four-currency repr., calc_detail JSONB, FX audit trail, calc_status enum) |
| `submission_token.project_id`, `submission_type` | 037 | Implemented |
| `reference_price.observation_type`, `source_document_path/hash`, `submission_response_id` | 037 | Implemented |
| `clause_tariff` amendment version history (MOH01 supersedes chain) | 038 | Implemented (pre-amendment original row, supersedes linkage) |
| Pipeline integrity fixes (annual ref_price unique index, asset_type seeds, metering_type CHECK) | 039 | Implemented |
| `meter.name` | 041 | Implemented (VARCHAR(100), human-readable meter names) |
| `contract_line` | 041 | Implemented (links contract to meters + energy categories, `energy_category` enum) |
| `meter_aggregate.available_energy_kwh`, `contract_line_id`, `ghi_irradiance_wm2`, `poa_irradiance_wm2` | 041 | Implemented |
| `plant_performance` | 041 | Implemented (derived monthly performance metrics, FKs to production_forecast + billing_period) |
| `energy_category` enum (`metered`, `available`, `test`) | 041 | Implemented |
| `contract.parent_contract_id` | 046 | Implemented (BIGINT FK, self-ref with CHECK + trigger for same-project) |
| `contract_amendment.amendment_date` nullable | 046 | Implemented (nullable — unknown signing dates) |
| `price_index` | — | **Pending** — needed for CPI escalation |
| `loan_schedule` / `loan_payment` | — | **Pending** — needed for loan repayment tracking |

---

## 16. Known Pipeline Gaps

From the MOH01 onboarding audit (`database/scripts/project-onboarding/audits/GH_MOH01_ONBOARDING_AUDIT.md`). These apply to all projects until resolved.

| # | Gap | Impact | Status |
|---|-----|--------|--------|
| 1 | `contract.effective_date` and `end_date` not extracted from PPA | Contract date range missing — requires manual PPA lookup | Open |
| 2 | `customer_contact` — no contacts in some Excel templates | Contact list empty — requires manual entry or template update | Open |
| 3 | `reference_price` — GRP needs ECG/utility market pricing data | Cannot calculate rebased tariff until GRP observations loaded | Open (resolved per-project via GRP ingestion flow) |
| 4 | `production_forecast.source_metadata` supplementary fields | Core forecast data intact; metadata (adjustment factors) incomplete | Open (low priority) |
| 5 | Tariff structure inference — pipeline should infer GRID from presence of floor/ceiling/discount | Pipeline uses Excel value (often incorrect) instead of inferring from PPA parameters | Open |
| 6 | Meter attributes — Excel parser extracts serial numbers and `metering_type` (via normalizer) but not `location_description` or `meter_type_id` | Meter records have serials and metering_type; `location_description` and `meter_type_id` remain missing | Partially resolved |
| 7 | `grp_method` — neither Excel nor LLM reliably extracts the GRP calculation method | NULL in `logic_parameters`; should be set when GRP parameters are present | Open |
| 8 | `grp_exclude_savings_charges` — LLM sometimes returns null for this parameter | May need prompt refinement in `onboarding_extraction_prompt.py` | Open |
| 9 | Guarantee pro-rata adjustment — pipeline uses base PPA values, not capacity-adjusted | `guaranteed_kwh` may be understated for projects with actual > design capacity | Open |
| 10 | SQL section sort order — `sorted(sections.keys())` uses lexicographic sort, placing `4.10` before `4.2` | Contract Billing Products (4.10) executed before Project (4.2) existed — FK JOINs returned zero rows silently | **Fixed** (Python service logic in `onboarding_service.py`, numeric sort key) |
| 11 | Pre-flight validation skipped — Step 3 validation parsed but `continue`d past in the upsert loop | FK/CHECK pre-flight assertions never ran; invalid data inserted silently | **Fixed** (validation runs before upsert loop) |
| 12 | Asset type enum mismatch — parser produced `SOLAR_PANEL`/`INVERTER` (uppercase), DB seeded `pv_module`/`inverter` (lowercase) | All asset inserts failed FK resolution (masked by skipped validation) | **Fixed** (parser now produces canonical lowercase codes) |
| 13 | Metering type constraint mismatch — normalizer can return `gross`/`bidirectional`, DB CHECK only allowed `net`/`export_only` | Onboarding would fail on meters with non-standard metering configs | **Fixed** (migration 039 expands CHECK constraint) |
| 14 | Operating year after billing period reconciliation — extraction could change `billing_month` but `operating_year` was computed from the original | Stored observation had wrong operating year when invoice month differed from submission | **Fixed** (recomputes operating_year after reconciliation) |
| 15 | PPA structured field mapping incomplete — LLM returns structured `default_rate` and `available_energy` but parser only populated deprecated flat fields | `default_rate` and `available_energy` always None in `PPAContractData` | **Fixed** (parser now populates structured models) |
| 16 | `formula_type` not set at onboarding — rebased market price engine requires `logic_parameters.formula_type` but tariff builder never set it | Engine would fail when invoked for onboarded REBASED_MARKET_PRICE projects | **Fixed** (infers GRID_DISCOUNT_BOUNDED from floor/ceiling presence) |
| 17 | Cross-tenant counterparty conflation — global unique key `(counterparty_type_id, LOWER(name))` means two orgs with same counterparty name conflict | Currently single-tenant (CBE only); will need `organization_id` added when second client onboards | Open (design debt) |
| 18 | Capacity mismatch — `project.installed_dc_capacity_kwp` vs `forecast.source_metadata.site_params.capacity_kwp` for 7 projects (MF01 -82%, NC02 -62%, MB01 -53%, IVL01 +235%, KAS01 -31%, NBL01 -21%, QMM01 +12%) | Forecast extension uses existing values as-is, but absolute energy figures may be wrong if based on wrong capacity | Open |
| 19 | UNSOS forecast data anomaly — 2025-2026 values appear templated/constant, causing 16.8% implicit degradation (capped to 1%) | Extended forecasts use capped degradation; underlying baseline may be incorrect | Open |
| 20 | Missing COD dates — AMP01, XFBV, XFL01, XFSS have NULL `cod_date` | `operating_year` NULL on projected rows; cannot use cod+term end date fallback | Open |

---

## 17. Portfolio Population (Migration 046)

**Migration:** `database/migrations/046_populate_portfolio_base_data.sql`
**Date:** 2026-02-27

### Schema Changes

| Change | Table | Details |
|--------|-------|---------|
| New column | `contract` | `parent_contract_id BIGINT REFERENCES contract(id)` — links ancillary docs to primary contract |
| Constraint | `contract` | `chk_contract_no_self_parent` — prevents self-reference |
| Trigger | `contract` | `trg_contract_same_project_parent` — parent must be same project |
| Index | `contract` | `idx_contract_parent` — partial index WHERE parent IS NOT NULL |
| Nullable | `contract_amendment` | `amendment_date` now nullable (unknown signing dates) |

### Legal Entity Mapping

11 entities total (3 existing + 8 new), all `organization_id = 1`.

| Code | Name | Country | Status |
|------|------|---------|--------|
| CBCH | CrossBoundary Energy Credit Holding | Mauritius | Existing |
| EGY0 | CrossBoundary Energy Egypt For Solar Energy | Egypt | Existing |
| GHA0 | CrossBoundary Energy Ghana Limited Company | Ghana | Existing |
| KEN0 | CrossBoundary Energy Kenya Limited | Kenya | **New** |
| MAD0 | CrossBoundary Energy Madagascar | Madagascar | **New** |
| MAD2 | CrossBoundary Energy Madagascar II SA | Madagascar | **New** |
| NIG0 | CrossBoundary Energy Nigeria Ltd | Nigeria | **New** |
| SL02 | CrossBoundary Energy (SL) Limited | Sierra Leone | **New** |
| SOM0 | KUBE Energy Somalia LLC | Somalia | **New** |
| MOZ0 | Balama Renewables, Limitada | Mozambique | **New** |
| ZIM0 | CrossBoundary Energy Zimbabwe Limited | Zimbabwe | **New** |

### Counterparty Mapping

~28 counterparties total (6 existing + ~22 new). All as `counterparty_type = OFFTAKER`.

| Counterparty Name | Industry | Country | Projects |
|--------------------|----------|---------|----------|
| GC Retail | Real Estate | Mauritius | GC01 |
| Zoodlabs Group | Telecom | Mauritius | ZO01, ZL02 |
| iSAT Africa | Telecom | Mauritius | TBC |
| Indorama Ventures | Oil, Petrochemical | Egypt | IVL01 |
| Diageo | Food & Drink | Ghana | GBL01 |
| Kasapreko Company | Food & Drink | Ghana | KAS01 |
| Unilever | Consumer Products | Ghana | UGL01 |
| Polytanks Ghana Limited | Consumer Products | Ghana | MOH01 (existing) |
| Arijiju Retreat | Hospitality | Kenya | AR01 |
| Oryx Ltd | Hospitality | Kenya | LOI01 |
| Devki Group | Manufacturing | Kenya | MB01, MF01, MP01, MP02, NC02, NC03 |
| Brush Manufacturers | Manufacturing | Kenya | TBM01 |
| Lipton | Food & Drink | Kenya | UTK01 |
| XFlora Group | Agriculture | Kenya | XF-AB |
| Ampersand | Transport | Kenya | AMP01 |
| Rio Tinto | Mining | Madagascar | QMM01 |
| Next Source Materials | Mining | Madagascar | ERG |
| Jabi Mall Development Co | Real Estate | Nigeria | JAB01 |
| Heineken | Food & Drink | Nigeria | NBL01, NBL02 |
| Miro Forestry and Timber Products | Forestry | Sierra Leone | MIR01 |
| UNSOS | NGO | Somalia | UNSOS |
| Twigg Exploration and Mining | Mining | Mozambique | TWG01 |
| Blanket Mine | Mining | Zimbabwe | CAL01 |
| Accra Breweries | Food & Drink | Ghana | ABI01 |
| Izuba BNT | Energy | Rwanda | BNT01 |

### Project Mapping

33 projects total. MOH01 is pre-existing (id=8).

| Sage ID | External ID | Project Name | Country | Legal Entity | COD Date | Capacity (kWp) | Currency |
|---------|-------------|--------------|---------|--------------|----------|----------------|----------|
| GC01 | KE 22006 | Garden City Mall | Kenya | CBCH | 2016-06-01 | 858 | USD |
| ZO01 | SL 22030 | Zoodlabs Group | Sierra Leone | CBCH | 2024-04-01 | - | USD |
| TBC | DRC 23521 | iSAT Africa | DRC | CBCH | 2025-08-29 | - | USD |
| IVL01 | EG 22008 | Indorama Ventures - Expanded | Egypt | EGY0 | 2023-10-02 | 3,238 | USD |
| GBL01 | GH 22005 | Guinness Ghana Breweries | Ghana | GHA0 | 2021-03-19 | 1,095 | GHS |
| KAS01 | GH 22010 | Kasapreko - Phase I and II | Ghana | GHA0 | 2024-05-03 | 1,305 | GHS |
| UGL01 | GH 22022 | Unilever Ghana | Ghana | GHA0 | 2021-01-05 | 970 | GHS |
| **MOH01** | **GH 22015** | **Mohinani Group** | **Ghana** | **GHA0** | **2025-12-12** | **2,617** | **GHS** |
| ABI01 | - | Accra Breweries Ghana | Ghana | GHA0 | - | - | - |
| AR01 | KE 22469 | Arijiju Retreat | Kenya | KEN0 | 2023-10-24 | 205 | USD |
| LOI01 | KE 22013 | Loisaba | Kenya | KEN0 | 2019-03-01 | 74 | USD |
| MB01 | KE 22434 | Maisha Mabati Mills LuKenya | Kenya | KEN0 | 2025-01-01 | 1,173 | USD |
| MF01 | KE 22435 | Maisha Minerals & Fertilizer | Kenya | KEN0 | 2023-10-24 | 674 | USD |
| MP02 | KE 22436 | Maisha Packaging LuKenya | Kenya | KEN0 | 2024-03-28 | 1,386 | USD |
| MP01 | KE 22471 | Maisha Packaging Nakuru | Kenya | KEN0 | 2024-04-05 | 681 | USD |
| NC02 | KE 22432 | National Cement Athi River | Kenya | KEN0 | 2023-10-24 | 493 | USD |
| NC03 | KE 22433 | National Cement Nakuru | Kenya | KEN0 | 2024-04-08 | 2,237 | USD |
| TBM01 | KE 22021 | TeePee Brushes | Kenya | KEN0 | 2023-02-08 | 1,508 | KES |
| UTK01 | KE 22023 | eKaterra Tea Kenya | Kenya | KEN0 | 2019-05-27 | 619 | KES |
| XF-AB | KE 22025 | XFlora Group | Kenya | KEN0 | 2021-02-01 | 424 | KES |
| AMP01 | KE 23622 | Ampersand | Kenya | KEN0 | - | 37 | USD |
| BNT01 | - | Izuba BNT | Rwanda | KEN0 | - | - | - |
| QMM01 | MG 22017 | Rio Tinto QMM | Madagascar | MAD0 | 2025-02-01 | 14,448 | MGA |
| ERG | MG 22028 | Molo Graphite | Madagascar | MAD2 | 2023-11-16 | 2,696 | MGA |
| JAB01 | NG 22009 | Jabi Lake Mall | Nigeria | NIG0 | 2020-06-30 | 610 | NGN |
| NBL01 | NG 22016 | Nigerian Breweries - Ibadan | Nigeria | NIG0 | 2025-01-01 | 3,173 | NGN |
| NBL02 | NG 22031 | Nigerian Breweries - Ama | Nigeria | NIG0 | 2023-02-27 | 4,006 | NGN |
| MIR01 | SL 22014 | Miro Forestry | Sierra Leone | SL02 | 2023-10-01 | 236 | SLE |
| ZL02 | SL 24702 | Zoodlabs Energy Services | Sierra Leone | SL02 | 2025-03-01 | - | USD |
| UNSOS | SO 22024 | UNSOS Baidoa | Somalia | SOM0 | 2024-03-17 | 2,732 | USD |
| TWG01 | MZ 22003 | Balama Graphite | Mozambique | MOZ0 | 2025-12-01 | 11,249 | MZN |
| CAL01 | ZW 23541 | Caledonia | Zimbabwe | ZIM0 | 2025-04-15 | 13,895 | USD |

### Contract Type Mapping

| CBE Agreement Type | FrontierMind `contract_type.code` |
|--------------------|-----------------------------------|
| SSA / PPA / RESA / Project Agreement | `PPA` |
| Finance Lease / Operating Lease / BOOT Operating Lease / Equipment Lease | `LEASE` |
| ESA / ESA + O&M / ESA + Battery Lease | `ESA` |
| Wheeling Agreement / Loan Agreement | `OTHER` |

### Contract Hierarchy

Primary contracts have `parent_contract_id = NULL`. Ancillary documents reference the primary via `parent_contract_id`.

**Ancillary Documents (~13):**

| Project | Ancillary Document | Document Type |
|---------|-------------------|---------------|
| GC01 | Garden City SolarAfrica-CBE Project Agreement Assignment | assignment_agreement |
| GC01 | Garden City Transaction Documents | transaction_documents |
| LOI01 | Loisaba SSA Revised Annexures | revised_annexures |
| LOI01 | Loisaba SolarAfrica COD Acceptance Certificate | cod_certificate |
| LOI01 | Loisaba Transfer Acceptance Certificates | transfer_certificate |
| QMM01 | QMM Permission Agreement | permission_agreement |
| UGL01 | Unilever Ghana SSA Schedules | ssa_schedules |
| UGL01 | Unilever Ghana COD Notice | cod_notice |
| UTK01 | Unilever Tea Kenya SSA Schedules | ssa_schedules |
| XF-AB | XFlora SSA 1st Amendment COD Extension | cod_extension |
| XF-AB | XFlora SSA Adherence Agreement | adherence_agreement |
| CAL01 | CMS Sale of Shares and Sale Claims Agreement | share_sale_agreement |
| ZO01 | Zoodlabs Solar Loan Agreement | loan_agreement |

### Amendment Mapping

~19 amendments total (1 existing MOH01 + 18 new). `NULL` dates indicate unknown signing dates.

| Project | # | Date | Description |
|---------|---|------|-------------|
| MOH01 | 1 | 2023-07-05 | *Existing* — Extended term, increased discount |
| GBL01 | 1 | 2019-12-19 | 1st Amendment to Guinness Ghana Breweries SSA |
| GBL01 | 2 | 2020-12-17 | 2nd Amendment to Guinness Ghana Breweries SSA |
| IVL01 | 1 | 2022-08-18 | Amendment & Restatement of IVL Dhunseri SSA |
| KAS01 | 1 | 2017-05-31 | Kasapreko SSA Amendment (Solar Africa) |
| KAS01 | 2 | 2019-04-26 | 1st Amendment Solar Phase II |
| KAS01 | 3 | 2020-07-06 | 2nd Amendment - Reinforcement Works |
| KAS01 | 4 | 2021-03-01 | 3rd Amendment - Interconnection Works |
| LOI01 | 1 | 2018-10-16 | 1st Amendment to Loisaba SSA |
| MIR01 | 1 | 2021-11-11 | 1st Amendment to Miro Forestry SSA |
| NBL01 | 1 | 2019-02-01 | 1st Amendment to Nigerian Breweries Ibadan SSA |
| NBL01 | 2 | 2021-05-07 | 2nd Amendment to Nigerian Breweries Ibadan SSA |
| NBL01 | 3 | 2022-10-22 | 3rd Amendment to Nigerian Breweries Ibadan SSA |
| NBL02 | 2 | 2021-05-01 | 2nd Amendment to Nigerian Breweries Ama SSA |
| QMM01 | 1 | *NULL* | 1st Amendment to QMM RESA |
| QMM01 | 2 | *NULL* | 2nd Amendment to QMM RESA |
| UNSOS | 2 | *NULL* | 2nd Amendment to UNSOS Baidoa SSA |
| UNSOS | 3 | 2023-11-14 | 3rd Amendment to UNSOS Baidoa SSA (Kube) |
| XF-AB | 1 | 2020-06-20 | 1st Amendment to XFlora Group SSA |

### Sage ID Normalization

| CBE Source Value | FrontierMind Sage ID | Reason |
|------------------|---------------------|--------|
| GC001 | GC01 | Normalized to 2-digit suffix |
| ZL01 (Zoodlabs Group, CBCH entity) | ZO01 | Disambiguated from ZL02 (Zoodlabs, SL02 entity) |
| XF-AB/BV/L01/SS | XF-AB | Shortened compound ID |

### Anomalies & Decisions

| Project | Issue | Decision |
|---------|-------|----------|
| CAL01 | No original PPA — only Amended & Restated version | Insert A&R as the primary contract |
| KAS01 | No original SSA — earliest doc is 2017 Solar Africa amendment | Insert placeholder primary contract; amendments reference it |
| UNSOS | Original SSA + 1st Amendment not available | Insert placeholder primary; 2nd & 3rd amendments reference it |
| NBL01 | 3rd Amendment may be duplicated (two files with same size) | Insert once |
| NBL02 | 2nd Amendment dated 2021-05-01 before SSA dated 2021-12-10 | Insert with actual dates; `amendment_number = 2` per source doc title |
| UNSOS | Original SSA + 1st Amendment not available | `amendment_number` starts at 2 (2nd) and 3 (3rd) per source doc titles |
| TBM01 | Two copies of SSA (stamped + signed) | Insert once |
| ABI01 | No Excel entry — found only in contract PDFs | Insert as project with limited metadata |
| BNT01 | No Excel entry — found only in contract PDFs | Insert as project with limited metadata |
| TBC / ZL02 | No contract PDFs available | Project + counterparty only, no contract row |
| ZO01 | Originally listed as no PDFs, but 2 exist | Primary ESA + ancillary loan agreement; country corrected to Sierra Leone |
| GC01 / TBC | `project.country` was legal jurisdiction (Mauritius) | Corrected to physical site location: Kenya (GC01), DRC (TBC) |
| GC01 / ZO01 / XF-AB | Sage ID normalized from source | `extraction_metadata.source_sage_customer_id` preserves original: GC001, ZL01, XF-AB/BV/L01/SS |
| Unclassified PDF | `Please sign IHS POC contract - signed.pdf` | Skipped — not attributable to any project |

### Backend Code Changes

| File | Change | Reason |
|------|--------|--------|
| `python-backend/api/billing.py` (~line 264) | Added `AND c.parent_contract_id IS NULL` to contract JOIN | Prevent billing from picking ancillary doc |
| `python-backend/api/billing.py` (~line 27-40) | Added 8 country codes to `_COUNTRY_NAME_TO_CODE`: EG, MG, SL, SO, MZ, ZW, CD, RW | `_country_to_code()` now resolves all portfolio countries |
| `python-backend/api/entities.py` (~line 728) | Changed ORDER BY to `c.parent_contract_id NULLS FIRST, c.effective_date` | Ensure `contracts[0]` is always the primary contract |

---

## 18. SAGE ERP Contract Number Mapping (Migration 047, Part A)

**Migration:** `database/migrations/047_populate_sage_contract_ids.sql` (Part A)

**Source:** `CBE_data_extracts/Data Extracts/FrontierMind Extracts_dim_finance_contract.csv` — SAGE ERP finance contract dimension extract with SCD Type 2 versioning. Only `DIM_CURRENT_RECORD=1` rows used.

### Purpose

Cross-references SAGE ERP contract records with FrontierMind's `contract` table to populate three fields that are critical for invoice verification:

| FM Column | SAGE Source Column | Purpose |
|---|---|---|
| `contract.external_contract_id` | `CONTRACT_NUMBER` | SAGE contract identifier (e.g., `CONKEN00-2023-00009`); displayed as "Contract ID" on Overview tab |
| `contract.payment_terms` | `PAYMENT_TERMS` | Payment term code (e.g., `30NET`, `90EOM`); determines invoice due dates |
| `contract.end_date` | `END_DATE` | Contract expiration date; used for contract validity checks |

### SAGE Contract Number Pattern

Format: `CON{FACILITY}-{YEAR}-{SEQ}`

| Component | Description | Example |
|---|---|---|
| `CON` | Fixed prefix | — |
| `{FACILITY}` | CBE legal entity facility code | `KEN00`, `GHA00`, `CBCH0`, `MAD00` |
| `{YEAR}` | Year contract was created in SAGE | `2021`, `2023`, `2024` |
| `{SEQ}` | 5-digit sequential ID within facility/year | `00001`, `00013` |

### Complete Mapping: project.sage_id -> SAGE Contract

| FM sage_id | SAGE Contract Number | SAGE Customer | SAGE Facility | Category | Payment Terms | Start Date | End Date | Active |
|---|---|---|---|---|---|---|---|---|
| GC01 | CONCBCH0-2021-00001 | GC001 | CBCH0 | KWH | 30EOM | 2021-01-01 | 2030-02-28 | 1 |
| IVL01 | CONEGY00-2023-00001 | IVL01 | EGY00 | KWH | 30NET | 2023-10-01 | 2048-08-30 | 1 |
| UGL01 | CONGHA00-2021-00001 | UGL01 | GHA00 | KWH | 90NET | 2021-01-01 | 2035-12-31 | 1 |
| KAS01 | CONGHA00-2021-00002 | KAS01 | GHA00 | KWH | 30EOM | 2021-01-01 | 2030-02-28 | 1 |
| GBL01 | CONGHA00-2021-00004 | GBL01 | GHA00 | KWH | 60NET | 2021-03-01 | 2047-05-31 | 1 |
| MOH01 | CONGHA00-2025-00005 | MOH01 | GHA00 | KWH | 30NET | 2025-08-15 | 2045-12-31 | 1 |
| UTK01 | CONKEN00-2021-00001 | UTK01 | KEN00 | KWH | 90EOM | 2021-04-01 | 2036-06-30 | 1 |
| LOI01 | CONKEN00-2021-00002 | LOI01 | KEN00 | KWH | 30EOM | 2021-04-01 | 2037-05-31 | 1 |
| XF-AB | CONKEN00-2021-00003 | XFAB | KEN00 | KWH | 30EOM | 2021-04-01 | 2047-05-31 | 1 |
| TBM01 | CONKEN00-2023-00007 | TBM01 | KEN00 | KWH | 30NET | 2023-02-01 | 2042-02-01 | 1 |
| AR01 | CONKEN00-2023-00008 | AR01 | KEN00 | RENTAL | 30NET | 2023-11-01 | 2035-11-01 | 1 |
| MB01 | CONKEN00-2023-00009 | MB01 | KEN00 | KWH | 30NET | 2023-11-01 | 2044-12-31 | 1 |
| NC02 | CONKEN00-2023-00010 | NC02 | KEN00 | KWH | 30NET | 2023-11-01 | 2043-11-01 | 1 |
| MF01 | CONKEN00-2023-00011 | MF01 | KEN00 | KWH | 30NET | 2023-11-01 | 2043-11-01 | 1 |
| MP02 | CONKEN00-2024-00012 | MP02 | KEN00 | KWH | 30NET | 2024-02-01 | 2044-02-29 | 1 |
| NC03 | CONKEN00-2024-00013 | NC03 | KEN00 | KWH | 30NET | 2024-03-01 | 2044-02-29 | 1 |
| MP01 | CONKEN00-2024-00014 | MP01 | KEN00 | KWH | 30NET | 2024-02-01 | 2044-03-31 | 1 |
| AMP01 | CONKEN00-2025-00013 | AMP01 | KEN00 | KWH | 30EOM | 2025-01-01 | 2032-03-31 | 1 |
| UNSOS | CONKUBE0-2024-00001 | UNSOS | KUBE0 | KWH | 30NET | 2024-03-01 | 2028-12-31 | 1 |
| QMM01 | CONMAD00-2023-00001 | QMM01 | MAD00 | KWH | 75EOM | 2023-02-01 | 2043-05-03 | 1 |
| ERG | CONMAD02-2023-00001 | ERG | MAD02 | KWH | 30NET | 2023-11-01 | 2043-11-13 | 1 |
| TWG01 | CONMOZ00-2023-00003 | TWG | MOZ00 | RENTAL | 30EOM | 2023-11-01 | 2033-11-01 | 1 |
| JAB01 | CONNIG00-2021-00001 | JAB01 | NIG00 | KWH | 30EOM | 2021-01-01 | 2033-02-28 | 1 |
| NBL01 | CONNIG00-2021-00002 | NBL01 | NIG00 | KWH | 60NET | 2021-02-01 | 2036-03-31 | 1 |
| NBL02 | CONNIG00-2023-00003 | NBL02 | NIG00 | KWH | 60NET | 2023-02-01 | 2038-03-01 | 1 |
| MIR01 | CONSLL02-2023-00002 | MIR01 | SLL02 | KWH | 30NET | 2022-10-01 | 2029-10-01 | 1 |
| CAL01 | CONZIM00-2025-00002 | CAL01 | ZIM00 | KWH | 30NET | 2025-04-01 | 2041-12-31 | 1 |

### XFlora Sub-Contract Mapping

SAGE has 4 separate contracts for XFlora sub-farms, all under KEN00 facility. FrontierMind consolidates these into a single project `XF-AB` with `CONKEN00-2021-00003` (XFAB) as the primary `external_contract_id`:

| SAGE Customer | SAGE Contract | FM Project | Notes |
|---|---|---|---|
| XFAB | CONKEN00-2021-00003 | XF-AB | Primary — used as `external_contract_id` |
| XFBV | CONKEN00-2021-00004 | XF-AB | Sub-contract (Bloom Valley) |
| XFL01 | CONKEN00-2021-00005 | XF-AB | Sub-contract (Xpressions Flora) |
| XFSS | CONKEN00-2021-00006 | XF-AB | Sub-contract (Sojanmi Spring) |

All 4 SAGE contracts share the same terms (30EOM) and end date (2047-05-31 for KEN00 records). The sub-contract numbers are stored in `extraction_metadata.sage_sub_contracts` for audit purposes.

### SAGE ID Mismatches

| FM sage_id | SAGE CUSTOMER_NUMBER | Resolution |
|---|---|---|
| GC01 | GC001 | FM normalized to GC01; original tracked in `extraction_metadata.source_sage_customer_id` |
| TWG01 | TWG | FM uses TWG01 for consistency; SAGE has TWG. Mapping via `project.sage_id` handles this. |

### Contracts Not in SAGE (3 FM projects)

| FM sage_id | FM contract_id | Reason |
|---|---|---|
| ABI01 | 42 | No SAGE contract record — project sourced from contract PDFs only |
| BNT01 | 43 | No SAGE contract record — project sourced from contract PDFs only |
| ZO01 | 56 | SAGE `ZL01` contracts reassigned to `ZL02` entity; ZO01 has ESA from PDF |

### Payment Terms Codes

SAGE payment term codes encode both the number of days and the calculation basis:

| Code | Days | Basis | Meaning |
|---|---|---|---|
| 30NET | 30 | Net | Due 30 days from invoice date |
| 30EOM | 30 | End of Month | Due 30 days from end of invoice month |
| 60NET | 60 | Net | Due 60 days from invoice date |
| 75EOM | 75 | End of Month | Due 75 days from end of invoice month |
| 90NET | 90 | Net | Due 90 days from invoice date |
| 90EOM | 90 | End of Month | Due 90 days from end of invoice month |

These are stored as raw VARCHAR in `contract.payment_terms`. Parsing into structured attributes (days, is_eom) is deferred until the billing engine consumes payment terms for due-date calculation.

### Verification Query

```sql
SELECT p.sage_id, c.external_contract_id, c.payment_terms, c.end_date
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE c.parent_contract_id IS NULL
  AND c.organization_id = 1
ORDER BY p.sage_id;
-- Expected: 27 rows with non-NULL external_contract_id, payment_terms, end_date
-- 3 rows (ABI01, BNT01, ZO01) with all NULL
```

## 19. Parent-Child Contract Line Hierarchy (Migration 047, Part B)

### Problem

CBE models certain contract lines at the **site level** — a single line covers all meters for an energy category. FrontierMind's billing engine operates **per-meter**, requiring each meter to have its own `contract_line` row. This creates a 1-to-many mapping that the standard identity chain (Layer 3: `CONTRACT_LINE_UNIQUE_ID → contract_line.external_line_id`) cannot represent with a simple 1-to-1 match.

**Example — MOH01 Available Energy:**

| System | Line | Description | Scope | parent_contract_line_id |
|--------|------|-------------|-------|------------------------|
| **CBE** | 1000 | Available Energy (EAvailable) | Site-level, all meters | — |
| **FrontierMind** | 1000 | Available Energy (EAvailable) - Site Level | Mother (meter_id NULL) | NULL |
| **FrontierMind** | 4001 | Available Energy (EAvailable) - PPL1 | Per-meter (PPL1) | → 1000 |
| **FrontierMind** | 5001 | Available Energy (EAvailable) - PPL2 | Per-meter (PPL2) | → 1000 |
| **FrontierMind** | 6001 | Available Energy (EAvailable) - Bottles | Per-meter (Bottles) | → 1000 |
| **FrontierMind** | 7001 | Available Energy (EAvailable) - BBM1 | Per-meter (BBM1) | → 1000 |
| **FrontierMind** | 8001 | Available Energy (EAvailable) - BBM2 | Per-meter (BBM2) | → 1000 |

CBE `CONTRACT_LINE_UNIQUE_ID = '11481428495164935368'` is stored as `external_line_id` on the mother line 1000. Children link via `parent_contract_line_id`.

### Solution: `parent_contract_line_id` Self-Referential FK

Migration 047 (Part B) adds a self-referential FK to `contract_line`, mirroring the existing `contract.parent_contract_id` pattern:

```sql
ALTER TABLE contract_line
    ADD COLUMN parent_contract_line_id BIGINT REFERENCES contract_line(id);

-- No self-parent
ALTER TABLE contract_line
    ADD CONSTRAINT chk_contract_line_no_self_parent
        CHECK (parent_contract_line_id <> id);

-- Trigger: parent must belong to same contract
CREATE TRIGGER trg_contract_line_same_contract_parent
    BEFORE INSERT OR UPDATE OF parent_contract_line_id ON contract_line
    FOR EACH ROW EXECUTE FUNCTION contract_line_same_contract_parent();
```

**Mother line properties:**
- `meter_id = NULL` (site-level, no specific meter)
- `external_line_id` set to CBE `CONTRACT_LINE_UNIQUE_ID` (for Layer 3 traceability)
- `parent_contract_line_id = NULL` (it IS the parent)
- Excluded from invoice generation via `AND cl.parent_contract_line_id IS NULL` filters

### How the Billing Resolver Uses It

`billing_resolver._bulk_resolve_contract_lines()` does **two-pass resolution**:

1. **Pass 1 — Direct match:** `contract_line.external_line_id = ANY(ids)` (existing 1-to-1 logic)
2. **Pass 2 — Parent-child fallback:** For matched lines with `meter_id IS NULL` (mother lines), query children via `parent_contract_line_id` to find the first active child with a valid `meter_id`

The parent-child fallback returns `DISTINCT ON (parent_contract_line_id)` — the first child line. Downstream meter routing (via the billing record's `FACILITY` / `device_id` field) assigns the correct meter.

### How the Eval Harness Handles It

`mapping_metrics.compute_contract_line_coverage()` uses direct `external_line_id` matching only. The mother line has `external_line_id` set, so Layer 3 coverage works without any special decomposition logic.

`test_billing_readiness.test_contract_line_meter_fk()` excludes mother lines (where `parent_contract_line_id IS None`) from the `meter_id` assertion, since mother lines legitimately have `meter_id = NULL`.

### CBE Fields NOT Mapped to `contract_line`

The following CBE fields from `dim_finance_contract_line` are intentionally excluded:

| CBE Field | Reason | Where It Belongs |
|-----------|--------|-----------------|
| `PRICE_ADJUST_DATE` | Tariff escalation trigger date (1753-01-01 = SQL Server NULL) | `clause_tariff.logic_parameters.escalation_start_date` |
| `IND_USE_CPI_INFLATION` | Escalation rule indicator | `clause_tariff.logic_parameters.escalation_rules` |
| `DIM_START_DATE` | SCD2 audit metadata (not a business date) | Not used — CBE internal |
| `DIM_END_DATE` | SCD2 audit metadata (not a business date) | Not used — CBE internal |
| `EXTRACTED_AT` | SCD2 extraction timestamp | Not used — CBE internal |
| `UPDATED_AT` / `UPDATED_BY` | SCD2 audit fields | Not used — CBE internal |
| `DIM_CURRENT_RECORD` | SCD2 current-version flag | Not used — FrontierMind uses `is_active` |

Use `EFFECTIVE_START_DATE` and `EFFECTIVE_END_DATE` (the business dates) for `contract_line.effective_start_date` / `effective_end_date`.

### When to Apply This Pattern

Apply parent-child contract line hierarchy when **all** of these conditions are true:

1. CBE has a **site-level** contract line (no meter association, or `METERED_AVAILABLE = 'N/A'`)
2. FrontierMind has **per-meter** lines for the same energy category
3. The CBE line's `CONTRACT_LINE_UNIQUE_ID` does not already match a direct `external_line_id`

**Steps for new projects:**
1. During onboarding, identify site-level CBE lines (typically line 1000 for available, line 2000 for metered)
2. Insert a mother `contract_line` with the CBE `CONTRACT_LINE_UNIQUE_ID` as `external_line_id`, `meter_id = NULL`
3. Create per-meter child lines as usual (line X001 per meter)
4. Set `parent_contract_line_id` on each child to the mother line's `id`
5. Verify with the Layer 3 coverage check

### Verification Query

```sql
-- Check parent-child hierarchy for a project
SELECT
    cl.contract_line_number,
    cl.product_desc,
    cl.parent_contract_line_id,
    cl.meter_id,
    cl.external_line_id,
    m.name AS meter_name
FROM contract_line cl
JOIN contract c ON c.id = cl.contract_id
LEFT JOIN meter m ON m.id = cl.meter_id
WHERE c.external_contract_id = 'CONGHA00-2025-00005'
  AND cl.energy_category = 'available'
ORDER BY cl.contract_line_number;
-- Expected: line 1000 has NULL parent, NULL meter, external_line_id set
-- Lines 4001-8001 have parent_contract_line_id pointing to line 1000's id
```

---

## 20. Pilot Project Data Population (Migration 049)

Migration 049 populates contract_line, clause_tariff, meter_aggregate, and contract_billing_product for 3 pilot projects, establishing the end-to-end data population pattern for the remaining 28 projects.

### 20.1 Pilot Projects

| Project | Sage ID | Country | Currency | Tariff Type | Why Selected |
|---------|---------|---------|----------|-------------|-------------|
| Kasapreko | KAS01 | Ghana | GHS | Floating grid | Same country as MOH01, validates Ghana pattern |
| Nigerian Breweries Ibadan | NBL01 | Nigeria | NGN | Floating generator | Different tariff type, different currency |
| Loisaba | LOI01 | Kenya | USD | Fixed solar + BESS | Fixed tariff, different geography, non-energy product (BESS) |

### 20.2 Contract Line Mapping

**Source:** `dim_finance_contract_line.csv` (DIM_CURRENT_RECORD=1)

| CBE Field | FrontierMind Field | Notes |
|-----------|--------------------|-------|
| CONTRACT_LINE_UNIQUE_ID | `contract_line.external_line_id` | Unique identifier from SAGE |
| CONTRACT_LINE | `contract_line.contract_line_number` | Integer line number (1000, 2000, etc.) |
| PRODUCT_DESC | `contract_line.product_desc` | Free-text product description |
| METERED_AVAILABLE | `contract_line.energy_category` | metered→metered, available→available, N/A→test |
| ACTIVE_STATUS | `contract_line.is_active` | 1→true, 0→false |
| EFFECTIVE_START_DATE | `contract_line.effective_start_date` | |
| EFFECTIVE_END_DATE | `contract_line.effective_end_date` | |

**Energy Category Classification (EXC-004 fix):**

The `METERED_AVAILABLE` field alone is insufficient for classification. N/A records must be cross-referenced against product descriptions using the ontology (`sage_to_fm_ontology.yaml` operational.product_classification):

- `METERED_AVAILABLE = metered` → `energy_category = metered` (energy products)
- `METERED_AVAILABLE = available` → `energy_category = available` (energy products)
- `METERED_AVAILABLE = N/A` + product matches non-energy pattern → `energy_category = test`
- `METERED_AVAILABLE = N/A` + no pattern match → `energy_category = test` (fallback)

Non-energy patterns: minimum offtake, bess capacity, o&m service, equipment lease, diesel, fixed monthly rental, esa lease, penalty, correction, inverter energy, early operating.

### 20.3 Pilot Contract Line Details

**KAS01 (4 lines):**

| Line | Product | METERED_AVAILABLE | energy_category | Active | Notes |
|------|---------|-------------------|-----------------|--------|-------|
| 1000 | Metered Energy (EMetered) - Phase 1 | metered | metered | Yes | Original phase |
| 2000 | Available Energy (EAvailable) Combined | available | available | Yes | Site-level available |
| 3000 | Inverter Energy - Phase 2 | N/A | test | No | Replaced by line 4000 |
| 4000 | Metered Energy (EMetered) - Phase 2 | metered | metered | Yes | From Feb 2025 |

**NBL01 (8 lines):**

| Line | Product | METERED_AVAILABLE | energy_category | Active | Notes |
|------|---------|-------------------|-----------------|--------|-------|
| 1000 | Grid (EMetered) | metered | metered | No | Legacy grid |
| 3000 | Grid (EAvailable) | available | available | No | Legacy grid |
| 4000 | Grid (EMetered) | metered | metered | No | Very short lived (Feb-Mar 2021) |
| 5000 | Grid (EAvailable) | available | available | No | Very short lived |
| 6000 | Generator (EMetered) Phase 1 | metered | metered | Yes | Active generator |
| 7000 | Generator (EAvailable) Combined Facility | available | available | Yes | Active available |
| 9000 | Early Operating Energy Phase 2 | N/A | test | No | Non-energy, pre-COD |
| 10000 | Generator (EMetered) Phase 2 | metered | metered | Yes | From Jan 2025 |

**LOI01 (3 lines on active contract CONKEN00-2021-00002):**

| Line | Product | METERED_AVAILABLE | energy_category | Active | Notes |
|------|---------|-------------------|-----------------|--------|-------|
| 1000 | Loisaba HQ (EMetered) | metered | metered | Yes | CPI escalation |
| 2000 | Loisaba Camp (EMetered) | metered | metered | Yes | CPI escalation |
| 3000 | BESS Capacity Charge | N/A | test | Yes | Non-energy, monthly capacity fee |

LOI01 also has a legacy contract (CONCBEH0-2021-00002, ACTIVE=0) with 3 lines — excluded from migration.

### 20.4 Meter Aggregate Mapping

**Source:** `meter readings.csv`

| CBE Field | FrontierMind Field | Notes |
|-----------|--------------------|-------|
| BILL_DATE | `billing_period_id` (via end_date join) | e.g. 2025/01/31 → billing_period id 14 |
| CONTRACT_LINE_UNIQUE_ID | `contract_line_id` (via external_line_id join) | FK to contract_line |
| OPENING_READING | `meter_aggregate.opening_reading` | |
| CLOSING_READING | `meter_aggregate.closing_reading` | |
| UTILIZED_READING | `meter_aggregate.utilized_reading` + `total_production` | |
| DISCOUNT_READING | `meter_aggregate.discount_reading` | LOI01 HQ has non-zero values in Apr-May 2025 |
| SOURCED_ENERGY | `meter_aggregate.sourced_energy` | NBL01 Phase 2 has non-zero values |
| METER_READING_UNIQUE_ID | `source_metadata->>'external_reading_id'` | CBE traceability |

**Energy routing based on contract_line.energy_category:**
- `metered` lines → `energy_kwh = utilized_reading`
- `available` lines → `available_energy_kwh = utilized_reading`
- `test` lines → both NULL (total_production still set)

### 20.5 Coverage Summary

| Table | Before 049 | After 049 | Delta |
|-------|-----------|----------|-------|
| contract_line | 12 (MOH01) | 27 | +15 |
| clause_tariff | 2 (MOH01) | 6 | +4 |
| meter_aggregate | 10 (MOH01) | 104 | +94 |
| contract_billing_product | varies | +8 | +8 |

### 20.6 Known Gaps (Post-Pilot)

1. **meter_id = NULL** on all pilot contract_lines and meter_aggregates — meters not yet available from source data
2. **clause_tariff.base_rate = NULL** — populated after PPA parsing (`batch_parse_ppas.py`)
3. **No tariff_rate records** — annual rate schedule populated after PPA parsing
4. **LOI01 BESS line 3000** has no meter readings — capacity charge, not metered energy
5. **NBL01 line 7000** has zero readings for some months (May-Jul 2025) — normal for available energy

### Verification

```sql
-- Count pilot data
SELECT p.sage_id,
       COUNT(DISTINCT cl.id) AS contract_lines,
       COUNT(DISTINCT ma.id) AS meter_aggregates
FROM project p
JOIN contract c ON c.project_id = p.id
LEFT JOIN contract_line cl ON cl.contract_id = c.id
LEFT JOIN meter_aggregate ma ON ma.contract_line_id = cl.id
WHERE p.sage_id IN ('KAS01', 'NBL01', 'LOI01')
GROUP BY p.sage_id;
-- Expected: KAS01 (4 lines, 36 aggregates), NBL01 (8 lines, 34 aggregates), LOI01 (3 lines, 24 aggregates)
```

---

## 21. GRP → MRP Terminology Rename (Migration 050)

**Date:** 2026-03-04
**Migration:** `database/migrations/050_rename_grp_to_mrp.sql`

### Summary
"Grid Reference Price" (GRP) has been renamed to "Market Reference Price" (MRP) across the entire application. This is a terminology-only change — no logic changes.

### Affected Mappings

| Old Term | New Term | Scope |
|----------|----------|-------|
| `calculated_grp_per_kwh` | `calculated_mrp_per_kwh` | `reference_price` column |
| `discounted_grp_local` | `discounted_mrp_local` | `tariff_monthly_rate` column |
| `grp_method` | `mrp_method` | `clause_tariff.logic_parameters` JSONB key |
| `grp_included_components` | `mrp_included_components` | `clause_tariff.logic_parameters` JSONB key |
| `grp_excluded_components` | `mrp_excluded_components` | `clause_tariff.logic_parameters` JSONB key |
| `grp_time_window_start` | `mrp_time_window_start` | `clause_tariff.logic_parameters` JSONB key |
| `grp_per_kwh` | `mrp_per_kwh` | `clause_tariff.logic_parameters` JSONB key |
| `grp_upload` | `mrp_upload` | `submission_token.submission_type` value |
| `grp-uploads/` | `mrp-uploads/` | S3 key prefix |

### API Route Changes

| Old Route | New Route |
|-----------|-----------|
| `POST /api/notifications/grp-collection` | `POST /api/notifications/mrp-collection` |
| `POST /api/projects/{id}/grp-observations` | `POST /api/projects/{id}/mrp-observations` |
| `POST /api/projects/{id}/grp-aggregate` | `POST /api/projects/{id}/mrp-aggregate` |
| `PATCH /api/projects/{id}/grp-observations/{obsId}` | `PATCH /api/projects/{id}/mrp-observations/{obsId}` |

### Backend File Renames

| Old Path | New Path |
|----------|----------|
| `models/grp.py` | `models/mrp.py` |
| `api/grp.py` | `api/mrp.py` |
| `services/grp/extraction_service.py` | `services/mrp/extraction_service.py` |
| `services/calculations/grid_reference_price.py` | `services/calculations/market_reference_price.py` |
| `services/prompts/grp_extraction_prompt.py` | `services/prompts/mrp_extraction_prompt.py` |

### Class/Type Renames

| Old Name | New Name |
|----------|----------|
| `GRPObservation` | `MRPObservation` |
| `GRPExtractionService` | `MRPExtractionService` |
| `GRPExtractionError` | `MRPExtractionError` |
| `GRPCollectionRequest` | `MRPCollectionRequest` |
| `GRPCollectionResponse` | `MRPCollectionResponse` |
| `AggregateGRPRequest` | `AggregateMRPRequest` |
| `AggregateGRPResponse` | `AggregateMRPResponse` |
| `BaseGRPCalculator` | `BaseMRPCalculator` |
| `GRPSection` (React) | `MRPSection` (React) |

### Notes
- Prior sections in this document reference GRP terminology — those represent the historical state at time of writing
- All new code and documentation should use "MRP" / "Market Reference Price"
- The GRP → MRP formula is unchanged: `effective = MAX(floor_local, MIN(MRP × (1 - discount), ceiling_local))`

---

## 22. Step 1 Coverage Gaps & Discrepancy Log

**Date:** 2026-03-07
**Script:** `python-backend/scripts/orchestrate_cbe_population.py --step 1`
**Source:** `CBE_data_extracts/Data Extracts/Customer summary.xlsx`
**Report:** `python-backend/reports/cbe-population/step1_2026-03-07.json`

### 22.1 Source Coverage Matrix

| Metric | Count |
|--------|-------|
| Projects in Customer summary.xlsx | 30 |
| Projects in FrontierMind DB | 32 |
| Matched after alias resolution | 30/30 |

**In DB but NOT in xlsx (PPA-only projects):**

| sage_id | Reason |
|---------|--------|
| ABI01 | Sourced from contract PDFs only; no xlsx entry |
| BNT01 | Sourced from contract PDFs only; no xlsx entry |

**Alias resolution applied:**

| xlsx Value | DB sage_id | Reason |
|------------|-----------|--------|
| GC001 | GC01 | Normalized to 2-digit suffix |
| ZL01 | ZO01 | Disambiguated from ZL02 (different entity) |

### 22.2 Orphan Sub-Rows (no sage_customer_id in xlsx)

These xlsx rows have no `sage_customer_id` and cannot be matched to a DB project directly:

| xlsx Row | Name | Likely Parent | Type |
|----------|------|--------------|------|
| 15 | Loisaba - BESS | LOI01 | Ancillary lease |
| 26 | Ampersand - BESS | AMP01 | Ancillary lease |
| 39 | Zoodlabs Group - O&M Fee | ZL02 | O&M service |

### 22.3 Projects Missing Contracts in DB

| sage_id | Issue | Next Step |
|---------|-------|-----------|
| TBC | iSAT Africa — no PPA, no SAGE data | Create contract in Step 2 |
| ZL02 | Has SAGE contract lines but no FM contract record | Create contract in Step 2 |

### 22.4 Full Discrepancy Table (23 items from Step 1 dry-run)

| # | Severity | Project | Field | xlsx Value | DB Value | Recommended Action | Status |
|---|----------|---------|-------|-----------|----------|-------------------|--------|
| 1 | info | GC01 | project.country | Mauritius | Kenya | DB wins — xlsx shows legal entity country, DB shows site country | resolved |
| 2 | warning | ZO01 | project.country | Mauritius | Sierra Leone | Review: xlsx shows legal entity jurisdiction, DB has site country | open |
| 3 | warning | TBC | project.country | Mauritius | DRC | Review: xlsx shows legal entity jurisdiction, DB has site country | open |
| 4 | warning | TBC | contract | xlsx project exists | NO CONTRACTS IN DB | Create contract in Step 2 | open |
| 5 | warning | KAS01 | project.cod_date | 2024-05-03 | 2018-10-03 | Review: xlsx may show Phase 2 COD, DB has Phase 1 | open |
| 6 | warning | MOH01 | project.cod_date | 2025-12-12 | 2025-09-01 | Review: check field authority matrix | open |
| 7 | warning | LOI01 | project.name | Loisaba - Solar | Loisaba | Review: xlsx appends technology suffix | open |
| 8 | warning | MF01 | counterparty.industry | Chemical | Manufacturing | Review: xlsx has specific sub-industry, DB has generic | open |
| 9 | warning | MP02 | counterparty.industry | Paper | Manufacturing | Review: xlsx has specific sub-industry, DB has generic | open |
| 10 | warning | MP01 | counterparty.industry | Paper | Manufacturing | Review: xlsx has specific sub-industry, DB has generic | open |
| 11 | warning | NC02 | counterparty.industry | Cement/Concrete | Manufacturing | Review: xlsx has specific sub-industry, DB has generic | open |
| 12 | warning | NC03 | project.name | National Cement\nNakuru | National Cement Nakuru | Review: xlsx has embedded newline | open |
| 13 | warning | NC03 | counterparty.industry | Cement/Concrete | Manufacturing | Review: xlsx has specific sub-industry, DB has generic | open |
| 14 | warning | AMP01 | project.name | Ampersand - Solar | Ampersand | Review: xlsx appends technology suffix | open |
| 15 | warning | QMM01 | project.name | Rio Tinto QMM - Solar Expanded | Rio Tinto QMM | Review: xlsx includes expansion label | open |
| 16 | info | QMM01 | project.country | Madagascar 1 | Madagascar | DB wins — xlsx has trailing suffix | resolved |
| 17 | warning | QMM01 | project.installed_dc_capacity_kwp | 30,597.76 (summed) | 14,447.76 (original phase) | **Key review item**: xlsx sums both phases, DB has Phase 1 only | open |
| 18 | warning | QMM01 | project.external_project_id | MG 22017 MG 22452 | MG 22017 | Review: xlsx concatenates both phase IDs | open |
| 19 | warning | ERG | project.country | Madagascar 2 | Madagascar | Review: xlsx has trailing suffix "2" | open |
| 20 | warning | NBL01 | project.external_project_id | NG 22016 NG 22051 | NG 22016 | Review: xlsx concatenates both phase IDs | open |
| 21 | warning | NBL01 | counterparty.name | Heineken | CROSSBOUNDARY ENERGY NIGERIA LTD. | **Key review item**: xlsx shows offtaker, DB shows CBE SPV entity | open |
| 22 | warning | ZL02 | project.name | Zoodlabs Group - Energy Services | Zoodlabs Energy Services | Review: minor naming difference | open |
| 23 | warning | ZL02 | contract | xlsx project exists | NO CONTRACTS IN DB | Create contract in Step 2 | open |

**Summary:** 0 critical, 21 warnings, 2 info. All warnings are open for review.

### 22.5 Key Items Requiring Later Review

1. **QMM01 capacity** (#17): xlsx=30,597.76 kWp (Phase 1 + Phase 2 summed) vs DB=14,447.76 kWp (Phase 1 only). Decision needed: update DB to expanded capacity, or keep phases separate.
2. **NBL01 counterparty** (#21): "Heineken" (xlsx, offtaker) vs "CROSSBOUNDARY ENERGY NIGERIA LTD." (DB, CBE SPV). The `counterparty` table holds the contract counterparty (CBE entity), not the end offtaker. xlsx column may represent a different relationship.
3. **Industry mismatches** (#8-11, #13): Devki subsidiaries (MF01, MP01, MP02, NC02, NC03) show specific sub-industries in xlsx (Chemical, Paper, Cement/Concrete) vs generic "Manufacturing" in DB. Consider adding `sub_industry` field or updating industry values.
4. **Country column** (#2, #3): GC01, ZO01, TBC show legal entity jurisdiction (Mauritius) in xlsx, not physical project site. DB values (Kenya, Sierra Leone, DRC) are correct for project location.
5. **Phase-concatenated IDs** (#18, #20): QMM01 and NBL01 xlsx rows concatenate multiple external project IDs. DB stores only the primary phase ID.

### 22.6 Stage A Gate Results

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| All projects have sage_id | 32/32 | 32/32 | Yes |
| Contracts have external_contract_id | 27+ | 27 | Yes |
| Contracts have payment_terms | 27+ | 27 | Yes |
| Contracts have end_date | 27+ | 27 | Yes |
| Multi-contract patterns flagged | XF-AB flagged | XF-AB: 1 project(s) | Yes |

**All 5 gates passed.** Step 1 is clear to proceed with live gap-fill execution.

---

## 23. Step 2: SAGE CSV Cross-Check & XF-AB Split

**Date:** 2026-03-08
**Migration:** `database/migrations/054_sage_id_aliases_and_data_fixes.sql` (Step 2 appended)
**Orchestrator:** `python-backend/scripts/orchestrate_cbe_population.py` — `step2_sage_crosscheck()`

### 23.1 XF-AB Split

**Governing rule:** Separate measurement + separate billing = separate FM projects (see MEMORY.md).

XF-AB had 4 SAGE customers (XFAB, XFBV, XFL01, XFSS), 4 separate invoices, and 4 separate Plant Performance Workbook tabs. Per the project boundary rule, these must be 4 separate FM projects.

| sage_id | Name | Contract | Terms | Start | End | Currency |
|---------|------|----------|-------|-------|-----|----------|
| XFAB | Xflora Africa Blooms | CONKEN00-2021-00003 | 30EOM | 2021-04-01 | 2047-05-31 | USD |
| XFBV | Xflora Bloom Valley | CONKEN00-2021-00004 | 30NET | 2021-04-01 | 2047-05-31 | USD |
| XFL01 | Xpressions Flora | CONKEN00-2021-00005 | 30NET | 2021-04-01 | 2047-05-31 | USD |
| XFSS | Sojanmi Spring | CONKEN00-2021-00006 | 30EOM | 2021-04-01 | 2047-05-31 | USD |

**Actions:**
- Renamed `XF-AB` → `XFAB` (existing project, contract id=31 stays)
- Updated counterparty: "XFlora Group" → "Xflora Africa Blooms"
- Created 3 new projects with counterparties, contracts (with external IDs, payment terms, dates), and contract lines (metered + available)
- Ancillary contracts (id=53,54) remain on XFAB
- Total projects: 32 → 35

### 23.2 ZL02 Contracts

ZL02 existed as a project but had no contracts (flagged as discrepancy #23 in Step 1). Added 4 SAGE contracts:

| Contract | Category | Currency | Terms | Start | End |
|----------|----------|----------|-------|-------|-----|
| CONCBCH0-2025-00002 | RENTAL | USD | 30NET | 2025-03-01 | 2035-11-30 |
| CONCBCH0-2025-00003 | OM | USD | 30NET | 2025-03-01 | 2035-11-30 |
| CONCBCH0-2025-00004 | RENTAL | USD | 30NET | 2025-06-01 | 2025-12-31 |
| CONSLL02-2025-00003 | OM | SLE | 30NET | 2025-03-01 | 2035-11-30 |

### 23.3 Parser Updates

| File | Change |
|------|--------|
| `sage_csv_parser.py` | Removed XFlora alias entries (XFAB/XFBV/XFL01/XFSS pass through as-is) |
| `customer_summary_parser.py` | `XFLORA_PREFIX` → maps to "XFAB" (only primary in xlsx) |
| `plant_performance_parser.py` | `"XFlora"` → `"XFAB"` (was `"XF-AB"`) |
| `tariff_type_overrides.yaml` | Replaced `XF-AB` with `XFAB, XFBV, XFL01, XFSS` in fixed list |
| `sage_to_fm_ontology.yaml` | Removed XFlora aliases, updated cardinality to one-to-one |
| `eval_exceptions.yaml` | Updated `XF-AB` → `XFAB` in EXC-002 |

### 23.4 SAGE Cross-Check Validation

Step 2 orchestrator (`step2_sage_crosscheck()`) compares all SAGE CSV projects against DB:

| Field | SAGE Source | DB Target | Compare |
|-------|-----------|-----------|---------|
| Contract number | `primary_contract_number` | `contract.external_contract_id` | Exact match |
| Payment terms | `payment_terms` | `contract.payment_terms` | Exact match |
| Start date | `contract_start_date` | `contract.effective_date` | Date match |
| End date | `contract_end_date` | `contract.end_date` | Date match |
| Customer name | `customer_name` | `counterparty.name` | Fuzzy match |
| Country | `country` | `project.country` | Exact match |
| Active line count | len(active lines) | COUNT(contract_line) | Info-level |
| CPI flag | `has_cpi_inflation` | — | Record for tariff |

Gap-fill (COALESCE): `contract.effective_date`, `contract.payment_terms`, `contract.end_date`.

### 23.5 Step 2 Gate Checks

| Gate | Expected | Description |
|------|----------|-------------|
| All projects have sage_id | 35/35 | Was 32, +3 XFlora sub-farms |
| Contracts have external_contract_id | 31+ | Was 27, +3 XFlora +1 ZL02 |
| Contracts have payment_terms | 31+ | Updated threshold |
| Contracts have end_date | 31+ | Updated threshold |
| XFlora split verified | XFAB, XFBV, XFL01, XFSS | 4 separate projects |
| ZL02 has contracts | 1+ | At least 1 contract |

---

## 24. Step 3: Contract Lines & Meter Cross-Check

**Date:** 2026-03-08
**Orchestrator:** `python-backend/scripts/orchestrate_cbe_population.py` — `step3_contract_lines_and_meter_crosscheck()`

### 24.1 Overview

Populates `contract_line` for all 31 SAGE-mapped projects from `dim_finance_contract_line.csv`. Deletes all existing contract_lines (and FK dependents: meter_aggregate, expected_invoice_line_item) then re-inserts from SAGE CSV source of truth.

### 24.2 Results

| Metric | Value |
|--------|-------|
| Contract lines inserted | 114 (87 active, 27 inactive) |
| Projects with lines | 31 of 35 |
| Auto-created contracts | 2 (IVL01 OM `CONEGY00-2025-00002`, TWG01 OM `CONMOZ00-2023-00002`) |
| Meter readings matched | 601 / 604 |
| Orphaned readings | 3 (CAL01 lines 1000/2000/3000 — SCD2-superseded) |
| Deleted dependents | 189 meter_aggregate + 12 expected_invoice_line_item |

### 24.3 Energy Category Mapping

| SAGE `energy_category` (parser) | DB `energy_category` enum |
|---------------------------------|---------------------------|
| metered_energy | metered |
| available_energy | available |
| non_energy | test |

### 24.4 Key Decisions

- **Delete-and-reinsert** pattern: all existing contract_lines and FK dependents wiped, then fresh insert from CSV. Meter_aggregate and expected_invoice_line_item will be repopulated in later steps.
- **Auto-create missing contracts**: Step 3 auto-creates contracts found in SAGE CSV but missing from DB (2 OM contracts for IVL01, TWG01).
- **SCD2 orphans acceptable**: CAL01 meter readings reference lines 1000/2000/3000 which have `DIM_CURRENT_RECORD=0`. Only line 5000 is current. Gate allows ≤10 SCD2 orphans.
- **4 projects without SAGE data**: ABI01, BNT01, TBC, ZL01 (PPA-only or no-data projects).

### 24.5 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| All contract_lines resolve to a contract | 114/114 | 114/114 | Yes |
| Contract_line count matches SAGE CSV | 114 from CSV | 114 in DB | Yes |
| Active/inactive line breakdown | active > 0 | 87 active, 27 inactive | Yes |
| Orphaned meter readings | ≤10 | 3 (SCD2-superseded) | Yes |
| Projects with contract_lines | 25+ | 31 | Yes |

## 25. Step 5: PPW Summary → Production Forecast Population

**Date:** 2026-03-08
**Script:** `python-backend/scripts/step5_ppw_summary.py`
**Source:** Operations Plant Performance Workbook — "Summary - Performance" tab

### 25.1 What Was Done

Populated `production_forecast` table from the PPW Summary-Performance tab. Extracted monthly forecast data (energy kWh, GHI irradiance, POA irradiance, PR) for all projects with PPW tabs.

### 25.2 Results

| Metric | Value |
|--------|-------|
| Projects with forecasts | 25 |
| Total forecast rows | 1,510 |
| Projects without PPW data | 10 (ABI01, AR01, BNT01, TBC, TWG01, XFBV, XFL01, XFSS, ZL01, ZL02) |

### 25.3 Bugs Fixed During Step 5

1. **TOTAL row matching**: TOTAL/AGREGATED/WEIGHTED AVERAGE rows now skipped in block header detection
2. **VARIANCE block leak**: VARIANCE blocks mapped to `None` → data rows skipped instead of leaking to previous field
3. **Cross-check formula**: Uses AVG×12 (implied annual) instead of SUM (lifetime)
4. **Batch INSERT**: `execute_values` + extended `statement_timeout` for Supabase
5. **Removed `updated_at`**: Column doesn't exist on `projects` table

### 25.4 Operating Year Backfill

SQL formula computed `operating_year` for all 1,472 NULL rows across 29 projects:
```
operating_year = (year_diff × 12 + month_diff) / 12 + 1
```
Relative to each project's first `forecast_month`.

### 25.5 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| Forecast rows inserted | > 0 | 1,510 | Yes |
| All values positive, no duplicates | 0 violations | 0 | Yes |
| Energy cross-check vs Summary tab | < 5% delta | All within tolerance | Yes |
| Projects covered | ≥ 20 | 25 | Yes |

## 26. Step 6: PPW Project Tabs → Forecast Enrichment

**Date:** 2026-03-08
**Script:** `python-backend/scripts/step6_project_tabs.py`
**Source:** Operations Plant Performance Workbook — individual project tabs (32 tabs)

### 26.1 What Was Done

Enrichment-only step (no new rows created). Parsed each project's individual PPW tab and updated existing `production_forecast` rows with:
- `source_metadata` JSONB merge (site_params, monthly allocation, tech model breakdown)
- `degradation_factor` (computed from site_params.degradation_pct)
- `forecast_poa_irradiance` (filled NULLs from project tab data)

### 26.2 Results

| Metric | Value |
|--------|-------|
| Projects processed | 34 (29 FM + 5 non-FM skipped) |
| Forecast rows enriched | 1,772 |
| Critical discrepancies | 0 |
| Warnings | 12 |
| Non-FM tabs skipped | 5 (ABB, AJJ, BM, BNTR, LTC) |

### 26.3 Discrepancy Log

#### Capacity Mismatches (PPW shows per-phase, DB has combined)

| Project | PPW (kWp) | DB (kWp) | Likely Cause |
|---------|-----------|----------|-------------|
| IVL01 | 3,242.52 | 967.68 | PPW has combined, DB has single phase |
| KAS01 | 904.8 | 1,305.24 | PPW picks Phase 2 only |
| MB01 | 544.92 | 1,172.52 | Multi-phase |
| MF01 | 118.5 | 674.0 | Multi-phase |
| NBL01 | 2,511.0 | 3,173.0 | Multi-phase |
| NC02 | 493.42 | 1,282.58 | Multi-phase |
| QMM01 | 16,150.0 | 14,447.76 | PPW larger — may be nameplate vs installed |

#### COD Mismatches

| Project | PPW | DB | Note |
|---------|-----|-----|------|
| CAL01 | 2023-01-27 | 2025-04-15 | PPW may have #REF! errors |
| KAS01 | 2018-10-17 | 2018-10-03 | 14-day difference |
| NBL01 | 2021-02-22 | 2025-01-01 | PPW may have #REF! errors |

#### Country Formatting

| Project | PPW | DB | Note |
|---------|-----|-----|------|
| ERG | Madagascar 2 | Madagascar | Site identifier in PPW tab name |
| QMM01 | Madagascar 1 | Madagascar | Site identifier in PPW tab name |

### 26.4 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| All FM projects with PPW tabs resolved | All resolved | 5 non-FM tabs skipped | Yes |
| Forecasts enriched with source_metadata | > 0 projects | 29 of 34 enriched | Yes |
| No critical discrepancies | 0 critical | 0 critical | Yes |

## 27. Step 7: Revenue Masterfile — Full Extraction

**Date:** 2026-03-08
**Script:** `python-backend/scripts/step7_revenue_masterfile.py`
**Source:** CBE Asset Management Operating Revenue Masterfile - new.xlsb (10 tabs)

### 27.1 What Was Done

Extracted data from 7 Revenue Masterfile tabs:
- **7a. Reporting Graphs** → `counterparty.industry` (all already populated — 0 updates)
- **7b. PO Summary** → `project.technical_specs` JSONB (29 projects), `clause_tariff` fields (50 updates, 14 with base_rate)
- **7c. Invoiced SAGE** → `exchange_rate` table (43 new GHS/KES/NGN monthly closing spot rates, 2024-2026)
- **7d. Energy Sales** → cross-check only (informational)
- **7e. Loans** → `project.technical_specs.loan_schedule` for ZL02 (199 rows) and GC001 (132 rows)
- **7f. Rental/Ancillary** → `project.technical_specs.rental_schedule` for LOI01, AR01, QMM01, TWG01, AMP01
- **7g. US CPI** → staging JSON (192 data points, 2010-2025, pending `price_index` migration)

### 27.2 Results

| Metric | Value |
|--------|-------|
| Project technical_specs enriched | 29 |
| Tariff rows updated | 50 (14 with base_rate) |
| Exchange rates inserted | 43 (GHS/KES/NGN, 2024-2026) |
| Loan schedules stored | 2 (ZL02, GC001) |
| Rental schedules stored | 5 (LOI01, AR01, QMM01, TWG01, AMP01) |
| CPI data points staged | 192 (2010-2025) |
| Discrepancies | 39 (0 critical) |

### 27.3 Technical Specs Fields Populated

Per project, the following JSONB fields were merged into `project.technical_specs`:

| Field | Source Column | Description |
|-------|-------------|-------------|
| `revenue_type` | PO Summary col D | e.g., "PPA", "Finance Lease", "Loan - repayment based on Energy Output" |
| `connection` | PO Summary col F | "Grid", "Off-Grid", "Generator" |
| `capex_usd` | PO Summary col G | SAGE agreed CAPEX in USD |
| `bess_kwh` | PO Summary col M | Battery storage capacity |
| `thermal_kwe` | PO Summary col N | Thermal capacity |
| `annual_specific_yield_kwh_kwp` | PO Summary col P | Contract Year 1 yield |
| `degradation_pct_po_summary` | PO Summary col R | Annual degradation % |
| `loan_fixed_payment` | PO Summary col AG | Monthly loan payment |
| `lease_rental` | PO Summary col AH | Monthly rental amount |
| `energy_fee` | PO Summary col AI | Energy fee |
| `bess_charge` | PO Summary col AJ | BESS charge |
| `om_fee` | PO Summary col AK | O&M fee |
| `charge_indexation` | PO Summary col AL | Indexation method for charges |
| `charge_comments` | PO Summary col AM | Context notes |
| `oy_definition` | PO Summary col AN | Operating Year definition text |

### 27.4 Tariff Fields Populated

| Field | Target | Source |
|-------|--------|--------|
| `base_rate` | `clause_tariff.base_rate` | Fixed tariff or computed solar tariff |
| `discount_percentage` | `logic_parameters.discount_percentage` | Grid/generator discount % |
| `grid_discount_pct` | `logic_parameters.grid_discount_pct` | Grid+Generator type |
| `generator_discount_pct` | `logic_parameters.generator_discount_pct` | Grid+Generator type |
| `floor_rate` | `logic_parameters.floor_rate` | Min tariff |
| `ceiling_rate` | `logic_parameters.ceiling_rate` | Max tariff |
| `indexation_method` | `logic_parameters.indexation_method` | e.g., "US CPI" |
| `first_indexation_date` | `logic_parameters.first_indexation_date` | ISO date |
| `indexation_context` | `logic_parameters.indexation_context` | Comments from col AF |
| `contract_term_years_po` | `logic_parameters.contract_term_years_po` | Term from PO Summary |
| `contract_end_date_po` | `logic_parameters.contract_end_date_po` | COD End from PO Summary |

### 27.5 Discrepancy Log

#### COD Mismatches (PO Summary vs DB)

| Project | PO Summary | DB | Note |
|---------|-----------|-----|------|
| KAS01 (Phase 1) | 2018-10-17 | 2018-10-03 | 14-day difference |
| KAS01 (Phase 2) | 2024-05-03 | 2018-10-03 | Phase 2 COD, DB has Phase 1 |
| LOI01 | 2019-10-31 | 2019-03-01 | 8-month difference |
| IVL01 (Phase 2) | 2026-03-16 | 2023-10-02 | Construction phase, DB has Phase 1 |
| TWG01 | 2026-02-01 | 2025-12-01 | 2-month difference |
| ZL02 (multiple) | 2024-04-01 / 2025-07-01 / 2026-01-01 | 2025-03-01 | Multiple phases |

#### Capacity Cross-Checks (info-level)

| Project | PO Summary (kWp) | DB (kWp) | Note |
|---------|-----------------|----------|------|
| KAS01 P1/P2 | 400.44 / 904.8 | 1,305.24 | Per-phase vs combined |
| XFAB | 424.32 | 141.45 | PO Summary has combined XFlora |
| MP02 | 1,386.0 | 693.0 | PO Summary may include extension |
| IVL01 P2 | 2,270.0 | 967.68 | Phase 2 capacity |

#### FX Rate Differences (26 info-level)

RevMasterfile closing spot rates differ from xe.com rates already in DB. This is expected — RevMasterfile rates are SAGE invoicing rates, xe.com are market mid-rates. Both retained.

### 27.6 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| PO Summary projects resolved | > 0 projects | 29 projects enriched | Yes |
| Tariff base_rate populated | Tariffs enriched | 14 tariffs got base_rate, 50 total | Yes |
| Exchange rates extracted | > 0 rates | 43 new rates inserted | Yes |
| No critical discrepancies | 0 critical | 0 critical | Yes |

---

## 28. Step 8 — Invoice Calibration & Tax Rule Extraction

**Script:** `python-backend/scripts/step8_invoice_calibration.py`
**Report:** `python-backend/reports/cbe-population/step8_2026-03-08.json`
**Migration:** `database/migrations/056_billing_tax_rule_project_scope.sql`
**Date:** 2026-03-08

### 28.1 Purpose

Two-phase step that uses OCR'd invoice PDFs as the authoritative source for:
- **Phase A:** Tax/levy/WHT formula extraction → populate `billing_tax_rule` per country and per project
- **Phase B:** Validate extracted invoice values against DB state → discrepancy report with 8 validation checks

### 28.2 Migration 056: billing_tax_rule Project Scoping

Added `project_id BIGINT REFERENCES project(id)` to `billing_tax_rule`:
- `NULL project_id` = country-level default rule
- Non-NULL `project_id` = project-specific override (e.g., different WHT rate)

GiST exclusion constraint updated to include `COALESCE(project_id, 0)` so project overrides coexist with country defaults without constraint violations.

### 28.3 Pipeline

```
For each invoice PDF/EML:
  1. Extract sage_id from filename (SAGE_ID_LOOKUP + progressive digit fallback)
  2. OCR via LlamaParse (disk-cached at reports/cbe-population/step8_ocr_cache/)
  3. Claude structured extraction → InvoiceExtraction Pydantic model
  4. Phase A: Collect tax structure per country/project
  5. Phase B: Run 8 validation checks against DB

After all invoices:
  6. Deduplicate tax structures per country (majority = default)
  7. INSERT billing_tax_rule rows (country defaults + project overrides)
  8. Write JSON report
```

### 28.4 Source Data

| Source | Location | Count |
|--------|----------|-------|
| Invoice PDFs | `CBE_data_extracts/Invoice samples/*.pdf` | 27 standalone |
| Invoice EMLs | `CBE_data_extracts/Invoice samples/*.eml` (PDF attachments) | 6 |
| **Total** | | **33 invoices, 27 projects** |

### 28.5 Tax Rules Created

**17 rows** in `billing_tax_rule` (1 pre-existing Ghana default + 16 new):

#### Country Defaults (project_id = NULL)

| Country | Code | VAT | Levies | Withholdings | Source Invoices |
|---------|------|-----|--------|-------------|----------------|
| Ghana | GH | 15% (on subtotal_after_levies) | NHIL 2.5%, GETFUND 2.5%, COVID 1.0% | WHT 3%, WHVAT 7% | Pre-existing |
| Kenya | KE | 16% | — | WHVAT 2% | LOI01, MP02, NC02, UTK01, XF*, AR01, MB01, MF01, MP01, NC03, TBM01 |
| Egypt | EG | 0% | — | WHT 3% | IVL01 |
| Madagascar | MG | 20% | — | — | ERG |
| Nigeria | NG | 7.5% | — | WHT 2% | NBL01, NBL02 |
| Sierra Leone | SL | 15% (levy labeled OTHER) | — | — | MIR01 (default pattern) |
| Zimbabwe | ZW | 15% | — | — | CAL01 |

#### Project-Specific Overrides

| Country | Project | Override Reason | Key Difference |
|---------|---------|----------------|----------------|
| GH | KAS01 (id=53) | Higher WHT | WHT 7.5% (vs country default 3%) |
| KE | GC001 (id=48) | VAT-exempt | VAT 0% (vs 16%) |
| KE | MP02 (id=59) | No WHVAT | VAT 16%, no withholdings |
| KE | NC02 (id=61) | No WHVAT | VAT 16%, no withholdings |
| KE | UTK01 (id=64) | No WHVAT | VAT 16%, no withholdings |
| KE | XFSS (id=115) | No WHVAT | VAT 16%, no withholdings |
| KE | AMP01 (id=66) | No WHVAT | VAT 16%, no withholdings |
| MG | QMM01 (id=67) | VAT-exempt | VAT 0% (vs 20%) |
| SL | MIR01 (id=72) | VAT + WHT | VAT 15%, WHT 6.5% |
| SL | ZL02 (id=73) | VAT + WHT | VAT 15%, WHT 6.5% |

### 28.6 Countries Without Tax Rules (No Invoice Samples)

| Country | Code | Projects | Note |
|---------|------|----------|------|
| DRC | CD | 1 | No invoice PDF provided |
| Mozambique | MZ | 1 | No invoice PDF provided |
| Rwanda | RW | 1 | No invoice PDF provided |
| Somalia | SO | 1 | No invoice PDF provided |

### 28.7 Validation Checks (Phase B)

| # | Check | DB Table(s) | Severity | Description |
|---|-------|-------------|----------|-------------|
| 1 | Line items → billing_product | contract_line, billing_product | warning | Verify energy lines match DB products |
| 2 | Quantity kWh vs meter_aggregate | meter_aggregate | info | Compare invoice kWh to DB meter data |
| 3 | Currency reference | clause_tariff, currency | info | Invoice billing currency vs tariff reference currency (floor/ceiling in USD is not a billing mismatch) |
| 4 | Tax rates vs billing_tax_rule | billing_tax_rule | warning | Compare extracted rates to DB rules |
| 5 | FX rate vs exchange_rate | exchange_rate | warning | 0.5% tolerance; skip when FX=1.0 (same-currency) |
| 6 | Tariff box vs clause_tariff | clause_tariff, reference_price | warning | Compare discount, floor, ceiling, solar tariff |
| 7 | Loan/rental vs technical_specs | project.technical_specs | warning | Verify loan/rental line items |
| 8 | Grand total self-consistency | (self-check) | critical | subtotal + non-WHT taxes = grand_total (5% + $10 tolerance) |

### 28.8 Discrepancy Summary

| Severity | Count | Categories |
|----------|-------|-----------|
| Critical | 1 | Grand total self-consistency failure (AMP01: 81% diff — EML extraction quality, flagged for manual review) |
| Warning | 44 | billing_product gaps (most projects), tariff rate differences, FX rate variances |
| Info | 33 | Sparse meter data (27), currency reference notes (6 — invoice in local currency, tariff reference in USD) |

### 28.9 Key Observations

1. **Currency reference vs billing currency:** Many Kenya and Sierra Leone projects have `clause_tariff.currency_id` pointing to USD (for floor/ceiling rates) but invoice in local currency (KES/SLE). This is expected — the contractual tariff formula references USD for bounds but billing is in local currency.

2. **billing_product gaps:** Most projects show "energy line(s) but no billing_products in DB" — this is expected pre-Step 9 (billing product population).

3. **Sparse meter_aggregate data:** 27 of 33 invoices show kWh with no corresponding `meter_aggregate` row — meter data ingestion is a separate pipeline.

4. **OCR quality:** 25/33 (76%) high confidence, 8/33 medium confidence. One invoice (AMP01) has a grand total self-consistency failure due to EML extraction quality — flagged for manual review.

5. **Ghana KAS01 WHT:** Invoice shows WHT 7.5% vs the country default of 3%. This is a legitimate project-specific override, now captured as a project-scoped `billing_tax_rule` row.

### 28.10 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| Invoices parsed successfully | > 0 invoices parsed | 33/33 invoices parsed | Yes |
| Tax rules created | > 0 tax rules created | 16 tax rules created | Yes |
| No critical validation failures | 0 critical checks | 1 critical (OCR quality) | No* |
| Extraction confidence acceptable | >= 50% high confidence | 25/33 high confidence (76%) | Yes |

\*Gate 3 failed due to EML extraction quality on AMP01, not a data integrity problem. Flagged for manual review.

---

## Section 29: MRP + Meter Population & Plant Performance (Steps 9 & 10)

**Run date:** 2026-03-09
**Script:** `python-backend/scripts/step9_mrp_and_meter_population.py`
**Report:** `python-backend/reports/cbe-population/step9_2026-03-09.json`
**Mode:** LIVE (3 sequential phases)

### 29.1 Phase A — Meter Readings CSV → meter_aggregate

**Source:** `CBE_data_extracts/Data Extracts/FrontierMind Extracts_meter readings.csv`

| Metric | Value |
|--------|-------|
| CSV rows parsed | 604 |
| Rows inserted | 600 |
| FK resolution rate | 99.5% |
| Projects covered | 28 |
| Unresolved rows | 3 (CAL01 — external_line_id not in contract_line) |

**Column mapping:**

| CSV Column | DB Column | Transform |
|------------|-----------|-----------|
| BILL_DATE | billing_period_id | Parse YYYY/MM/DD → first-of-month → lookup billing_period |
| CONTRACT_LINE_UNIQUE_ID | contract_line_id | Lookup via contract_line.external_line_id |
| OPENING_READING | opening_reading | Direct |
| CLOSING_READING | closing_reading | Direct |
| UTILIZED_READING | utilized_reading | Direct |
| DISCOUNT_READING | discount_reading | Direct |
| SOURCED_ENERGY | sourced_energy | Direct |
| METERED_AVAILABLE | routing | metered → total_production/energy_kwh; available → available_energy_kwh |
| (computed) | total_production | utilized - discount - sourced |

All rows use `source_system = 'snowflake'`, `period_type = 'monthly'`, `unit = 'kWh'`, `organization_id = 1`.

### 29.2 Phase B — MRP Formula OCR + Monthly Data

**Source:** `CBE_data_extracts/MRP/Sage Contract Extracts market Ref pricing data.xlsx`

#### B1: Formula Screenshot OCR

Extracted **60+ embedded images** from 9 project tabs using openpyxl `ws._images`. Each image sent to Claude vision (claude-sonnet-4-20250514) for structured extraction of:
- MRP method (utility_variable_charges_tou, utility_total_charges, generator_cost, blended_grid_generator)
- Included/excluded tariff components
- VAT/demand exclusion flags
- MRP currency (local utility currency)
- Floor/ceiling currency and escalation mechanism

OCR results cached by SHA256 hash in `reports/cbe-population/step9_ocr_cache/`.

#### B2: clause_tariff Updates

Updated **7 clause_tariff rows** (UTK01, UGL01, TBM01, GBL01, JAB01, NBL01, NBL02):
- `logic_parameters.mrp_method` — set from OCR interpretation
- `logic_parameters.mrp_clause_text` — OCR'd formula text
- `logic_parameters.mrp_included_components` — list of included charges
- `logic_parameters.mrp_excluded_components` — list of excluded charges
- `logic_parameters.mrp_exclude_vat` — boolean
- `logic_parameters.mrp_exclude_demand_charges` — boolean
- `market_ref_currency_id` — resolved from country (GHS, KES, NGN)

KAS01 + MOH01 cross-validated against existing data — no discrepancies.

**Final clause_tariff MRP state (all 9 projects):**

| Project | ct.id | mrp_method | MRP Currency |
|---------|-------|-----------|-------------|
| KAS01 | 11 | utility_variable_charges_tou | GHS |
| MOH01 | 2 | utility_variable_charges_tou | GHS |
| UTK01 | 42 | utility_total_charges | KES |
| UGL01 | 53 | utility_total_charges | GHS |
| TBM01 | 49 | utility_variable_charges_tou | KES |
| GBL01 | 28 | utility_variable_charges_tou | GHS |
| JAB01 | 52 | blended_grid_generator | NGN |
| NBL01 | 12 | utility_variable_charges_tou | NGN |
| NBL02 | 40 | generator_cost | NGN |

#### B3: Monthly MRP Observations → reference_price

Inserted **287 new rows** (353 total) across 9 projects.

**Sheet layout handling:**
- **Single section** (UTK01, UGL01, TBM01, KAS01): One ZDAT header, data rows below
- **Side-by-side dual section** (GBL01, JAB01): Grid cols A-E + Generator cols G-L in same rows. Grid MRP stored as primary `calculated_mrp_per_kwh`; generator total stored in `source_metadata`
- **Dual generator** (NBL01, NBL02): Two generator sections side-by-side, first section as primary
- **Multi-entity** (MOH001): 4 parallel billing entity sections, deduped by project+period

**reference_price row shape:**
```json
{
  "project_id": "<resolved>",
  "organization_id": 1,
  "operating_year": "<from COD>",
  "period_start": "YYYY-MM-01",
  "period_end": "YYYY-MM-last",
  "calculated_mrp_per_kwh": "<total from ZPRITOT>",
  "currency_id": "<MRP currency>",
  "verification_status": "estimated",
  "observation_type": "monthly",
  "source_metadata": {
    "source_file": "Sage Contract Extracts market Ref pricing data.xlsx",
    "sheet_name": "<tab>",
    "mrp_type": "grid|generator",
    "tariff_components": {"energy_charge": X, "levy": Y, ...},
    "extraction_date": "2026-03-09"
  }
}
```

### 29.3 Phase C — Plant Performance Enrichment (Step 10 partial)

| Metric | Value |
|--------|-------|
| Rows inserted | 292 |
| Rows updated | 13 |
| Total plant_performance | 381 |
| Projects covered | 28 |

**Computed:** `energy_comparison = SUM(metered total_production) / forecast_energy_kwh` per project per billing_month.

**Not computed (irradiance gap):**
- `irr_comparison` — requires `meter_aggregate.ghi_irradiance_wm2` (not in CSV)
- `pr_comparison` — requires `actual_pr` computation (needs GHI + capacity)
- `actual_pr` — requires irradiance data from Plant Performance Workbook project tabs

### 29.4 Remaining Gaps

| Gap | Blocked By | Resolution Path |
|-----|-----------|----------------|
| `irr_comparison` NULL | No GHI irradiance in meter readings CSV | Import from PPW project tabs → `meter_aggregate.ghi_irradiance_wm2` |
| `pr_comparison` NULL | Depends on `actual_pr` | Compute after irradiance import |
| `actual_pr` NULL | Depends on GHI irradiance | `total_energy * 1000 / (actual_ghi * capacity)` |
| CAL01 3 unresolved meter rows | `external_line_id` not in `contract_line` | Verify CAL01 contract_line data; may need additional migration |
| JAB01 utility PDFs | 17 monthly PDFs not parsed | Could enrich MRP observations with per-line-item detail |

### 29.5 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| Meter readings inserted | > 550 of 604 | 600 | Yes |
| FK resolution rate | > 95% | 99.5% | Yes |
| MRP formula OCR'd | >= 7 project tabs | 9 | Yes |
| MRP rules in clause_tariff | >= 7 tariffs | 9 (7 new + 2 existing) | Yes |
| MRP observations inserted | >= 300 total | 353 | Yes |
| KAS01/MOH01 consistency | < 5% diff | 0 discrepancies | Yes |
| Plant performance enriched | > 0 rows | 305 (292 new + 13 updated) | Yes |
| No critical discrepancies | 0 | 0 | Yes |

---

## 30. Step 10b — Tariff Rate Population (2026-03-09)

**Script:** [`python-backend/scripts/step10b_tariff_rate_population.py`](../python-backend/scripts/step10b_tariff_rate_population.py)

Populates `tariff_rate` rows for all `clause_tariff` entries that have a `base_rate` but no computed rate schedule. Creates annual rate period rows showing the standing/escalated rate per contract year, and monthly FX tracking rows for local-currency tariffs.

### 30.1 Pre-requisites

- Step 4 completed (clause_tariff records exist with base_rate, currency, escalation type)
- Exchange rate table populated (xe.com + revenue_masterfile sources)
- Pipeline notes cleaned (internal "Step N" strings NULLed from contract_billing_product.notes)

### 30.2 What It Does

1. **Sets `valid_from`** on clause_tariff from `cod_date` → `effective_date` → `end_date - term` fallback
2. **Inserts annual `tariff_rate` rows** — Year 1 for flat tariffs; Years 1..N for PERCENTAGE escalation
3. **Inserts monthly `tariff_rate` rows** — for local-currency tariffs, one per exchange_rate month with FX-converted USD rate
4. **Skips** REBASED_MARKET_PRICE tariffs (handled by `RebasedMarketPriceEngine`)

### 30.3 Coverage Summary

| Project | Currency | Annual Rows | Monthly FX Rows | Escalation | Current Year |
|---------|----------|-------------|-----------------|------------|--------------|
| AMP01 | USD | 1 | — | flat | 1 |
| CAL01 | USD | 1 | — | US_CPI (flat until CPI data) | 1 |
| ERG | MGA | 1 | 14 | flat | 3 |
| IVL01 | USD | 1 | — | flat | 3 |
| JAB01 | NGN | 1 | 26 | flat | 6 |
| MB01 | USD | 3 | — | PERCENTAGE 1% | 2 |
| MF01 | USD | 4 | — | PERCENTAGE 1% | 3 |
| MIR01 | SLE | 1 | 14 | flat | 3 |
| MP01 | USD | 3 | — | PERCENTAGE 1% | 2 |
| MP02 | USD | 3 | — | PERCENTAGE 1% | 2 |
| UGL01 | GHS | 7 | 25 | PERCENTAGE 2% | 6 |
| UNSOS | USD | 3 | — | PERCENTAGE 2.5% | 2 |
| XFAB | KES | 1 | 26 | US_CPI (fixed 10 yrs) | 6 |
| **Totals** | | **30** | **105** | | |

**Previously populated (reference projects):** KAS01 (1 annual + 4 monthly), MOH01 (1 annual + 5 monthly) — populated by `RebasedMarketPriceEngine`.

### 30.4 Unpopulated Tariffs (Pending PPA Parsing)

~26 tariffs remain without `tariff_rate` rows because they have NULL `base_rate`. These require Step 11 (PPA contract parsing) or manual entry:

ABI01, AR01, BNT01, GBL01, GC001, IVL01 (OM), LOI01 (×2), NBL01, NBL02, NC02, NC03, QMM01 (×2), TBM01, TWG01 (×2), UTK01, XFBV, XFL01, XFSS, ZL01, ZL02 (×4).

### 30.5 Frontend Changes

- **Monthly FX tracking** expanded from REBASED_MARKET_PRICE-only to all tariff types with monthly data
- **Period column** aligned to always show contractual date range (no more mixed "As of" display)
- **Rate column** consistently shows the annual contractual rate; monthly FX breakdown in expandable sub-rows

### 30.6 Dashboard Audit Fix (same session)

- Cleared 72 `contract_billing_product.notes` rows containing internal pipeline string `"Step 4 auto-derived from contract_line"` — set to NULL so they no longer display on Pricing & Tariffs tab

---

## 31. Step 11: Forecast Extension to Contract End (2026-03-09)

**Script:** `python-backend/scripts/extend_forecasts.py`
**Report:** `python-backend/reports/cbe-population/extend_forecasts_2026-03-09.json`
**Mode:** LIVE (single-project test on GBL01, then full run)

### 31.1 What Was Done

Extended `production_forecast` rows from their last existing month to the contract end date for all eligible projects. Uses the last full calendar year of existing forecasts as a baseline, applies annual degradation, and projects forward month-by-month.

**Methodology:**
1. Determine contract end date: `cod_date + contract_term_years_po` → fallback to `contract.end_date`
2. Extract baseline from last full calendar year of existing forecasts (12 months)
3. Determine degradation: explicit (from `clause_tariff.logic_parameters.degradation_pct`) → implicit (Year 1 vs baseline year energy ratio) → flat (0%)
4. Cap implicit degradation at 1%/year (anything higher is a data artifact)
5. Project forward: energy and PR degrade; GHI and POA stay constant
6. Insert with `ON CONFLICT (project_id, forecast_month) DO NOTHING` (idempotent)

All projected rows have `forecast_source = 'projected'` and `source_metadata` containing engine name, baseline year, degradation rate and source.

### 31.2 Results

| Metric | Value |
|--------|-------|
| Projects processed | 35 |
| Projects extended | 27 (+ GBL01 in test run = 28 unique) |
| Projects skipped | 8 |
| Total rows inserted | 4,379 (+ 245 GBL01 test = 4,624 total) |

### 31.3 Per-Project Summary

| Project | Months | Range | Degradation | Source | End Date Via |
|---------|--------|-------|-------------|--------|-------------|
| AMP01 | 63 | → 2032-03 | 0.0% flat | — | contract.end_date |
| CAL01 | 184 | → 2042-04 | 1.0% capped | implicit (raw 1.85%) | cod + 17y |
| ERG | 203 | → 2043-11 | 0.0% flat | — | cod + 20y |
| GBL01 | 245 | → 2047-05 | 0.5% implicit | Y1=2021, BL=2026 | contract.end_date |
| GC001 | 38 | → 2030-02 | 0.4% implicit | Y1=2016, BL=2026 | contract.end_date |
| IVL01 | 262 | → 2048-10 | 0.0% flat | — | cod + 25y |
| JAB01 | 102 | → 2035-06 | 0.5% implicit | Y1=2020, BL=2026 | cod + 15y |
| LOI01 | 27 | → 2029-03 | 0.0% flat | — | cod + 10y |
| MB01 | 217 | → 2045-01 | 0.0% flat | — | cod + 20y |
| MF01 | 202 | → 2043-10 | 0.0% flat | — | cod + 20y |
| MIR01 | 46 | → 2030-10 | 0.0% flat | — | cod + 7y |
| MOH01 | 288 | → 2050-12 | 0.7% explicit | clause_tariff | cod + 25y |
| MP01 | 208 | → 2044-04 | 0.55% implicit | Y1=2024, BL=2026 | cod + 20y |
| MP02 | 207 | → 2044-03 | 0.55% implicit | Y1=2024, BL=2026 | cod + 20y |
| NBL01 | 111 | → 2036-03 | 0.0% flat | — | contract.end_date |
| NBL02 | 135 | → 2038-03 | 0.4% implicit | Y1=2023, BL=2026 | contract.end_date |
| NC02 | 203 | → 2043-11 | 0.0% flat | — | contract.end_date |
| NC03 | 206 | → 2044-02 | 0.55% implicit | Y1=2024, BL=2026 | contract.end_date |
| QMM01 | 197 | → 2043-05 | 0.0% flat | — | contract.end_date |
| TBM01 | 194 | → 2043-02 | 0.7% implicit | Y1=2023, BL=2026 | cod + 20y |
| TWG01 | 96 | → 2035-12 | 0.0% flat | — | cod + 10y |
| UGL01 | 109 | → 2036-01 | 0.5% implicit | Y1=2021, BL=2026 | cod + 15y |
| UNSOS | 87 | → 2034-03 | 1.0% capped | implicit (raw 16.78%) | cod + 10y |
| UTK01 | 89 | → 2034-05 | 0.7% implicit | Y1=2019, BL=2026 | cod + 15y |
| XFAB | 170 | → 2041-02 | 0.5% implicit | Y1=2021, BL=2026 | cod + 20y |
| XFBV | 245 | → 2047-05 | 0.5% implicit | Y1=2021, BL=2026 | contract.end_date |
| XFL01 | 245 | → 2047-05 | 0.5% implicit | Y1=2021, BL=2026 | contract.end_date |
| XFSS | 245 | → 2047-05 | 0.5% implicit | Y1=2021, BL=2026 | contract.end_date |

### 31.4 Skipped Projects

| Project | Reason |
|---------|--------|
| KAS01 | Already covered (existing forecasts extend past contract end) |
| ABI01, BNT01 | No existing forecast rows (construction phase) |
| AR01, ZL02 | No existing forecast rows (cod + term exist, but PPW data missing) |
| TBC | No existing forecast rows (construction phase, no tariff) |
| ZL01 | No existing forecast rows (legacy entity) |

### 31.5 Data Quality Issues

#### Issue 1: UNSOS — Anomalous Forecast Data (Severity: HIGH)

Hybrid plant (solar + diesel) with templated/placeholder forecast values:
- 2024: real-looking values (241K–410K kWh, varying monthly)
- 2025: repeating constants (~332K, ~321K kWh)
- 2026: different repeating constants (~216K, ~209K kWh) — **~35% drop from 2025**
- Implicit degradation: 16.78% → **capped to 1%**

**Action:** Investigate whether PPW source data for UNSOS was templated/incorrectly parsed. The hybrid structure may have caused the parser to pick up wrong sections. See Known Pipeline Gap #19.

#### Issue 2: CAL01 — Elevated Implicit Degradation (Severity: MEDIUM)

- PR drops from ~0.81 (2025) to ~0.77 (2026) — ~5% PR loss in one year
- Implicit degradation: 1.85% → **capped to 1%** (typical solar: 0.3–0.7%/yr)
- Energy values otherwise correlate with irradiance

**Action:** Check if PPW source data has a step-change between 2025 and 2026 (different PVSyst scenario or capacity assumption). See also Section 26.3 COD mismatch for CAL01.

#### Issue 3: Capacity Mismatches (Severity: HIGH)

Cross-reference of `project.installed_dc_capacity_kwp` (from CBE Customer Summary) vs `forecast.source_metadata.site_params.capacity_kwp` (from PPW project tabs). Already documented in Section 26.3 — repeated here for extension context:

| Project | `project` table (kWp) | `forecast` metadata (kWp) | Variance |
|---------|----------------------|--------------------------|----------|
| MF01 | 674 | 118.5 | -82% |
| NC02 | 1,282.58 | 493.42 | -62% |
| MB01 | 1,172.52 | 544.92 | -53% |
| IVL01 | 967.68 | 3,242.52 | +235% |
| KAS01 | 1,305.24 | 904.8 | -31% |
| NBL01 | 3,173 | 2,511 | -21% |
| QMM01 | 14,447.76 | 16,150 | +12% |

Forecast extension is unaffected (extends existing values as-is), but energy figures may be wrong if the wrong capacity was used in the original PVSyst model. See Known Pipeline Gap #18.

#### Issue 4: Missing COD Dates (Severity: LOW)

| Project | Impact |
|---------|--------|
| AMP01 | `operating_year` NULL on projected rows; falls back to `contract.end_date` |
| XFBV, XFL01, XFSS | Same — COD should match XFAB (2021-01-11) |

See Known Pipeline Gap #20.

### 31.6 Gate Checks

| Gate | Expected | Actual | Passed |
|------|----------|--------|--------|
| GBL01 test: GHI constant, energy/PR declining | Verified | avg_ghi ~150.58 across all years | Yes |
| GBL01 test: forecast_source = 'projected' | All new rows | Confirmed | Yes |
| Full run: rows inserted | ~4,624 | 4,624 (245 + 4,379) | Yes |
| Full run: no errors | 0 errors | 0 errors | Yes |
| Degradation cap applied where needed | UNSOS + CAL01 | Both capped to 1% | Yes |
| Idempotent re-run | ON CONFLICT DO NOTHING | GBL01 skipped on second run | Yes |

---

## 32. Live Data Pipeline — Lifecycle Categorization & Billing Cycle Architecture

> Added 2026-03-15. Documents the transition from one-time CBE population scripts (Steps 1–12) to a recurring monthly live operations pipeline.

### 32.1 Context

Steps 1–12 above populated FrontierMind from CBE-specific Excel files and Snowflake CSVs. These scripts are **not reusable** for ongoing monthly billing. The live pipeline separates three concerns:
1. **One-time onboarding/backfill** from CBE workbooks (Part A of `CBE_DATA_POPULATION_WORKFLOW.md`)
2. **Recurring external live inputs** pushed by clients/operations monthly
3. **Internal derived computations** triggered by upstream data arrival

### 32.2 Five-Way Lifecycle Classification

Every FrontierMind table falls into one of these categories:

| Category | Tables | Update Trigger |
|----------|--------|---------------|
| **Baseline Master** | `project`, `contract`, `contract_line`, `meter`, `counterparty`, `asset`, `customer_contact`, `production_forecast`, `production_guarantee` | Onboarding, dashboard PATCH |
| **Slow-Changing Config** | `contract_amendment`, `clause_tariff`, `billing_tax_rule`, `billing_product`, `clause` | Amendment discovery, tax recalibration, manual calibration |
| **Live External Input** | `exchange_rate`, `reference_price`, `meter_aggregate` | Monthly API push (`/api/ingest/*`) |
| **Live Derived** | `tariff_rate`, `plant_performance`, `expected_invoice_header`, `expected_invoice_line_item` | Compute services triggered by upstream data |
| **System / Lookup** | `billing_period`, `currency`, `tariff_type`, `meter_type`, `invoice_line_item_type`, `data_source`, `counterparty_type`, `clause_type`, `clause_category`, `escalation_type` | Seeded once, rarely changes |

### 32.3 Live Input Endpoints

| Endpoint | Table | Auth | Scope | Canonical Model |
|----------|-------|------|-------|----------------|
| `POST /api/ingest/billing-reads` | `meter_aggregate` | API-key | `billing_reads` | `BillingReadsBatchRequest` — untyped dicts mapped by adapter |
| `POST /api/ingest/fx-rates` | `exchange_rate` | API-key | `fx_rates` | `FXRateBatchRequest` — `currency_code`, `rate_date`, `rate` |
| `POST /api/ingest/reference-prices` | `reference_price` | API-key | `reference_prices` | `ReferencePriceBatchRequest` — `project_sage_id`, `period_start`, `total_variable_charges`, `total_kwh_invoiced`, `currency_code`, `operating_year` (auto-derived from COD) |

### 32.4 Compute Services

| Service | API Endpoint | Inputs | Output Table |
|---------|-------------|--------|-------------|
| `TariffRateService` | `POST /api/projects/{id}/billing/generate-tariff-rates` | `clause_tariff` + `exchange_rate` + `reference_price` (conditional) | `tariff_rate` |
| `PerformanceService` | `POST /api/projects/{id}/plant-performance/compute` | `meter_aggregate` + `production_forecast` | `plant_performance` |
| `InvoiceService` | `POST /api/projects/{id}/billing/generate-expected-invoice` | `tariff_rate` + `meter_aggregate` + `contract_line` + `billing_tax_rule` | `expected_invoice_header` + `expected_invoice_line_item` |
| `BillingCycleOrchestrator` | `POST /api/projects/{id}/billing/run-cycle` | All of the above | All derived tables |

### 32.5 Orchestrator Prerequisite Logic

The orchestrator checks prerequisites **per tariff family**, not globally:

- **Deterministic tariffs** (NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE): No FX or MRP gate. `RatePeriodGenerator.generate()` runs once per project.
- **Floating tariffs** (REBASED_MARKET_PRICE, FLOATING_GRID, etc.): Requires FX rates + MRP data. `RebasedMarketPriceEngine.calculate_and_store()` runs per tariff.
- **US_CPI**: Explicitly blocked — external CPI feed not yet supported.
- **Mixed projects**: Deterministic tariffs generate successfully even when floating prerequisites are missing.

### 32.6 Service Implementation Files

| File | Purpose |
|------|---------|
| `python-backend/models/billing_cycle.py` | Request/response models for tariff generation, performance compute, billing cycle |
| `python-backend/models/reference_price_ingest.py` | Canonical model for `POST /api/ingest/reference-prices` |
| `python-backend/services/billing/tariff_rate_service.py` | Dispatches to RatePeriodGenerator or RebasedMarketPriceEngine per tariff type |
| `python-backend/services/billing/performance_service.py` | Computes plant_performance from meter_aggregate + production_forecast |
| `python-backend/services/billing/invoice_service.py` | Extracted invoice generation (single source of truth, replaces inline SQL in api/billing.py) |
| `python-backend/services/billing/billing_cycle_orchestrator.py` | Dependency-graph runner: verify inputs → compute → generate |
| `data-ingestion/processing/adapters/generic_billing_adapter.py` | Passthrough adapter for non-CBE clients sending canonical fields |
| `data-ingestion/processing/adapters/__init__.py` | Adapter registry (`snowflake` → CBE, `generic` → Generic, fallback → Generic) |
