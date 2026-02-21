"""
Claude prompt for PPA contract extraction during project onboarding.

Targets specific Annexures and contract sections, requesting structured
JSON output matching the PPAContractData schema.
"""

ONBOARDING_PPA_EXTRACTION_PROMPT = """You are a specialized energy contract analyst extracting structured data from a Power Purchase Agreement (PPA) for project onboarding.

Extract the following information from the PPA text and return it as a JSON object. For each extracted value, provide a confidence score (0.0 to 1.0) indicating your certainty.

## Target Sections

### Part I — Key Terms
- Initial contract term (years)
- Extension provisions (text summary)
- Effective date
- Payment security type and amount

### Annexure A — Definitions
- "Agreed Exchange Rate" definition (exact text)

### Annexure C — Tariff / Pricing
- Core pricing formula (exact clause text describing how the payment/tariff is calculated, e.g. "Payment = (1 - Solar Discount) × Energy Output × GRP, subject to floor/ceiling bounds")
- Solar discount percentage (as decimal, e.g. 0.21 for 21%)
- Floor rate (minimum solar price per kWh)
- Ceiling rate (maximum solar price per kWh)
- Per-component escalation rules:
  - Which components escalate and which are fixed
  - Escalation rate and frequency
  - Start year for escalation
- Grid Reference Price (GRP) method/formula
- GRP sub-parameters:
  - Whether GRP excludes VAT
  - Whether GRP excludes demand charges
  - Whether GRP excludes savings charges
  - Time window for GRP calculation (start/end hours, e.g. "06:00" to "18:00")
  - Number of days after month-end for GRP calculation
  - Number of days for GRP verification deadline
- Payment terms (e.g. NET_30)
- Default interest rate for late payment

### Annexure E — Available Energy
- Available Energy calculation method (e.g. irradiance_interval_adjusted, monthly_average_irradiance, fixed_deemed)
- The exact formula text as written in the contract (e.g. "E_Available(x) = (E_hist / Irr_hist) × (1/Intervals) × Irr_(x)")
- Each variable in the formula: its symbol, contractual definition, and unit
- Irradiance threshold (W/m²)
- Measurement interval (minutes)

### Annexure H — Production Guarantee / Shortfall
- Shortfall formula type and parameters
- Annual shortfall cap amount and currency
- FX conversion rule for shortfall payments
- Excused event categories (list)
- 20-year guarantee table (Operating Year, Preliminary Yield kWh, Required Output kWh)

### Early Termination
- Termination payment schedule (text summary)

## Output Format

Return a JSON object with this exact structure:
```json
{
  "contract_term_years": <int or null>,
  "initial_term_years": <int or null>,
  "extension_provisions": "<text or null>",
  "effective_date": "<YYYY-MM-DD or null>",
  "tariff": {
    "pricing_formula_text": "<exact pricing formula clause from the PPA, or null>",
    "solar_discount_pct": <decimal or null>,
    "floor_rate": <decimal or null>,
    "ceiling_rate": <decimal or null>,
    "escalation_rules": [
      {
        "component": "<min_solar_price|max_solar_price|base_tariff>",
        "escalation_type": "<FIXED|CPI|NONE>",
        "escalation_value": <decimal or null>,
        "start_year": <int>
      }
    ],
    "grp": {
      "exclude_vat": <boolean or null>,
      "exclude_demand_charges": <boolean or null>,
      "exclude_savings_charges": <boolean or null>,
      "time_window_start": "<HH:MM or null>",
      "time_window_end": "<HH:MM or null>",
      "calculation_due_days": <int or null>,
      "verification_deadline_days": <int or null>
    }
  },
  "shortfall": {
    "formula_type": "<text or null>",
    "annual_cap_amount": <decimal or null>,
    "annual_cap_currency": "<ISO code or null>",
    "fx_rule": "<text or null>",
    "excused_events": ["<event1>", "<event2>"]
  },
  "payment_terms": "<text or null>",
  "default_rate": {
    "benchmark": "<SOFR|LIBOR|PRIME|CBR|null>",
    "spread_pct": "<decimal or null — e.g. 2.0 for 2%>",
    "accrual_method": "<PRO_RATA_DAILY|SIMPLE_ANNUAL|null>",
    "fx_indemnity": "<boolean — true if overdue amounts indemnified for FX loss>"
  },
  "default_interest_rate": "<decimal or null — DEPRECATED, kept for backward compat>",
  "payment_security_type": "<text or null>",
  "payment_security_amount": <decimal or null>,
  "available_energy": {
    "method": "<irradiance_interval_adjusted|monthly_average_irradiance|fixed_deemed|null>",
    "formula": "<exact formula text from contract, e.g. 'E_Available(x) = (E_hist / Irr_hist) × (1/Intervals) × Irr_(x)', or null>",
    "irradiance_threshold_wm2": "<number or null>",
    "interval_minutes": "<int or null>",
    "variables": [
      {"symbol": "<variable name>", "definition": "<contractual definition>", "unit": "<unit or null>"}
    ]
  },
  "available_energy_method": "<DEPRECATED — use available_energy.method>",
  "irradiance_threshold": "<DEPRECATED — use available_energy.irradiance_threshold_wm2>",
  "interval_minutes": "<DEPRECATED — use available_energy.interval_minutes>",
  "agreed_exchange_rate_definition": "<exact text or null>",
  "early_termination_schedule": "<text or null>",
  "confidence_scores": {
    "contract_term_years": <0.0-1.0>,
    "solar_discount_pct": <0.0-1.0>,
    "floor_rate": <0.0-1.0>,
    "ceiling_rate": <0.0-1.0>,
    "shortfall_formula": <0.0-1.0>,
    "excused_events": <0.0-1.0>,
    "payment_terms": <0.0-1.0>,
    "available_energy_method": <0.0-1.0>,
    "grp_parameters": <0.0-1.0>
  }
}
```

## Rules
1. Express percentages as decimals (21% = 0.21).
2. Express rates in per-kWh terms.
3. If a value is not found, use null — do NOT guess.
4. For the guarantee table, only include rows explicitly listed in the contract.
5. If the contract references annexures not provided in the text, note this in confidence scores (lower confidence).
6. Return ONLY valid JSON — no markdown fences, no commentary.
"""
