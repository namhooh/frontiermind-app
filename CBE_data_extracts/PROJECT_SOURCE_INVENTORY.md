# Project Source Document Inventory

> Generated: 2026-02-28 | Schema version: 1.0
> Maps each of the 32 FrontierMind projects to available source documents for data population.

## Source Files

| Source | Path | Row Count |
|--------|------|-----------|
| Contract Lines CSV | `Data Extracts/FrontierMind Extracts_dim_finance_contract_line.csv` | 1,084 rows |
| Meter Readings CSV | `Data Extracts/FrontierMind Extracts_meter readings.csv` | 604 rows |
| Contracts CSV | `Data Extracts/FrontierMind Extracts_dim_finance_contract.csv` | 118 rows |
| PPA Documents | `Customer Offtake Agreements/*.pdf` | 62 files |
| AM Onboarding Template | `AM Onboarding Template 2025_MOH01_Mohinani Group.xlsx` | MOH01 only |
| Plant Performance Workbook | `Operations Plant Performance Workbook.xlsx` | Portfolio-wide |
| Operating Revenue Masterfile | `CBE Asset Management Operating Revenue Masterfile - new.xlsb` | Portfolio-wide |
| SAGE Contract Extracts | `Sage Contract Extracts market Ref pricing data.xlsx` | Portfolio-wide |

## Project × Document Matrix

Filtered to DIM_CURRENT_RECORD=1 for contract lines. CUSTOMER_NUMBER aliases noted where applicable.

| Sage ID | Project Name | PPA Docs | Contract Lines (active) | Meter Readings | CBE Alias | Population Status |
|---------|-------------|----------|------------------------|----------------|-----------|-------------------|
| ABI01 | Accra Breweries Ghana | 1 | 0 | 0 | — | PPA-only |
| AMP01 | Ampersand | 1 | 3 | 2 | — | Partial |
| AR01 | Arijiju Retreat | 1 | 1 | 0 | — | Minimal |
| BNT01 | Izuba BNT | 1 | 0 | 0 | — | PPA-only |
| CAL01 | Caledonia | 2 | 6 | 22 | — | Ready |
| ERG | Molo Graphite | 1 | 2 | 14 | — | Ready |
| GBL01 | Guinness Ghana Breweries | 3 | 6 | 24 | — | Ready |
| GC01 | Garden City Mall | 3 | 3 | 24 | GC001 | Ready |
| IVL01 | Indorama Ventures | 2 | 3 | 13 | — | Ready |
| JAB01 | Jabi Lake Mall | 1 | 4 | 41 | — | Ready |
| **KAS01** | **Kasapreko** | **4** | **4** | **36** | — | **Pilot** |
| **LOI01** | **Loisaba** | **5** | **6** | **24** | — | **Pilot** |
| MB01 | Maisha Mabati Mills | 1 | 7 | 24 | — | Ready |
| MF01 | Maisha Minerals & Fertilizer | 1 | 5 | 24 | — | Ready |
| MIR01 | Miro Forestry | 2 | 6 | 12 | — | Ready |
| MOH01 | Mohinani | 1 | 7 | 7 | — | **Onboarded** |
| MP01 | Maisha Packaging Nakuru | 1 | 3 | 13 | — | Ready |
| MP02 | Maisha Packaging LuKenya | 1 | 5 | 25 | — | Ready |
| **NBL01** | **Nigerian Breweries Ibadan** | **5** | **8** | **34** | — | **Pilot** |
| NBL02 | Nigerian Breweries Ama | 2 | 2 | 19 | — | Ready |
| NC02 | National Cement Athi River | 1 | 3 | 12 | — | Ready |
| NC03 | National Cement Nakuru | 1 | 3 | 13 | — | Ready |
| QMM01 | Rio Tinto QMM | 4 | 8 | 34 | — | Ready |
| TBC | iSAT Africa | 0 | 0 | 0 | — | No data |
| TBM01 | TeePee Brushes | 2 | 3 | 24 | — | Ready |
| TWG01 | Balama Graphite | 1 | 4 | 0 | TWG | No readings |
| UGL01 | Unilever Ghana | 3 | 4 | 23 | — | Ready |
| UNSOS | UNSOS Baidoa | 2 | 4 | 21 | — | Ready |
| UTK01 | eKaterra Tea Kenya | 2 | 4 | 24 | — | Ready |
| XF-AB | XFlora Group | 4 | 16* | 95* | XFAB/XFBV/XFSS/XFL01 | Ready |
| ZL02 | Zoodlabs Energy Services | 0 | 9 | 0 | — | No PPA, no readings |
| ZO01 | Zoodlabs Group | 2 | 0 | 0 | ZL01 | PPA-only |

*XFlora: 4 CBE sub-customers aggregate to 1 FM project.

## Population Pipeline by Project Type

### Type A: Full Pipeline (CSV + PPA)
Projects with contract lines, meter readings, AND PPA documents.
**Pipeline:** Migration (contract lines + meter aggregates) → PPA parsing (tariffs) → Eval

Projects: KAS01, NBL01, LOI01, CAL01, ERG, GBL01, GC01, IVL01, JAB01, MB01, MF01, MIR01, MP01, MP02, NBL02, NC02, NC03, QMM01, TBM01, UGL01, UNSOS, UTK01, XF-AB

### Type B: PPA-Only
Projects with PPA documents but no/minimal CBE structured data.
**Pipeline:** PPA parsing only → Manual contract line creation

Projects: ABI01, AR01, BNT01, ZO01

### Type C: CSV-Only
Projects with CBE data but no PPA documents.
**Pipeline:** Migration only → Tariffs from workbook extraction

Projects: AMP01, TWG01, ZL02

### Type D: No Data
Projects with no source documents available.
**Pipeline:** Manual data entry required

Projects: TBC

## Pilot Project Details

### KAS01 — Kasapreko (Ghana, GHS)
- **Contract:** CONGHA00-2021-00002
- **Active lines:** 1000 (Metered Phase 1), 2000 (Available Combined), 4000 (Metered Phase 2)
- **Inactive lines:** 3000 (Inverter Energy Phase 2, ACTIVE_STATUS=0)
- **Meter readings:** 36 (Jan-Dec 2025, lines 1000/2000/4000)
- **PPA docs:** SSA Amendment + 3 amendments (2019-2021)
- **Tariff type:** Floating grid-tied

### NBL01 — Nigerian Breweries Ibadan (Nigeria, NGN)
- **Contract:** CONNIG00-2021-00002
- **Active lines:** 6000 (Generator Metered P1), 7000 (Generator Available P1), 10000 (Generator Metered P2)
- **Inactive lines:** 1000, 3000, 4000, 5000 (legacy grid lines), 9000 (Early Operating)
- **Meter readings:** 34 (Jan-Dec 2025, lines 6000/7000/10000)
- **PPA docs:** SSA + 4 amendments (2019-2022)
- **Tariff type:** Floating generator

### LOI01 — Loisaba (Kenya, USD)
- **Contract:** CONKEN00-2021-00002 (active) + CONCBEH0-2021-00002 (legacy, inactive)
- **Active lines:** 1000 (HQ Metered), 2000 (Camp Metered), 3000 (BESS Capacity)
- **Meter readings:** 24 (Jan-Dec 2025, lines 1000/2000 only; no readings for BESS line 3000)
- **PPA docs:** SSA + Amendment + Annexures + COD + Transfer certs
- **Tariff type:** Fixed solar + BESS capacity charge
- **Note:** LOI01 uses CPI escalation (IND_USE_CPI=1); legacy contract lines have empty METERED_AVAILABLE
