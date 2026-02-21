# CBE to FrontierMind Data Mapping

This document maps CBE's data architecture to FrontierMind's canonical schema. CBE is the first client adapter; the mapping demonstrates how client-specific data fits into the platform's generic tables.

Sources: Snowflake data warehouse, AM Onboarding Template, Operations Plant Performance Workbook, Operating Revenue Masterfile.

---

## Architecture Philosophy

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
|    contract, clause_tariff, meter_aggregate,          |
|    exchange_rate, invoice tables, price_index,        |
|    production_forecast, production_guarantee,         |
|    customer_contact                                   |
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

## Principles

1. **No client-specific columns on core tables** — CBE identifiers live in `source_metadata` JSONB
2. **Adapter writes, core reads** — The CBE adapter ingests data and maps to generic columns; the pricing calculator and comparison engine operate on generic columns only
3. **`tariff_group_key`** groups the same logical tariff line across time periods
4. **`total_production`** on `meter_aggregate` is the final billable quantity
5. **Tariff selection logic is generic** — FIXED/GRID/GENERATOR structures are platform-level concepts, not CBE-specific

---

## Table Mappings

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

These fields are stored in `meter_aggregate.source_metadata` JSONB, not as standalone columns. The only performance column on the table itself is `availability_percent` (migration 007).

| Workbook Column | Storage | Key / Column | Notes |
|---|---|---|---|
| Col AA "Actual GHI Irradiance" | `source_metadata` | `actual_ghi_irradiance` | kWh/m2, from vCOM/AMMP/SMA |
| (if available) | `source_metadata` | `actual_poa_irradiance` | kWh/m2, from vCOM |
| Col AB "Actual PR" | `source_metadata` | `actual_pr` | Calculated: `(total_energy * 1000) / (GHI * capacity)` |
| Col AC "Availability %" | Column | `availability_percent` | System availability from monitoring (migration 007) |
| Col AD "Capacity Factor" | `source_metadata` | `capacity_factor` | `total_energy / (capacity * days * 24)` |

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

## Data Flow

### Complete Monthly Pipeline

```
                        AM Onboarding Template (one-time at COD)
                                    |
                    Sets: tariff_structure, floor/ceiling, escalation rules,
                          meters, production guarantee, contacts
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
| 2. meter_aggregate                                                    |
|    clause_tariff_id -> tariff line                                     |
|    opening_reading = 11333714.94                                      |
|    closing_reading = 12117657.60                                      |
|    utilized_reading = 783942.656                                      |
|    total_production = 783942.656 (final billable)                     |
|    actual_ghi_irradiance = 158200 Wh/m2                               |
|    actual_pr = 0.798                                                  |
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

## Non-Metered Tariff Lines

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

## Pricing Calculator: Tariff Selection Logic

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

## CBE Portfolio Summary

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

## Source Files

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

## Schema Implementation Status

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
| `price_index` | — | **Pending** — needed for CPI escalation |
| `loan_schedule` / `loan_payment` | — | **Pending** — needed for loan repayment tracking |
