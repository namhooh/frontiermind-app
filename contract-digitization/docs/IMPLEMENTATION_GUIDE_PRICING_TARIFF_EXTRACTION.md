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

## Pipeline Architecture — Compiler Model

The pipeline is a **compiler**, not a prompt-and-store pipeline. Claude extracts raw
formulas (no DB mapping). The compiler resolves semantic bindings, compiles into
runtime config + dashboard provenance, validates strictly, and quarantines failures.

```
+-------------------------------------------------------------------+
|                Step 11P Compiler Pipeline                          |
|          scripts/step11p_pricing_extraction.py                    |
+--------+----------+----------+----------+----------+--------------+
         |          |          |          |          |
    Phase 1    Phase 2    Phase 3    Phase 4    Phase 5    Phase 6
    Classify   Extract    Resolve    Compile    Validate   Promote
         |          |          |          |          |          |
         v          v          v          v          v          v
  +-----------+ +--------+ +--------+ +--------+ +--------+ +------+
  | Contract  | | Claude | | Match  | | Compile| | Strict | | Write|
  | Classifier|→| raw IR |→| symbols|→| to:    |→| check  |→| to   |
  | → select  | | (no DB | | to     | | (a) LP | | hard-  | | prod |
  |   formula | | mapping| | binding| | (b) TF | | stop   | | or   |
  |   compo-  | | at all)| | keys   | | (c) TR | | quarant| | quar |
  |   nents   | |        | |        | |        | | -ine   | | ine  |
  +-----------+ +--------+ +--------+ +--------+ +--------+ +------+
```

### Phase 1: Contract Classification

**File:** `services/pricing/contract_classifier.py`

Multi-signal classification using escalation_code, floor/ceiling, country, filename.
Returns a list of formula component keys (composable, not monolithic template).

### Phase 2: Raw Extraction (Claude API)

**File:** `services/pricing/pricing_extractor.py` + `services/prompts/pricing_extraction_prompt.py`

Claude extracts raw formulas ONLY:
- `formula_text` — the equation as written in the contract
- Variable `symbol` and `description` — what each variable represents
- `section_ref` — contract clause/annexure reference
- Project-specific values (rates, percentages, energy schedules)

**Claude does NOT do DB mapping.** No `maps_to`, `lookup_key`, `filter`, or `role`.

### Phase 3: Semantic Resolution

**File:** `services/pricing/template_resolver.py`

Matches Claude's extracted symbols to **binding keys** from the resolver registry.
Each binding key encodes the full business context:

```
Claude: {"symbol": "Grid Reference Price"}
  ↓ pattern match
Resolver: binding_key = "grid_mrp"
  ↓ resolve
  maps_to = reference_price.calculated_mrp_per_kwh
  filter  = {"observation_type": "monthly"}
  lookup_key = billing_month
  role = input
  time_grain = billing_month
  aggregation = None
  fallback_order = None
  compiles_to_engine = rebased_market_price_engine
```

### Phase 4: Compilation

**File:** `services/pricing/formula_compiler.py`

Compiles resolved bindings into THREE synchronized outputs from the SAME source:

| Output | Table | Purpose |
|---|---|---|
| (a) `logic_parameters` patch | `clause_tariff` | Runtime billing engine input |
| (b) `tariff_formula` rows | `tariff_formula` | Dashboard provenance + audit |
| (c) Rate entries | `tariff_rate` / `production_guarantee` | Rate schedule |

These outputs are compiled from the same bindings and **CANNOT diverge**.

### Phase 5: Strict Validation

**File:** `services/pricing/strict_validator.py`

Hard-stop validation — no writes to production on ANY error:

| # | Check | Level | Rule |
|---|-------|-------|------|
| 1 | `binding_key_missing` | ERROR | Every variable must have a binding_key in the registry |
| 2 | `maps_to_column_missing` | ERROR | Every maps_to must be a real DB column (or LP/source_metadata sub-key) |
| 3 | `duplicate_maps_to_no_filter` | ERROR | Two input variables sharing maps_to must have distinct filters |
| 4 | `output_wrong_table` | ERROR | Payment outputs must map to `invoice_line_item.line_total_amount`, not `tariff_rate` |
| 5 | `section_ref_missing` | WARN | Formulas should have section_ref for traceability |
| 6 | `mixed_temporal_scope` | WARN | Mixing `billing_month` and `operating_year` inputs in same formula |
| 7 | `formula_text_symbol_unmatched` | ERROR | Every symbol in `formula_text` must match a variable in the JSONB array |
| 8 | `role_wrong_payment_input` | ERROR | In PAYMENT_CALCULATION formulas, non-payment variables with role=output should be role=input |
| 9 | `role_wrong_metered_energy` | ERROR | `meter_aggregate.energy_kwh` (raw metered) is always an input, never output (except in DEEMED_ENERGY) |
| 10 | `role_deemed_not_output` | WARN | `available_energy_kwh` should only be role=output in DEEMED_ENERGY formulas |
| 11 | `derived_maps_to_raw` | WARN | Variables described as derived/computed should map to source inputs, not raw DB columns |

**Checks 8-11 (semantic role validation)** were added after CAL01 extraction revealed:
- Energy Output in a payment formula had `role=output` instead of `input` (consumed, not produced)
- Deemed energy in a Green Energy formula had `role=output` instead of `input` (wrong context)
- Make-Whole Energy mapped to raw `meter_aggregate.energy_kwh` instead of constituent inputs

These checks enforce the principle: **a variable's role is relative to the formula it appears in,
not its role in the broader formula chain.** A value can be the output of one formula (DEEMED_ENERGY)
and an input to another (ENERGY_OUTPUT).

**Failed outputs are quarantined** to `reports/cbe-population/step11p_quarantine_*.json`
for human review. Only promoted after validation passes.

### Phase 6: Promote to Production

Only after Phase 5 passes: delete existing + insert new rows.

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
     "maps_to": "meter_aggregate.energy_kwh", "lookup_key": "operating_year"},
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
     "maps_to": "meter_aggregate.energy_kwh", "unit": "kWh", "lookup_key": "billing_month"}
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
     "maps_to": "meter_aggregate.energy_kwh", "lookup_key": "operating_year"},
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

### Semantic Binding Architecture

**File:** `services/pricing/resolver_registry.py` (42 bindings)

The core innovation: variables are mapped to DB through **named business concepts**
(binding keys), not raw column names. Each binding encodes the full resolution semantics.

#### Why bindings, not column names?

`reference_price.calculated_mrp_per_kwh` can mean:
- Grid MRP for January 2025 (observation_type='monthly')
- Generator MRP for January 2025 (observation_type='generator')
- Annual weighted average for OY3

A column name is not a query. The billing engine needs: **which table, which row,
what aggregation, what derivation, and what the value MEANS.** Bindings encode all this.

#### Binding structure

Each binding defines:

| Field | Purpose |
|---|---|
| `binding_key` | Named business concept (e.g., `grid_mrp`, `annual_guarantee`) |
| `source_kind` | `db_column`, `logic_parameter`, `derived`, `source_metadata` |
| `table` + `column` | Actual DB location |
| `required_filters` | Row filter (e.g., `{"observation_type": "monthly"}`) |
| `time_grain` | `billing_month`, `operating_year`, `static`, `derived` |
| `aggregation` | `None` (single row), `SUM`, `AVG` |
| `fallback_order` | e.g., `["billing_month", "operating_year"]` — try monthly first |
| `derivation_rule` | For derived values: e.g., `annual_guarantee / 12` |
| `compiles_to_lp_key` | Which `logic_parameters` key this maps to for runtime |
| `compiles_to_engine` | Which engine service reads this value |

#### Key bindings showing resolution nuances

| Binding Key | Resolves To | Filter | Time | Notes |
|---|---|---|---|---|
| `grid_mrp` | `reference_price.calculated_mrp_per_kwh` | `observation_type=monthly` | billing_month | Grid utility MRP |
| `generator_mrp` | same column | `observation_type=generator` | billing_month | Generator fuel-based MRP |
| `monthly_metered_energy` | `meter_aggregate.energy_kwh` | — | billing_month | Raw metered (E_metered) |
| `annual_metered_energy` | same column | — | operating_year | SUM across OY months |
| `billing_energy_output` | `meter_aggregate.total_production` | — | billing_month | Confirmed billing energy (Energy Output) |
| `annual_billing_energy_output` | same column | — | operating_year | SUM across OY months |
| `grid_period_energy` | `meter_aggregate.energy_kwh` | `energy_source=grid` | billing_month | Grid hours only |
| `generator_period_energy` | same column | `energy_source=generator` | billing_month | Generator hours only |
| `effective_tariff_monthly` | `tariff_rate.effective_rate_contract_ccy` | — | billing_month | Fallback: try monthly → annual |
| `monthly_guarantee` | (derived) | — | derived | `annual_guarantee / 12` or monthly schedule |
| `base_rate` | `clause_tariff.base_rate` | — | static | Year-1 only; compiles to LP key |

#### Compilation: same source → three outputs

The compiler reads bindings and produces SYNCHRONIZED outputs:

```
Resolved bindings
  ├─→ clause_tariff.logic_parameters  (runtime engine: rebased_market_price_engine)
  ├─→ tariff_formula.variables        (dashboard: provenance + audit trail)
  └─→ tariff_rate / production_guarantee  (rate schedule)
```

These three outputs are compiled from the SAME bindings. They CANNOT diverge.

### Formula Components (Composable Templates)

**File:** `services/pricing/formula_components.py` (26 components, 10 compositions)

Instead of monolithic contract-type templates, formula families are composed:

| Component | formula_type | Used By |
|---|---|---|
| `payment_simple` | PAYMENT_CALCULATION | Kenya SSA, CPI, ESA |
| `mrp_bounded_single` | MRP_BOUNDED | Ghana single-source |
| `mrp_bounded_dual_source` | MRP_BOUNDED | NBL01, NBL02, GBL01 |
| `mrp_calculation_grid` | MRP_CALCULATION | NBL01, NBL02 |
| `mrp_calculation_generator` | MRP_CALCULATION | NBL01, NBL02 |
| `deemed_energy_canonical` | DEEMED_ENERGY | Kenya SSA, Ghana SSA |
| `deemed_energy_pr_based` | DEEMED_ENERGY | Ghana PPA (ABI01) |
| `deemed_energy_pr_actual` | DEEMED_ENERGY | CAL01 (actual PR from metered data, reference PR fallback) |
| `energy_output_annual` | ENERGY_OUTPUT | All SSA projects |
| `energy_output_monthly` | ENERGY_OUTPUT | All SSA projects |
| `shortfall_rate_differential` | SHORTFALL_PAYMENT | Kenya SSA, Ghana SSA |
| `shortfall_replacement_cost` | SHORTFALL_PAYMENT | Unilever SSA |
| `take_or_pay` | TAKE_OR_PAY | LOI01, ERG |
| `percentage_escalation` | PERCENTAGE_ESCALATION | Kenya SSA |
| `cpi_escalation` | CPI_ESCALATION | CPI projects |
| `green_energy_output` | ENERGY_OUTPUT | CAL01 (Max(metered, Min(cap, metered+deemed))) |
| `make_whole_availability` | SHORTFALL_PAYMENT | CAL01 (availability-based make-whole, BCOE tariff) |
| `availability_ld` | SHORTFALL_PAYMENT | GC001 |
| `wheeling_payment` | PAYMENT_CALCULATION | BNT01 (Rwanda wheeling) |
| `energy_output_wheeling_monthly` | ENERGY_OUTPUT | BNT01 |
| `energy_output_wheeling_biannual` | ENERGY_OUTPUT | BNT01 |
| `shortfall_output_regulated` | SHORTFALL_PAYMENT | BNT01 |
| `peak_excess_energy` | PAYMENT_CALCULATION | BNT01 |
| `excess_energy_biannual` | PAYMENT_CALCULATION | BNT01 |
| `deemed_energy_pr_interval` | DEEMED_ENERGY | BNT01 |
| `available_energy_discount` | AVAILABLE_ENERGY_DISCOUNT | XF-AB (XFAB, XFBV, XFSS, XFL01) |

Compositions per contract type:

```python
"CBE_SSA_KENYA": [payment_simple, deemed_energy_canonical, energy_output_annual,
                  energy_output_monthly, shortfall_rate_differential, percentage_escalation]

"CBE_SSA_GHANA_FLOATING_DUAL": [mrp_bounded_dual_source, mrp_calculation_grid,
                                 mrp_calculation_generator, deemed_energy_canonical,
                                 energy_output_monthly, shortfall_rate_differential]

"CPI_ESCALATED_AVAILABILITY": [payment_simple, green_energy_output,
                               deemed_energy_pr_actual, make_whole_availability,
                               cpi_escalation]
# CPI-escalated PPA with availability guarantee (CAL01 — Blanket Mine):
# - Flat tariff (13.4 USc/kWh) escalated annually by US CPI
# - Green Energy = Max(metered, Min(forecast_cap, metered + deemed))
# - Deemed Energy from actual PR × P_DC × Irr × τ (10-min intervals)
# - Make-Whole Payment when Achieved Availability < 90%:
#   Payment = (BCOE - Tariff) × E_metered × (A_guarantee/A_achieved - 1)
#   Capped at USD 420,000/yr
# - BCOE = blended cost of grid + genset energy (proposed by Buyer annually)
# - Annexure E forecast production as monthly Green Energy cap

"RWANDA_WHEELING": [wheeling_payment, energy_output_wheeling_monthly,
                    energy_output_wheeling_biannual, shortfall_output_regulated,
                    peak_excess_energy, excess_energy_biannual, deemed_energy_pr_interval]
# Three-party wheeling (Izuba → EUCL → Customer). Unique mechanics:
# - Wheeling charge at flat rate (USD 0.02/kWh)
# - Monthly EO = Delivered + Deemed; Bi-annual EO = Σ monthly × (1 - 3% loss)
# - Shortfall at regulated tariff (EUCL), capped USD 84k/yr
# - Peak excess energy payment (floor 96 MWh, threshold 144 MWh)
# - Bi-annual excess energy reconciliation
# - Deemed energy with interval duration factor (PR × Cap × Time × Irr)
```

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
| Output role mapping | Payment formula outputs must map to `invoice_line_item.line_total_amount`, not rate columns |
| No null maps_to | Every variable MUST have a `maps_to` pointing to a real DB source (see rules below) |
| No duplicate maps_to without filter | Two input variables sharing same `maps_to` MUST have distinct `filter` values |
| Column existence | Every `maps_to` must point to an actual DB column, `logic_parameters.*` key, or `source_metadata.*` key |

### Variable Mapping Integrity Rules (Mandatory)

These rules are enforced by the strict validator and must be followed for all new formulas.

#### Rule 1: No null maps_to — every variable must trace to a DB source

If a value is derived (e.g., `Additional Energy Output = Actual - Minimum`), break it into
its constituent inputs that DO have DB sources. Make the derivation explicit in `formula_text`.

| WRONG | RIGHT |
|---|---|
| `{"symbol": "Additional Energy", "maps_to": null}` | `{"symbol": "Actual Energy Output", "maps_to": "meter_aggregate.total_production"}` + `{"symbol": "Minimum Energy Output", "maps_to": "production_guarantee.guaranteed_kwh"}` with formula `Payment = MAX(0, Actual - Minimum) × Tariff` |
| `{"symbol": "N", "maps_to": null}` | `{"symbol": "N", "maps_to": "clause_tariff.logic_parameters.oy_start_date", "description": "Derived: N = floor((billing_date - oy_start_date) / 365) + 1"}` |
| `{"symbol": "Monthly Guarantee", "maps_to": null}` | `{"symbol": "Annual Guarantee", "maps_to": "production_guarantee.guaranteed_kwh", "description": "Pro-rated: annual / 12 or per contract monthly schedule"}` |

#### Rule 2: Correct column names — use actual DB schema

| WRONG maps_to | CORRECT maps_to | Why |
|---|---|---|
| `invoice_line_item.amount` | `invoice_line_item.line_total_amount` | Column doesn't exist |
| `production_guarantee.minimum_offtake_kwh` | `production_guarantee.guaranteed_kwh` | Column doesn't exist |
| `project.capacity_kwp` | `project.installed_dc_capacity_kwp` | Column doesn't exist |
| `meter_aggregate.metered_energy_kwh` | `meter_aggregate.energy_kwh` | Column doesn't exist — use `energy_kwh` for raw metered |
| `meter_aggregate.historical_energy_kwh` | `meter_aggregate.energy_kwh` | Column doesn't exist — use `energy_kwh` for raw metered |
| `tariff_formula.DEEMED_ENERGY` | `meter_aggregate.available_energy_kwh` | Invented cross-reference |

#### Rule 3: Same column, different business meaning → use filter

When two variables in the same formula map to the same `table.column` but represent
different real-world values, they MUST have distinct `filter` values.

| Variable pair | Same column | Correct filters |
|---|---|---|
| `Irr(x)` vs `Irr_hist` | `meter_aggregate.ghi_irradiance_wm2` | `{"period": "current"}` vs `{"period": "reference"}` |
| Grid MRP vs Generator MRP | `reference_price.calculated_mrp_per_kwh` | `{"observation_type": "monthly"}` vs `{"observation_type": "generator"}` |
| Grid energy vs Generator energy | `meter_aggregate.energy_kwh` | `{"energy_source": "grid"}` vs `{"energy_source": "generator"}` |

#### Rule 4: Derived values → use the source binding, describe the derivation

For values that don't exist as a single column but are computed at runtime,
map to the **source input** the engine reads, and describe the derivation in `description`.

| Business concept | Source binding | Description |
|---|---|---|
| Operating year N | `clause_tariff.logic_parameters.oy_start_date` | `N = floor((billing_date - oy_start_date) / 365) + 1` |
| Monthly guarantee | `production_guarantee.guaranteed_kwh` | `annual / 12 or per contract monthly schedule` |
| Additional energy (above minimum) | `meter_aggregate.total_production` + `production_guarantee.guaranteed_kwh` | `MAX(0, actual - minimum)` — break into two explicit variables |

#### Rule 5: Payment outputs → invoice_line_item.line_total_amount

ALL formula outputs that produce a monetary payment amount map to
`invoice_line_item.line_total_amount`. Never to `tariff_rate.effective_rate_contract_ccy`
(that's a per-kWh rate, not a total amount).

#### Rule 6: Current rate vs base rate

| Use case | Correct maps_to | WRONG |
|---|---|---|
| Payment formula (current month) | `tariff_rate.effective_rate_contract_ccy` | `clause_tariff.base_rate` (year-1 only) |
| Escalation formula (base input) | `clause_tariff.base_rate` | `tariff_rate.effective_rate_contract_ccy` |

`clause_tariff.base_rate` is the year-1 contract rate — static. For any formula that
calculates a current-period payment, use `tariff_rate.effective_rate_contract_ccy` which
holds the escalated/bounded rate for the billing period.

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
    variables             JSONB NOT NULL DEFAULT '[]',  -- [{symbol, binding_key, role, variable_type, units, maps_to, lookup_key, filter, description, resolution_metadata}]
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

**Formula Type Taxonomy (15 types across 5 categories):**

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
| billing | `AVAILABLE_ENERGY_DISCOUNT` | Discount = IF(E_avail > (E_met + E_avail) × threshold, -(E_met + E_avail) × threshold, -E_avail) |

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
| Performance Ratio (PR) — reference table | `input` | Read from `clause_tariff.logic_parameters.performance_ratio_monthly` (static fallback) |
| Performance Ratio (PR) — actual computed | `input` | Read from `plant_performance.actual_pr` (primary source when contract says "computed from metered data") |
| Plant capacity (Cap) | `input` | Read from `project.capacity_kwp` |
| Operating year number (N) | `input` | Derived at runtime from billing period |
| Irradiance, metered energy, available energy | `input` | Read from `meter_aggregate` for billing period |

**Rule of thumb:** if the value comes from ANY database table, it is `input`. Use
`parameter` ONLY for literal numeric constants that are truly fixed for the life of
the contract AND appear as bare numbers in the formula (e.g., exponent `1` in
`(1 + pct)^(N-1)`). In practice, almost nothing should be `parameter`.

### Contextual role rule (Lesson from CAL01)

**A variable's role is relative to the formula it appears in, not its role in the
broader formula chain.** A value can be the output of one formula and an input to another.

| Variable | In DEEMED_ENERGY formula | In ENERGY_OUTPUT formula | In PAYMENT formula |
|---|---|---|---|
| `available_energy_kwh` | `output` (formula produces it) | `input` (formula consumes it) | N/A |
| `total_production` (Energy Output) | N/A | `output` (formula produces it) | `input` (formula consumes it) |
| `energy_kwh` (metered) | `input` | `input` | `input` (always input) |

The `default_role` on a binding key is a hint, not a rule. Components MUST use
`role_override` when the formula context differs from the binding's default.

### maps_to rules

| Variable type | Correct maps_to | WRONG maps_to |
|---|---|---|
| Payment amount output | `invoice_line_item.amount` | `tariff_rate.effective_rate_contract_ccy` (that's a rate, not an amount) |
| Performance Ratio (PR) | `clause_tariff.logic_parameters.performance_ratio_monthly` | `production_forecast.degradation_factor` (different concept) |
| Current-year effective rate | `tariff_rate.effective_rate_contract_ccy` | `clause_tariff.base_rate` (that's year-1 only) |
| Shortfall payment output | `invoice_line_item.amount` | `production_guarantee.guaranteed_kwh` (that's an energy value) |
| Escalation percentage | `clause_tariff.logic_parameters.escalation_pct` | hardcoded in formula_text |
| Escalation fixed amount | `clause_tariff.logic_parameters.escalation_amount` | hardcoded in formula_text |

### Distinct variables must have distinct maps_to

**If a formula has two variables that represent different real-world values, they MUST map to
different DB sources.** No two variables should share the same `maps_to` unless they genuinely
read the same data point. When two variables map to the same `table.column`, use the `filter`
field to differentiate.

### MRP & Dual-Source (Grid vs Generator) Treatment

**Core principle: ALL MRP-related values live in `reference_price`, never in `clause_tariff.logic_parameters`.**

Dual-source projects (GBL01, NBL01, NBL02) have separate Grid and Generator reference prices.
Both are stored in `reference_price` table, differentiated by `observation_type`:

#### MRP_CALCULATION formulas (compute the reference prices)

**Grid Reference Price** (`observation_type = 'grid'`):

| Variable | maps_to | filter |
|---|---|---|
| Grid Reference Price (output) | `reference_price.calculated_mrp_per_kwh` | `{"observation_type": "grid"}` |
| total variable charges | `reference_price.total_variable_charges` | `{"observation_type": "grid"}` |
| total kWh invoiced | `reference_price.total_kwh_invoiced` | `{"observation_type": "grid"}` |

**Generator Reference Price** (`observation_type = 'generator'`):

| Variable | maps_to | filter |
|---|---|---|
| Generator Reference Price (output) | `reference_price.calculated_mrp_per_kwh` | `{"observation_type": "generator"}` |
| diesel fuel price | `reference_price.source_metadata.diesel_fuel_price_per_litre` | `{"observation_type": "generator"}` |
| total kWh generator | `reference_price.total_kwh_invoiced` | `{"observation_type": "generator"}` |
| genset efficiency | `clause_tariff.logic_parameters.genset_efficiency` | — (static contract constant) |
| surcharge factor | `clause_tariff.logic_parameters.genset_surcharge_factor` | — (static contract constant) |

#### MRP_BOUNDED formula (calculates the bounded payment)

| Variable | maps_to | filter |
|---|---|---|
| Energy OutputGrid | `meter_aggregate.energy_kwh` | `{"energy_source": "grid"}` |
| Energy OutputGenerator | `meter_aggregate.energy_kwh` | `{"energy_source": "generator"}` |
| Grid Reference Price | `reference_price.calculated_mrp_per_kwh` | `{"observation_type": "grid"}` |
| Generator Reference Price | `reference_price.calculated_mrp_per_kwh` | `{"observation_type": "generator"}` |
| Solar Discount Grid | `clause_tariff.logic_parameters.discount_pct_grid` | — |
| Solar Discount Generator | `clause_tariff.logic_parameters.discount_pct_generator` | — |
| Minimum Solar Price (floor) | `clause_tariff.logic_parameters.floor_rate` | — |
| Maximum Solar Price (ceiling) | `clause_tariff.logic_parameters.ceiling_rate` | — |

#### Table separation principle

| Data type | Table | Why |
|---|---|---|
| MRP inputs (charges, kWh, fuel prices) | `reference_price` | Per-period MRP components |
| MRP output (calculated rate) | `reference_price.calculated_mrp_per_kwh` | Computed MRP |
| Raw metered energy (E_metered) | `meter_aggregate.energy_kwh` | Raw meter readings |
| Billing energy output (Energy Output) | `meter_aggregate.total_production` | Confirmed billing energy after MOG conditional |
| Contract constants (efficiency, surcharge, discount) | `clause_tariff.logic_parameters` | Static across billing periods |
| Floor/ceiling rates | `clause_tariff.logic_parameters` | Static (or CPI-escalated) |

**WRONG patterns:**
- ✗ Diesel fuel price in `clause_tariff.logic_parameters` — it's a per-period MRP input
- ✗ Generator kWh in `clause_tariff.logic_parameters` — it's a per-period value
- ✗ Grid and Generator Reference Price sharing `maps_to` without `filter`
- ✗ Grid and Generator energy sharing `maps_to` without `filter`

#### Formula chain for dual-source billing engine

```
1. MRP_CALCULATION (Grid)    → reference_price row (observation_type='grid')
   inputs: utility invoices (total_variable_charges, total_kwh_invoiced)
   output: calculated_mrp_per_kwh

2. MRP_CALCULATION (Generator) → reference_price row (observation_type='generator')
   inputs: diesel price, efficiency, surcharge
   output: calculated_mrp_per_kwh

3. MRP_BOUNDED (Payment)     → invoice_line_item.amount
   inputs: Grid MRP + Generator MRP + metered energy + discounts + floor/ceiling
   output: MAX(Floor, MIN(Discounted, Ceiling))
```

### lookup_key rules

**The lookup_key is determined by the formula's temporal scope, not the source table.**

| Formula scope | All variables use | Exception |
|---|---|---|
| Annual (Annual Energy Output, Shortfall Payment) | `operating_year` | `clause_tariff.*`, `project.*` → null (static) |
| Monthly (Monthly Energy Output, Monthly Payment, Deemed Energy) | `billing_month` | `clause_tariff.*`, `project.*` → null (static) |
| Escalation | output → `operating_year` | base/pct inputs → null (static from clause_tariff) |

**CRITICAL:** An annual shortfall formula reads `meter_aggregate.energy_kwh` (raw metered) summed
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

## Amendment Processing (Planned)

When a contract amendment changes pricing terms, Step 11P creates a **new `clause_tariff` version**
that supersedes the original. The original tariff and its formulas are preserved for audit.

### Schema

`clause_tariff.supersedes_tariff_id` already exists in the schema. No migration needed.

### Flow

1. Parse amendment PDF through Step 11P (same pipeline, `--amendment N` flag)
2. Extract only changed pricing terms
3. Mark current `clause_tariff.is_current = false`
4. INSERT new `clause_tariff` row:
   - `contract_amendment_id` = amendment.id
   - `version` = previous.version + 1
   - `supersedes_tariff_id` = previous.id
   - Copy unchanged fields from previous, overlay changed fields
5. INSERT `tariff_formula` rows for new `clause_tariff_id`:
   - Copy unchanged formulas from previous clause_tariff_id
   - Override/add changed formulas from amendment extraction
6. Old `tariff_formula` rows remain untouched (linked to old `clause_tariff_id`, historical audit)
7. Recalculate `tariff_rate` rows from amendment effective_date forward

### Key Principles

- Each amendment creates a **new** `clause_tariff` row — never overwrite the original
- `tariff_formula` rows are version-specific — old formulas stay for audit
- The `supersedes_tariff_id` chain provides full version history
- Only `is_current = true` tariff is used by the billing engine

### Known Projects with Amendments

| Project | Amendments | Notes |
|---|---|---|
| KAS01 | 3 | Phase II, Reinforcement Works, Interconnection Works |
| Others | TBD | To be identified during portfolio rollout |

---

## Corrections Log

Reference of all corrections applied during pilot (MB01, KAS01, MOH01). These inform
the rules above and are now enforced in the prompt + decomposer + validator.

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | `formula_type: "pricing"` instead of `"MRP_BOUNDED"` | Claude used category names | Added alias map in extractor + explicit enum list in prompt |
| 2 | `CureMechanism.description: null` | Claude returns null for Optional str | Made str fields `Optional[str]` in Pydantic model |
| 3 | `tariff_rate` year column name | Was `contract_year`, now renamed to `operating_year` (migration 066) | Column is `operating_year` |
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
| 19 | Energy Output `role=output` in payment formula (CAL01) | Binding default_role leaked — `billing_energy_output` has `default_role=output` | Added `role_override="input"` to `payment_simple` component + validator Check 8 |
| 20 | `E_deemed` `role=output` in ENERGY_OUTPUT formula (CAL01) | Same binding leak — `monthly_available_energy` has `default_role=output` | Added `role_override="input"` to `green_energy_output` component + validator Check 10 |
| 21 | `PR_month` mapped to static LP instead of actual PR (CAL01) | Contract says PR is computed from actual metered data; LP reference table is fallback only | New binding `actual_pr_monthly` → `plant_performance.actual_pr`, new component `deemed_energy_pr_actual` |
| 22 | Missing `τ_i` in deemed energy variables (CAL01) | Interval duration in formula_text but absent from variables array | Added to `deemed_energy_pr_based` and `deemed_energy_pr_actual` components |
| 23 | `E_i` mapped to raw metered energy in Make-Whole (CAL01) | E_i is Make-Whole Energy (derived), not raw E_metered | Expanded formula_text to show derivation; mapped to constituent inputs |
| 24 | `availability_guarantee_pct` not stored in LP (CAL01) | Extraction didn't populate the value | Added to LP patch (0.90 = 90%) |

---

## File Structure

```
python-backend/
|-- services/
|   +-- pricing/                              # Pricing compiler module
|       |-- __init__.py
|       |-- resolver_registry.py              # Layer 1: Semantic variable bindings (48 bindings)
|       |-- formula_components.py             # Layer 2: Composable formula templates (26 components, 10 compositions)
|       |-- contract_classifier.py            # Layer 3: Contract type classification
|       |-- template_resolver.py              # Layer 4: Symbol → binding matching
|       |-- formula_compiler.py               # Layer 5: Compile to runtime + display + rates
|       |-- strict_validator.py               # Layer 6: Hard-stop validation + quarantine
|       |-- section_isolator.py               # OCR section isolation (optional)
|       |-- pricing_extractor.py              # Claude API wrapper (raw extraction only)
|       |-- formula_decomposer.py             # (Legacy) Direct decomposition — being replaced by compiler
|       +-- pricing_validator.py              # (Legacy) Soft validation — being replaced by strict_validator
|-- services/prompts/
|   +-- pricing_extraction_prompt.py          # Claude prompt (raw extraction, no DB mapping)
|-- models/
|   +-- pricing.py                            # Pydantic models
|-- scripts/
|   +-- step11p_pricing_extraction.py         # Orchestrator
|-- tests/
|   +-- pricing/                              # Regression tests
|       +-- test_formula_bindings.py          # Golden fixtures from corrected projects
+-- database/
    +-- migrations/
        +-- 062_tariff_formula.sql            # tariff_formula table + amendment versioning
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

## Compiler Outputs (Synchronized)

The compiler produces three synchronized outputs from the SAME semantic bindings:

| Output | Table | Purpose | Consumed By |
|---|---|---|---|
| Runtime config | `clause_tariff.logic_parameters` | Billing engine input | `rebased_market_price_engine.py`, `tariff_rate_service.py` |
| Dashboard provenance | `tariff_formula.variables` | Human-readable formula display + audit | `entities.py` dashboard endpoint, `PricingTariffsTab.tsx` |
| Rate schedule | `tariff_rate`, `production_guarantee` | Pre-computed rates + energy guarantees | `tariff_rate_service.py`, performance service |

### Variable JSONB structure (with provenance)

```json
{
  "symbol": "Grid Reference Price",
  "binding_key": "grid_mrp",
  "role": "input",
  "variable_type": "PRICE",
  "units": "per_kwh",
  "maps_to": "reference_price.calculated_mrp_per_kwh",
  "lookup_key": "billing_month",
  "filter": {"observation_type": "monthly"},
  "description": "Grid MRP: sum of utility variable charges / total kWh invoiced",
  "resolution_metadata": {
    "source_kind": "db_column",
    "time_grain": "billing_month",
    "aggregation": null,
    "fallback_order": null,
    "compiles_to_lp_key": null,
    "compiles_to_engine": "rebased_market_price_engine",
    "resolver_version": "1.0.0"
  }
}
```

The `binding_key` + `resolution_metadata` enable:
- Re-resolution when schema changes (re-run resolver, recompile)
- Audit trail (which binding version produced this mapping)
- Engine traceability (which service reads this value)

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
| **Monthly Billing** | available_energy_method, interval_minutes, irradiance_threshold, shortfall formula, take-or-pay params, available_energy_discount (curtailment allowance) |
| **Plant Performance** | guaranteed_kwh, excused_events, shortfall_excused_events |
| **Overview** | OY definition, payment terms (enrichment only) |

---

## Dashboard Verification Checklist

After extraction or re-extraction, verify the Pricing & Tariffs tab displays correctly
for every affected project. This checklist can be run as a SQL audit or visual review.

### Step V1: Product-to-Tariff Matching

Verify every billing product matches to the correct tariff via `energy_sale_type_code`.

```sql
-- Show product → tariff mapping gaps
SELECT p.sage_id, bp.name AS product_name,
       CASE
         WHEN bp.name ~* 'energy|metered|available' THEN 'ENERGY_SALES/ENERGY_AS_SERVICE'
         WHEN bp.name ~* 'bess|battery' THEN 'BESS_LEASE'
         WHEN bp.name ~* 'equipment|rental|lease|rent' THEN 'EQUIPMENT_RENTAL_LEASE'
         WHEN bp.name ~* 'loan' THEN 'LOAN'
         WHEN bp.name ~* 'o\s*&\s*m|maintenance|service|diesel|fuel|penal' THEN 'OTHER_SERVICE'
         ELSE 'NO MATCH (fallback to all)'
       END AS expected_type,
       est.code AS actual_tariff_type,
       ct.name AS tariff_name,
       ct.id AS clause_tariff_id
FROM contract_billing_product cbp
JOIN billing_product bp ON bp.id = cbp.billing_product_id
JOIN contract c ON c.id = cbp.contract_id AND c.parent_contract_id IS NULL
JOIN project p ON p.id = c.project_id
LEFT JOIN clause_tariff ct ON ct.contract_id = c.id AND ct.is_current = true
LEFT JOIN energy_sale_type est ON est.id = ct.energy_sale_type_id
ORDER BY p.sage_id, bp.name;
```

**What to check:**
- Every energy product (metered, available) should match a tariff with `ENERGY_SALES` or `ENERGY_AS_SERVICE`
- Non-energy products (BESS, rent, O&M, loan) should match tariffs with their corresponding type
- Products with `NO MATCH` will show ALL tariffs as fallback — add a regex rule in `helpers.ts` if needed

### Step V2: Formula-to-Tariff Placement

Verify each formula sits on the correct `clause_tariff_id`.

```sql
-- Check formula placement: formula_type should be on the right tariff type
SELECT p.sage_id, ct.name AS tariff_name, est.code AS tariff_type,
       tf.formula_type, tf.formula_name, tf.id AS formula_id
FROM tariff_formula tf
JOIN clause_tariff ct ON ct.id = tf.clause_tariff_id
JOIN project p ON p.id = ct.project_id
LEFT JOIN energy_sale_type est ON est.id = ct.energy_sale_type_id
WHERE tf.is_current = true
ORDER BY p.sage_id, ct.id, tf.formula_type;
```

**Rules:**
- Energy formulas (`PAYMENT_CALCULATION`, `MRP_BOUNDED`, `DEEMED_ENERGY`, `ENERGY_OUTPUT`, `SHORTFALL_PAYMENT`, `TAKE_OR_PAY`, `AVAILABLE_ENERGY_DISCOUNT`) should be on `ENERGY_SALES` or `ENERGY_AS_SERVICE` tariffs
- Escalation formulas should match the tariff they escalate (rent escalation → `EQUIPMENT_RENTAL_LEASE`, energy escalation → `ENERGY_SALES`)
- BESS formulas should be on `BESS_LEASE` tariffs

### Step V3: Duplicate Detection

```sql
-- Duplicate formulas: same tariff + same type + same name
SELECT p.sage_id, tf.clause_tariff_id, tf.formula_type, tf.formula_name,
       COUNT(*) AS cnt, string_agg(tf.id::text, ', ') AS formula_ids
FROM tariff_formula tf
JOIN clause_tariff ct ON ct.id = tf.clause_tariff_id
JOIN project p ON p.id = ct.project_id
WHERE tf.is_current = true
GROUP BY p.sage_id, tf.clause_tariff_id, tf.formula_type, tf.formula_name
HAVING COUNT(*) > 1;
```

**If duplicates found:** Check if they're semantically different (different `formula_text` or `section_ref`). If truly identical, delete the duplicate. If different, rename to distinguish (e.g., "Base Rate Escalation" vs "Rent Escalation").

### Step V4: Formula Completeness

Every project with active energy tariffs should have a minimum formula set.

```sql
-- Projects missing expected formulas
SELECT p.sage_id, ct.id AS clause_tariff_id, est.code AS tariff_type,
       (SELECT string_agg(DISTINCT tf.formula_type, ', ' ORDER BY tf.formula_type)
        FROM tariff_formula tf WHERE tf.clause_tariff_id = ct.id AND tf.is_current = true) AS formula_types,
       (SELECT count(*) FROM tariff_formula tf WHERE tf.clause_tariff_id = ct.id AND tf.is_current = true) AS formula_count
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
JOIN clause_tariff ct ON ct.contract_id = c.id AND ct.is_current = true
LEFT JOIN energy_sale_type est ON est.id = ct.energy_sale_type_id
WHERE est.code IN ('ENERGY_SALES', 'ENERGY_AS_SERVICE')
ORDER BY p.sage_id;
```

**Minimum expected formulas per tariff type:**

| Tariff Type | Minimum formulas | Expected types |
|---|---|---|
| `ENERGY_SALES` (Kenya SSA) | 4-6 | PAYMENT_CALCULATION, DEEMED_ENERGY, ENERGY_OUTPUT, SHORTFALL_PAYMENT, PERCENTAGE_ESCALATION |
| `ENERGY_SALES` (Ghana MRP) | 4-6 | MRP_BOUNDED, DEEMED_ENERGY, ENERGY_OUTPUT, SHORTFALL_PAYMENT |
| `ENERGY_SALES` (Nigeria dual) | 6 | MRP_BOUNDED, MRP_CALCULATION (×2), DEEMED_ENERGY, ENERGY_OUTPUT, SHORTFALL_PAYMENT |
| `ENERGY_AS_SERVICE` | 2-5 | PAYMENT_CALCULATION or TAKE_OR_PAY, SHORTFALL_PAYMENT |
| `BESS_LEASE` | 0-2 | PAYMENT_CALCULATION, PERCENTAGE_ESCALATION |
| `EQUIPMENT_RENTAL_LEASE` | 0-2 | PERCENTAGE_ESCALATION, SHORTFALL_PAYMENT (if performance guarantee) |

### Step V5: Frontend Deduplication Check

Formulas should appear **once** per product section, under the primary product card only when multiple products share the same tariff. The "Contract Formulas — Full Reference" section at the bottom always shows all formulas regardless.

**Visual check per project:**
1. Open Pricing & Tariffs tab
2. Expand each billing product card
3. Verify formulas appear only under the primary product (not duplicated under Available Energy, Minimum Offtake, etc.)
4. Verify the "Contract Formulas — Full Reference" section lists all formulas exactly once
5. Verify formula type badges have correct colours (blue=pricing, violet=escalation, emerald=energy, amber=performance, red=discount)

### Step V6: Formula Type Labels

Every `formula_type` used in `tariff_formula` must have an entry in `FORMULA_TYPE_LABELS` and `FORMULA_CATEGORY_STYLE` in `PricingTariffsTab.tsx`. Unknown types fall back to raw string + grey badge.

```sql
-- Find formula types not in the frontend label map
SELECT DISTINCT tf.formula_type
FROM tariff_formula tf WHERE tf.is_current = true
ORDER BY tf.formula_type;
```

Compare against the `FORMULA_TYPE_LABELS` object in `PricingTariffsTab.tsx` (currently 16 types).

### Step V7: `logic_parameters` Consistency

Verify `clause_tariff.logic_parameters` keys used by the billing engine are present where expected.

```sql
-- Check available_energy_discount config (XF-AB projects)
SELECT p.sage_id, ct.id,
       ct.logic_parameters->'available_energy_discount' AS discount_config,
       ct.logic_parameters->'performance_ratio_monthly' AS pr_monthly,
       ct.logic_parameters->'billing_taxes' IS NOT NULL AS has_billing_taxes
FROM clause_tariff ct
JOIN project p ON p.id = ct.project_id
WHERE ct.is_current = true
  AND p.sage_id IN ('XFAB', 'XFBV', 'XFL01', 'XFSS')
ORDER BY p.sage_id;
```

**Key `logic_parameters` entries to verify:**
- `billing_taxes` — required for invoice generation (levies, VAT, withholdings)
- `available_energy_discount` — present for XF-AB projects
- `performance_ratio_monthly` — present for projects with deemed energy
- `mrp_method`, `discount_pct`, `floor_rate`, `ceiling_rate` — present for MRP-bounded projects
