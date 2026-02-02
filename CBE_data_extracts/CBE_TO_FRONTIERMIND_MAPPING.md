# CBE to FrontierMind Data Mapping

This document maps CBE's Snowflake data architecture to FrontierMind's canonical schema. CBE is the first client adapter; the mapping demonstrates how client-specific data fits into the platform's generic tables.

---

## Architecture Philosophy

FrontierMind is a **power purchase ontology, contract compliance, and financial verification platform**. It owns the canonical data model — the domain-level definitions of what a contract, tariff line, meter reading, and invoice are. Clients bring their own data warehouses and source systems; FrontierMind does not replace them.

### Client Data Warehouse vs FrontierMind Platform

```
Client Source Systems (ERP, Billing, SCADA)
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
|    tariff_type, clause_category, clause_type          |
|    (FrontierMind defines the domain vocabulary)       |
|                                                       |
|  Core Tables                                          |
|    contract, clause_tariff, meter_aggregate,          |
|    exchange_rate, invoice tables                      |
|    (generic — no client-specific columns)             |
|                                                       |
|  Engines                                              |
|    Pricing Calculator, Comparison Engine,             |
|    Contract Parser, Compliance Rules                  |
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

1. **No client-specific columns on core tables** - CBE identifiers live in `source_metadata` JSONB
2. **Adapter writes, core reads** - The CBE adapter ingests data and maps to generic columns; the pricing calculator and comparison engine operate on generic columns only
3. **`tariff_group_key`** groups the same logical tariff line across time periods
4. **`total_production`** on `meter_aggregate` is the final billable quantity

---

## Table Mappings

### 1. CBE Contract Lines -> `clause_tariff`

CBE provides contract line data from `dim_finance_contract_line` (Snowflake/CSV).

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
| (derived from PRODUCT_CODE) | `tariff_type_id` (FK) | Adapter maps product codes to tariff_type (e.g. ENER0001 -> METERED_ENERGY) |
| Full original record | `source_metadata.original_record` | Preserved for audit |

**Tariff Type Mapping:**

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

**source_metadata example (CBE):**
```json
{
  "external_line_id": "4000",
  "external_line_key": "CBE-CONZIM00-2025-00002-4000",
  "product_code": "ENER0001",
  "metered_available": "EMetered",
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

### 2. CBE Meter Readings -> `meter_aggregate`

CBE provides monthly meter readings from Snowflake.

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
| `SOURCE_SYSTEM` | `source_system` | 'cbe_snowflake' |
| Full original record | `source_metadata` | Preserved for audit |

**Billable quantity calculation:**
```
total_production = utilized_reading - discount_reading - sourced_energy
                 = 783942.656 - 0 - 0
                 = 783942.656 kWh
```

### 3. CBE Contracts -> `contract`

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CONTRACT_NUMBER` | External reference stored in `extraction_metadata` | e.g. "CONZIM00-2025-00002" |
| `CONTRACT_NAME` | `name` | |
| `CUSTOMER_NUMBER` | Resolved to `counterparty_id` (FK) | Via customer lookup |
| `START_DATE` | `start_date` | |
| `END_DATE` | `end_date` | |
| `CURRENCY_CODE` | `currency_id` (FK) | Contract default currency |

### 4. CBE Customers -> `counterparty`

| CBE Field | FrontierMind Column | Notes |
|-----------|-------------------|-------|
| `CUSTOMER_NUMBER` | External reference in counterparty metadata | |
| `CUSTOMER_NAME` | `name` | |
| (derived) | `organization_id` (FK) | CBE organization |

### 5. Exchange Rates -> `exchange_rate`

CBE operates in ZAR primarily. Exchange rates entered manually or from CBE treasury.

| Input | FrontierMind Column | Notes |
|-------|-------------------|-------|
| ZAR | `currency_id` (FK) | Resolved from `currency.code = 'ZAR'` |
| Rate date | `rate_date` | Monthly or as-needed |
| Rate | `rate` | 1 USD = X ZAR (e.g. 18.50) |
| 'manual' | `source` | Until auto-fetch is implemented |

### 6. CBE Sage Invoices -> `received_invoice_header` / `received_invoice_line_item`

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

## Data Flow

```
CBE Snowflake / CSV Extracts
        |
   CBE Adapter (Python ingester)
        |
        v
+-------------------------------------------------------+
| 1. clause_tariff                                      |
|    tariff_group_key = "CONZIM00-2025-00002-4000"      |
|    tariff_type = METERED_ENERGY                       |
|    base_rate = 0.12 ZAR                               |
|    source_metadata = {external_line_id: "4000", ...}  |
+-------------------------------------------------------+
        |
        v
+-------------------------------------------------------+
| 2. meter_aggregate                                    |
|    clause_tariff_id -> tariff line                     |
|    opening_reading = 11333714.94                      |
|    closing_reading = 12117657.60                      |
|    utilized_reading = 783942.656                      |
|    total_production = 783942.656 (final billable)     |
|    source_system = 'cbe_snowflake'                    |
+-------------------------------------------------------+
        |
        v
+-------------------------------------------------------+
| 3. exchange_rate                                      |
|    currency = ZAR, rate = 18.50 (1 USD = 18.50 ZAR)  |
|    Looked up at calculation time                      |
+-------------------------------------------------------+
        |
        v  Pricing Calculator
+-------------------------------------------------------+
| 4. expected_invoice_header                            |
|    invoice_direction = 'receivable'                   |
|                                                       |
|    expected_invoice_line_item                          |
|      clause_tariff_id -> pricing                      |
|      meter_aggregate_id -> readings                   |
|      quantity = 783942.656                            |
|      line_unit_price = 0.12 ZAR                       |
|      line_total_amount = 94073.12 ZAR                 |
+-------------------------------------------------------+
        |
        v  Import Sage invoice from Snowflake
+-------------------------------------------------------+
| 5. received_invoice_header                            |
|    invoice_direction = 'receivable'                   |
|                                                       |
|    received_invoice_line_item                          |
|      clause_tariff_id -> same tariff line              |
|      quantity = 783942.656                            |
|      line_unit_price = 0.12                           |
|      line_total_amount = 94073.10                     |
+-------------------------------------------------------+
        |
        v  Compare
+-------------------------------------------------------+
| 6. invoice_comparison                                 |
|    invoice_direction = 'receivable'                   |
|    variance_amount = 0.02                             |
|                                                       |
|    invoice_comparison_line_item                        |
|      variance_amount = 0.02                           |
|      variance_percent = 0.00002                       |
|      variance_details = {                             |
|        "method_1": {"name": "standard", ...},         |
|        "rounding_difference_usd": 0.001               |
|      }                                                |
+-------------------------------------------------------+
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
| `line_item.line_unit_price` source | `clause_tariff.base_rate` | `clause_tariff.base_rate` |

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
