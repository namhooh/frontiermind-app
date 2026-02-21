"""
Claude extraction prompt for utility invoice line items.

Used by GRPExtractionService to extract structured data from OCR'd utility invoices.
The extracted line items are classified by type and used to calculate the Grid Reference Price.
"""

GRP_EXTRACTION_PROMPT = """You are an expert at reading utility electricity invoices and extracting structured billing data.

Given the OCR text of a utility invoice, extract ALL charge line items and invoice metadata.

## Classification Rules

Classify each line item into ONE of these types:
- **VARIABLE_ENERGY**: Energy consumption charges billed per kWh (e.g., "Energy Charge", "Active Energy", "kWh charge", "Units consumed"). These are the charges used in GRP calculation.
- **DEMAND**: Demand charges billed per kW/kVA (e.g., "Maximum Demand", "Capacity charge", "kVA charge").
- **FIXED**: Fixed monthly charges not tied to consumption (e.g., "Service charge", "Meter rental", "Connection fee", "Network access charge").
- **TAX**: Taxes, levies, and surcharges (e.g., "VAT", "NHIL", "GETFUND", "ESLA", "Fuel surcharge").

## Time-of-Use Rules

If the invoice shows time-of-use periods, note them:
- **peak**: Typically 6pm–10pm or similar premium hours
- **off_peak**: Typically 10pm–6am or nighttime hours
- **standard**: Typically 6am–6pm or daytime hours
- If no time-of-use distinction, use "flat"

## Billing Period Rules

1. The billing period should reflect the ACTUAL SERVICE DATES — the date range when electricity was consumed, NOT a cycle label or invoice issue date.
2. Look for fields labelled "Period", "Service Period", "From/To", "Billing Period", or "Supply Period".
3. If the invoice shows both a "Cycle" label (e.g., "Cycle: 2025-10") and a "Period" (e.g., "01/09/2025 - 01/10/2025"), use the Period dates — the cycle label is an internal reference, not the service dates.
4. `billing_period_start` = first day of the service period.
5. `billing_period_end` = last day of the service period (NOT the first day of the next month). If the invoice says "01/09/2025 - 01/10/2025", the end is 2025-09-30 (September 30th), because "01/10/2025" means "up to but not including October 1st".
6. If only a single month is evident, set billing_period_start to the 1st and billing_period_end to the last day of that month.

## Output Format

Return ONLY valid JSON with this exact structure:

```json
{
  "invoice_metadata": {
    "invoice_number": "string or null",
    "invoice_date": "YYYY-MM-DD or null",
    "billing_period_start": "YYYY-MM-DD or null",
    "billing_period_end": "YYYY-MM-DD or null",
    "utility_name": "string or null",
    "account_number": "string or null",
    "total_amount": "number or null"
  },
  "line_items": [
    {
      "description": "Original line item description from invoice",
      "type_code": "VARIABLE_ENERGY | DEMAND | FIXED | TAX",
      "amount": 1234.56,
      "kwh": 8000.0,
      "time_of_use": "flat | peak | off_peak | standard",
      "unit_rate": 0.1543,
      "notes": "Any relevant observation about this line item"
    }
  ],
  "extraction_confidence": "high | medium | low",
  "extraction_notes": "Any issues or ambiguities encountered during extraction"
}
```

## Important Rules

1. Extract ALL line items visible on the invoice — do not skip any charges.
2. For VARIABLE_ENERGY items, both `amount` and `kwh` are required. Set to 0 if unreadable.
3. For DEMAND/FIXED/TAX items, `kwh` should be null (not 0).
4. `unit_rate` = amount / kwh for VARIABLE_ENERGY items. Set to null for others.
5. Amounts should be in the invoice's local currency (do not convert).
6. If the invoice has multiple pages, capture line items from ALL pages.
7. Set `extraction_confidence` to "low" if the OCR text is poorly formatted or key values are unclear.

## Invoice Text

{ocr_text}
"""
