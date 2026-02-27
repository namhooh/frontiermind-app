# CBE to FrontierMind Data Mapping

This document maps CBE's data architecture to FrontierMind's canonical schema and documents the complete pipeline from source documents through extraction, validation, staging, and dashboard display. CBE is the first client adapter; the mapping demonstrates how client-specific data fits into the platform's generic tables.

**Sources:** AM Onboarding Template (Excel), PPA Contract PDFs, Utility Invoices (GRP — Grid Reference Price), Snowflake data warehouse, Operations Plant Performance Workbook, Operating Revenue Masterfile.

**Schema version:** v10.9 (migration 046)

**Companion documentation:**
- [`contract-digitization/docs/IMPLEMENTATION_GUIDE.md`](../contract-digitization/docs/IMPLEMENTATION_GUIDE.md) — Full contract digitization pipeline (OCR, PII, clause extraction, ontology)
- [`contract-digitization/docs/POWER_PURCHASE_ONTOLOGY_FRAMEWORK.md`](../contract-digitization/docs/POWER_PURCHASE_ONTOLOGY_FRAMEWORK.md) — Ontology concepts, clause categories, relationship types
- [`database/scripts/project-onboarding/audits/`](../database/scripts/project-onboarding/audits/) — Per-project onboarding audit trail
- [`database/migrations/046_populate_portfolio_base_data.sql`](../database/migrations/046_populate_portfolio_base_data.sql) — Full portfolio population (Section 17)

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
| (derived from PRODUCT_CODE) | `tariff_type_id` (FK) | Adapter maps product codes to tariff_type |
| Full original record | `source_metadata.original_record` | Preserved for audit |

#### Tariff Structure Fields (from Onboarding Template / `Inp_Proj`)

These fields define HOW the tariff is calculated, not just the base rate. They come from the AM Onboarding Template (one-time at COD) and the `Inp_Proj` tabs in the Operating Revenue Masterfile.

**Classification FKs** — Three classification axes on `clause_tariff` (after migration 034 dropped `tariff_structure_type`):

> **Multi-value service types:** The onboarding parser now supports Contract Service/Product Type 1 and Type 2 from the template. When a contract has multiple service types (e.g., "Energy Sales" + "Equipment Rental/Lease/BOOT"), the system creates one `clause_tariff` row per service type, each with its own rate (base_rate for energy, equipment_rental_rate for rental, bess_fee for BESS, etc.).

| Source Field | FrontierMind Column | Storage | Notes |
|---|---|---|---|
| Onboarding "Contract Service/Product Type" | `tariff_type_id` | FK → `tariff_type` | Resolves to ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, BESS_LEASE, ENERGY_AS_SERVICE, OTHER_SERVICE, NOT_APPLICABLE |
| Onboarding "Energy Sales Tariff Type" | `energy_sale_type_id` | FK → `energy_sale_type` | Resolves to FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES |
| Onboarding "Price Adjustment type" / `Inp_Proj` row 108 | `escalation_type_id` | FK → `escalation_type` | Resolves to FIXED_INCREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, NONE |
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

#### Tariff Type Mapping

| CBE Product Code | CBE Description | FrontierMind tariff_type |
|-----------------|-----------------|--------------------------|
| ENER0001 | Metered Energy | METERED_ENERGY |
| ENER0002 | Available Energy | AVAILABLE_ENERGY |
| ENER0003 | Deemed Energy | DEEMED_ENERGY |
| BESS0001 | BESS Capacity | BESS_CAPACITY |
| RENT0001 | Equipment Rental | EQUIP_RENTAL |
| OMFE0001 | O&M Fee | OM_FEE |
| DIES0001 | Diesel | DIESEL |
| PNLT0001 | Penalty | PENALTY |

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

Canonical `escalation_type.code` values (from migration 027). CBE-specific detail (rate, index name) lives in `clause_tariff.logic_parameters`.

| Canonical Code | CBE Label | Description | Formula | logic_parameters keys | CBE Examples |
|------|------|-------------|---------|------|-------------|
| `FIXED` | FIXED_PCT | Fixed annual percentage increase | `base * (1 + pct)^years` | `escalation_rate`, `escalation_month` | MF01 (1%), Kasapreko floor (2.5%) |
| `CPI` | US_CPI | Indexed to CPI (index specified in params) | `base * (CPI_current / CPI_base)` | `price_index_name` = 'US_CPI_U' | Garden City, Loisaba, Caledonia, Unilever Ghana |
| `GRID_PASSTHROUGH` | REBASED_MKT | Rebased to current market reference | `market_price * (1 - discount)` | `market_ref_price`, `discount_pct` | MOH01 |
| `NONE` | NONE | No escalation, fixed for contract life | `base` | — | Some projects |

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

**MOH01 seed data** (contract_id=7, 8 lines): 5 metered lines (PPL1, PPL2, Bottles, BBM1, BBM2 at line codes 4000-8000) + 3 available energy lines (PPL1, PPL2, BBM1 at line codes 4001, 5001, 7001).

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

The calculation filters on `energy_sale_type.code = 'MIN_OFFTAKE'` (via `clause_tariff.energy_sale_type_id`), reads `min_offtake_pct` from `clause_tariff.logic_parameters` JSONB, and joins through `meter_aggregate` and `expected_invoice_line_item` to compute monthly variance and cumulative deferred kWh.

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
| `fx_rate_hard_id` (FK) | FK to `exchange_rate` for hard currency |
| `fx_rate_local_id` (FK) | FK to `exchange_rate` for local currency |
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
|    tariff_type_id -> ENERGY_SALES (FK to tariff_type)                 |
|    energy_sale_type_id -> FIXED_SOLAR (FK to energy_sale_type)       |
|    escalation_type_id -> FIXED (FK to escalation_type)               |
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
| `clause_tariff.tariff_type` | METERED_ENERGY | EQUIP_RENTAL, OM_FEE, etc. |
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

    if tariff.escalation_type == 'FIXED':  # canonical; CBE label: FIXED_PCT
        rate = tariff.logic_parameters['escalation_rate']
        return tariff.base_rate * (1 + rate) ** years

    elif tariff.escalation_type == 'CPI':  # canonical; CBE label: US_CPI
        index_name = tariff.logic_parameters.get('price_index_name', 'US_CPI_U')
        cpi_base = price_index_data.get(index_name, tariff.escalation_start_date)
        cpi_now = price_index_data.get(index_name, billing_date)
        return tariff.base_rate * (cpi_now / cpi_base)

    elif tariff.escalation_type == 'GRID_PASSTHROUGH':  # canonical; CBE label: REBASED_MKT
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
| `clause_tariff` classification FKs (`tariff_type_id`, `energy_sale_type_id`, `escalation_type_id`, `market_ref_currency_id`) | 027 + 034 | Implemented (`tariff_structure_id` dropped in 034) |
| `energy_sale_type` lookup | 027 | Implemented (seeded: FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, FLOATING_GRID_GENERATOR, NOT_ENERGY_SALES) |
| `escalation_type` lookup | 027 | Implemented (seeded: FIXED, CPI, CUSTOM, NONE, GRID_PASSTHROUGH) |
| `meter_aggregate` | 000_baseline + 007 + 022 + 026 | Implemented |
| `customer_contact` | 028 | Implemented |
| `production_forecast` | 029 | Implemented |
| `production_guarantee` | 029 | Implemented |
| Deferred energy calculation | — | Deferred to pricing calculator / rules engine — no DB view |
| `exchange_rate` | 022 | Implemented |
| `currency` (seeded) | 022 | Implemented (11 currencies) |
| `tariff_type` (seeded) | 022 | Implemented (14 types) |
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
