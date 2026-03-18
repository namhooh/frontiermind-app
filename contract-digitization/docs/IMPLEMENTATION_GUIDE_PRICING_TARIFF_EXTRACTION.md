# Pricing & Tariff Extraction Workflow (Step 11P)

> Standalone parsing pipeline focused exclusively on pricing, tariff, energy output,
> and billing-engine-relevant contractual terms from PPA/SSA/ESA documents.

## Overview

Step 11P is a **separate, independently callable** workflow that extracts pricing
and tariff terms from contract PDFs. It does NOT perform full contract clause
extraction (that remains Step 11). Instead, it isolates pricing-relevant sections
from the OCR text and runs a deep, focused extraction pass.

### Why Separate?

| Concern | Step 11 (Full Extraction) | Step 11P (Pricing Only) |
|---------|--------------------------|-------------------------|
| Scope | 13 clause categories | 9 pricing objects |
| Input | Full contract text (~60 pages) | Isolated sections (~10-15 pages) |
| Focus | Legal provisions across all areas | Formulas, rates, schedules, billing params |
| Output | `clause` table (140 rows per contract) | `clause_tariff.logic_parameters` + `tariff_formula` |
| LLM budget | Spread across 13 categories | 100% on pricing/tariff |
| Dependency | Requires LlamaParse OCR | Reuses Step 11 OCR cache (or runs independently) |

### Relationship to Other Steps

```
Step 7 (Revenue Masterfile)  <- AUTHORITATIVE for base_rate, escalation_type
        |
Step 11 (Full PPA Parsing)   <- 13-category extraction (unchanged, independent)
        |
Step 11P (This Workflow)      <- Focused pricing/formula extraction
        |                        Runs independently, uses same OCR text
        |                        Defensive merge: enriches, never overwrites Step 7
        |
        |-- clause_tariff.logic_parameters  <- Enriched with formula variables
        |-- tariff_formula                  <- Decomposed computation graphs
        |-- tariff_rate                     <- Year-by-year explicit rates (if in annexure)
        |-- production_guarantee            <- Energy output schedule from annexure
```

**Key principle:** Step 7 (Revenue Masterfile) remains authoritative for `base_rate`
and `escalation_type`. Step 11P enriches `logic_parameters` with formula structure,
variable definitions, and billing engine parameters — it never overwrites values
set by Step 7.

---

## Pipeline Architecture

```
+----------------------------------------------------------+
|                Step 11P Orchestrator                      |
|          scripts/step11p_pricing_extraction.py            |
+---------+------------+------------+----------------------+
          |            |            |
     Phase 1      Phase 2      Phase 3       Phase 4
     Section      Deep         Formula        Validate
     Isolator     Extraction   Decomposer     & Store
          |            |            |            |
          v            v            v            v
+----------+  +----------+  +----------+  +--------------+
| Identify |  | Focused  |  | Parse to |  | Consistency  |
| pricing  |  | Claude   |  | compute  |  | checks +     |
| sections |->| prompt   |->| graph +  |->| delete+insert|
| from OCR |  | (pricing |  | variable |  | clause_tariff|
| text     |  |  only)   |  | registry |  | + tariff_    |
|          |  |          |  | + tables |  |   formula    |
+----------+  +----------+  +----------+  +--------------+
```

### Phase 1 — Section Isolation

**File:** `services/pricing/section_isolator.py`

Scans OCR text (from LlamaParse, cached from Step 11 or extracted fresh) and
isolates pricing-relevant sections by heading pattern matching.

**Target sections:**

| Section Type | Pattern Examples | Content |
|---|---|---|
| Part I Project Terms | "Part I", "Project Terms and Conditions" | OY definition, key dates, capacity |
| Pricing Annexure | "Annexure - Pricing and Payment", "Annexure C" | Base rates, escalation, floor/ceiling |
| Energy Output | "Annexure - Expected Energy Output", "Annexure E" | Guaranteed kWh per year, degradation |
| Energy Calculation | "Annexure - Energy Output Calculation" | Available/deemed energy formulas |
| Required Energy | "Annexure - Required Energy Output" | Performance thresholds, shortfall |
| Performance Guarantee | "Article X - Performance Guarantee" | Guarantee %, weather adjustment |
| Liquidated Damages | "Article X - Liquidated Damages" | Shortfall payment formulas |
| Deemed Energy | "Article X - Available/Deemed Energy" | Deemed energy method, intervals |
| CPI/Indexation | "Annexure - Indexation", "US CPI" | CPI parameters, adjustment dates |
| Definitions | "Article 1 - Definitions" | Variable definitions for formulas |

**Output:** `PricingSectionBundle` — concatenated text of matched sections with
section markers, typically ~10-15 pages vs ~60 pages full contract.

### Phase 2 — Deep Extraction (Claude API)

**File:** `services/prompts/pricing_extraction_prompt.py`

A dedicated Claude prompt that extracts **9 structured objects**:

#### Object 1: `tariff_schedule`

Core rate structure — base rate, year-by-year schedule, floor/ceiling.

```json
{
  "base_rate": {"value": 0.184, "currency": "USD", "unit": "per_kwh"},
  "escalation_type": "PERCENTAGE",
  "escalation_params": {
    "annual_pct": 2.5,
    "start_year": 2,
    "compound": true
  },
  "year_by_year_rates": [
    {"year": 1, "rate": 0.184, "source": "explicit_table"},
    {"year": 2, "rate": 0.1886, "source": "explicit_table"}
  ],
  "floor": {
    "contract_ccy": {"value": 0.08, "currency": "USD"},
    "local_ccy": {"value": 1.20, "currency": "GHS", "source": "explicit"},
    "escalation": {"type": "FIXED_INCREASE", "annual_amount": 0.002}
  },
  "ceiling": {
    "contract_ccy": {"value": 0.12, "currency": "USD"},
    "local_ccy": {"value": 1.80, "currency": "GHS", "source": "explicit"},
    "escalation": {"type": "FIXED_INCREASE", "annual_amount": 0.003}
  },
  "discount_pct": 18.5,
  "raw_text_refs": ["Annexure C, Section 2.1", "Annexure C, Table 1"]
}
```

#### Object 2: `pricing_formulas`

Every mathematical formula, decomposed into variables and operations.

```json
[
  {
    "formula_id": "effective_rate",
    "formula_name": "Effective Rate Calculation",
    "formula_text": "P_Effective = MAX(P_Floor, MIN(MRP * (1 - d), P_Ceiling))",
    "formula_type": "MRP_BOUNDED",
    "variables": [
      {"symbol": "P_Effective", "role": "output", "variable_type": "RATE",
       "description": "Effective tariff rate", "unit": "USD/kWh",
       "maps_to": "tariff_rate.effective_rate_contract_ccy", "lookup_key": "billing_month"},
      {"symbol": "P_Floor", "role": "input", "variable_type": "RATE",
       "description": "Minimum tariff rate", "unit": "USD/kWh",
       "maps_to": "clause_tariff.logic_parameters.floor_rate", "lookup_key": null},
      {"symbol": "MRP", "role": "input", "variable_type": "PRICE",
       "description": "Market Reference Price", "unit": "USD/kWh",
       "maps_to": "reference_price.calculated_mrp_per_kwh", "lookup_key": "billing_month"},
      {"symbol": "d", "role": "parameter", "variable_type": "PERCENTAGE",
       "description": "Discount percentage", "unit": "percent",
       "maps_to": "clause_tariff.logic_parameters.discount_pct", "lookup_key": null},
      {"symbol": "P_Ceiling", "role": "input", "variable_type": "RATE",
       "description": "Maximum tariff rate", "unit": "USD/kWh",
       "maps_to": "clause_tariff.logic_parameters.ceiling_rate", "lookup_key": null}
    ],
    "operations": ["MIN", "MAX", "MULTIPLY", "SUBTRACT"],
    "conditions": [],
    "section_ref": "Annexure C, Clause 3.2"
  }
]
```

> **Note:** `billing_engine_params` and `mrp_definition` are extracted on the
> `PricingFormula` model but are NOT stored on `tariff_formula` — they get merged
> into `clause_tariff.logic_parameters` by the formula decomposer.

#### Object 3: `energy_output_schedule`

Expected/guaranteed energy output by year with degradation.

```json
{
  "schedule_type": "expected_annual_energy",
  "degradation_rate_pct_per_year": 0.5,
  "entries": [
    {"year": 1, "kwh": 15200000, "source": "annexure_table"},
    {"year": 2, "kwh": 15124000, "source": "annexure_table"}
  ],
  "guaranteed_percentage": 80,
  "guaranteed_basis": "expected_annual_energy",
  "weather_adjustment": {
    "method": "irradiance_corrected",
    "description": "Guaranteed output adjusted for actual vs reference irradiance"
  },
  "measurement_period": "annual",
  "cure_mechanism": {
    "allowed": true,
    "window_years": 2,
    "description": "Seller may cure shortfall within 2 subsequent operating years"
  },
  "section_ref": "Annexure E, Table 1"
}
```

#### Object 4: `payment_mechanics`

Invoice timing, FX conversion, take-or-pay, operating year definition.

```json
{
  "billing_frequency": "monthly",
  "invoice_timing_days_after_month_end": 10,
  "payment_due_days": 30,
  "currency": {
    "billing": "USD",
    "local": "GHS",
    "fx_source": "Bank of Ghana mid-rate",
    "fx_determination_date": "last_business_day_of_billing_month"
  },
  "take_or_pay": {
    "applies": true,
    "minimum_offtake_pct": 90,
    "shortfall_rate_pct_of_tariff": 100
  },
  "late_payment_interest_pct": 2.0,
  "operating_year": {
    "definition": "cod_anniversary",
    "start_date": "2021-06-15",
    "start_month": null,
    "note": "Operating Year commences on each anniversary of the COD"
  },
  "section_refs": ["Article 8", "Annexure D", "Article 1.1"]
}
```

#### Object 5: `escalation_rules`

Per-component escalation with CPI parameters and first indexation date.

```json
[
  {
    "component": "base_rate",
    "method": "PERCENTAGE",
    "annual_pct": 2.5,
    "start_year": 2,
    "first_indexation_date": "2022-06-15",
    "compound": true
  },
  {
    "component": "floor_rate",
    "method": "FIXED_INCREASE",
    "annual_amount": 0.002,
    "currency": "USD"
  },
  {
    "component": "ceiling_rate",
    "method": "US_CPI",
    "cpi_params": {
      "index_name": "CPI-U",
      "reference_year": 2020,
      "base_index_value": 258.811,
      "cap_pct": 3.0,
      "floor_pct": 0.0,
      "lag_months": 3,
      "adjustment_frequency": "annual"
    }
  }
]
```

#### Object 6: `definitions_registry`

Contract-defined terms that formulas reference.

```json
[
  {"term": "Normal Operation", "definition": "Period during which irradiance >= 100 W/m2 and plant is grid-connected", "section_ref": "Article 1.1"},
  {"term": "Expected Energy Output", "definition": "Annual energy output as set out in Annexure E", "section_ref": "Article 1.1"},
  {"term": "Grid Tariff", "definition": "The prevailing utility tariff charged by ECG to the Buyer", "section_ref": "Article 1.1"}
]
```

#### Object 7: `shortfall_mechanics`

Penalty/shortfall payment formulas, excused events, caps.

```json
{
  "shortfall_formula_type": "annual_energy_shortfall",
  "formula_text": "SP = MAX(0, (E_Guaranteed - E_Actual) × (P_Alternate - P_Effective))",
  "formula_variables": [
    {"symbol": "SP", "role": "output", "variable_type": "CURRENCY",
     "maps_to": "invoice_line_item.amount", "unit": "USD", "lookup_key": null},
    {"symbol": "E_Guaranteed", "role": "input", "variable_type": "ENERGY",
     "maps_to": "production_guarantee.guaranteed_kwh", "lookup_key": "operating_year"},
    {"symbol": "E_Actual", "role": "input", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.total_production", "lookup_key": "operating_year"},
    {"symbol": "P_Alternate", "role": "input", "variable_type": "RATE",
     "maps_to": "reference_price.calculated_mrp_per_kwh", "lookup_key": "operating_year"},
    {"symbol": "P_Effective", "role": "input", "variable_type": "RATE",
     "maps_to": "tariff_rate.effective_rate_contract_ccy", "lookup_key": "operating_year"}
  ],
  "excused_events": ["Force Majeure", "Grid Unavailability", "Buyer Curtailment"],
  "payment_cap": {"type": "annual", "value": 15, "unit": "percent_of_annual_revenue"},
  "cure_mechanism": {"allowed": true, "window_years": 2},
  "measurement_period": "annual",
  "weather_adjustment": {
    "method": "irradiance_corrected",
    "description": "Guarantee adjusted for actual vs reference irradiance"
  },
  "section_refs": ["Article 12", "Annexure H"]
}
```

#### Object 8: `deemed_energy_params`

Available/deemed energy calculation parameters for the billing engine.

```json
{
  "available_energy_method": "irradiance_interval_adjusted",
  "formula_text": "E_Available(x) = MAX(0, PR_month × Cap × Irr(x) - E_metered(x))",
  "formula_variables": [
    {"symbol": "E_Available(x)", "role": "output", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.available_energy_kwh", "unit": "kWh", "lookup_key": "billing_month"},
    {"symbol": "PR_month", "role": "input", "variable_type": "PERCENTAGE",
     "maps_to": "clause_tariff.logic_parameters.performance_ratio_monthly", "lookup_key": null},
    {"symbol": "Cap", "role": "input", "variable_type": "CAPACITY",
     "maps_to": "project.capacity_kwp", "unit": "kWp", "lookup_key": null},
    {"symbol": "Irr(x)", "role": "input", "variable_type": "IRRADIANCE",
     "maps_to": "meter_aggregate.ghi_irradiance_wm2", "unit": "kW/m2", "lookup_key": "billing_month"},
    {"symbol": "E_metered(x)", "role": "input", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.total_production", "unit": "kWh", "lookup_key": "billing_month"}
  ],
  "interval_minutes": 15,
  "irradiance_threshold_wm2": 100,
  "reference_period": "same_month_prior_year",
  "excused_events": ["Force Majeure", "Grid Outage", "Scheduled Maintenance"],
  "section_refs": ["Article 10", "Annexure G"]
}
```

#### Object 9: `energy_output_definition`

Contractual Energy Output definition — the conditional formula that defines
what counts as "Energy Output" for billing and performance measurement.

Contracts typically have TWO variants — **annual** and **monthly** — each
extracted as a separate `tariff_formula` row with distinct `extraction_metadata`.

**Annual variant (`applies_annually: true, applies_monthly: false`):**

```json
{
  "formula_text": "If: ∑E_metered(i) > Annual Minimum Offtake Guarantee Then: Energy Output = ∑E_metered(i) Else: Energy Output = MIN(∑E_metered(i) + ∑E_Available(x), Annual Minimum Offtake Guarantee)",
  "formula_variables": [
    {"symbol": "Energy Output", "role": "output", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.total_production", "lookup_key": "operating_year"},
    {"symbol": "E_metered(i)", "role": "input", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.total_production", "lookup_key": "operating_year"},
    {"symbol": "E_Available(x)", "role": "input", "variable_type": "ENERGY",
     "maps_to": "meter_aggregate.available_energy_kwh", "lookup_key": "operating_year"},
    {"symbol": "Annual Minimum Offtake Guarantee", "role": "input", "variable_type": "ENERGY",
     "maps_to": "production_guarantee.minimum_offtake_kwh", "lookup_key": "operating_year"}
  ],
  "operations": ["IF", "MIN", "SUM"],
  "conditions": [
    {"type": "threshold", "compare": "∑E_metered(i)", "against": "Annual Minimum Offtake Guarantee",
     "operator": ">", "then": "Energy Output = ∑E_metered(i)",
     "else": "Energy Output = MIN(∑E_metered(i) + ∑E_Available(x), Annual Minimum Offtake Guarantee)",
     "description": "If total metered energy exceeds the annual guarantee, use metered only; otherwise cap at guarantee"}
  ],
  "applies_monthly": false,
  "applies_annually": true,
  "section_ref": "Article 1.1 / Annexure G"
}
```

**Monthly variant (`applies_monthly: true, applies_annually: false`):**

Same structure but with `Monthly Minimum Offtake Guarantee` and `lookup_key: "billing_month"` on all variables.

### Phase 3 — Formula Decomposition & DB Mapping

**File:** `services/pricing/formula_decomposer.py`

Takes Phase 2 output and:
1. Maps formula variables to DB source columns via canonical mapping
2. Enriches each variable with `variable_type` and `lookup_key`
3. Generates enriched `logic_parameters` JSONB for the billing engine
4. Populates `tariff_formula` rows (computation graphs)
5. Extracts year-by-year schedules into `tariff_rate` or `production_guarantee`
6. Deduplicates formulas by `(formula_type, normalized formula_text)`

**Canonical Variable Mapping:**

| maps_to | DB Table.Column | variable_type |
|---|---|---|
| `clause_tariff.base_rate` | clause_tariff.base_rate | RATE |
| `clause_tariff.logic_parameters.floor_rate` | clause_tariff (JSONB) | RATE |
| `clause_tariff.logic_parameters.ceiling_rate` | clause_tariff (JSONB) | RATE |
| `clause_tariff.logic_parameters.discount_pct` | clause_tariff (JSONB) | PERCENTAGE |
| `clause_tariff.logic_parameters.performance_ratio_monthly` | clause_tariff (JSONB) | PERCENTAGE |
| `reference_price.calculated_mrp_per_kwh` | reference_price | PRICE |
| `tariff_rate.effective_rate_contract_ccy` | tariff_rate | RATE |
| `meter_aggregate.total_production` | meter_aggregate | ENERGY |
| `meter_aggregate.available_energy_kwh` | meter_aggregate | ENERGY |
| `meter_aggregate.ghi_irradiance_wm2` | meter_aggregate | IRRADIANCE |
| `meter_aggregate.performance_ratio` | meter_aggregate | PERCENTAGE |
| `production_forecast.forecast_energy_kwh` | production_forecast | ENERGY |
| `production_forecast.degradation_factor` | production_forecast | PERCENTAGE |
| `production_guarantee.guaranteed_kwh` | production_guarantee | ENERGY |
| `production_guarantee.p50_annual_kwh` | production_guarantee | ENERGY |
| `production_guarantee.guarantee_pct_of_p50` | production_guarantee | PERCENTAGE |
| `production_guarantee.minimum_offtake_kwh` | production_guarantee | ENERGY |
| `price_index.index_value` | price_index | INDEX |
| `exchange_rate.rate` | exchange_rate | CURRENCY |
| `project.capacity_kwp` | project | CAPACITY |
| `invoice_line_item.amount` | invoice_line_item | CURRENCY |
| `tariff_formula.DEEMED_ENERGY` | tariff_formula (child) | ENERGY |

**Temporal Lookup Rules (`lookup_key`):**

| maps_to prefix | Default lookup_key | Notes |
|---|---|---|
| `meter_aggregate.` | `billing_month` | Override to `operating_year` in annual formulas |
| `reference_price.` | `billing_month` | Override to `operating_year` in annual formulas |
| `tariff_rate.` | `billing_month` | Override to `operating_year` for escalation outputs |
| `production_guarantee.` | `operating_year` | Always annual |
| `production_forecast.` | `operating_year` | Always annual |
| `exchange_rate.` | `billing_month` | Monthly FX |
| `price_index.` | `operating_year` | Annual index |
| `clause_tariff.` | null (static) | Base rate, floor, ceiling — contract-level constants |
| `project.` | null (static) | Capacity — fixed |
| `invoice_line_item.` | null | Output target, not looked up |

**IMPORTANT:** The `lookup_key` depends on the **formula's time scope**, not just the source table. An annual Energy Output formula should use `operating_year` for ALL its variables (including `meter_aggregate` inputs), because the formula aggregates across the full operating year.

### Phase 4 — Validation & Storage

**File:** `services/pricing/pricing_validator.py`

Consistency checks before DB write:

| Check | Rule |
|-------|------|
| Floor < Ceiling | `floor_rate < ceiling_rate` (same currency) |
| Escalation direction | FIXED_INCREASE → annual_amount > 0 |
| Rate continuity | Year-by-year schedule matches formula output (1% tolerance) |
| Variable completeness | All formula input variables have a DB source mapping (`maps_to`) |
| Currency consistency | Floor/ceiling currency matches contract billing currency |
| Energy output monotonic | Expected energy decreasing or stable (degradation) |
| Cross-formula coherence | If ENERGY_OUTPUT references E_Available, DEEMED_ENERGY should exist |
| Shortfall formula coherence | If shortfall formula exists, guarantee and tariff must exist |
| CPI params complete | If escalation = US_CPI, cpi_params must have index_name + reference_year |
| Formula text symbols | Every variable symbol in `variables` array must appear in `formula_text` |
| Output role mapping | Payment formula outputs must map to `invoice_line_item.amount`, not rate columns |

---

## Database: `tariff_formula` Table

**Migration:** `database/migrations/062_tariff_formula.sql`

Stores decomposed mathematical formulas as structured computation graphs,
linked to the `clause_tariff` they parameterize.

```sql
CREATE TABLE tariff_formula (
    id                    BIGSERIAL PRIMARY KEY,
    clause_tariff_id      BIGINT NOT NULL REFERENCES clause_tariff(id) ON DELETE CASCADE,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),
    formula_name          VARCHAR(255) NOT NULL,
    formula_text          TEXT NOT NULL,
    formula_type          VARCHAR(50) NOT NULL,   -- MRP_BOUNDED, CPI_ESCALATION, ENERGY_OUTPUT, etc.
    variables             JSONB NOT NULL DEFAULT '[]',  -- [{symbol, role, variable_type, description, unit, maps_to, lookup_key}]
    operations            JSONB NOT NULL DEFAULT '[]',
    conditions            JSONB DEFAULT '[]',     -- [{type, compare, against, operator, then, else, description}]
    section_ref           VARCHAR(255),
    extraction_confidence NUMERIC(3,2),
    extraction_metadata   JSONB DEFAULT '{}',
    version               INTEGER NOT NULL DEFAULT 1,
    is_current            BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- No unique constraint — multiple formulas of same type allowed per clause_tariff
-- (e.g. PERCENTAGE_ESCALATION for base_rate and floor_rate)
-- Re-extraction deletes all rows for the clause_tariff and inserts fresh
```

**Formula Type Taxonomy (14 types across 5 categories):**

| Category | formula_type | Description |
|---|---|---|
| pricing | `MRP_BOUNDED` | Effective rate = MAX(floor, MIN(MRP × (1-d), ceiling)) |
| pricing | `MRP_CALCULATION` | MRP = Σ(variable_charges) / Σ(energy_kwh) |
| escalation | `PERCENTAGE_ESCALATION` | Rate_N = base × (1 + pct)^(N-1) |
| escalation | `FIXED_ESCALATION` | Rate_N = base ± amount × (N-1) |
| escalation | `CPI_ESCALATION` | Rate_N = base × (CPI_current / CPI_base) |
| escalation | `FLOOR_CEILING_ESCALATION` | floor/ceiling escalated by CPI or fixed |
| energy | `ENERGY_OUTPUT` | Contractual Energy Output definition (conditional) |
| energy | `DEEMED_ENERGY` | E_Available(x) = MAX(0, PR × Cap × Irr - E_metered) |
| energy | `ENERGY_DEGRADATION` | E_Year_N = E_Year_1 × (1 - deg)^(N-1) |
| energy | `ENERGY_GUARANTEE` | E_Guaranteed = P50 × guarantee_pct |
| energy | `ENERGY_MULTIPHASE` | E_combined = E_phase1 + E_phase2 |
| performance | `SHORTFALL_PAYMENT` | SP = MAX(0, (E_Guaranteed - E_Actual)) × (P_Alternate - P_Effective) |
| performance | `TAKE_OR_PAY` | Shortfall = MAX(0, E_min - E_actual) × rate |
| billing | `FX_CONVERSION` | amount_hard = amount_local / fx_rate |

---

## Hardcoded Value → Variable Remapping (Critical Design Principle)

**The tariff_formula table is a living formula engine, not a snapshot of year-1 values.**

Contracts contain specific numbers (e.g., "0.0654 USD/kWh", "1% annual escalation",
"80% of P50"). When Claude extracts these, they appear as hardcoded literals in
`formula_text` and `description`. The **second analysis pass** (Phase 3 decomposition +
Phase 4 validation) must verify that every hardcoded value that changes over time is
remapped to a named variable with the correct `maps_to` and `lookup_key`.

### The test: "Will this formula produce the correct result in year 10?"

For each formula, ask: if the billing engine evaluates this formula in operating year 10,
will it get the right answer? If the formula says `Rate_N = base × (1 + 1.0%)^(N-1)`,
the 1.0% is baked in — if the contract is amended to 1.5%, the formula is wrong.
Instead: `Rate_N = base × (1 + escalation_pct)^(N-1)` where `escalation_pct` maps to
`clause_tariff.logic_parameters.escalation_pct`.

### Common hardcoded values that MUST be variables

| Hardcoded value | What it should be | maps_to | Why |
|---|---|---|---|
| `"0.0654 USD/kWh"` in payment formula | Variable `Solar_Tariff` | `tariff_rate.effective_rate_contract_ccy` | Rate escalates annually — year 1 value is not year 10 value |
| `"1% annual escalation"` in escalation formula | Variable `escalation_pct` | `clause_tariff.logic_parameters.escalation_pct` | May be amended; engine should read from DB |
| `"80% of P50"` in guarantee formula | Variable `guarantee_pct` | `production_guarantee.guarantee_pct_of_p50` | Stored per project, engine reads it |
| `"100 W/m²"` irradiance threshold | Variable `irradiance_threshold` | `clause_tariff.logic_parameters.irradiance_threshold_wm2` | Varies by contract |
| `"15 minutes"` interval | Variable `interval_minutes` | `clause_tariff.logic_parameters.interval_minutes` | Varies by contract |
| `"1,108,667 kWh"` annual guarantee | Variable `Annual_MOG` | `production_guarantee.minimum_offtake_kwh` | Changes by operating year (degradation) |

### What CAN stay hardcoded

- Mathematical constants: `0`, `1`, `-1`
- Operators that are part of the formula structure: `MAX`, `MIN`, `IF`
- The formula structure itself (which operations in which order)

### How the decomposer enforces this

1. **formula_text**: uses variable symbols, never literal values
   - WRONG: `Rate_N = base × (1 + 1.0%)^(N-1)`
   - RIGHT: `Rate_N = base × (1 + escalation_pct)^(N-1)`

2. **variables**: every time-varying input has `maps_to` + `lookup_key`
   - The actual value (e.g., 1.0%) goes in the variable's `description` field for reference
   - The `maps_to` tells the engine where to read the current value at runtime

3. **description field**: safe place to record the contract's stated value
   - `"description": "Annual escalation percentage (1.0% per contract Annexure C)"`
   - This is informational only — the engine uses `maps_to`, not `description`

### Validation checks (Phase 4)

- `formula_text_symbols`: every variable symbol must appear in formula_text
- `output_role_mapping`: payment outputs must map to `invoice_line_item.amount`
- **Manual review**: scan formula_text for numeric literals (digits followed by %) — any
  match should be a variable, not a hardcoded value

---

## Variable Rules (Lessons from MB01)

Critical rules for variable extraction quality. These are enforced in the prompt
and should be verified during manual review.

### Role assignment

| Concept | Correct role | Why |
|---|---|---|
| Payment amount (SP, monthly payment, deemed energy payment) | `output` | Computed by the formula |
| Solar Tariff / effective rate used in payment calc | `input` | Looked up from `tariff_rate` for current period — escalates annually |
| Escalation percentage, discount percentage | `input` | Stored in `clause_tariff.logic_parameters`, read at runtime |
| Minimum Offtake Guarantee | `input` | Queried from `production_guarantee` by period — changes by OY |
| Floor / ceiling rates | `input` | Read from `clause_tariff.logic_parameters` |
| Performance Ratio (PR) | `input` | Read from `clause_tariff.logic_parameters.performance_ratio_monthly` |
| Plant capacity (Cap) | `input` | Read from `project.capacity_kwp` |
| Operating year number (N) | `input` | Derived at runtime from billing period |
| Irradiance, metered energy, available energy | `input` | Read from `meter_aggregate` for billing period |

**Rule of thumb:** if the value comes from ANY database table, it is `input`. Use
`parameter` ONLY for literal numeric constants that are truly fixed for the life of
the contract AND appear as bare numbers in the formula (e.g., exponent `1` in
`(1 + pct)^(N-1)`). In practice, almost nothing should be `parameter`.

### maps_to rules

| Variable type | Correct maps_to | WRONG maps_to |
|---|---|---|
| Payment amount output | `invoice_line_item.amount` | `tariff_rate.effective_rate_contract_ccy` (that's a rate, not an amount) |
| Performance Ratio (PR) | `clause_tariff.logic_parameters.performance_ratio_monthly` | `production_forecast.degradation_factor` (different concept) |
| Current-year effective rate | `tariff_rate.effective_rate_contract_ccy` | `clause_tariff.base_rate` (that's year-1 only) |
| Shortfall payment output | `invoice_line_item.amount` | `production_guarantee.guaranteed_kwh` (that's an energy value) |
| Escalation percentage | `clause_tariff.logic_parameters.escalation_pct` | hardcoded in formula_text |
| Escalation fixed amount | `clause_tariff.logic_parameters.escalation_amount` | hardcoded in formula_text |

### lookup_key rules

**The lookup_key is determined by the formula's temporal scope, not the source table.**

| Formula scope | All variables use | Exception |
|---|---|---|
| Annual (Annual Energy Output, Shortfall Payment) | `operating_year` | `clause_tariff.*`, `project.*` → null (static) |
| Monthly (Monthly Energy Output, Monthly Payment, Deemed Energy) | `billing_month` | `clause_tariff.*`, `project.*` → null (static) |
| Escalation | output → `operating_year` | base/pct inputs → null (static from clause_tariff) |

**CRITICAL:** An annual shortfall formula reads `meter_aggregate.total_production` summed
across the full operating year — its `lookup_key` must be `operating_year`, NOT `billing_month`.
The auto-inference from table prefix is a fallback only; the formula's scope takes precedence.

### formula_text rules

- Every symbol in `formula_text` MUST match a symbol in `variables`
- Use `∑E_metered(i)` not `∑ i` — always include the variable name in summations
- Use `×` for multiply — verify OCR didn't render `×` as `/`
- Never hardcode values that vary over time — use variable symbols instead
- Use the project's billing currency for payment output units (e.g., `KSH`), not `"USD or KSH"`
- Do NOT invent formulas from prose descriptions — only extract explicit mathematical expressions

### conditions format

```json
{
  "type": "threshold",
  "compare": "∑E_metered(i)",
  "against": "Annual Minimum Offtake Guarantee",
  "operator": ">",
  "then": "Energy Output = ∑E_metered(i)",
  "else": "Energy Output = MIN(∑E_metered(i) + ∑E_Available(x), Annual Minimum Offtake Guarantee)",
  "description": "If total metered energy exceeds the annual guarantee, use metered only; otherwise cap at guarantee"
}
```

All symbols in `compare`, `against`, `then`, `else` MUST match symbols in the `variables` array.
Conditions must be actionable — use full formula expressions in `then`/`else`, not vague labels
like `"metered_only"`.

---

## MB01 Corrections Log

Reference of all corrections applied during MB01 pilot. These inform the rules above
and are now enforced in the prompt + decomposer + validator.

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | `formula_type: "pricing"` instead of `"MRP_BOUNDED"` | Claude used category names | Added alias map in extractor + explicit enum list in prompt |
| 2 | `CureMechanism.description: null` | Claude returns null for Optional str | Made str fields `Optional[str]` in Pydantic model |
| 3 | `tariff_rate.operating_year` column error | Wrong column name | Fixed to `contract_year` |
| 4 | `PRmonth` mapped to `degradation_factor` | Semantic confusion | Added PR mapping rule to prompt |
| 5 | Duplicate SHORTFALL_PAYMENT rows | Claude + synthesizer both created one | Dedup by `(formula_type, normalized formula_text)` |
| 6 | Available Energy typed as `ENERGY_OUTPUT` | Wrong formula_type | Clarified in prompt: DEEMED_ENERGY for available energy formulas |
| 7 | Payment output mapped to `tariff_rate` | Rate vs amount confusion | Added `invoice_line_item.amount` mapping + prompt rule |
| 8 | `"USD or KSH"` as unit | Claude hedged on currency | Prompt rule: use billing currency only |
| 9 | Solar Tariff as `parameter` mapped to `base_rate` | Should be temporal input | Fixed role→input, maps_to→`tariff_rate`, lookup_key→billing_month |
| 10 | `formula_text: "∑ i > Guarantee"` | Symbol dropped in summation | Prompt rule + validator check |
| 11 | Conditions as vague labels | `"then": "metered_only"` | New format: `compare`/`against`/`operator` with full formula expressions |
| 12 | `applies_monthly: true, applies_annually: true` on annual formula | Wrong metadata | Separate annual/monthly rows |
| 13 | MOG as `parameter` without `lookup_key` | Should be temporal input | Role→input, lookup_key→operating_year |
| 14 | Mixed `lookup_key` (year/month) in annual formula | Auto-inference by table prefix | Formula scope overrides table prefix |
| 15 | Hallucinated "Deemed Energy Payment" formula | Claude invented from prose | Prompt rule: only explicit mathematical expressions |
| 16 | `"1.0%"` hardcoded in escalation formula_text | Baked literal value | Variable `escalation_pct` with `maps_to` |
| 17 | Missing `E_metered(i)` in deemed energy variables | Incomplete variable list | Validator: formula_text_symbols check |
| 18 | `Cap`, `PRmonth` as `parameter` | Should be DB-sourced input | Prompt: if from DB table → role is `input` |

---

## File Structure

```
python-backend/
|-- services/
|   +-- pricing/                              # Pricing extraction module
|       |-- __init__.py
|       |-- section_isolator.py               # Phase 1
|       |-- pricing_extractor.py              # Phase 2: Claude API wrapper
|       |-- formula_decomposer.py             # Phase 3
|       +-- pricing_validator.py              # Phase 4
|-- services/prompts/
|   +-- pricing_extraction_prompt.py          # Dedicated pricing prompt
|-- models/
|   +-- pricing.py                            # Pydantic models
|-- scripts/
|   +-- step11p_pricing_extraction.py         # Orchestrator
+-- database/
    +-- migrations/
        +-- 062_tariff_formula.sql            # New table
```

---

## Usage

```bash
# Single project
python -m scripts.step11p_pricing_extraction --project MB01

# Full portfolio
python -m scripts.step11p_pricing_extraction --all

# Dry run (extract + validate, no DB writes)
python -m scripts.step11p_pricing_extraction --project MB01 --dry-run

# Force re-extraction (delete existing + re-insert)
python -m scripts.step11p_pricing_extraction --project MB01 --force

# Skip Phase 1 (use full OCR text, no section isolation)
python -m scripts.step11p_pricing_extraction --project MB01 --no-isolate

# Use existing OCR cache from Step 11
python -m scripts.step11p_pricing_extraction --project MB01 --use-cache
```

---

## Storage Targets

| Phase 2 Object | Primary DB Target | Secondary Target |
|---|---|---|
| tariff_schedule | `clause_tariff.logic_parameters` | `tariff_rate` (if explicit schedule) |
| pricing_formulas | `tariff_formula` (new table) | `clause_tariff.logic_parameters` |
| energy_output_schedule | `production_guarantee` | `clause_tariff.logic_parameters.degradation_pct` |
| payment_mechanics | `clause_tariff.logic_parameters` | — |
| escalation_rules | `clause_tariff.logic_parameters.escalation_rules` | `tariff_formula` (escalation formulas) |
| definitions_registry | `tariff_formula.variables` (enrichment) | — |
| shortfall_mechanics | `clause_tariff.logic_parameters` | `tariff_formula` (shortfall formula) |
| deemed_energy_params | `clause_tariff.logic_parameters` | `tariff_formula` (deemed energy formula) |
| energy_output_definition | `tariff_formula` (ENERGY_OUTPUT) | `clause_tariff.logic_parameters` |

---

## Defensive Merge Rules

1. **Never overwrite `base_rate`** — Step 7 (Revenue Masterfile) is authoritative
2. **Never overwrite `escalation_type_id`** — Step 7 is authoritative
3. **Never overwrite `energy_sale_type_id`** — Step 7 is authoritative
4. **Enrich only NULL/absent keys** in `logic_parameters`
5. **`tariff_formula` rows** use delete+insert — all existing rows for the clause_tariff are deleted, then fresh rows inserted
6. **`production_guarantee`** rows use defensive COALESCE — only fill NULL `guaranteed_kwh`

---

## Dashboard Integration

### Formula Display

`tariff_formula` rows are served via the project dashboard endpoint (`/projects/{id}/dashboard`)
in the `tariff_formulas` array. The `PricingTariffsTab` renders them in a "Contract Formulas"
collapsible section with:

- **Type badge** — colour-coded by category (blue=pricing, violet=escalation, emerald=energy, amber=performance)
- **Formula expression** — math-formatted with bold operators (MAX, MIN, IF/THEN/ELSE), subscript variables, and summation symbols
- **Conditions** — if/then/else branching displayed in a highlighted box
- **Variables table** — 4 columns: Symbol, Description, Source (maps_to), Scope (lookup_key)
- **Confidence** — extraction confidence percentage

**Files:**
- Backend CTE: `python-backend/api/entities.py` → `tariff_formulas_data` CTE
- Frontend types: `lib/api/adminClient.ts` → `TariffFormula`, `TariffFormulaVariable`, `TariffFormulaCondition`
- Display components: `app/projects/components/PricingTariffsTab.tsx` → `FormulaCard`, `FormulaText`

### Tab Coverage

This workflow extracts all contractual fields displayed on the dashboard that
originate from PPA annexures:

| Dashboard Tab | Contractual Fields Covered |
|---|---|
| **Pricing & Tariffs** | floor/ceiling (dual-currency), discount_pct, mrp_method, mrp_time_window, mrp_components, escalation_rules, CPI params, billing_frequency, fx_source, pricing formulas, year-by-year rates |
| **Technical** | production guarantees (kWh/year), degradation rate, guarantee %, weather adjustment |
| **Monthly Billing** | available_energy_method, interval_minutes, irradiance_threshold, shortfall formula, take-or-pay params |
| **Plant Performance** | guaranteed_kwh, excused_events, shortfall_excused_events |
| **Overview** | OY definition, payment terms (enrichment only) |
