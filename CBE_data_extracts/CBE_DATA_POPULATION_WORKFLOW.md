# CBE Data Population Workflow

> Consolidated guide for populating FrontierMind project data from CrossBoundary Energy (CBE) source documents.
> Merges former `DATA_POPULATION_WORKFLOW.md` and `PROJECT_SOURCE_INVENTORY.md`.
>
> **Schema version:** v10.11+ (migration 049+)
> **Last updated:** 2026-03-07
>
> **Companion documentation:**
> - [`CBE_TO_FRONTIERMIND_MAPPING.md`](./CBE_TO_FRONTIERMIND_MAPPING.md) — Field-level schema mapping (CBE → FM)
> - [`contract-digitization/docs/IMPLEMENTATION_GUIDE.md`](../contract-digitization/docs/IMPLEMENTATION_GUIDE.md) — Generic contract digitization pipeline
> - [`database/DATABASE_GUIDE.md`](../database/DATABASE_GUIDE.md) — Schema and migration reference

---

## 1. Source Document Inventory

### 1.1 Snowflake CSV Extracts (structured, SCD Type 2)

All CSVs use Snowflake SCD2 versioning. Filter on `DIM_CURRENT_RECORD=1` for current state.

| File | Path | Rows | Key Fields | Filter |
|------|------|------|------------|--------|
| Customers | `Data Extracts/...dim_finance_customer.csv` | ~32 | CUSTOMER_NUMBER, CUSTOMER_NAME, COUNTRY_NAME, PAYMENT_TERM_CODE | DIM_CURRENT_RECORD=1 |
| Contracts | `Data Extracts/...dim_finance_contract.csv` | 118 | CONTRACT_NUMBER, CONTRACT_CURRENCY, PAYMENT_TERMS, TAX_RULE, START_DATE, END_DATE | DIM_CURRENT_RECORD=1, ACTIVE=1 |
| Contract Lines | `Data Extracts/...dim_finance_contract_line.csv` | 1,084 | CONTRACT_LINE_UNIQUE_ID, PRODUCT_DESC, METERED_AVAILABLE, ACTIVE_STATUS, IND_USE_CPI_INFLATION | DIM_CURRENT_RECORD=1 |
| Meter Readings | `Data Extracts/...meter readings.csv` | 604 | METER_READING_UNIQUE_ID, BILL_DATE, UTILIZED_READING, DISCOUNT_READING, SOURCED_ENERGY, CONTRACT_LINE_UNIQUE_ID | All rows |
| Product Codes | `Data Extracts/...dim_finance_product_code.csv` | ~50 | PRODUCT_CODE, PRODUCT_NAME | All rows |

### 1.2 Workbooks (semi-structured)

| File | Path | Scope | Key Data |
|------|------|-------|----------|
| Customer Summary | `Customer summary.xlsx` | Portfolio-wide | Project metadata, COD dates, capacities, country, currency, contract type |
| Revenue Masterfile | `CBE Asset Management Operating Revenue Masterfile - new.xlsb` | Portfolio-wide | Revenue, tariffs, FX, CPI, loans, rentals (10 tabs — see Step 7) |
| Plant Performance | `Operations Plant Performance Workbook.xlsx` | Portfolio-wide | Technical specs, forecasts, actuals, performance comparisons (50+ tabs — see Steps 5-6, 10) |
| AM Onboarding Template | `AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx` | MOH01 only | Detailed onboarding data (not available for other projects) |

### 1.3 SAGE Extracts

| File | Path | Key Data |
|------|------|----------|
| MRP Pricing | `MRP/Sage Contract Extracts market Ref pricing data.xlsx` | Market Reference Price per project, discount %, floor/ceiling rates |

### 1.4 Invoice Samples

| Path | Contents |
|------|----------|
| `Invoice samples/` | 58 files (30 .eml + 26 .pdf + eTIMS). Covers ~26 projects. |

Invoice PDFs contain: energy line items (page 1), tariff parameter box (page 2: MRP, discount %, floor/ceiling, FX rate).
Invoice .eml files contain embedded metadata in `##...##` delimiters (recipient, due date, amounts).

**Role:** Invoices are **calibration sources**, not primary structure. Use to validate taxes/levies, non-energy charges, and monthly rate application. Do not let invoice-only anomalies overwrite canonical contract structure automatically.

### 1.5 MRP / Utility Source Documents

| Path | Contents |
|------|----------|
| `MRP/Sage Contract Extracts market Ref pricing data.xlsx` | SAGE-sourced MRP parameters per project |
| `MRP/JAB01/2024/` | 7 utility PDFs (May-Dec 2024) |
| `MRP/JAB01/2025/` | 10 utility PDFs (Jan-Oct 2025) |

JAB01 has deep utility invoice support. Other projects may only have workbook-level MRP data.

### 1.6 Loans & Rentals

| Path | Contents |
|------|----------|
| `Loans and rentals/Loans and Rentals schedule.xlsx` | Loan amortization schedules, rental payment terms |
| `Loans and rentals/Invoices w rental/` | 3 rental invoices (AMP01, AR01, QMM01) |
| `Loans and rentals/Repayment notices/` | 4 repayment notices (GC01, ZL01, ZL02, iSAT) |
| `Loans and rentals/*.pdf` | ZL02 diesel annex, ECR receipts |

### 1.7 Contract PDFs (PPA / SSA / ESA)

| Path | Contents |
|------|----------|
| `Customer Offtake Agreements/*.pdf` | 62 PPA/SSA/ESA documents across portfolio |

**Role:** PDF parsing is **final reconciliation/enrichment**. Use to confirm legal clause changes, amendment supersession, and tariff terms. Only promote parsed values where higher-authority structured sources are absent or clearly wrong.

---

## 2. Project x Document Matrix

Filtered to DIM_CURRENT_RECORD=1 for contract lines. Note: "Contract Lines" count includes both active (ACTIVE_STATUS=1) and inactive (ACTIVE_STATUS=0) current records. Pilot section details break these down individually. CUSTOMER_NUMBER aliases noted where applicable.

| Sage ID | Project Name | PPA Docs | Contract Lines (DIM_CURRENT) | Meter Readings | Invoices | CBE Alias | Population Status |
|---------|-------------|----------|------------------------|----------------|----------|-----------|-------------------|
| ABI01 | Accra Breweries Ghana | 1 | 0 | 0 | 1 | -- | PPA-only |
| AMP01 | Ampersand | 1 | 3 | 2 | 1 | -- | Partial |
| AR01 | Arijiju Retreat | 1 | 1 | 0 | 1 | -- | Minimal |
| BNT01 | Izuba BNT | 1 | 0 | 0 | 0 | -- | PPA-only |
| CAL01 | Caledonia | 2 | 6 | 22 | 1 | -- | Ready |
| ERG | Molo Graphite | 1 | 2 | 14 | 1 | -- | Ready |
| GBL01 | Guinness Ghana Breweries | 3 | 6 | 24 | 1 | -- | Ready |
| GC01 | Garden City Mall | 3 | 3 | 24 | 1 | GC001 | Ready |
| IVL01 | Indorama Ventures | 2 | 3 | 13 | 1 | -- | Ready |
| JAB01 | Jabi Lake Mall | 1 | 4 | 41 | 1 | -- | Ready |
| **KAS01** | **Kasapreko** | **4** | **4** | **36** | **1** | -- | **Pilot** |
| **LOI01** | **Loisaba** | **5** | **6** | **24** | **1** | -- | **Pilot** |
| MB01 | Maisha Mabati Mills | 1 | 7 | 24 | 1 | -- | Ready |
| MF01 | Maisha Minerals & Fertilizer | 1 | 5 | 24 | 1 | -- | Ready |
| MIR01 | Miro Forestry | 2 | 6 | 12 | 1 | -- | Ready |
| MOH01 | Mohinani | 1 | 7 | 7 | 1 | -- | **Onboarded** |
| MP01 | Maisha Packaging Nakuru | 1 | 3 | 13 | 1 | -- | Ready |
| MP02 | Maisha Packaging LuKenya | 1 | 5 | 25 | 1 | -- | Ready |
| **NBL01** | **Nigerian Breweries Ibadan** | **5** | **8** | **34** | **1** | -- | **Pilot** |
| NBL02 | Nigerian Breweries Ama | 2 | 2 | 19 | 1 | -- | Ready |
| NC02 | National Cement Athi River | 1 | 3 | 12 | 1 | -- | Ready |
| NC03 | National Cement Nakuru | 1 | 3 | 13 | 1 | -- | Ready |
| QMM01 | Rio Tinto QMM | 4 | 8 | 34 | 1 | -- | Ready |
| TBC | iSAT Africa | 0 | 0 | 0 | 0 | -- | No data |
| TBM01 | TeePee Brush Manufacturers | 2 | 3 | 24 | 1 | -- | Ready |
| TWG01 | Balama Graphite | 1 | 4 | 0 | 1 | TWG | No readings |
| UGL01 | Unilever Ghana | 3 | 4 | 23 | 1 | -- | Ready |
| UNSOS | UNSOS Baidoa | 2 | 4 | 21 | 1 | -- | Ready |
| UTK01 | eKaterra Tea Kenya | 2 | 4 | 24 | 1 | -- | Ready |
| XF-AB | XFlora Group | 4 | 16* | 95* | 4* | XFAB/XFBV/XFSS/XFL01 | Ready |
| ZL02 | Zoodlabs Energy Services | 0 | 9 | 0 | 2 | -- | No PPA, no readings |
| ZO01 | Zoodlabs Group | 2 | 0 | 0 | 0 | ZL01 | PPA-only |

*XFlora: 4 CBE sub-customers aggregate to 1 FM project.

### Customer Alias Map

Canonical alias resolution for cross-source joins. See also CBE_TO_FRONTIERMIND_MAPPING.md Section 18.

| FM sage_id | CBE CUSTOMER_NUMBER(s) | Notes |
|------------|----------------------|-------|
| GC01 | GC001 | FM normalized; original in `extraction_metadata.source_sage_customer_id` |
| TWG01 | TWG | FM uses TWG01 for consistency |
| XF-AB | XFAB, XFBV, XFL01, XFSS | 4 sub-customers → 1 FM project |
| ZO01 | ZL01 | SAGE ZL01 contracts reassigned to ZL02; ZO01 has ESA from PDF |
| ABI01 | -- | No SAGE record; contract from PDF only |
| BNT01 | -- | No SAGE record; contract from PDF only |

All cross-source joins MUST resolve through this alias map. Unresolved aliases are logged as discrepancies.

### Multi-Contract / Multi-Customer Patterns

**Primary rule:** If the Invoice AND the Plant Performance Workbook tabs are separated, create them as **separate FM projects**. If invoiced together and on the same PPW tab, keep as 1 FM project.

| Pattern | Example | Invoice | PPW Tabs | FM Handling |
|---------|---------|---------|----------|-------------|
| Multiple SAGE customers, separate invoices + PPW tabs | XF-AB (XFAB/XFBV/XFL01/XFSS) | 4 separate invoices | 4 separate tabs | **4 separate FM projects** (not 1 consolidated). Current DB has 1 XF-AB project — **NEEDS MIGRATION to split into 4 projects.** |
| Sub-projects billed together, single PPW tab | QMM01 (phases/sub-sites) | 1 invoice | 1 tab (QMM01) | 1 FM project. Capture separate generation/forecast as separate `contract_line` / `billing_product` / `meter` entries. |
| Phase 1 + Phase 2, single invoice + single PPW tab | KAS01 | 1 invoice | 1 tab (KAS01) | 1 FM project, phases tracked in `project.technical_specs` and per-phase breakdown in `production_forecast.source_metadata` |
| Phase 1 + Phase 2, separate invoices + separate PPW tabs | (check per project) | Separate | Separate | **Separate FM projects** — follow the rule |
| Hybrid billing lines under same SAGE ID | ERG, UNSOS | 1 invoice | 1 tab each | 1 FM project per tab. Capture hybrid sub-lines as separate `contract_line` entries. |

**Discrepancy rule:** If the PPW tab structure, invoice structure, and /Data Extracts CSVs disagree on project/phase boundaries, raise for manual review.

---

## 3. Field Authority Matrix

When multiple sources provide values for the same DB field, this matrix determines which source wins. Conflicts between sources of equal authority are flagged for manual review.

| DB Field | Primary Source | Secondary Source | Conflict Action |
|----------|---------------|-----------------|-----------------|
| `project.name` | Customer summary.xlsx | dim_finance_customer.csv | Primary wins |
| `project.cod_date` | Plant Performance Workbook (project tab col A) | Customer summary.xlsx | PPW wins if valid; flag if >30 days apart or if PPW value is `#REF!`/error — do NOT blindly overwrite |
| `project.installed_dc_capacity_kwp` | Plant Performance Workbook (Project Waterfall col B) | Customer summary.xlsx | PPW wins if valid; flag if PPW value is `#REF!`/error — do NOT blindly overwrite |
| `project.technology` | Revenue Masterfile (PO Summary: Connection col F) | Customer summary.xlsx | Flag if mismatch |
| `counterparty.industry` | Revenue Masterfile (Reporting Graphs col D) | -- | Single source |
| `contract.external_contract_id` | dim_finance_contract.csv | SAGE MRP xlsx | Primary wins |
| `clause_tariff.currency_id` | dim_finance_contract.csv (CONTRACT_CURRENCY) | Invoice PDF (header) | Primary wins; flag if mismatch. Note: there is no `contract_currency` column on `contract`. Currency is stored on `clause_tariff.currency_id`. The 4-currency system (hard/local/billing/contract) in `tariff_rate` derives from this + `exchange_rate`. |
| `contract.payment_terms` | dim_finance_contract.csv | Invoice .eml metadata | Primary wins |
| `contract.effective_date` | dim_finance_contract.csv | PPA PDF (parsed) | Primary wins; flag if mismatch |
| `contract.end_date` | dim_finance_contract.csv | Revenue Masterfile (PO Summary: COD End col J) | Flag if mismatch |
| `contract_line.product_desc` | dim_finance_contract_line.csv | -- | Single source |
| `contract_line.energy_category` | dim_finance_contract_line.csv (METERED_AVAILABLE) | -- | Derived (see classification rules) |
| `clause_tariff.base_rate` | Revenue Masterfile (PO Summary: tariff cols U-AC) | PPA PDF (parsed) | Masterfile wins for current rate; PPA wins for Year 1 / contractual base |
| `clause_tariff.discount_percentage` | Revenue Masterfile (PO Summary) / SAGE MRP xlsx | Invoice PDF (tariff box) | Primary wins; invoice validates |
| `clause_tariff.floor_rate` | Revenue Masterfile (PO Summary: Min Tariff col AB) | PPA PDF (parsed) | Primary wins; PPA confirms contractual basis |
| `clause_tariff.ceiling_rate` | Revenue Masterfile (PO Summary: Max Tariff col AC) | PPA PDF (parsed) | Primary wins |
| `reference_price.price_per_kwh` (MRP) | SAGE MRP xlsx | Invoice PDF (tariff box) | Primary wins; invoice validates monthly |
| `reference_price.price_per_kwh` (utility) | Utility PDF (JAB01 etc.) | -- | Single source (where available) |
| `billing_tax_rule.rules` (tax rates) | Invoice PDF (tax lines) | Country tax legislation | Invoice wins for project-specific rates |
| `billing_tax_rule.rules` (WHT rate) | Invoice PDF | -- | **Project-scoped** (Ghana: KAS01=7.5%, MOH01=3.0%) |
| `meter_aggregate.utilized_kwh` | meter readings.csv | Invoice PDF (line quantity) | CSV wins; invoice validates |
| `tariff_rate.*` | Revenue Masterfile | Invoice PDF (computed rate) | Masterfile wins; invoice validates |
| `exchange_rate.rate` | Revenue Masterfile (Invoiced SAGE rows 62-64) | Invoice PDF (FX box) | Masterfile wins; invoice validates |
| `production_forecast.forecast_energy_kwh` | Plant Performance Workbook (project tab: Technical Model) | Revenue Masterfile (Energy Sales tab) | PPW wins; flag if >5% variance |
| `production_forecast.degradation_factor` | Plant Performance Workbook (project tab: Annual Degradation) | Revenue Masterfile (Energy Sales row 3) | Flag if mismatch |
| `production_guarantee.guaranteed_kwh` | PPA PDF (parsed) | Revenue Masterfile (PO Summary: Annual Production col Q) | PPA wins (contractual obligation) |
| `plant_performance.actual_pr` | Derived (meter_aggregate + production_forecast) | Plant Performance Workbook | Derived wins (computed from raw data) |

### Formula Handling Policy

When a source cell contains a formula (e.g., Plant Performance Workbook forecast calculations, Revenue Masterfile escalation):

- **Extract the full calculation formula** — capture the symbolic formula and cell references
- **Compute with the formula** — apply the formula logic to calculate the DB value
- **Store both:**
  - Operational columns (`forecast_energy_kwh`, `base_rate`, etc.): Store the **computed numeric result**
  - Provenance metadata (`source_metadata` JSONB or `extraction_metadata` JSONB): Store the formula text + cell reference + source workbook/tab for audit trail and reproducibility

This applies specifically to: forecast energy calculations (degradation-adjusted), PR/GHI/POA formulas, tariff escalation calculations, CPI-adjusted rates.

---

## 4. Population Pipeline Overview

### 4-Stage Dependency Chain

```
STAGE A: Identity & Structure (Steps 1-3)
  [A1] organization, counterparty, legal_entity (Customer Summary)
  [A2] project (Customer Summary + dim_customer CSV)
  [A3] contract (dim_contract CSV)
  [A4] customer_contact (invoice .eml contact lists)
  [A5] Flag multi-contract/multi-customer patterns for review
         |
STAGE B: Billing Structure & Technical Baseline (Steps 4-6)
  [B1] billing_product (dim_product_code CSV)
  [B2] contract_line (dim_contract_line CSV)
  [B3] contract_billing_product (junction)
  [B4] clause_tariff placeholders
  [B5] meter (when available)
  [B6] Cross-check meter readings ↔ contract lines (asymmetric rules)
  [B7] production_forecast (Plant Performance Workbook: project tabs)
  [B8] production_guarantee (PPA terms / Plant Performance Workbook)
         |
STAGE C: Readings, Performance & Invoice Validation (Steps 7-8)
  [C1] billing_period (from meter readings date range)
  [C2] meter_aggregate (meter readings CSV + Plant Performance Workbook)
  [C3] plant_performance (derived: meter_aggregate + production_forecast)
  [C4] exchange_rate (Revenue Masterfile: Invoiced SAGE tab)
  [C5] Revenue Masterfile full extraction (10 tabs — see Step 7)
  [C6] Invoice calibration (Step 8)
         |
STAGE D: Pricing & Enrichment (Steps 9-11)
  [D1] reference_price / MRP (SAGE MRP xlsx + utility PDFs)
  [D2] tariff_rate (Revenue Masterfile: 4-currency)
  [D3] billing_tax_rule (invoice tax lines, project-scoped)
  [D4] PPA PDF parsing — clause extraction, amendment reconciliation (final)
  [D5] price_index (US CPI data from Revenue Masterfile) — BLOCKED: migration pending
  [D6] loan_schedule + loan_payment — BLOCKED: migration pending
```

### FK Dependency Order (full)

| Step | Table | Depends On | Source |
|------|-------|------------|--------|
| A1 | `organization` | -- | Seed data |
| A1 | `counterparty` | `organization` | Customer Summary + dim_customer CSV |
| A1 | `legal_entity` | `organization` | Customer Summary |
| A2 | `project` | `organization`, `legal_entity` | Customer Summary + dim_customer CSV |
| A3 | `contract` | `project`, `counterparty` | dim_contract CSV |
| A4 | `customer_contact` | `counterparty` | Invoice .eml contact lists (To/CC) |
| B1 | `billing_product` | `organization` | dim_product_code CSV |
| B2 | `contract_line` | `contract` | dim_contract_line CSV |
| B3 | `contract_billing_product` | `contract`, `billing_product` | dim_contract_line x product_code join |
| B4 | `clause_tariff` | `project`, `contract`, `currency` | Derived from contract structure |
| B5 | `meter` | `project` | When meter data available |
| B6 | -- | `contract_line`, meter readings CSV | Cross-check validation only |
| B7 | `production_forecast` | `project`, `organization` | Plant Performance Workbook (project tabs) |
| B8 | `production_guarantee` | `project`, `organization` | PPA terms / workbook |
| C1 | `billing_period` | `organization` | meter readings date range |
| C2 | `meter_aggregate` | `billing_period`, `contract_line` | meter readings CSV + Plant Performance Workbook |
| C3 | `plant_performance` | `project`, `production_forecast`, `billing_period` | Derived |
| C4 | `exchange_rate` | `organization`, `currency` | Revenue Masterfile (Invoiced SAGE tab) |
| C5 | multiple | various | Revenue Masterfile (10 tabs) |
| D1 | `reference_price` | `project`, `currency` | SAGE MRP xlsx + utility PDFs |
| D2 | `tariff_rate` | `clause_tariff`, `billing_period`, `exchange_rate` | Revenue Masterfile |
| D3 | `billing_tax_rule` | `organization` | Invoice tax lines |
| D4 | `clause` + `clause_relationship` | `contract` | PPA PDF parsing |
| D5 | `price_index` | -- | **PENDING MIGRATION** |
| D6 | `loan_schedule` + `loan_payment` | `contract` | **PENDING MIGRATION** |

---

## 5. Step-by-Step Workflow

### Step 1: Customer Summary → Projects & Counterparties (Stage A)

**Source:** Customer summary.xlsx
**Tables:** `organization`, `counterparty`, `legal_entity`, `project`, `customer_contact`

1. Extract project list from Customer summary.xlsx
2. Populate `counterparty` with customer names, country
3. Populate `project` with metadata: name, sage_id, country, currency, cod_date, installed_dc_capacity_kwp, technology
4. Populate `customer_contact` from invoice .eml contact lists (To/CC email addresses and names) — this is the primary source, not Customer Summary

### Step 2: Match & Cross-Check with SAGE CSVs (Stage A)

**Source:** dim_finance_customer.csv, dim_finance_contract.csv, dim_finance_contract_line.csv
**Tables:** `contract` (update), `project` (verify)

1. Match CUSTOMER_NUMBER from dim_finance_customer.csv to FM counterparties via alias map
2. Match CONTRACT_NUMBER from dim_finance_contract.csv → `contract.external_contract_id`
3. Populate contract details: payment_terms, effective_date, end_date, tax_rule; currency goes on `clause_tariff.currency_id` (not contract table)
4. **Flag multi-contract/multi-customer patterns** (see Section 2 rules):
   - Multiple SAGE customers → 1 FM project (e.g., XF-AB: XFAB/XFBV/XFL01/XFSS)
   - Sub-projects or phases under same SAGE ID (e.g., QMM01, KAS01) — capture as separate contract_line/billing_product/meter entries under 1 project when generation/revenue is tracked separately
   - Use Invoice as primary rule for project boundary determination; cross-check against PPW tabs
5. Only count DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=1 (both filters required for "active contract line")
6. Verify: all 32 projects resolved, 27 contracts have external_contract_id (3 PPA-only = NULL)

### Step 3: Meter Readings Cross-Check & Population (Stage B)

**Source:** dim_finance_contract_line.csv, meter readings.csv
**Tables:** `contract_line`, `meter_aggregate` (later in Step 7)

1. Populate `contract_line` from dim_finance_contract_line.csv (DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=1 for active lines; DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=0 inserted with `is_active=false`)
2. Energy category classification:

| METERED_AVAILABLE | Product Pattern | energy_category |
|-------------------|-----------------|-----------------|
| `metered` | Any | `metered` |
| `available` | Any | `available` |
| `N/A` | Matches NON_ENERGY_PATTERNS | `test` |
| `N/A` | No match | `test` (fallback) |
| empty | Any | `test` |

   Non-energy patterns: minimum offtake, bess capacity, o&m service, equipment lease, diesel, fixed monthly rental, esa lease, penalty, correction, inverter energy, early operating.

3. Cross-check meter readings ↔ contract lines:
   - **contract_line exists but no meter reading → OK** (readings populated later or non-energy line)
   - **meter reading exists but no contract_line → ERROR** (flag for correction)
4. Populate meter data for each meter type identified (metered, available, test)
5. Inactive lines (ACTIVE_STATUS=0): Insert with `is_active=false`
6. Legacy contracts (ACTIVE=0 at contract level): Exclude entirely

### Step 4: Billing Product & Tariff Structure (Stage B)

**Source:** dim_finance_product_code.csv, contract structure
**Tables:** `billing_product`, `contract_billing_product`, `clause_tariff`

1. Populate/verify `billing_product` from dim_finance_product_code.csv (already seeded in migration 034)
2. Create `contract_billing_product` junction from contract_line × billing_product join
3. Create `clause_tariff` placeholders — one per project/contract/currency:
   - Tariff type: Derived from PO Summary **Energy Sale Type (col E) + Connection (col F)** as primary source (not Project Waterfall col K which has broken `#REF!` formulas)
   - Mapping: Energy Sale Type "PPA" + Connection "Grid" → GRID; "PPA" + "Generator" → GENERATOR; "Finance Lease" → FIXED; etc.
   - `base_rate` = NULL initially (populated in Step 7/9)
   - `energy_sale_type_id` from `energy_sale_type` lookup

### Step 5: Plant Performance Workbook — Summary Tabs (Stage B)

**Source:** Operations Plant Performance Workbook.xlsx
**Tables:** `project` (verify/update), `production_forecast` (preliminary)

#### 5a. "Summary - Performance" tab

Extract per-project monthly time series for each of the following blocks. Each block repeats the project list (~30 projects, Tab ID in col E):

| Row Range | Section | Target Table/Field |
|-----------|---------|-------------------|
| 6-35 | ACTUAL INVOICED ENERGY (kWh) — Metered + Available | `meter_aggregate` / `plant_performance` validation |
| 39-68 | EXPECTED OUTPUT (kWh) — Metered + Available | `production_forecast.forecast_energy_kwh` |
| 72-101 | VARIANCE (kWh) — Energy Output | Derived (actual - expected) |
| 107-134 | ACTUAL IRRADIANCE (Wh/m2) | `meter_aggregate.actual_ghi_irradiance` validation |
| 141-168 | EXPECTED IRRADIANCE (Wh/m2) | `production_forecast.forecast_ghi_irradiance` |
| 175-202 | VARIANCE (Wh/m2) — Irradiation | Derived |
| 209+ | PLANT AVAILABILITY (%) | `plant_performance.actual_availability_pct` |
| (further) | EXPECTED PR (%) | `production_forecast.forecast_pr` |

**HYBRID PLANTS:** ERG (Molo Graphite) and UNSOS (Baidoa) are listed separately as hybrid plants in irradiance sections. If hybrid billing lines (sub-projects) are captured under the same project/SAGE ID, capture them as separate `contract_line` entries following the multi-contract rules in Section 2. Their expected output uses the hybrid-specific calculation formula (includes genset component), not the standard PV-only calculation.

#### 5b. "Project Waterfall" tab

Extract per project (one row per Tab ID):

| Column | Field | Target |
|--------|-------|--------|
| A | Tab ID (sage_id) | Join key |
| B | kWp Installed Capacity | `project.installed_dc_capacity_kwp` (overwrite if conflict) |
| C | Expected Energy (kWh) | Cross-check with forecast |
| D | Actual Energy (kWh) | Cross-check with meter_aggregate |
| J | $/kWh (tariff rate) | Cross-check with clause_tariff |
| K | Tariff type | **SKIP** — col K has broken `#REF!` formulas. Use PO Summary Energy Sale Type (col E) + Connection (col F) instead (see Step 4) |

### Step 6: Plant Performance Workbook — Project Tabs (Stage B)

**Source:** Operations Plant Performance Workbook.xlsx — ~30 per-project tabs (GBL01, KAS01, MOH01, etc.)
**Tables:** `project`, `production_forecast`, `production_guarantee`

Each project tab has a consistent structure:

#### 6a. Basic Project Details (col A, rows 2-8)

| Row | Field | Target | Conflict Rule |
|-----|-------|--------|--------------|
| 2 | Customer | `counterparty.name` | Verify match |
| 3 | Country | `project.country` | Verify match |
| 4 | COD Phase 1 | `project.cod_date` | **Flag + review** if conflict with earlier data (PPW may contain `#REF!` errors) |
| 5 | COD Phase 2 | Phase 2 handling (see note) | Store in `project.technical_specs` |
| 6 | Term (Yrs) | `contract.contract_term_years` | Verify match |
| 7 | Project ID | Cross-check only | e.g., "GH 22010" |
| 8 | Sage ID | `project.sage_id` | Must match exactly |

#### 6b. Fixed Parameters (col F-H, rows 3-5)

| Row | Field | Target |
|-----|-------|--------|
| 3 | Installed Capacity (kWp) | `project.installed_dc_capacity_kwp` — per phase |
| 4 | Annual Specific Yield (kWh/kWp) | `production_forecast.source_metadata` |
| 5 | Annual Degradation | `production_forecast.degradation_factor` |

#### 6c. Monthly Allocation (col F-J, rows 8-20)

12 rows (Jan-Dec), per phase:

| Column | Field | Target |
|--------|-------|--------|
| G | GHI IRR (Wh/m2) | `production_forecast.forecast_ghi_irradiance` (monthly basis) |
| H | POA IRR (Wh/m2) | `production_forecast.forecast_poa_irradiance` |
| I | Energy (%) | Monthly energy allocation fraction — used in forecast formula |
| J | PR (%) | Baseline PR for the month |

Store allocation percentages in `production_forecast.source_metadata` JSONB.

#### 6d. Technical Model — Forecast per Operating Year (row 22+)

Headers at row 23: Date, Year, Month, OY, Forecast Energy Phase 1 (kWh), Forecast Energy Phase 2 (kWh), Forecast Combined Phase 1 + Phase 2 (kWh), GHI Irr Phase 1, GHI Irr Phase 2, POA Irr Phase 1, POA Irr Phase 2, PR GHI %, PR POA %

Monthly rows organized by Operating Year (OY 1, OY 2, ... up to contract term):

| Column | Field | Target |
|--------|-------|--------|
| E | Operating Year (OY) | `production_forecast.operating_year` |
| F | Forecast Energy Phase 1 (kWh) | `production_forecast.forecast_energy_kwh` (phase 1) |
| G | Forecast Energy Phase 2 (kWh) | `production_forecast.forecast_energy_kwh` (phase 2) |
| H | Forecast Combined (kWh) | `production_forecast.forecast_energy_kwh` (combined) |
| I-J | GHI Irr Phase 1/2 (Wh/m2) | `production_forecast.forecast_ghi_irradiance` |
| K-L | POA Irr Phase 1/2 (Wh/m2) | `production_forecast.forecast_poa_irradiance` |
| M | PR GHI % | `production_forecast.source_metadata.pr_ghi_pct` |
| N | PR POA % | `production_forecast.source_metadata.pr_poa_pct` |

**Formula extraction:** Extract the full calculation formula for Forecast Energy (e.g., `= installed_capacity * annual_specific_yield * monthly_energy_pct * (1 - degradation)^(OY-1)`). Store formula in `production_forecast.source_metadata.formula`. Compute and store the result in `production_forecast.forecast_energy_kwh`.

#### 6e. Actual Data (col O+)

Headers at row 23: Phase-1 Meter Opening, Phase-1 Meter Closing, Phase-1 Invoiced Energy, Phase-2 equivalents, etc.

Extract actual meter readings and invoiced energy per month per phase. Cross-check against `meter_aggregate` data from CSV.

#### 6f. Required Energy Output per Operating Year

Extract annual required energy output → `production_guarantee.guaranteed_kwh` per operating year. Cross-check against PPA terms.

### Step 7: Revenue Masterfile — Full Extraction (Stage C)

**Source:** CBE Asset Management Operating Revenue Masterfile - new.xlsb (10 tabs)
**Tables:** Multiple (see per-tab details)

#### 7a. "Reporting Graphs" tab

| Column | Field | Target |
|--------|-------|--------|
| D (col 4) | Industry | `counterparty.industry` (e.g., "Real Estate", "Telecom", "Mining") |

Cross-check project list against FM projects.

#### 7b. "PO Summary" tab

One row per project (some projects have Phase 1/Phase 2 as separate rows). Headers at row 4:

**Identity & verification fields (verify against earlier data, flag conflicts):**

| Column | Field | Target | Action |
|--------|-------|--------|--------|
| A (1) | Name | Cross-check | Verify |
| B (2) | Country | `project.country` | Verify |
| C (3) | Customer | `counterparty.name` | Verify |
| H (8) | COD | `project.cod_date` | **Flag if conflict** with PPW data |
| I (9) | Term | `contract.contract_term_years` | **Flag if conflict** |
| J (10) | COD End | `contract.end_date` | **Flag if conflict** |
| P (16) | Annual Specific Yield (kWh/kWp) | `production_forecast.source_metadata` | **Flag if conflict** with PPW |
| Q (17) | Annual Production (kWh) | `production_forecast` totals | **Flag if conflict** with PPW |
| R (18) | Degradation (%) | `production_forecast.degradation_factor` | **Flag if conflict** with PPW |

**New fields to extract and store:**

| Column | Field | Target |
|--------|-------|--------|
| D (4) | Revenue Type | `project.technical_specs.revenue_type` — e.g., "Loan - repayment based on Energy Output" |
| E (5) | Energy Sale Type | `clause_tariff.energy_sale_type_id` — e.g., "Finance Lease", "PPA" |
| F (6) | Connection | `project.technical_specs.connection` — e.g., "Grid", "Off-Grid", "Generator" |
| G (7) | CAPEX | `project.technical_specs.capex_usd` |
| L (12) | PV kWp | `project.installed_dc_capacity_kwp` (verify) |
| M (13) | BESS kWh | `project.technical_specs.bess_kwh` |
| N (14) | Thermal kWe | `project.technical_specs.thermal_kwe` |
| O (15) | Wind MW | `project.technical_specs.wind_mw` |
| T (20) | Tariff Currency | `clause_tariff.currency_id` |

**Tariff fields:**

| Column | Field | Target |
|--------|-------|--------|
| U (21) | Fixed Tariff | `clause_tariff.base_rate` (for FIXED type) |
| V (22) | Grid MRP | `reference_price` cross-check |
| W (23) | Grid Discount (%) | `clause_tariff.discount_percentage` (GRID type) |
| X (24) | Grid Solar Tariff | `clause_tariff.base_rate` (GRID type, computed) |
| Y (25) | Generator MRP | `reference_price` cross-check |
| Z (26) | Generator Discount (%) | `clause_tariff.discount_percentage` (GENERATOR type) |
| AA (27) | Generator Solar Tariff | `clause_tariff.base_rate` (GENERATOR type, computed) |
| AB (28) | Min Tariff (Floor) | `clause_tariff.floor_rate` |
| AC (29) | Max Tariff (Ceiling) | `clause_tariff.ceiling_rate` |

**Indexation fields:**

| Column | Field | Target | Notes |
|--------|-------|--------|-------|
| AD (30) | Indexation Rate/Method | `clause_tariff.escalation_type` | e.g., "US CPI". **Check col AD notation** to determine indexation method per project. |
| AE (31) | 1st Indexation Date | `clause_tariff.logic_parameters.first_indexation_date` | Date (stored as serial number, convert) |
| AF (32) | Comments | `clause_tariff.logic_parameters.indexation_context` | **CRITICAL: Check both col AD notation AND AF comments** to determine if indexation applies to fixed tariff, floor rate, ceiling rate, or combination. Parse per-project. e.g., GC01: "Linked to 1st day of month of Interconnection Date Anniversary" |

**Loan & charge fields:**

| Column | Field | Target |
|--------|-------|--------|
| AG (33) | Loan Fixed Payment | `project.technical_specs.loan_fixed_payment` or `loan_schedule` (PENDING) |
| AH (34) | Lease Rental | `project.technical_specs.lease_rental` |
| AI (35) | Energy Fee | `project.technical_specs.energy_fee` |
| AJ (36) | BESS Charge | `project.technical_specs.bess_charge` |
| AK (37) | O&M Fee | `project.technical_specs.om_fee` |
| AL (38) | Indexation (charges) | `project.technical_specs.charge_indexation` |
| AM (39) | Comments | `project.technical_specs.charge_comments` — **read and note context** |
| AN (40) | OY Definition | `project.technical_specs.oy_definition` — **read and note context** (e.g., "Tariff shall be adjusted by the US CPI on the 1st day of the month in which the Interconnection Date occurred...") |

**Phase 1/Phase 2 handling:** Projects with multiple phases appear as separate rows under the same SAGE ID. Each phase may have different kWp, COD, forecast, and sometimes different tariff parameters. Flag phase boundaries and handle separately.

> **Schema limitation:** `production_forecast` has a UNIQUE constraint on `(project_id, forecast_month)`, so per-phase forecasts cannot be stored as separate rows. Store the combined (total) kWh in the `forecast_energy_kwh` column. Store per-phase breakdown (Phase 1 kWh, Phase 2 kWh, individual PR/irradiance) in `source_metadata` JSONB. See Q3 in Section 9.4.

#### 7c. "Invoiced SAGE" tab — Historic Exchange Rates

| Row | Currency | Target |
|-----|----------|--------|
| 62 | GHS closing spot (monthly) | `exchange_rate` table (GHS/USD) |
| 63 | KES closing spot (monthly) | `exchange_rate` table (KES/USD) |
| 64 | NGN closing spot (monthly) | `exchange_rate` table (NGN/USD) |
| 66+ | GHS average rate (annual) | `exchange_rate` table (average variant) |

Monthly columns correspond to billing periods. Populate `exchange_rate` table with `currency_id`, `rate`, `rate_date`. Convention: rate = units of currency_id per 1 USD. UNIQUE key is `(organization_id, currency_id, rate_date)`.

#### 7d. "Energy Sales" tab

| Row | Field | Target |
|-----|-------|--------|
| 3 | Annual Degradation Factor (per project) | Cross-check against PPW and PO Summary degradation. **Flag if conflict.** |
| 4+ | Production Forecast per OY per month (kWh) | Cross-check against PPW forecast. **Flag if >5% variance.** |

Projects are arranged in column groups. Each group has: OY, PPA Energy (kWh). Monthly rows with dates.

#### 7e. "Loans" tab

Loan repayment schedules with columns: Month, Principal, Interest, Payment, Closing Balance, Date Paid, Difference, Comments.

| Loan | Columns | Project |
|------|---------|---------|
| Zoodlabs Loan Schedule 1 | 1-9 | ZL01/ZL02 |
| Zoodlabs ESA Loan | 11-16 | ZL01 |
| iSAT Loan | 18-24 | TBC (iSAT) |
| Garden City Interest | 26+ | GC01 |

**Minimum extraction schema for loan/rental data:**

| Field | Type | Source Column |
|-------|------|-------------|
| `principal` | DECIMAL | "Principle" column |
| `interest` | DECIMAL | "Interest" column |
| `due_date` | DATE | "Month" column (serial → date) |
| `period` | INTEGER | Row sequence (1-based) |
| `currency` | VARCHAR | From `clause_tariff.currency_id` (contract's tariff currency) |
| `status` | VARCHAR | Derived: paid/pending/overdue (from "Date Paid" + "Difference") |
| `source_doc_ref` | VARCHAR | Tab name + row reference |
| `invoice_line_linkage` | VARCHAR | Link to matching invoice line item (from Step 8 calibration) |

→ `loan_schedule` + `loan_payment` tables (**PENDING MIGRATION** — use this minimum schema as design input)
→ Interim: Store in `project.technical_specs.loan_schedule` JSONB with above fields

#### 7f. "Rental and Ancillary" tab

Monthly charges per project, per operating year:

| Project ID | Charge Type | Column |
|------------|-------------|--------|
| KE 22013 (LOI01) | BESS Charge | 5 |
| KE 22469 (AR01) | Rental Fee | 8 |
| MG 22017 (QMM01) | BESS Charge | 11 |
| MZ 22003 (TWG01) | Rental Fee + O&M Fee | 14-15 |
| Ampersand | BESS Charge | 18 |
| Zoodlabs | Rental Fee | 21 |

→ Interim: Store in `project.technical_specs.rental_schedule` JSONB using minimum schema: amount, due_date, period, currency, status, source_doc_ref, invoice_line_linkage
→ Link rental line items to matching invoice lines during Step 8 calibration

#### 7g. "US CPI" tab

Source: BLS CUUR0000SA0 series (All items, U.S. city average, not seasonally adjusted, 1982-84=100).
Data range: 2010-2020+.

→ `price_index` table (**PENDING MIGRATION**)
→ Interim: Store in a staging JSON file for when migration is created
→ Needed for: LOI01 (IND_USE_CPI=1), GC01 ("US CPI" indexation), any CPI-linked escalation projects

### Step 8: Invoice Calibration & Tax Rule Extraction (Stage C)

**Source:** Invoice samples/ (PDF + .eml)
**Purpose:** Two-phase step:
- **Phase A — Extract & Populate:** Extract tax/levy/WHT formulas from invoices and populate `billing_tax_rule` per country and per project (where rates differ).
- **Phase B — Validate:** Compare all extracted invoice values against DB state.

**Tables (writes):** `billing_tax_rule`
**Prerequisite migration:** Add nullable `project_id` column to `billing_tax_rule` (resolves Section 9.3 decision → Option A).

#### Phase A: Tax Rule Extraction

For each parsed invoice, extract the tax/levy structure:
- Tax types: VAT, WHT, WHVAT, NHIL, GETFUND, COVID Levy, eTIMS levies, etc.
- Per-tax: rate (%), base amount it applies to, computed amount
- Derive the formula: which taxes apply to energy subtotal vs subtotal-after-levies

Population logic:
1. Group extracted tax structures by country_code
2. For each country with no existing `billing_tax_rule`, INSERT a country-default rule
3. For projects where WHT or other rates differ from the country default (e.g., Ghana KAS01=7.5% vs MOH01=3.0%), INSERT a project-specific override row with `project_id` set
4. Country-default rows have `project_id = NULL`; project-specific overrides have `project_id` set
5. Billing engine resolution order: project-specific rule (if exists) → country default

Countries needing rules (from invoice samples):
- **KE** (Kenya): ~14 invoices — USD-denominated, eTIMS compliance, WHT + VAT
- **GH** (Ghana): ~5 invoices — GHS, NHIL/GETFUND/COVID/VAT/WHT/WHVAT (already has 1 country rule, but needs project-specific WHT overrides)
- **NG** (Nigeria): invoices if available — NGN, WHT + VAT
- **MG** (Madagascar): ERG invoice — MGA
- **SL** (Sierra Leone): MIR01, ZL02 — SLE/USD
- **EG** (Egypt): IVL01 — USD
- **ZW** (Zimbabwe): CAL01 — USD
- **MZ** (Mozambique): TWG01 — MZN (no invoice sample)

#### Phase B: Validation Checks

1. Invoice line items map to known `billing_product` / `contract_line` — if not, flag
2. Line item quantities match `meter_aggregate` for that period
3. Currency matches `clause_tariff.currency_id` for the relevant contract
4. Tax rates/levies match `billing_tax_rule` for that project — especially WHT (project-specific)
5. FX rate on invoice matches `exchange_rate` for that period
6. Tariff box parameters (MRP, discount %, floor, ceiling) match `reference_price` / `clause_tariff`
7. Loan/rental/charge line items match loan schedule / rental schedule data from Revenue Masterfile
8. Invoice total reconciles with sum of line items + taxes

**Output:** Discrepancy records (see Section 7) + populated `billing_tax_rule` rows.
**Rule:** Invoice-only anomalies do NOT auto-overwrite structured data (except `billing_tax_rule` which invoices are the authoritative source for).

### Step 9: MRP Data Population (Stage D) — COMPLETE

**Source:** MRP/Sage Contract Extracts market Ref pricing data.xlsx
**Tables:** `clause_tariff`, `reference_price`, `meter_aggregate`
**Script:** `python-backend/scripts/step9_mrp_and_meter_population.py`
**Report:** `python-backend/reports/cbe-population/step9_2026-03-09.json`
**Run date:** 2026-03-09

Three phases run sequentially:

**Phase A — Meter Readings CSV → meter_aggregate (COMPLETE)**
- Source: `CBE_data_extracts/Data Extracts/FrontierMind Extracts_meter readings.csv` (604 rows)
- Inserted **600 rows** across **28 projects** (99.5% FK resolution)
- 3 unresolved: CAL01 contract lines not in DB (external_line_id mismatch)
- Routing: `energy_category = 'metered'` → `total_production`, `'available'` → `available_energy_kwh`
- `total_production = utilized_reading - discount_reading - sourced_energy`
- Dedup: `ON CONFLICT DO NOTHING` (no prior meter_aggregate data)

**Phase B — MRP Formula OCR + Monthly Data (COMPLETE)**
- Sub-phase B1: Extracted **60+ embedded images** from 9 project tabs, OCR'd via Claude vision (claude-sonnet-4-20250514)
  - OCR results cached in `reports/cbe-population/step9_ocr_cache/{sha256}.json`
  - Formula images saved in `reports/cbe-population/step9_mrp_images/{sage_id}_{idx}.png`
- Sub-phase B2: Updated **7 clause_tariff rows** with `mrp_method` + `market_ref_currency_id` (UTK01, UGL01, TBM01, GBL01, JAB01, NBL01, NBL02). KAS01+MOH01 already populated — cross-validated, no discrepancies.
- Sub-phase B3: Inserted **287 new reference_price rows** (353 total across 9 projects)
  - Dual-section handling: GBL01/JAB01 have Grid+Generator side-by-side columns; grid MRP is primary, generator stored in source_metadata
  - MOH01 has 4 parallel billing entity sections — deduped by project+period

| Project | mrp_method | MRP Currency | Monthly Observations |
|---------|-----------|-------------|---------------------|
| KAS01 | utility_variable_charges_tou | GHS | 51 (pre-existing) |
| MOH01 | utility_variable_charges_tou | GHS | 18 |
| UTK01 | utility_total_charges | KES | 46 |
| UGL01 | utility_total_charges | GHS | 60 |
| TBM01 | utility_variable_charges_tou | KES | 36 |
| GBL01 | utility_variable_charges_tou | GHS | 24 |
| JAB01 | blended_grid_generator | NGN | 45 |
| NBL01 | utility_variable_charges_tou | NGN | 49 |
| NBL02 | generator_cost | NGN | 24 |

**Phase C — Plant Performance Enrichment (COMPLETE — partial Step 10)**
- Computed `energy_comparison` from `meter_aggregate` + `production_forecast`
- **292 rows inserted**, **13 rows updated** across **28 projects**
- `irr_comparison` and `pr_comparison` remain NULL — require irradiance data not in CSV (see Section 9.10)

### Step 10: Plant Performance Workbook — Actual Comparisons (Stage D) — PARTIALLY COMPLETE

**Source:** Operations Plant Performance Workbook.xlsx — each project tab
**Tables:** `plant_performance`

**Completed (via Step 9 Phase C):**
- `energy_comparison` = actual metered kWh / forecast kWh — populated for 305 project-months

**Remaining (irradiance-dependent):**
- `irr_comparison` = actual GHI / forecast GHI — requires GHI irradiance from PPW project tabs or meter_aggregate.ghi_irradiance_wm2
- `pr_comparison` = actual PR / forecast PR — requires actual_pr computation (needs GHI + capacity)
- `actual_pr` = total_energy × 1000 / (actual_ghi × capacity) — blocked on irradiance data

**Next step:** Import irradiance data from Plant Performance Workbook project tabs into `meter_aggregate.ghi_irradiance_wm2`, then recompute `irr_comparison`, `pr_comparison`, and `actual_pr`.

Import endpoint: `POST /api/projects/{project_id}/plant-performance/import`

### Step 11: Contract Digitization — PPA Parsing (Stage D, Final)

**Source:** Customer Offtake Agreements/*.pdf
**Tables:** `clause`, `clause_relationship`, `clause_tariff` (update base_rate), `contract` (update metadata)

1. Identify the **entire contract history** per project: original SSA/PPA/ESA + all amendments
2. Parse each document: LlamaParse OCR → Presidio PII → Claude extraction → DB storage
3. Combined PDF detection: If multiple logical documents found in one PDF, prompt user before proceeding
4. **Compare updates on key terms** across amendments:
   - Track which clauses are superseded (`supersedes_clause_id`, `is_current` flags)
   - Identify changes in: tariff rates, escalation terms, term length, capacity, penalties
   - Store amendment timeline in `contract.extraction_metadata`
5. Only promote parsed values to operational columns where structured sources are absent or clearly wrong
6. Update `clause_tariff.base_rate` from PRICING clauses (for Year 1 / contractual base rate)
7. Update `production_guarantee` if contractual guaranteed kWh found in PPA

---

## 6. Pipeline by Project Type

### Type A: Full Pipeline (CSV + PPA)

Projects with contract lines, meter readings, AND PPA documents.
**Pipeline:** Steps 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

Projects: KAS01, NBL01, LOI01, CAL01, ERG, GBL01, GC01, IVL01, JAB01, MB01, MF01, MIR01, MP01, MP02, NBL02, NC02, NC03, QMM01, TBM01, UGL01, UNSOS, UTK01, XF-AB

### Type B: PPA-Only

Projects with PPA documents but no/minimal CBE structured data.
**Pipeline:** Steps 1 → 2 (partial) → 7 (where available) → 11 → Manual contract_line creation

Projects: ABI01, AR01, BNT01, ZO01

### Type C: CSV-Only

Projects with CBE data but no PPA documents.
**Pipeline:** Steps 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 (skip Step 11)

Projects: AMP01, TWG01, ZL02

### Type D: No Data

No source documents available.
**Pipeline:** Manual data entry required.

Projects: TBC

---

## 7. Discrepancy Tracking

Every discrepancy found during ingestion is recorded with this schema:

| Field | Type | Description |
|-------|------|-------------|
| `severity` | `critical` / `warning` / `info` | Critical = blocks billing; Warning = needs review; Info = cosmetic |
| `category` | `alias_mismatch` / `fk_resolution` / `value_conflict` / `missing_data` / `duplicate` / `formula_error` | Classification |
| `project` | VARCHAR | FM sage_id |
| `step` | 1-11 | Which workflow step detected it |
| `field` | VARCHAR | DB field name (e.g., `clause_tariff.currency_id`) |
| `source_a` | VARCHAR | First source value + source name |
| `source_b` | VARCHAR | Second source value + source name (if conflict) |
| `recommended_action` | VARCHAR | Per field authority matrix |
| `status` | `open` / `resolved` / `accepted` | Tracking |

Output: One versioned file per batch run (`discrepancies_YYYY-MM-DD.csv`) or persisted to a DB table when volume warrants.

### Source Priority (when field authority matrix has no specific entry)

1. Plant Performance Workbook project tabs (detailed technical model) — highest for technical/forecast fields
2. Snowflake CSV extracts (structured, SCD2-versioned) — highest for financial/contract fields
3. Revenue Masterfile (semi-structured, multi-tab) — high for tariff/pricing fields
4. SAGE MRP workbook (reconciled to ERP) — high for MRP fields
5. Invoice PDFs (operational output, monthly) — calibration only
6. PPA/SSA PDFs (legal, but parsed with OCR uncertainty) — lowest for operational fields; highest for legal/clause fields

---

## 8. Migration & Idempotency Pattern

Follow the pattern established in migrations 046-049:

```sql
-- 1. CTE with source data tuples
WITH source_data(sage_id, ...) AS (VALUES
    ('KAS01', ...),
    ('NBL01', ...)
)
-- 2. Join to project/contract via sage_id (not hardcoded IDs)
INSERT INTO contract_line (...)
SELECT c.id, v.line_num, ...
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN source_data v
WHERE p.sage_id = v.sage_id
  AND c.external_contract_id = v.ext_contract_id
-- 3. Idempotent via ON CONFLICT
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- 4. Post-load assertions
DO $$ ... RAISE EXCEPTION IF count < expected ... $$;
```

### Conflict Keys per Table

| Table | Conflict Key | ON CONFLICT Action |
|-------|-------------|-------------------|
| `project` | `(organization_id, sage_id)` | DO UPDATE (name, metadata) |
| `counterparty` | `(organization_id, name)` | DO NOTHING |
| `contract` | `(project_id, external_contract_id)` | DO UPDATE (payment_terms, end_date) |
| `contract_line` | `(contract_id, contract_line_number)` | DO NOTHING |
| `clause_tariff` | `(project_id, contract_id, currency_id)` | DO UPDATE (rates when non-NULL) |
| `meter_aggregate` | `(billing_period_id, contract_line_id)` | DO UPDATE (readings) |
| `billing_product` | `(code, organization_id)` | DO NOTHING |
| `reference_price` | `(project_id, observation_date, currency_id)` | DO UPDATE (price_per_kwh) |
| `tariff_rate` | `(clause_tariff_id, billing_period_id)` | DO UPDATE (rate columns) |
| `billing_tax_rule` | GiST exclusion on `(org, country, daterange)` | Manual review |
| `production_forecast` | `(project_id, forecast_month)` | DO UPDATE (energy, irradiance, PR) |
| `production_guarantee` | `(project_id, operating_year)` | DO UPDATE (guaranteed_kwh, pct) |
| `plant_performance` | `(project_id, billing_month)` | DO UPDATE (derived metrics) |
| `exchange_rate` | `(organization_id, currency_id, rate_date)` | DO UPDATE (rate) |
| `customer_contact` | `(counterparty_id, email)` | DO UPDATE (name, role) |

---

## 9. Remaining Gaps & Open Questions

### 9.1 Pending Migrations (Blockers)

| Table | Blocks | Data Source | Interim Storage |
|-------|--------|-------------|-----------------|
| `price_index` | CPI/indexation (US CPI tab, LOI01/GC01 CPI-linked escalation) | Revenue Masterfile "US CPI" tab (BLS CUUR0000SA0) | Staging JSON file |
| `loan_schedule` | Loan amortization persistence | Revenue Masterfile "Loans" tab + Loans and Rentals schedule.xlsx | `project.technical_specs.loan_schedule` JSONB |
| `loan_payment` | Loan repayment tracking | Repayment notices (GC01, ZL01, ZL02, iSAT) | `project.technical_specs` JSONB |

### 9.2 Schema Gaps for Revenue Masterfile Fields

The following PO Summary fields have **no dedicated DB column** — currently stored in `project.technical_specs` JSONB:

| Field | PO Summary Column | Current Storage | Needs Column? |
|-------|-------------------|-----------------|---------------|
| Revenue Type | D (4) | `project.technical_specs.revenue_type` | TBD |
| Connection | F (6) | `project.technical_specs.connection` | TBD |
| CAPEX | G (7) | `project.technical_specs.capex_usd` | TBD |
| BESS kWh | M (13) | `project.technical_specs.bess_kwh` | TBD |
| Thermal kWe | N (14) | `project.technical_specs.thermal_kwe` | TBD |
| Wind MW | O (15) | `project.technical_specs.wind_mw` | TBD |
| Loan Fixed Payment | AG (33) | `project.technical_specs.loan_fixed_payment` | Blocked by `loan_schedule` migration |
| Lease Rental | AH (34) | `project.technical_specs.lease_rental` | TBD |
| Energy Fee | AI (35) | `project.technical_specs.energy_fee` | TBD |
| BESS Charge | AJ (36) | `project.technical_specs.bess_charge` | TBD |
| O&M Fee | AK (37) | `project.technical_specs.om_fee` | TBD |
| OY Definition | AN (40) | `project.technical_specs.oy_definition` | TBD |

Decision needed: Keep in JSONB or promote to first-class columns?

### 9.3 billing_tax_rule Project-Scoping Issue — RESOLVED

**Decision:** Option A — Add nullable `project_id` column to `billing_tax_rule`.

- `project_id = NULL` → country-level default rule
- `project_id = <id>` → project-specific override (e.g., Ghana KAS01 WHT=7.5% vs country default WHT=3.0%)
- Billing engine resolution: project-specific rule (if exists) → country default
- Migration: `056_billing_tax_rule_project_scope.sql` — adds `project_id BIGINT REFERENCES project(id)`, updates GiST exclusion constraint to include `project_id`
- Populated during Step 8 (Invoice Calibration) from extracted invoice tax structures

### 9.4 Resolved Decisions (from Q&A 2026-03-07)

| # | Decision | Resolution |
|---|----------|------------|
| Q1 | **Multi-contract/multi-customer boundary** | If Invoice AND PPW tabs are separate → separate FM projects. If billed together + same PPW tab → 1 FM project with separate contract_line/billing_product/meter entries. XF-AB (4 invoices + 4 PPW tabs) needs migration to split into 4 projects. Align with /Data Extracts CSVs; flag discrepancies for manual review. |
| Q2 | **Tariff type source** | Use PO Summary Energy Sale Type (col E) + Connection (col F) as primary. Project Waterfall col K is broken (`#REF!`) — skip it. |
| Q3 | **Phase 1/Phase 2 forecast storage** | Capture phases as separate `contract_line`/`billing_product`/`meter` entries where generation is tracked separately. For `production_forecast` (UNIQUE on project_id+forecast_month), store combined kWh in operational column and per-phase breakdown in `source_metadata` JSONB. Aggregate at whole project level. |
| Q4 | **Hybrid plant handling** | Follow same rule as Q1. If hybrid billing lines are under same project/SAGE ID, capture as separate `contract_line` entries. Use hybrid-specific formula for expected output (not PV-only). |
| Q5 | **Indexation context** | Check PO Summary col AD notation AND col AF comments per project to determine what indexation applies to (fixed tariff, floor, ceiling, or combination). Parse per-project — not a blanket rule. |
| Q6 | **Loan/rental extraction schema** | Minimum fields: principal, interest, due_date, period, currency, status, source_doc_ref, invoice_line_linkage. Use as design input for `loan_schedule` migration. Interim: store in `project.technical_specs` JSONB with these fields. |
| Q7 | **Contract currency canonical location** | There is no `contract_currency` column on the `contract` table. Currency is stored on `clause_tariff.currency_id`. The 4-currency system (hard/local/billing/contract) in `tariff_rate` + `exchange_rate` derives from this. |
| Q8 | **customer_contact source** | Primary source is invoice .eml contact lists (To/CC email addresses and names), NOT Customer Summary. |
| Q9 | **Active contract line definition** | Both filters required: DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=1 for "active" lines. DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=0 → insert with `is_active=false`. |

### 9.5 Coverage Asymmetry — UPDATED 2026-03-09

- **MRP utility PDFs:** Only JAB01 has deep per-month utility coverage. Other projects rely on workbook-level MRP data only. **All 9 MRP projects now have monthly observations from SAGE xlsx (Step 9 Phase B).**
- **AM Onboarding Template:** MOH01-specific. Do not assume similar template coverage portfolio-wide.
- **Invoice samples:** ~26 of 32 projects covered. BNT01, TBC, ZO01 have no invoice samples.
- **PVSyst reports:** Not directly available as source files. Forecast data comes from Plant Performance Workbook project tabs (which embed PVSyst output).

### 9.6 Mother Line Decomposition

10/11 mother lines from pilot have no metered children yet. Child decomposition (per-meter available lines) required for metered billing accuracy. KAS01 line 2000 (Available Energy Combined) is a candidate.

### 9.7 Amendment Parsing

Only base SSAs parsed so far. Amendments need clause versioning logic (`supersedes_clause_id`, `is_current` flags) before parsing. Affects NBL01 (4 amendments), LOI01 (1 amendment), KAS01 (3 amendments).

### 9.8 LlamaParse Reliability

504 outages blocked 2/3 pilot docs (NBL01, LOI01). Consider fallback OCR for production resilience.

### 9.9 JSON Truncation in Large Contracts

Sonnet 4.5 max output ~16K tokens. Contracts with 130+ clauses may truncate. Repair logic recovers most but tail clauses may be lost.

### 9.10 Plant Performance Workbook → meter_aggregate Enrichment — PARTIALLY RESOLVED

The Plant Performance Workbook contains actual GHI irradiance and available energy data not present in meter readings CSV. Import endpoint must run after meter_aggregate base load (Step 3) to avoid overwriting CSV-sourced readings.

**Status (2026-03-09):**
- `meter_aggregate` base load COMPLETE (600 rows from CSV, Step 9 Phase A)
- `energy_comparison` computed from meter_aggregate + production_forecast (Step 9 Phase C)
- **Still needed:** GHI irradiance import from PPW project tabs → `meter_aggregate.ghi_irradiance_wm2` / `poa_irradiance_wm2`
- Once irradiance is populated: `actual_pr`, `irr_comparison`, `pr_comparison` can be computed in `plant_performance`

---

## 10. Validation Gates per Stage

### Stage A Gate (after Steps 1-2)

- [ ] All 32 projects have `sage_id` set
- [ ] All active dim_contract rows resolve to a FM project (alias map applied)
- [ ] 27+ contracts have non-NULL `external_contract_id`, `payment_terms`, `end_date`
- [ ] 0 unresolved alias joins
- [ ] Multi-contract/multi-customer patterns flagged and documented

### Stage B Gate (after Steps 3-6)

- [ ] Every active contract_line resolves to an existing contract
- [ ] No meter reading references an unmapped contract_line (zero errors)
- [ ] Contract_line without meter reading — documented as expected gap
- [ ] billing_product coverage: all PRODUCT_CODE values from CSV have a billing_product row
- [ ] contract_line count matches dim_contract_line CSV (DIM_CURRENT_RECORD=1) per project
- [ ] production_forecast populated for all projects with Plant Performance Workbook tabs
- [ ] Formula extraction verified: forecast formula text stored in source_metadata

### Stage C Gate (after Steps 7-8)

- [ ] All meter reading rows resolve to an existing contract_line (via external_line_id)
- [ ] meter_aggregate count matches meter readings CSV row count per project
- [ ] Invoice line items map to known product/line IDs (unmapped flagged)
- [ ] exchange_rate populated for all 6 portfolio currencies (GHS, KES, NGN, RWF, SLE, USD) from Revenue Masterfile
- [ ] Revenue Masterfile PO Summary crosschecked: COD/Term/Degradation/Yield conflicts flagged
- [ ] US CPI data extracted and staged (pending price_index migration)

### Stage D Gate (after Steps 9-11)

- [x] Tariff fields populated for all in-scope projects *(9/9 MRP tariffs have mrp_method + market_ref_currency_id)*
- [x] MRP observations exist for projects with GRID/GENERATOR tariff types *(353 rows across 9 projects)*
- [x] billing_tax_rule exists for each project (project-scoped where applicable) *(Step 8)*
- [x] meter_aggregate populated from CSV *(600 rows, 28 projects — Step 9 Phase A)*
- [x] energy_comparison computed in plant_performance *(305 project-months — Step 9 Phase C)*
- [ ] irr_comparison + pr_comparison computed *(blocked: needs GHI irradiance from PPW project tabs)*
- [ ] tariff_rate rows exist for each clause_tariff × billing_period
- [ ] PPA parsing_status = `completed` or `not_applicable` for all projects
- [ ] Contract amendment history documented per project
- [ ] All unresolved conflicts listed in discrepancy log

---

## 11. Evaluation Checkpoints

Run after each stage completion:

```bash
cd python-backend
DATABASE_URL=$DATABASE_URL pytest evals/ -m eval -v
```

| Scorecard | What It Checks | Target |
|-----------|---------------|--------|
| Scorecard 2 (Mapping Integrity) | contract_line coverage | 100% after Stage B |
| Scorecard 3 (Ingestion Fidelity) | Completeness + classification accuracy | Per-batch complete |
| Scorecard 4 (Billing Readiness) | Contract line + meter FK + tariff | All Type A projects after Stage D |

---

## 12. Pilot Project Details

### KAS01 — Kasapreko (Ghana, GHS) — PILOT COMPLETE

- **Contract:** CONGHA00-2021-00002
- **Active lines:** 1000 (Metered Phase 1), 2000 (Available Combined), 4000 (Metered Phase 2)
- **Inactive lines:** 3000 (Inverter Energy Phase 2, ACTIVE_STATUS=0)
- **Meter readings:** 36 (Jan-Dec 2025, lines 1000/2000/4000)
- **PPA docs:** SSA Amendment + 3 amendments (2019-2021)
- **Tariff:** GRID type, discount 19.2%, MRP 1.5540 GHS/kWh, floor 0.0989 USD/kWh
- **Invoice:** WHT 7.5%, NHIL 2.5%, GETFUND 2.5%, COVID 1%, VAT 15%
- **PPW:** Phase 1 COD 2018-10-17, Phase 2 COD 2024-05-03, kWp 400.44 (P1) + 904.8 (P2), 18-year term
- **PPA parsing:** COMPLETE (140 clauses, 13/13 categories, base_rate=0.6672 GHS/kWh)

### NBL01 — Nigerian Breweries Ibadan (Nigeria, NGN) — PILOT (PPA ON HOLD)

- **Contract:** CONNIG00-2021-00002
- **Active lines:** 6000 (Generator Metered P1), 7000 (Generator Available P1), 10000 (Generator Metered P2)
- **Inactive lines:** 1000, 3000, 4000, 5000 (legacy grid), 9000 (Early Operating)
- **Meter readings:** 34 (Jan-Dec 2025, lines 6000/7000/10000)
- **Tariff:** GENERATOR type, diesel discount 23.2%, Generator Ref Price 304.8760 NGN/kWh
- **Invoice:** VAT 7.5%, WHT 2%
- **PPA parsing:** FAILED (LlamaParse 504). Retry pending.

### LOI01 — Loisaba (Kenya, USD) — PILOT (PPA ON HOLD)

- **Contract:** CONKEN00-2021-00002 (active) + CONCBEH0-2021-00002 (legacy, inactive)
- **Active lines:** 1000 (HQ Metered), 2000 (Camp Metered), 3000 (BESS Capacity)
- **Meter readings:** 24 (Jan-Dec 2025, lines 1000/2000 only; no BESS line 3000)
- **Tariff:** FIXED solar + BESS capacity charge ($2,524.58/mo)
- **Invoice:** VAT 16%, WHT-VAT 2%, MRP 0.2433 USD/kWh
- **Note:** Uses CPI escalation (IND_USE_CPI=1); blocked by pending `price_index` migration
- **PPA parsing:** NOT STARTED (LlamaParse 504). Retry pending.

### MOH01 — Mohinani (Ghana, GHS) — ONBOARDED

- **Contract:** via AM Onboarding Template
- **Active lines:** 7 (Available + PPL1/PPL2/Bottles/BBM1/BBM2 + other)
- **Invoice:** WHT 3.0%, Grid Discount 22.0%, MRP 1.8199, Floor 0.0790, Ceiling 0.2100

---

## 13. Lessons from Pilot

### Key Decisions

1. **meter_id = NULL is acceptable** — Meters back-filled when actual meter data available. Billing resolver handles gracefully.
2. **N/A classification matters** — Non-energy products (BESS, rental, penalties) must be `test` category, not `available`.
3. **Legacy contracts excluded** — Only active contracts (ACTIVE=1) get contract lines.
4. **Inactive lines included** — ACTIVE_STATUS=0 lines inserted with `is_active=false` for historical completeness.
5. **Invoices calibrate, not dictate** — Invoice values validate structured data but do not auto-overwrite it.
6. **Tax rules are project-specific** — Do not assume uniform rates within a country.
7. **Extract formulas AND compute** — Operational columns store computed numbers; formula text and cell references go in source_metadata JSONB.
8. **Phase handling** — Phase 1/Phase 2 under same SAGE ID require separate forecast/capacity tracking but share the same contract.
9. **Invoice + PPW tab defines project boundary** — If invoice AND PPW tabs are separate, create separate FM projects. If billed together on same PPW tab, keep as 1 FM project with separate contract_line entries.
10. **Active line = both filters** — DIM_CURRENT_RECORD=1 AND ACTIVE_STATUS=1. Both required.
11. **customer_contact from .eml** — Primary source is invoice .eml To/CC lists, not Customer Summary.
12. **Loan/rental minimum schema** — principal, interest, due_date, period, currency, status, source_doc_ref, invoice_line_linkage.

### Mother Line Pattern

When a project has a site-level available line that decomposes into per-meter children:
- Mother line: `meter_id = NULL`, `parent_contract_line_id = NULL`, `external_line_id` set
- Children: `parent_contract_line_id = mother.id`, `meter_id` set when available

Established in migration 047 (MOH01).
