# GH-MOH01 Discrepancy Register

**Project:** GH-MOH01 (Polytanks Ghana Limited)
**Date:** 2026-02-18
**Sources:** AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx, CBE - MOH01_Mohanini_PPA.pdf, Supabase DB
**Correction Script:** `database/scripts/correct_gh_moh01.sql`

---

## 1. Cross-Source Discrepancies (Excel vs PDF)

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

---

## 2. Extraction/Preview Discrepancies

| # | Field | Expected | Parser Produced | Status |
|---|-------|----------|-----------------|--------|
| 9 | `customer_name` | Polytanks Ghana Limited | `null` | Fixed by correction script |
| 10 | Contacts | Contact list from Excel | 0 rows | Not fixable (no source data) |
| 11 | Assets | PV modules + inverters | 0 rows | Fixed by correction script |
| 12 | Meter attributes | Serial + location + type + model | Serials only, attributes null | Fixed by correction script |
| 13 | Tariff escalation type | Canonical code (GRID_PASSTHROUGH) | Free-text "Rebased Market Price" | Fixed by correction script |
| 14 | Guarantee pro-rata | Adjusted for installed capacity | Raw PDF base values | Fixed by correction script |

---

## 3. Database State Discrepancies (Before vs After Correction)

| # | Field | Before | After | Status |
|---|-------|--------|-------|--------|
| 15 | `project.country` | `GH` | `Ghana` | Fixed |
| 16 | `contract.contract_term_years` | 25 | 20 | Fixed |
| 17 | `contract.counterparty` | Mohinani Group | Polytanks Ghana Limited | Fixed |
| 18 | `contract.effective_date` | `null` | `null` | Open (no source data) |
| 19 | `contract.end_date` | `null` | `null` | Open (depends on effective_date) |
| 20 | `contract.payment_security_details` | `null` | Letter of Credit; Amount: 220000 USD | Fixed |
| 21 | `contract.agreed_fx_rate_source` | `null` | Bank of Ghana USD rate + 1% | Fixed |
| 22 | `contract.extraction_metadata` | `null` | initial_term=20, extensions, payment_terms=30d, default_rate=SOFR+2% | Fixed |
| 23 | `clause_tariff.tariff_structure` | FIXED (id=1) | GRID (id=2) | Fixed |
| 24 | `clause_tariff.energy_sale_type` | `null` | TAKE_OR_PAY (id=1) | Fixed |
| 25 | `clause_tariff.escalation_type` | `null` | GRID_PASSTHROUGH (id=5) | Fixed |
| 26 | `clause_tariff.market_ref_currency` | `null` | GHS (id=5) | Fixed |
| 27 | `clause_tariff.logic_parameters.floor_rate` | `null` | 0.079 | Fixed |
| 28 | `clause_tariff.logic_parameters.ceiling_rate` | `null` | 0.210 | Fixed |
| 29 | `clause_tariff.logic_parameters.grp_method` | `null` | utility_variable_charges_tou | Fixed |
| 30 | `production_guarantee.guaranteed_kwh` (Y1) | 3,249,363 | 3,280,333.188 | Fixed (pro-rata adjusted) |
| 31 | `production_guarantee.shortfall_cap_usd` | `null` | 119,000 | Fixed |
| 32 | `production_guarantee.shortfall_cap_fx_rule` | `null` | agreed_exchange_rate_at_invoicing | Fixed |
| 33 | `asset` rows | 0 | 2 (PV module + Inverter) | Fixed |
| 34 | `meter.location_description` | all `null` | BBM1, BBM2, Bottles, PPL 1, PPL 2 | Fixed |
| 35 | `meter.metering_type` | all `null` | export_only | Fixed |
| 36 | `meter.model` | all `null` | SPM33 & SPM93 Pilot Meter | Fixed |
| 37 | `meter.meter_type_id` | all `null` | REVENUE (id=1) | Fixed |
| 38 | `customer_contact` rows | 0 | 0 | Open (no source data) |
| 39 | `production_forecast.source_metadata` | `{}` | `{}` | Open (metadata supplementary; core data intact) |
| 40 | `reference_price` rows | 0 | 0 | Open (requires separate market data ingestion) |

---

## 4. Summary

| Category | Total | Fixed | Open |
|----------|-------|-------|------|
| Cross-source conflicts | 8 | 8 | 0 |
| Extraction/preview gaps | 6 | 5 | 1 |
| Database state issues | 26 | 23 | 3 |
| **Total** | **40** | **36** | **4** |

### Open Items (require manual action or separate data source)

1. **`contract.effective_date`** and **`end_date`** — Neither Excel nor LLM extraction provided the contract execution date. Requires manual lookup of the signed PPA.
2. **`customer_contact`** — No contacts found in Excel template. Requires manual entry from CBE operational records.
3. **`reference_price`** — GRP tariff calculation needs ECG market reference pricing data. Requires separate market data ingestion.
