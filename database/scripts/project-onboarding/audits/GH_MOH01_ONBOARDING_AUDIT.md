# GH-MOH01 Onboarding Audit

**Project:** GH-MOH01 (Polytanks Ghana Limited)
**Organization:** FrontierSolar
**Date:** 2026-02-18 (initial), 2026-02-19 (pipeline re-onboarding, migration 034 backfill)
**Sources:** AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx, CBE - MOH01_Mohanini_PPA.pdf, Supabase DB
**Correction Script:** `database/scripts/correct_gh_moh01.sql` (superseded by pipeline re-onboarding)

---

## 1. Data Extraction Summary

### 1.1 Project

| Field | Value |
|-------|-------|
| `external_project_id` | GH-MOH01 |
| `name` | GH-MOH01 |
| `country` | Ghana |
| `cod_date` | 2025-09-01 |
| `installed_dc_capacity_kwp` | 2,616.705 |
| `installed_ac_capacity_kw` | 2,500.0 |
| `installation_location_url` | 5.647196, -0.103068 |

### 1.2 Counterparty

| Field | Value |
|-------|-------|
| `name` | Polytanks Ghana Limited |
| `registered_name` | — |
| `registration_number` | — |
| `tax_pin` | — |
| `registered_address` | — |

### 1.3 Contract

| Field | Value |
|-------|-------|
| `external_contract_id` | GH-MOH01-PPA-001 |
| `name` | GH-MOH01 PPA |
| `contract_type` | PPA |
| `contract_status` | ACTIVE |
| `contract_term_years` | 20 |
| `effective_date` | — |
| `end_date` | — |
| `interconnection_voltage_kv` | 0.415 |
| `payment_security_required` | Yes |
| `payment_security_details` | Letter of Credit; Amount: 220,000 USD |
| `agreed_fx_rate_source` | Full Bank of Ghana definition (see extraction metadata) |

**Extraction metadata:**

| Key | Value |
|-----|-------|
| `initial_term_years` | 20 |
| `extension_provisions` | Up to two (2) Additional Terms of five (5) years each, by mutual agreement. |
| `payment_terms` | NET_30 |
| `early_termination_schedule` | 1.155 USD/Wp (Y1) declining to 0.06 USD/Wp (Y20), 0.04 USD/Wp (Y21-25) |
| `confidence_scores` | contract_term: 1.0, discount: 1.0, floor/ceiling: 1.0, shortfall: 1.0, excused_events: 1.0, payment_terms: 1.0, available_energy: 0.95, grp: 0.9 |

### 1.4 Tariff (clause_tariff)

| Field | Value | Notes |
|-------|-------|-------|
| `tariff_group_key` | GH-MOH01-PPA-001-MAIN | |
| `tariff_structure` | FIXED (id=1) | Pipeline uses Excel value; should be GRID — see open item #5 |
| `energy_sale_type` | FIXED_SOLAR | Set via reference table alignment (2026-02-19) |
| `escalation_type` | REBASED_MARKET_PRICE | Set via reference table alignment (2026-02-19) |
| `billing_currency` | USD | |
| `market_ref_currency` | GHS (id=5) | Preserved from prior upsert |
| `base_rate` | 0.1087 USD/kWh | |
| `valid_from` | 2025-09-01 | |

**Logic parameters (current DB state):**

| Parameter | Value |
|-----------|-------|
| `discount_pct` | 0.21 (21%) |
| `floor_rate` | 0.079 USD/kWh |
| `ceiling_rate` | 0.210 USD/kWh |
| `escalation_rules` | `[{component: "min_solar_price", type: FIXED, value: 0.025, start_year: 2}, {component: "max_solar_price", type: NONE}]` |
| `escalation_value` | null |
| `grp_method` | null |
| `grp_exclude_vat` | true |
| `grp_exclude_demand_charges` | true |
| `grp_time_window_start` | 06:00 |
| `grp_time_window_end` | 18:00 |
| `grp_calculation_due_days` | 15 |
| `grp_verification_deadline_days` | 30 |
| `available_energy_method` | Full formula: EAvailable(x) = Ehist * Irr(x) / Irrhist * Intervals ... |
| `irradiance_threshold_wm2` | 100 |
| `interval_minutes` | 15 |
| `shortfall_formula_type` | SP = MAX[0, (Eguaranteed - Eperiod) X (PAlternate - Psolar)] |
| `excused_events` | 4 categories (Customer acts/omissions, Force Majeure, third-party damage, equipment manufacturer delays) |

### 1.5 Assets (2 rows)

| Asset Type | Model | Capacity | Unit | Qty |
|------------|-------|----------|------|-----|
| pv_module | JKM585N-72HL4-BDV | 2,616.705 | kWp | 4,473 |
| inverter | Sungrow SG125CX-P2 | 2,500.0 | kW | 20 |

### 1.6 Meters (5 rows)

| Serial | Location | Type | Model | Meter Type |
|--------|----------|------|-------|------------|
| 23450523 | — | — | SPM33 & SPM93 Pilot Meter | — |
| 23450514 | — | — | SPM33 & SPM93 Pilot Meter | — |
| 24220566 | — | — | SPM33 & SPM93 Pilot Meter | — |
| 23450183 | — | — | SPM33 & SPM93 Pilot Meter | — |
| 23450520 | — | — | SPM33 & SPM93 Pilot Meter | — |

Note: `location_description`, `metering_type`, and `meter_type_id` were populated by the manual correction script but are not extracted by the automated pipeline's Excel parser. The meter model is preserved. See open item #8.

### 1.7 Production Forecast (12 months, Year 1 P50)

| Month | Energy (kWh) | GHI (Wh/m²) | POA (Wh/m²) | PR |
|-------|-------------|-------------|-------------|------|
| Jan 2025 | 289,311 | 139,528 | 138,778 | 0.7967 |
| Feb 2025 | 284,495 | 137,559 | 136,715 | 0.7953 |
| Mar 2025 | 319,056 | 155,562 | 154,531 | 0.7890 |
| Apr 2025 | 315,606 | 153,874 | 152,843 | 0.7891 |
| May 2025 | 312,158 | 150,967 | 149,748 | 0.7966 |
| Jun 2025 | 255,394 | 122,649 | 121,618 | 0.8025 |
| Jul 2025 | 295,729 | 141,403 | 140,184 | 0.8062 |
| Aug 2025 | 304,783 | 145,810 | 144,685 | 0.8050 |
| Sep 2025 | 311,991 | 150,030 | 148,998 | 0.8002 |
| Oct 2025 | 336,865 | 163,251 | 162,126 | 0.7941 |
| Nov 2025 | 326,601 | 158,563 | 157,813 | 0.7909 |
| Dec 2025 | 292,826 | 141,591 | 140,934 | 0.7940 |
| **Annual** | **3,644,815** | | | |

### 1.8 Production Guarantee (20 years)

| Year | P50 (kWh) | Guaranteed (kWh) | % of P50 | Shortfall Cap (USD) | FX Rule |
|------|-----------|-------------------|----------|---------------------|---------|
| 1 | 3,610,403 | 3,249,363 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 2 | 3,585,130 | 3,226,617 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 3 | 3,560,034 | 3,204,031 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 4 | 3,535,114 | 3,181,603 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 5 | 3,510,368 | 3,159,332 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 6 | 3,485,796 | 3,137,216 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 7 | 3,461,395 | 3,115,256 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 8 | 3,437,165 | 3,093,449 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 9 | 3,413,105 | 3,071,795 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 10 | 3,389,214 | 3,050,292 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 11 | 3,365,489 | 3,028,940 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 12 | 3,341,931 | 3,007,738 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 13 | 3,318,537 | 2,986,683 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 14 | 3,295,307 | 2,965,777 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 15 | 3,272,240 | 2,945,016 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 16 | 3,249,335 | 2,924,401 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 17 | 3,226,589 | 2,903,930 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 18 | 3,204,003 | 2,883,603 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 19 | 3,181,575 | 2,863,418 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |
| 20 | 3,159,304 | 2,843,374 | 90% | 119,000 | Agreed Exchange Rate on invoicing date |

Guarantee values are base PPA values extracted by regex from the PDF guarantee table (not pro-rata adjusted). P50 values are `preliminary_yield_kwh` from the PPA. The 90% guarantee factor is calculated as `guaranteed_kwh / p50_annual_kwh`.

### 1.9 Billing Products (2 rows)

| Product Code | Name | Primary | Source |
|---|---|---|---|
| GHREVS001 | Metered Energy (EMetered) | Yes | Canonical seed (migration 034) |
| GHREVS002 | Available Energy (EAvailable) | No | Canonical seed (migration 034) |

Product codes are from `dim_finance_product_code.csv` (Sage ERP). GHREVS001 is the primary metered energy revenue line. GHREVS002 covers the available energy calculation defined in the PPA (Annexure E). Both resolve to canonical (platform-level) billing products — no org-scoped overrides for this project.

Note: The Excel template had no "product to be billed" field populated. Products were manually identified from the tariff structure (metered + available energy) and backfilled via migration 034 onboarding (2026-02-19).

### 1.10 Tariff Rate Period (1 row)

| Clause Tariff | Year | Period Start | Period End | Effective Rate | Currency | Current | Basis |
|---|---|---|---|---|---|---|---|
| GH-MOH01-PPA-001-MAIN | 1 | 2025-09-01 | — | 0.1087 | USD | Yes | Year 1: original contractual base rate |

Year 1 effective_rate equals the clause_tariff.base_rate. Future escalation (REBASED_MARKET_PRICE) will insert new rows and flip `is_current` on this row to false. The unique partial index `idx_tariff_rate_period_current` enforces exactly one current rate per clause_tariff.

### 1.11 Customer Contacts

No contacts populated. Source Excel template contained no contact data.

### 1.12 Entity Count Summary

| Entity | Rows |
|--------|------|
| Project | 1 |
| Counterparty | 1 |
| Contract | 1 |
| Clause Tariff | 1 |
| Billing Products | 2 |
| Tariff Rate Periods | 1 |
| Assets | 2 |
| Meters | 5 |
| Production Forecast | 12 |
| Production Guarantee | 20 |
| Customer Contacts | 0 |
| Reference Prices | 0 |

---

## 2. Discrepancy Analysis (Initial — 2026-02-18)

### 2.1 Cross-Source Discrepancies (Excel vs PDF)

| # | Field | Excel Value | PDF Value | Selected | Rationale |
|---|-------|-------------|-----------|----------|-----------|
| 1 | `customer_name` | *(blank)* | Polytanks Ghana Limited | PDF | Legal contract is authoritative; Excel field was empty |
| 2 | `contract_term_years` | 25 | 20 initial + 2x5yr extensions | PDF (20) | Initial legal term; extensions stored separately in metadata |
| 3 | Pricing model | Fixed Solar Tariff (0.1087 USD/kWh) | GRP-linked: 21% discount, floor 0.079, ceiling 0.210 | PDF (GRID) | Tariff structure corrected from FIXED to GRID |
| 4 | `discount_pct` | *(blank)* | 21% | PDF (0.21) | Excel blank because Fixed tariff was selected |
| 5 | `floor_rate` | *(blank)* | 0.079 USD/kWh | PDF | Available from Annexure C |
| 6 | `ceiling_rate` | *(blank)* | 0.210 USD/kWh | PDF | Available from Annexure C |
| 7 | `payment_security_details` | Required=Yes, details blank | Letter of Credit, USD 220,000 | PDF | LOC details only in contract |
| 8 | Guarantee Y1 | 3,280,333.491 kWh (adjusted) | 3,249,363 kWh (base) | PDF base + pro-rata | Script applies actual/expected DC capacity ratio x 0.9 |

### 2.2 Extraction/Preview Discrepancies

| # | Field | Expected | Parser Produced | Status |
|---|-------|----------|-----------------|--------|
| 9 | `customer_name` | Polytanks Ghana Limited | `null` | Preserved from prior counterparty upsert |
| 10 | Contacts | Contact list from Excel | 0 rows | Not fixable (no source data) |
| 11 | Assets | PV modules + inverters | 2 rows | Fixed (Excel parser extracts assets) |
| 12 | Meter attributes | Serial + location + type + model | Serials + model only | Partial — location/type not in Excel parser |
| 13 | Tariff escalation type | Canonical code (REBASED_MARKET_PRICE) | Free-text "Rebased Market Price" | Fixed — normalizer maps to REBASED_MARKET_PRICE (2026-02-19) |
| 14 | Guarantee pro-rata | Adjusted for installed capacity | Raw PDF base values | Open — pipeline uses base PPA values |

### 2.3 Database State Discrepancies (Before vs After Correction)

| # | Field | Before | After | Status |
|---|-------|--------|-------|--------|
| 15 | `project.country` | `GH` | `Ghana` | Fixed |
| 16 | `contract.contract_term_years` | 25 | 20 | Fixed |
| 17 | `contract.counterparty` | Mohinani Group | Polytanks Ghana Limited | Fixed |
| 18 | `contract.effective_date` | `null` | `null` | Open (no source data) |
| 19 | `contract.end_date` | `null` | `null` | Open (depends on effective_date) |
| 20 | `contract.payment_security_details` | `null` | Letter of Credit; Amount: 220000 USD | Fixed |
| 21 | `contract.agreed_fx_rate_source` | `null` | Full Bank of Ghana definition (353 chars) | Fixed |
| 22 | `contract.extraction_metadata` | `null` | initial_term=20, extensions, payment_terms=NET_30, early_termination, confidence_scores | Fixed |
| 23 | `clause_tariff.tariff_structure` | FIXED (id=1) | FIXED (id=1) | Open — should be GRID (see open item #5) |
| 24 | `clause_tariff.energy_sale_type` | `null` | FIXED_SOLAR | Fixed — reference tables aligned with Excel dropdowns (2026-02-19) |
| 25 | `clause_tariff.escalation_type` | `null` | REBASED_MARKET_PRICE | Fixed — reference tables aligned with Excel dropdowns (2026-02-19) |
| 26 | `clause_tariff.market_ref_currency` | `null` | GHS (id=5) | Fixed (preserved from prior upsert) |
| 27 | `clause_tariff.logic_parameters.floor_rate` | `null` | 0.079 | Fixed |
| 28 | `clause_tariff.logic_parameters.ceiling_rate` | `null` | 0.210 | Fixed |
| 29 | `clause_tariff.logic_parameters.grp_method` | `null` | `null` | Open — should be `utility_variable_charges_tou` (see open item #9) |
| 30 | `production_guarantee.guaranteed_kwh` (Y1) | 3,249,363 | 3,249,363 | Base PPA value (not pro-rata) |
| 31 | `production_guarantee.shortfall_cap_usd` | `null` | 119,000 | Fixed |
| 32 | `production_guarantee.shortfall_cap_fx_rule` | `null` | Agreed Exchange Rate on invoicing date | Fixed |
| 33 | `asset` rows | 0 | 2 (PV module + Inverter) | Fixed |
| 34 | `meter.location_description` | all `null` | all `null` | Open — not in Excel parser (see open item #8) |
| 35 | `meter.metering_type` | all `null` | all `null` | Open — not in Excel parser (see open item #8) |
| 36 | `meter.model` | all `null` | SPM33 & SPM93 Pilot Meter | Fixed |
| 37 | `meter.meter_type_id` | all `null` | all `null` | Open — not in Excel parser (see open item #8) |
| 38 | `customer_contact` rows | 0 | 0 | Open (no source data) |
| 39 | `production_forecast.source_metadata` | `{}` | `{}` | Open (metadata supplementary; core data intact) |
| 40 | `reference_price` rows | 0 | 0 | Open (requires separate market data ingestion) |

---

## 3. Pipeline Re-Onboarding (2026-02-19)

### 3.1 Context

The initial onboarding used a manual correction script (`correct_gh_moh01.sql`) to fix parser gaps. On 2026-02-19, the project was re-onboarded through the automated pipeline (`POST /api/onboard/preview` + `POST /api/onboard/commit`) to validate the new PPA extraction code end-to-end.

### 3.2 Pre-Requisite Fix

Two key names in `clause_tariff.logic_parameters` were mismatched between the manual correction script and the calculation service (`available_energy.py`):

| Manual script key (wrong) | Calc service key (correct) |
|---|---|
| `available_energy_irradiance_threshold_wm2` | `irradiance_threshold_wm2` |
| `available_energy_interval_minutes` | `interval_minutes` |

Fixed via SQL UPDATE before re-onboarding. The pipeline now produces the correct key names natively.

### 3.3 Schema Fix

`contract.agreed_fx_rate_source` was VARCHAR(255) but the LLM-extracted Bank of Ghana definition is 353 characters. Column widened to TEXT. Staging table definition in `onboarding_service.py` updated to match.

### 3.4 SQL Fix

`onboard_project.sql` counterparty INSERT failed on NOT NULL constraint when `customer_name` is null (Excel parser does not extract it for this template). Fixed with `COALESCE(s.customer_name, s.external_project_id || ' Offtaker')`. In this case, the existing counterparty "Polytanks Ghana Limited" was preserved by the ON CONFLICT upsert.

### 3.5 Pipeline Improvements Over Manual Script

Fields now extracted by the automated PPA parser (LLM phase) that were previously set manually:

| Field | Manual Script | Pipeline (LLM) |
|-------|---------------|-----------------|
| `shortfall_formula_type` | Not set | `SP = MAX[0, (Eguaranteed - Eperiod) X (PAlternate - Psolar)]` |
| `excused_events` | Not set | 4 categories extracted from PPA |
| `escalation_rules` | Individual keys (`floor_escalation_rate`, `ceiling_escalation_rate`) | Structured array with component/type/value/start_year |
| `available_energy_method` | Short code `irradiance_interval_adjusted` | Full formula text from Annexure E |
| `extraction_metadata` | 4 fields | 5 fields + `confidence_scores` (9 fields, all 0.9-1.0) |
| `early_termination_schedule` | Not set | Full schedule text extracted |
| `agreed_fx_rate_source` | Summary text | Full contractual definition |

### 3.6 Regressions From Manual Corrections

Fields that were correctly set by the manual script but are not handled by the automated pipeline:

| # | Field | Manual Script Value | Pipeline Value | Root Cause |
|---|-------|---------------------|----------------|------------|
| R1 | `tariff_structure_id` | GRID (id=2) | FIXED (id=1) | Pipeline uses Excel value; Excel has "FIXED" because template was filled for fixed tariff |
| R2 | `energy_sale_type_id` | TAKE_OR_PAY (id=1) | FIXED_SOLAR | Reference tables aligned with Excel template dropdowns; normalizer updated (2026-02-19) |
| R3 | `escalation_type_id` | GRID_PASSTHROUGH (id=5) | REBASED_MARKET_PRICE | Reference tables aligned with Excel template dropdowns; normalizer maps "Rebased Market Price" (2026-02-19) |
| R4 | `grp_method` | `utility_variable_charges_tou` | null | Neither Excel nor LLM extracts `grp_method` as a logic_parameters key |
| R5 | `grp_exclude_savings_charges` | true | *(not set)* | LLM returned null for this field |
| R6 | `meter.location_description` | BBM1, BBM2, Bottles, PPL 1, PPL 2 | null | Excel parser does not extract meter location |
| R7 | `meter.metering_type` | export_only | null | Excel parser does not extract metering type |
| R8 | `meter.meter_type_id` | REVENUE (id=1) | null | Excel parser does not extract meter type |
| R9 | Guarantee pro-rata adjustment | Adjusted by (actual DC / expected DC) ratio | Base PPA values only | Pipeline does not apply pro-rata capacity adjustment |

### 3.7 Key Name Changes

| Old Key (manual script) | New Key (pipeline) | Notes |
|---|---|---|
| `floor_escalation_rate` | `escalation_rules[0].escalation_value` | Restructured as array |
| `floor_escalation_start_year` | `escalation_rules[0].start_year` | Restructured as array |
| `ceiling_escalation_rate` | `escalation_rules[1].escalation_value` | Restructured as array |
| `available_energy_irradiance_threshold_wm2` | `irradiance_threshold_wm2` | Shortened to match calc service |
| `available_energy_interval_minutes` | `interval_minutes` | Shortened to match calc service |

---

## 4. Migration 034 Backfill (2026-02-19)

### 4.1 Context

Migration 034 (`034_billing_product_and_rate_period.sql`) added three new tables: `billing_product`, `contract_billing_product`, and `tariff_rate_period`. The migration was applied after GH-MOH01's initial onboarding, so the project had no data in these tables.

A post-implementation review identified integrity gaps in migration 034:
- `UNIQUE(code, organization_id)` didn't prevent duplicate canonical rows (NULL ≠ NULL)
- No cross-tenant guard on `contract_billing_product`
- `tariff_rate_period.is_current` index was non-unique, allowing multiple current rows
- No CHECK constraints on `tariff_rate_period`
- Multiple `is_primary` billing products per contract allowed
- Step 4.10 JOIN could match both canonical AND org-scoped rows for same code

All six issues were fixed in migration 034 before the backfill (partial unique indexes, validation trigger, unique partial index for is_current, CHECK constraints, unique partial index for is_primary, LATERAL JOIN with org preference).

### 4.2 Data Inserted

**contract_billing_product** (2 rows):
- GHREVS001 (Metered Energy) — `is_primary = true`
- GHREVS002 (Available Energy) — `is_primary = false`

Both resolve to canonical billing products (`organization_id IS NULL`) via the updated LATERAL JOIN in `onboard_project.sql` Step 4.10, which prefers org-scoped over canonical (`ORDER BY organization_id NULLS LAST`).

**tariff_rate_period** (1 row):
- clause_tariff_id = 2 (GH-MOH01-PPA-001-MAIN)
- contract_year = 1, effective_rate = 0.1087 USD, is_current = true
- Created via `onboard_project.sql` Step 4.11 logic (effective_rate = base_rate for Year 1)

### 4.3 Integrity Constraints Verified

| Constraint | Result |
|---|---|
| `uq_billing_product_canonical` — no duplicate canonical codes | Seed data ON CONFLICT confirmed |
| `uq_contract_billing_product_primary` — single primary per contract | 1 primary (GHREVS001) |
| `trg_contract_billing_product_org_check` — cross-tenant validation | Both products canonical (NULL org) — allowed |
| `idx_tariff_rate_period_current` (UNIQUE) — single current per tariff | 1 current row for clause_tariff_id=2 |
| `CHECK (contract_year >= 1)` | contract_year = 1 |
| `CHECK (effective_rate >= 0)` | effective_rate = 0.1087 |
| `CHECK (period_end IS NULL OR period_end >= period_start)` | period_end = NULL |

### 4.4 Template Updates

`onboard_project.sql` and `validate_onboarding_project.sql` were updated to cover the new entities:

| File | Change |
|---|---|
| `onboard_project.sql` | Prerequisites reference migration 034; `stg_project_core.agreed_fx_rate_source` widened to TEXT; Step 3 validates billing product codes exist; Step 5 asserts billing product count, single primary, and tariff rate period count |
| `validate_onboarding_project.sql` | 4 new core checks (billing_product_count, billing_product_single_primary, tariff_rate_period_count, tariff_rate_period_single_current); 2 new snapshot tables |

---

## 5. Summary

| Category | Total | Fixed | Open |
|----------|-------|-------|------|
| Cross-source conflicts | 8 | 8 | 0 |
| Extraction/preview gaps | 6 | 3 | 3 |
| Database state issues | 26 | 18 | 8 |
| Pipeline regressions | 9 | 2 | 7 |
| Migration 034 backfill | 3 | 3 | 0 |
| **Total** | **52** | **34** | **18** |

Migration 034 backfill items (all fixed):
- `contract_billing_product`: 2 rows (GHREVS001 primary, GHREVS002 secondary)
- `tariff_rate_period`: 1 row (Year 1, effective_rate = 0.1087 USD, is_current = true)
- Schema integrity: 6 constraints verified (partial unique indexes, cross-tenant trigger, CHECKs)

### Open Items

**Require pipeline enhancement:**

1. **`contract.effective_date`** and **`end_date`** — Neither Excel nor LLM extraction provided the contract execution date. Requires manual lookup of the signed PPA.
2. **`customer_contact`** — No contacts found in Excel template. Requires manual entry from CBE operational records.
3. **`reference_price`** — GRP tariff calculation needs ECG market reference pricing data. Requires separate market data ingestion.
4. **`production_forecast.source_metadata`** — Supplementary; core forecast data intact.
5. **`tariff_structure_id`** — Pipeline should infer GRID from PPA data (floor/ceiling/discount presence) instead of using Excel's FIXED value.
6. ~~**`energy_sale_type_id`**~~ — **Fixed (2026-02-19).** Reference tables aligned with Excel template dropdowns; normalizer maps Excel values to DB codes. GH-MOH01 set to FIXED_SOLAR.
7. ~~**`escalation_type_id`**~~ — **Fixed (2026-02-19).** Reference tables aligned with Excel template dropdowns; normalizer maps "Rebased Market Price" → REBASED_MARKET_PRICE. GH-MOH01 set to REBASED_MARKET_PRICE.
8. **Meter attributes** — Excel parser should extract `location_description`, `metering_type`, and `meter_type_id` from the onboarding template.
9. **`grp_method`** — Pipeline should set `grp_method` in logic_parameters (e.g., `utility_variable_charges_tou`) when GRP parameters are present.
10. **`grp_exclude_savings_charges`** — LLM returned null; may need prompt refinement or default-to-true when other GRP exclusions are set.
11. **Guarantee pro-rata adjustment** — Pipeline uses base PPA guarantee values. Consider applying (actual DC / expected DC) capacity ratio adjustment for systems where installed capacity differs from PPA design capacity.
