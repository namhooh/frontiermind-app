#!/usr/bin/env python3
"""
Step 8: Invoice Calibration & Tax Rule Extraction

Three-phase step:
  Phase A: Extract tax/levy/WHT formulas from invoice PDFs → populate billing_tax_rule
  Phase B: Validate extracted invoice values against DB state → discrepancy report
  Phase C: Populate received_invoice_header + received_invoice_line_item from extractions

Source: CBE_data_extracts/Invoice samples/*.pdf and *.eml (PDF attachments)

Usage:
    python scripts/step8_invoice_calibration.py [--dry-run] [--no-cache] [--project SAGE_ID]
"""

import argparse
import email
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger('step8_invoice_calibration')

INVOICE_DIR = Path(__file__).resolve().parent.parent.parent / 'CBE_data_extracts' / 'Invoice samples'
REPORT_DIR = Path(__file__).resolve().parent.parent / 'reports' / 'cbe-population'
OCR_CACHE_DIR = REPORT_DIR / 'step8_ocr_cache'
ORG_ID = 1

# Known sage_id lookup for filename resolution
# Maps the alphanumeric part after SIN to the canonical sage_id
SAGE_ID_LOOKUP = {
    'AMP01': 'AMP01', 'AR01': 'AR01', 'ABI01': 'ABI01', 'BNT01': 'BNT01',
    'CAL01': 'CAL01', 'ERG': 'ERG', 'GBL01': 'GBL01', 'GC001': 'GC001',
    'IVL01': 'IVL01', 'JAB01': 'JAB01', 'KAS01': 'KAS01', 'LOI01': 'LOI01',
    'MB01': 'MB01', 'MF01': 'MF01', 'MIR01': 'MIR01', 'MOH01': 'MOH01',
    'MP01': 'MP01', 'MP02': 'MP02', 'NBL01': 'NBL01', 'NBL02': 'NBL02',
    'NC02': 'NC02', 'NC03': 'NC03', 'QMM01': 'QMM01', 'TBM01': 'TBM01',
    'TWG01': 'TWG01', 'UGL01': 'UGL01', 'UTK01': 'UTK01', 'UNSOS': 'UNSOS',
    'XFAB': 'XFAB', 'XFBV': 'XFBV', 'XFL01': 'XFL01', 'XFSS': 'XFSS',
    'ZL02': 'ZL02', 'GC00': 'GC001',
}

# Country name → ISO 3166-1 alpha-2 code
COUNTRY_ISO = {
    'Ghana': 'GH', 'Kenya': 'KE', 'Nigeria': 'NG', 'Sierra Leone': 'SL',
    'Madagascar': 'MG', 'Egypt': 'EG', 'Mozambique': 'MZ', 'Rwanda': 'RW',
    'Somalia': 'SO', 'Zimbabwe': 'ZW', 'DRC': 'CD',
}


def _country_to_iso(country_name: str) -> Optional[str]:
    """Convert project.country (full name) to ISO 3166-1 alpha-2 code."""
    if not country_name:
        return None
    return COUNTRY_ISO.get(country_name) or COUNTRY_ISO.get(country_name.title())

# Regex: SIN + alpha + optional digits + optional space + 7 trailing digits
SAGE_ID_PATTERN = re.compile(r'SIN([A-Z]{2,5}\d{0,3})\s*(\d{7})', re.IGNORECASE)


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class InvoiceLineItem(BaseModel):
    description: str = ""
    line_type: str = "other"  # energy|fixed|tax|levy|loan|rental|credit_note|other
    quantity_kwh: Optional[float] = None
    unit_rate: Optional[float] = None
    amount: Optional[float] = None
    notes: Optional[str] = None


class TaxLevyBreakdown(BaseModel):
    code: str = "OTHER"  # WHT|WHVAT|VAT|NHIL|GETFUND|COVID|ETIMS|OTHER
    rate: Optional[float] = None  # decimal, e.g. 0.03
    amount: Optional[float] = None
    base_amount: Optional[float] = None
    applies_to: str = "energy_subtotal"  # energy_subtotal|subtotal_after_levies|grand_total


class TariffBoxParams(BaseModel):
    mrp_rate: Optional[float] = None
    discount_pct: Optional[float] = None
    floor_rate: Optional[float] = None
    ceiling_rate: Optional[float] = None
    solar_tariff: Optional[float] = None


class InvoiceExtraction(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    customer_name: Optional[str] = None
    sage_id: Optional[str] = None
    billing_period_month: Optional[str] = None  # YYYY-MM
    currency: Optional[str] = None
    line_items: List[InvoiceLineItem] = Field(default_factory=list)
    tax_levy_breakdown: List[TaxLevyBreakdown] = Field(default_factory=list)
    tariff_box: Optional[TariffBoxParams] = None
    fx_rate: Optional[float] = None
    fx_currency_pair: Optional[str] = None  # e.g. "USD/GHS"
    subtotal: Optional[float] = None
    tax_total: Optional[float] = None
    grand_total: Optional[float] = None
    extraction_confidence: str = "medium"
    extraction_notes: Optional[str] = None


# ─── Invoice Discovery ───────────────────────────────────────────────────────

def extract_sage_id_from_filename(filename: str) -> Optional[str]:
    """Extract sage_id from invoice filename using SIN{SAGE_ID}{7digits} pattern.

    Handles tricky cases like 'SINGBL 012511024' where sage_id is GBL01 but
    the filename has a space: SIN + GBL + ' ' + 01 + 2511024.
    Strategy: extract the alpha+digit block after SIN, then try progressively
    longer prefixes against the known sage_id lookup.
    """
    m = SAGE_ID_PATTERN.search(filename)
    if not m:
        return None

    raw = m.group(1).strip().upper()
    trailing_digits = m.group(2)  # 7-digit number

    # Direct lookup
    if raw in SAGE_ID_LOOKUP:
        return SAGE_ID_LOOKUP[raw]

    # The filename may split sage_id digits into the trailing number.
    # E.g., SINGBL 012511024 → raw='GBL', trailing='012511024' (but our regex
    # captures 7 digits, so it becomes raw='GBL', trailing='2511024' with
    # the space-separated '01' lost). Let's try prepending digits from
    # the trailing number to the raw part.
    for n in range(1, min(4, len(trailing_digits))):
        candidate = raw + trailing_digits[:n]
        if candidate in SAGE_ID_LOOKUP:
            return SAGE_ID_LOOKUP[candidate]

    # Fallback: return raw as-is
    return raw


def discover_invoices(project_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Find all invoice PDFs in the invoice samples directory."""
    if not INVOICE_DIR.exists():
        log.error(f"Invoice directory not found: {INVOICE_DIR}")
        return []

    invoices = []
    seen_sage_ids = set()

    # Find PDF files
    for pdf_path in sorted(INVOICE_DIR.glob('*.pdf')):
        sage_id = extract_sage_id_from_filename(pdf_path.name)
        if not sage_id:
            log.warning(f"  Could not extract sage_id from: {pdf_path.name}")
            continue
        if project_filter and sage_id != project_filter.upper():
            continue
        invoices.append({
            'path': pdf_path,
            'filename': pdf_path.name,
            'sage_id': sage_id,
            'source': 'pdf',
        })
        seen_sage_ids.add(sage_id)

    # Find EML files with PDF attachments
    for eml_path in sorted(INVOICE_DIR.glob('*.eml')):
        sage_id = extract_sage_id_from_filename(eml_path.name)
        if not sage_id:
            continue
        if project_filter and sage_id != project_filter.upper():
            continue
        # Only use EML if we don't already have a PDF for this sage_id
        if sage_id not in seen_sage_ids:
            pdf_bytes = extract_pdf_from_eml(eml_path)
            if pdf_bytes:
                invoices.append({
                    'path': eml_path,
                    'filename': eml_path.name,
                    'sage_id': sage_id,
                    'source': 'eml',
                    'pdf_bytes': pdf_bytes,
                })
                seen_sage_ids.add(sage_id)

    log.info(f"Discovered {len(invoices)} invoices ({len(seen_sage_ids)} unique projects)")
    return invoices


def extract_pdf_from_eml(eml_path: Path) -> Optional[bytes]:
    """Extract first PDF attachment from an EML file."""
    try:
        with open(eml_path, 'rb') as f:
            msg = email.message_from_bytes(f.read())
        for part in msg.walk():
            ct = part.get_content_type()
            fn = part.get_filename() or ''
            if ct == 'application/pdf' or fn.lower().endswith('.pdf'):
                return part.get_payload(decode=True)
    except Exception as e:
        log.warning(f"  Failed to extract PDF from EML {eml_path.name}: {e}")
    return None


# ─── OCR ──────────────────────────────────────────────────────────────────────

def ocr_invoice(pdf_bytes: bytes, filename: str, use_cache: bool = True) -> str:
    """OCR a PDF via LlamaParse with disk cache."""
    cache_key = hashlib.sha256(filename.encode()).hexdigest()
    cache_path = OCR_CACHE_DIR / f'{cache_key}.md'

    if use_cache and cache_path.exists():
        log.info(f"  OCR cache hit: {filename}")
        return cache_path.read_text()

    log.info(f"  OCR running LlamaParse: {filename}")
    from llama_parse import LlamaParse

    api_key = os.getenv('LLAMA_CLOUD_API_KEY')
    if not api_key:
        raise RuntimeError("LLAMA_CLOUD_API_KEY not set")

    parser = LlamaParse(api_key=api_key, result_type='markdown', num_workers=1)

    # Write to temp file for LlamaParse
    from uuid import uuid4
    tmp_path = Path('/tmp') / f'step8_{uuid4().hex}.pdf'
    try:
        tmp_path.write_bytes(pdf_bytes)
        documents = parser.load_data(str(tmp_path))
        text = '\n\n'.join(doc.text for doc in documents)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # Cache the result
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text)
    log.info(f"  OCR complete: {len(text)} chars, cached → {cache_key}.md")
    return text


# ─── Claude Extraction ────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are extracting structured data from a solar energy invoice.

The invoice is from CrossBoundary Energy (CBE) to one of their customers.

## OCR Text

{ocr_text}

## Instructions

Extract ALL of the following from this invoice. Return a single JSON object with these fields:

```json
{{
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "customer_name": "string or null",
  "sage_id": "extracted from invoice number SIN prefix, e.g. KAS01 from SINKAS01...",
  "billing_period_month": "YYYY-MM format",
  "currency": "3-letter ISO code",
  "line_items": [
    {{
      "description": "line description",
      "line_type": "energy|fixed|tax|levy|loan|rental|credit_note|other",
      "quantity_kwh": null or float,
      "unit_rate": null or float,
      "amount": float,
      "notes": "any additional context"
    }}
  ],
  "tax_levy_breakdown": [
    {{
      "code": "WHT|WHVAT|VAT|NHIL|GETFUND|COVID|ETIMS|OTHER",
      "rate": 0.03,
      "amount": float,
      "base_amount": float,
      "applies_to": "energy_subtotal|subtotal_after_levies|grand_total"
    }}
  ],
  "tariff_box": {{
    "mrp_rate": null or float,
    "discount_pct": null or float,
    "floor_rate": null or float,
    "ceiling_rate": null or float,
    "solar_tariff": null or float
  }},
  "fx_rate": null or float,
  "fx_currency_pair": "USD/GHS or null",
  "subtotal": float,
  "tax_total": float,
  "grand_total": float,
  "extraction_confidence": "high|medium|low",
  "extraction_notes": "any issues or ambiguities"
}}
```

Key rules:
1. line_type must be one of: energy, fixed, tax, levy, loan, rental, credit_note, other
2. For taxes/levies, compute the RATE by dividing amount by base_amount if not shown explicitly
3. "applies_to" indicates what the tax/levy is calculated against:
   - "energy_subtotal" = applied to energy charges subtotal
   - "subtotal_after_levies" = applied after levies (e.g., VAT on subtotal + levies)
   - "grand_total" = applied to final total
4. The tariff_box captures any tariff calculation box showing MRP rate, discount, floor/ceiling
5. For WHT (Withholding Tax), identify if it's deducted at source or listed as payable
6. WHVAT is Withholding VAT - distinct from standard VAT
7. Look for eTIMS references (Kenya electronic tax management)
8. Capture ANY credit notes or adjustments as separate line items with line_type="credit_note"
9. IMPORTANT: "grand_total" = the Invoice Total INCLUDING taxes and levies but BEFORE withholding deductions.
   Do NOT use the "Total payable after Withholding taxes" as grand_total.
   Example: if Invoice Total = 203,658.26 and Total Payable = 178,731.42, use 203,658.26.
10. "subtotal" = sum of energy/fixed lines BEFORE any taxes/levies
11. Return ONLY valid JSON, no markdown code fences
"""


def extract_invoice_data(ocr_text: str, sage_id: str) -> InvoiceExtraction:
    """Use Claude to extract structured invoice data from OCR text."""
    client = anthropic.Anthropic()
    prompt = EXTRACTION_PROMPT.replace('{ocr_text}', ocr_text)

    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}],
    )

    content = response.content[0].text

    # Extract JSON from response
    json_text = content
    if '```json' in content:
        json_text = content.split('```json')[1].split('```')[0]
    elif '```' in content:
        json_text = content.split('```')[1].split('```')[0]

    try:
        raw = json.loads(json_text.strip())
    except json.JSONDecodeError as e:
        log.error(f"  JSON parse error for {sage_id}: {e}")
        log.error(f"  Raw response: {content[:500]}")
        return InvoiceExtraction(extraction_confidence='low', extraction_notes=f'JSON parse error: {e}')

    # Validate through Pydantic
    try:
        extraction = InvoiceExtraction.model_validate(raw)
        return extraction
    except Exception as e:
        log.error(f"  Validation error for {sage_id}: {e}")
        return InvoiceExtraction.model_validate({**raw, 'extraction_confidence': 'low',
                                                  'extraction_notes': f'Partial validation: {e}'})


# ─── Phase A: Tax Rule Aggregation ────────────────────────────────────────────

def aggregate_tax_rules(
    extractions: List[Dict[str, Any]],
    db_projects: Dict[str, Any],
) -> Tuple[List[Dict], List[Dict]]:
    """
    Aggregate tax structures by country from invoice extractions.

    Returns:
        (tax_rules_to_create, discrepancies)
    """
    # Group extractions by country
    country_extractions = defaultdict(list)
    for ext in extractions:
        sage_id = ext['sage_id']
        proj = db_projects.get(sage_id)
        if not proj:
            continue
        country = _country_to_iso(proj.get('country', ''))
        if not country:
            continue
        country_extractions[country].append(ext)

    tax_rules = []
    discrepancies = []

    for country, exts in country_extractions.items():
        log.info(f"  Phase A: Analyzing {country} ({len(exts)} invoices)")

        # Collect all tax structures for this country
        tax_structures = []
        for ext in exts:
            extraction = ext['extraction']
            breakdown = extraction.tax_levy_breakdown
            if not breakdown:
                continue
            tax_structures.append({
                'sage_id': ext['sage_id'],
                'breakdown': breakdown,
                'currency': extraction.currency,
            })

        if not tax_structures:
            log.warning(f"    No tax breakdowns found for {country}")
            continue

        # Find the majority pattern (country default)
        # Serialize each structure to compare
        pattern_counts = defaultdict(list)
        for ts in tax_structures:
            # Create a signature: sorted list of (code, rate, applies_to)
            sig = tuple(sorted(
                (t.code, round(t.rate, 4) if t.rate else 0, t.applies_to)
                for t in ts['breakdown']
            ))
            pattern_counts[sig].append(ts)

        # Most common pattern = country default
        majority_sig = max(pattern_counts, key=lambda s: len(pattern_counts[s]))
        majority_items = pattern_counts[majority_sig]
        default_structure = majority_items[0]['breakdown']

        log.info(f"    Country default: {len(majority_items)}/{len(tax_structures)} invoices match majority pattern")

        # Build the rules JSONB matching Ghana format
        country_rules = _build_rules_jsonb(default_structure)

        # Create country-default rule (project_id = NULL)
        tax_rules.append({
            'organization_id': ORG_ID,
            'country_code': country,
            'project_id': None,
            'name': f'{country} Standard Tax Regime',
            'rules': country_rules,
            'source_invoices': [ts['sage_id'] for ts in majority_items],
        })

        # Identify project-specific deviations
        for sig, items in pattern_counts.items():
            if sig == majority_sig:
                continue
            for item in items:
                deviation_rules = _build_rules_jsonb(item['breakdown'])
                proj = db_projects.get(item['sage_id'])
                pid = proj['id'] if proj else None

                tax_rules.append({
                    'organization_id': ORG_ID,
                    'country_code': country,
                    'project_id': pid,
                    'name': f"{country} Tax Regime — {item['sage_id']} override",
                    'rules': deviation_rules,
                    'source_invoices': [item['sage_id']],
                })

                # Log discrepancy
                discrepancies.append({
                    'severity': 'info',
                    'category': 'tax_deviation',
                    'project': item['sage_id'],
                    'field': 'billing_tax_rule',
                    'source_a': f"Invoice: {_summarize_breakdown(item['breakdown'])}",
                    'source_b': f"Country default: {_summarize_breakdown(default_structure)}",
                    'recommended_action': f"Project-specific tax override created for {item['sage_id']}",
                    'status': 'resolved',
                })

    return tax_rules, discrepancies


def _build_rules_jsonb(breakdown: List[TaxLevyBreakdown]) -> Dict:
    """Convert a list of TaxLevyBreakdown into the billing_tax_rule.rules JSONB format."""
    levies = []
    vat = None
    withholdings = []
    sort_order = 10

    for t in breakdown:
        entry = {
            'code': t.code,
            'name': t.code,  # Will be enriched with full name
            'rate': t.rate or 0,
            'applies_to': {'base': t.applies_to},
            'sort_order': sort_order,
        }

        # Assign human-readable names
        CODE_NAMES = {
            'VAT': 'VAT',
            'WHT': 'Withholding Tax',
            'WHVAT': 'Withholding VAT',
            'NHIL': 'NHIL',
            'GETFUND': 'GETFund',
            'COVID': 'COVID Levy',
            'ETIMS': 'eTIMS Levy',
        }
        entry['name'] = CODE_NAMES.get(t.code, t.code)

        if t.code == 'VAT':
            vat = entry
        elif t.code in ('WHT', 'WHVAT'):
            withholdings.append(entry)
        else:
            levies.append(entry)
        sort_order += 1

    rules = {
        'rounding_mode': 'ROUND_HALF_UP',
        'rounding_precision': 2,
        'levies': levies,
        'withholdings': withholdings,
    }
    if vat:
        rules['vat'] = vat

    return rules


def _summarize_breakdown(breakdown: List[TaxLevyBreakdown]) -> str:
    """Create a short summary of a tax breakdown for discrepancy reporting."""
    parts = []
    for t in breakdown:
        rate_str = f"{t.rate*100:.1f}%" if t.rate else "?"
        parts.append(f"{t.code}={rate_str}")
    return ', '.join(parts)


# ─── Phase B: Validation Checks ──────────────────────────────────────────────

def run_validation_checks(
    extraction: InvoiceExtraction,
    sage_id: str,
    db_state: Dict[str, Any],
) -> List[Dict]:
    """Run 8 validation checks against DB state."""
    checks = []
    proj = db_state['projects'].get(sage_id)
    if not proj:
        return [{'check': 0, 'severity': 'warning', 'field': 'project',
                 'message': f'Project {sage_id} not found in DB'}]

    pid = proj['id']

    # Check 1: Line items → billing_product / contract_line
    checks.extend(_check_line_items(extraction, sage_id, db_state))

    # Check 2: Quantity kWh vs meter_aggregate
    checks.extend(_check_quantity_kwh(extraction, sage_id, db_state))

    # Check 3: Currency vs clause_tariff
    checks.extend(_check_currency(extraction, sage_id, db_state))

    # Check 4: Tax rates vs billing_tax_rule
    checks.extend(_check_tax_rates(extraction, sage_id, db_state))

    # Check 5: FX rate vs exchange_rate
    checks.extend(_check_fx_rate(extraction, sage_id, db_state))

    # Check 6: Tariff box vs clause_tariff.logic_parameters
    checks.extend(_check_tariff_box(extraction, sage_id, db_state))

    # Check 7: Loan/rental vs technical_specs
    checks.extend(_check_loan_rental(extraction, sage_id, db_state))

    # Check 8: Grand total self-consistency
    checks.extend(_check_self_consistency(extraction, sage_id))

    return checks


def _check_line_items(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 1: Line items have matching billing_product / contract_line."""
    results = []
    products = db['billing_products'].get(sage_id, [])
    product_codes = {p['code'].lower() for p in products if p.get('code')}

    energy_lines = [li for li in ext.line_items if li.line_type == 'energy']
    if energy_lines and not products:
        results.append({
            'check': 1, 'severity': 'warning', 'field': 'billing_product',
            'message': f'{sage_id}: {len(energy_lines)} energy line(s) but no billing_products in DB',
        })
    return results


def _check_quantity_kwh(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 2: kWh quantity vs meter_aggregate."""
    results = []
    total_kwh = sum(li.quantity_kwh or 0 for li in ext.line_items if li.line_type == 'energy')
    if not total_kwh:
        return results

    meter_data = db['meter_aggregates'].get(sage_id)
    if not meter_data:
        results.append({
            'check': 2, 'severity': 'info', 'field': 'meter_aggregate',
            'message': f'{sage_id}: Invoice shows {total_kwh:.0f} kWh but no meter_aggregate data in DB (sparse)',
        })
    else:
        # Compare against latest meter aggregate
        db_kwh = meter_data.get('total_production')
        if db_kwh and abs(total_kwh - float(db_kwh)) / max(total_kwh, 1) > 0.05:
            results.append({
                'check': 2, 'severity': 'warning', 'field': 'meter_aggregate.total_production',
                'message': f'{sage_id}: Invoice kWh={total_kwh:.0f} vs DB={float(db_kwh):.0f} (>{5}% diff)',
            })
    return results


def _check_currency(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 3: Currency vs clause_tariff.

    The clause_tariff.currency_id is the contractual reference currency (often USD
    for floor/ceiling rates), NOT necessarily the invoicing currency.  Projects that
    bill in local currency (KES, SLE, etc.) will legitimately differ.  Record as
    info-level note, not critical.
    """
    results = []
    if not ext.currency:
        return results

    tariffs = db['tariffs'].get(sage_id, [])
    for t in tariffs:
        db_currency = db['currencies'].get(t.get('currency_id'))
        if db_currency and db_currency.upper() != ext.currency.upper():
            results.append({
                'check': 3, 'severity': 'info', 'field': 'currency',
                'message': (
                    f'{sage_id}: Invoice billed in {ext.currency}, '
                    f'clause_tariff reference currency is {db_currency} '
                    f'(floor/ceiling rates — not a billing mismatch)'
                ),
            })
            break
    return results


def _check_tax_rates(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 4: Tax rates vs billing_tax_rule."""
    results = []
    proj = db['projects'].get(sage_id)
    if not proj:
        return results

    country = _country_to_iso(proj.get('country', ''))
    db_rules = db['tax_rules'].get(country) if country else None
    if not db_rules or not ext.tax_levy_breakdown:
        return results

    rules_json = db_rules.get('rules', {})

    for tax in ext.tax_levy_breakdown:
        # Find matching rule
        db_rate = _find_db_tax_rate(tax.code, rules_json)
        if db_rate is not None and tax.rate is not None:
            if abs(tax.rate - db_rate) > 0.001:
                results.append({
                    'check': 4, 'severity': 'warning', 'field': f'tax_rate.{tax.code}',
                    'message': f'{sage_id}: Invoice {tax.code} rate={tax.rate:.4f} vs DB={db_rate:.4f}',
                })
    return results


def _find_db_tax_rate(code: str, rules: Dict) -> Optional[float]:
    """Find a tax rate in the billing_tax_rule rules JSONB."""
    # Check VAT
    vat = rules.get('vat', {})
    if code == 'VAT' and vat:
        return vat.get('rate')

    # Check levies
    for levy in rules.get('levies', []):
        if levy.get('code') == code:
            return levy.get('rate')

    # Check withholdings
    for wh in rules.get('withholdings', []):
        if wh.get('code') == code:
            return wh.get('rate')

    return None


def _check_fx_rate(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 5: FX rate vs exchange_rate table (0.5% tolerance).

    Skip if fx_rate is 1.0 or null (no conversion), or if the currency pair
    is same-to-same (e.g., GHS/GHS).
    """
    results = []
    if not ext.fx_rate or not ext.billing_period_month:
        return results

    # Skip if rate is 1.0 (no conversion) or same-currency pair
    if ext.fx_rate == 1.0:
        return results
    if ext.fx_currency_pair:
        parts = ext.fx_currency_pair.replace('/', ' ').split()
        if len(parts) == 2 and parts[0] == parts[1]:
            return results

    # Find the invoice currency in our currency map
    inv_currency_id = None
    for cid, code in db['currencies'].items():
        if code.upper() == (ext.currency or '').upper():
            inv_currency_id = cid
            break

    if not inv_currency_id:
        return results

    # Find matching exchange rate for the billing month
    rate_date_prefix = ext.billing_period_month[:7]  # YYYY-MM
    for (cid, rd), rate in db['exchange_rates'].items():
        if cid == inv_currency_id and rate_date_prefix in str(rd):
            tolerance = abs(ext.fx_rate - float(rate)) / max(ext.fx_rate, 0.001)
            if tolerance > 0.005:  # 0.5%
                results.append({
                    'check': 5, 'severity': 'warning', 'field': 'exchange_rate',
                    'message': f'{sage_id}: Invoice FX={ext.fx_rate:.4f} vs DB={float(rate):.4f} ({tolerance*100:.1f}% diff)',
                })
            break
    return results


def _check_tariff_box(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 6: Tariff box vs clause_tariff.logic_parameters."""
    results = []
    if not ext.tariff_box:
        return results

    tariffs = db['tariffs'].get(sage_id, [])
    for t in tariffs:
        lp = t.get('logic_parameters') or {}
        tb = ext.tariff_box

        if tb.solar_tariff and t.get('base_rate'):
            db_rate = float(t['base_rate'])
            if abs(tb.solar_tariff - db_rate) / max(db_rate, 0.0001) > 0.01:
                results.append({
                    'check': 6, 'severity': 'warning', 'field': 'clause_tariff.base_rate',
                    'message': f'{sage_id}: Invoice solar_tariff={tb.solar_tariff:.4f} vs DB base_rate={db_rate:.4f}',
                })

        if tb.discount_pct and lp.get('discount_percentage'):
            db_disc = float(lp['discount_percentage'])
            # Normalize: invoice may report as percentage (19.2) or decimal (0.192)
            inv_disc = tb.discount_pct
            if inv_disc > 1.0:
                inv_disc = inv_disc / 100.0  # Convert percentage to decimal
            if abs(inv_disc - db_disc) > 0.001:
                results.append({
                    'check': 6, 'severity': 'warning', 'field': 'clause_tariff.discount_percentage',
                    'message': f'{sage_id}: Invoice discount={inv_disc:.4f} vs DB={db_disc:.4f}',
                })

        if tb.floor_rate and lp.get('floor_rate'):
            db_floor = float(lp['floor_rate'])
            if abs(tb.floor_rate - db_floor) / max(db_floor, 0.0001) > 0.01:
                results.append({
                    'check': 6, 'severity': 'warning', 'field': 'clause_tariff.floor_rate',
                    'message': f'{sage_id}: Invoice floor={tb.floor_rate:.4f} vs DB={db_floor:.4f}',
                })
    return results


def _check_loan_rental(ext: InvoiceExtraction, sage_id: str, db: Dict) -> List[Dict]:
    """Check 7: Loan/rental lines vs technical_specs schedules."""
    results = []
    loan_lines = [li for li in ext.line_items if li.line_type in ('loan', 'rental')]
    if not loan_lines:
        return results

    proj = db['projects'].get(sage_id)
    if not proj:
        return results

    specs = proj.get('technical_specs') or {}
    has_loan = 'loan_schedule' in specs
    has_rental = 'rental_schedule' in specs

    for li in loan_lines:
        if li.line_type == 'loan' and not has_loan:
            results.append({
                'check': 7, 'severity': 'warning', 'field': 'technical_specs.loan_schedule',
                'message': f'{sage_id}: Invoice has loan line ({li.description}) but no loan_schedule in technical_specs',
            })
        if li.line_type == 'rental' and not has_rental:
            results.append({
                'check': 7, 'severity': 'warning', 'field': 'technical_specs.rental_schedule',
                'message': f'{sage_id}: Invoice has rental line ({li.description}) but no rental_schedule in technical_specs',
            })
    return results


def _check_self_consistency(ext: InvoiceExtraction, sage_id: str) -> List[Dict]:
    """Check 8: Grand total = sum(non-tax lines) + levies + VAT self-consistency.

    Withholdings (WHT, WHVAT) are NOT part of the invoice total — they are
    deducted after the total to compute "total payable". So self-consistency
    checks the stated grand_total against energy subtotal + levies + VAT only.
    """
    results = []
    if ext.grand_total is None:
        return results

    # Prefer stated subtotal from the invoice over summing line items,
    # because OCR table parsing can misalign columns and produce wrong
    # individual line amounts while the stated totals are usually correct.
    if ext.subtotal is not None:
        line_total = ext.subtotal
    else:
        line_total = sum(li.amount or 0 for li in ext.line_items
                         if li.line_type not in ('tax', 'levy'))

    # Sum levies + VAT from tax breakdown (exclude withholdings)
    WITHHOLDING_CODES = {'WHT', 'WHVAT'}
    if ext.tax_total is not None:
        # Use stated tax_total if available (may include or exclude withholdings)
        # Cross-check: stated tax_total should ≈ non-WHT breakdown total
        tax_component = ext.tax_total
    else:
        levy_vat_total = sum(t.amount or 0 for t in ext.tax_levy_breakdown
                             if t.code not in WITHHOLDING_CODES)
        tax_line_total = sum(li.amount or 0 for li in ext.line_items
                             if li.line_type in ('tax', 'levy'))
        tax_component = max(levy_vat_total, tax_line_total)

    computed = line_total + tax_component
    diff = abs(computed - ext.grand_total)
    # Use percentage tolerance for large amounts, absolute for small
    pct_diff = diff / max(ext.grand_total, 1) * 100
    if pct_diff > 5.0 and diff > 10.0:  # >5% AND >$10
        severity = 'critical' if pct_diff > 20 else 'warning'
        results.append({
            'check': 8, 'severity': severity, 'field': 'grand_total',
            'message': f'{sage_id}: Computed total={computed:.2f} vs stated grand_total={ext.grand_total:.2f} (diff={diff:.2f}, {pct_diff:.1f}%)',
        })
    return results


# ─── DB State Loading ─────────────────────────────────────────────────────────

def load_db_state() -> Dict[str, Any]:
    """Load all required DB state into memory dicts keyed by sage_id."""
    state = {
        'projects': {},
        'contracts': {},
        'billing_products': {},
        'tariffs': {},
        'currencies': {},  # id → code
        'tax_rules': {},   # country_code → rules row
        'exchange_rates': {},  # (currency_id, rate_date) → rate
        'reference_prices': {},
        'meter_aggregates': {},
    }

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '120s'")

        # Projects
        cur.execute("""
            SELECT p.id, p.sage_id, p.country, p.technical_specs,
                   p.installed_dc_capacity_kwp, p.cod_date::text as cod_date
            FROM project p WHERE p.organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            state['projects'][row['sage_id']] = dict(row)

        # Contracts + contract_lines
        cur.execute("""
            SELECT c.id as contract_id, p.sage_id,
                   cl.id as contract_line_id, cl.product_desc,
                   cl.billing_product_id
            FROM contract c
            JOIN project p ON c.project_id = p.id
            LEFT JOIN contract_line cl ON cl.contract_id = c.id
            WHERE p.organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in state['contracts']:
                state['contracts'][sid] = []
            state['contracts'][sid].append(dict(row))

        # Billing products
        cur.execute("""
            SELECT bp.id, bp.code, bp.name, p.sage_id
            FROM billing_product bp
            JOIN contract_billing_product cbp ON cbp.billing_product_id = bp.id
            JOIN contract c ON cbp.contract_id = c.id
            JOIN project p ON c.project_id = p.id
            WHERE bp.organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in state['billing_products']:
                state['billing_products'][sid] = []
            state['billing_products'][sid].append(dict(row))

        # Tariffs
        cur.execute("""
            SELECT ct.id, p.sage_id, ct.base_rate, ct.currency_id,
                   ct.logic_parameters,
                   est.name as energy_sale_type_name
            FROM clause_tariff ct
            JOIN project p ON ct.project_id = p.id
            LEFT JOIN energy_sale_type est ON ct.energy_sale_type_id = est.id
            WHERE ct.is_current = true AND p.organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in state['tariffs']:
                state['tariffs'][sid] = []
            state['tariffs'][sid].append(dict(row))

        # Currencies
        cur.execute("SELECT id, code FROM currency")
        for row in cur.fetchall():
            state['currencies'][row['id']] = row['code']

        # Tax rules (by country_code, prefer project_id IS NULL as default)
        cur.execute("""
            SELECT id, country_code, project_id, rules
            FROM billing_tax_rule
            WHERE organization_id = %s AND is_active = true
            ORDER BY country_code, project_id NULLS FIRST
        """, (ORG_ID,))
        for row in cur.fetchall():
            cc = row['country_code'].strip()
            if cc not in state['tax_rules']:
                state['tax_rules'][cc] = dict(row)

        # Exchange rates
        cur.execute("""
            SELECT currency_id, rate_date::text as rate_date, rate
            FROM exchange_rate WHERE organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            state['exchange_rates'][(row['currency_id'], row['rate_date'])] = row['rate']

        # Reference prices
        cur.execute("""
            SELECT rp.id, p.sage_id, rp.period_start::text as period_start,
                   rp.calculated_mrp_per_kwh
            FROM reference_price rp
            JOIN project p ON rp.project_id = p.id
            WHERE p.organization_id = %s
        """, (ORG_ID,))
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in state['reference_prices']:
                state['reference_prices'][sid] = {}
            state['reference_prices'][sid][row['period_start']] = row['calculated_mrp_per_kwh']

        # Meter aggregates (latest per project)
        cur.execute("""
            SELECT p.sage_id, ma.total_production,
                   ma.period_start::text as period_start
            FROM meter_aggregate ma
            JOIN contract_line cl ON cl.id = ma.contract_line_id
            JOIN contract c ON c.id = cl.contract_id
            JOIN project p ON p.id = c.project_id
            WHERE p.organization_id = %s
              AND ma.total_production IS NOT NULL
            ORDER BY ma.period_start DESC
        """, (ORG_ID,))
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in state['meter_aggregates']:
                state['meter_aggregates'][sid] = dict(row)

    log.info(f"DB state loaded: {len(state['projects'])} projects, "
             f"{sum(len(v) for v in state['tariffs'].values())} tariffs, "
             f"{len(state['tax_rules'])} tax rule countries, "
             f"{len(state['exchange_rates'])} exchange rates")
    return state


# ─── Tax Rule Insertion ───────────────────────────────────────────────────────

def insert_tax_rules(tax_rules: List[Dict], existing_rules: Dict, dry_run: bool) -> List[Dict]:
    """Insert billing_tax_rule rows, skipping existing countries/projects."""
    created = []

    if dry_run:
        for rule in tax_rules:
            cc = rule['country_code']
            pid = rule.get('project_id')
            log.info(f"  [DRY RUN] Would create tax rule: {cc} project_id={pid} — {rule['name']}")
            created.append(rule)
        return created

    with get_db_connection() as conn:
        cur = conn.cursor()

        for rule in tax_rules:
            cc = rule['country_code']
            pid = rule.get('project_id')

            # Check if a rule already exists for this country+project
            if pid:
                cur.execute("""
                    SELECT id FROM billing_tax_rule
                    WHERE organization_id = %s AND country_code = %s AND project_id = %s AND is_active = true
                """, (ORG_ID, cc, pid))
            else:
                cur.execute("""
                    SELECT id FROM billing_tax_rule
                    WHERE organization_id = %s AND country_code = %s AND project_id IS NULL AND is_active = true
                """, (ORG_ID, cc))

            if cur.fetchone():
                log.info(f"    Tax rule already exists: {cc} project_id={pid}, skipping")
                continue

            cur.execute("""
                INSERT INTO billing_tax_rule (
                    organization_id, country_code, project_id, name,
                    effective_start_date, effective_end_date,
                    rules, is_active
                ) VALUES (%s, %s, %s, %s, %s, NULL, %s, true)
                RETURNING id
            """, (
                ORG_ID, cc, pid, rule['name'],
                '2025-01-01',
                json.dumps(rule['rules']),
            ))

            new_id = cur.fetchone()['id']
            rule['db_id'] = new_id
            created.append(rule)
            log.info(f"    Created tax rule #{new_id}: {cc} project_id={pid} — {rule['name']}")

        conn.commit()

    return created


# ─── Phase C: Received Invoice Population ────────────────────────────────────

# Map extraction line_type → invoice_line_item_type code
LINE_TYPE_MAP = {
    'energy': 'ENERGY',
    'fixed': 'FIXED',
    'tax': 'TAX',
    'levy': 'LEVY',
    'loan': 'FIXED',
    'rental': 'FIXED',
    'credit_note': 'LD_CREDIT',
    'other': 'FIXED',
}

# Map tax_levy_breakdown code → invoice_line_item_type code
TAX_CODE_MAP = {
    'VAT': 'TAX',
    'WHT': 'WITHHOLDING',
    'WHVAT': 'WITHHOLDING',
    'NHIL': 'LEVY',
    'GETFUND': 'LEVY',
    'COVID': 'LEVY',
    'ETIMS': 'LEVY',
    'OTHER': 'LEVY',
}


def populate_received_invoices(
    extractions: List[Dict[str, Any]],
    db_state: Dict[str, Any],
    dry_run: bool,
) -> List[Dict]:
    """
    Phase C: Insert received_invoice_header + received_invoice_line_item
    from the Claude-extracted invoice data.

    Idempotent: skips invoices whose invoice_number already exists for the project.
    """
    results = []

    # Pre-load line item type IDs
    line_type_ids: Dict[str, int] = {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, code FROM invoice_line_item_type")
        for row in cur.fetchall():
            line_type_ids[row['code']] = row['id']

    for ext_record in extractions:
        sage_id = ext_record['sage_id']
        extraction: InvoiceExtraction = ext_record['extraction']

        proj = db_state['projects'].get(sage_id)
        if not proj:
            log.warning(f"  Phase C: {sage_id} — project not found, skipping")
            results.append({'sage_id': sage_id, 'status': 'skipped', 'reason': 'project not found'})
            continue

        project_id = proj['id']

        # Resolve contract_id, counterparty_id, currency_id
        contract_info = _resolve_contract_info(project_id, extraction.currency, db_state)
        if not contract_info:
            log.warning(f"  Phase C: {sage_id} — no contract found, skipping")
            results.append({'sage_id': sage_id, 'status': 'skipped', 'reason': 'no contract'})
            continue

        # Resolve billing_period_id from billing_period_month
        billing_period_id = _resolve_billing_period(extraction.billing_period_month)
        if not billing_period_id:
            log.warning(f"  Phase C: {sage_id} — billing period {extraction.billing_period_month} not found, skipping")
            results.append({'sage_id': sage_id, 'status': 'skipped', 'reason': f'billing period {extraction.billing_period_month} not found'})
            continue

        # Parse dates
        invoice_date = _parse_date(extraction.invoice_date)
        due_date = _parse_date(extraction.due_date)

        # grand_total is the invoice total BEFORE withholding deductions
        total_amount = extraction.grand_total

        if dry_run:
            log.info(f"  Phase C [DRY RUN]: {sage_id} — {extraction.invoice_number}, "
                     f"period={extraction.billing_period_month}, total={total_amount}, "
                     f"{len(extraction.line_items)} lines + {len(extraction.tax_levy_breakdown)} tax items")
            results.append({
                'sage_id': sage_id, 'status': 'dry_run',
                'invoice_number': extraction.invoice_number,
                'line_count': len(extraction.line_items) + len(extraction.tax_levy_breakdown),
            })
            continue

        with get_db_connection() as conn:
            cur = conn.cursor()

            # Idempotency: check if invoice_number already exists for this project
            cur.execute("""
                SELECT id FROM received_invoice_header
                WHERE project_id = %s AND invoice_number = %s
            """, (project_id, extraction.invoice_number))
            existing = cur.fetchone()
            if existing:
                log.info(f"  Phase C: {sage_id} — invoice {extraction.invoice_number} already exists (id={existing['id']}), skipping")
                results.append({
                    'sage_id': sage_id, 'status': 'exists',
                    'invoice_number': extraction.invoice_number,
                    'existing_id': existing['id'],
                })
                continue

            # Insert header
            cur.execute("""
                INSERT INTO received_invoice_header (
                    project_id, contract_id, billing_period_id,
                    counterparty_id, currency_id,
                    invoice_number, invoice_date, due_date,
                    total_amount, status, invoice_direction
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'verified', 'receivable'
                )
                RETURNING id
            """, (
                project_id, contract_info['contract_id'], billing_period_id,
                contract_info['counterparty_id'], contract_info['currency_id'],
                extraction.invoice_number, invoice_date, due_date,
                total_amount,
            ))
            header_id = cur.fetchone()['id']

            # Insert energy/fixed line items
            line_count = 0
            for li in extraction.line_items:
                # Skip tax/levy lines from line_items — we use tax_levy_breakdown instead
                if li.line_type in ('tax', 'levy'):
                    continue

                type_code = LINE_TYPE_MAP.get(li.line_type, 'FIXED')
                type_id = line_type_ids.get(type_code)

                cur.execute("""
                    INSERT INTO received_invoice_line_item (
                        received_invoice_header_id, invoice_line_item_type_id,
                        description, quantity, line_unit_price, line_total_amount
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    header_id, type_id,
                    li.description,
                    li.quantity_kwh,
                    li.unit_rate,
                    li.amount,
                ))
                line_count += 1

            # Insert tax/levy/withholding line items from tax_levy_breakdown
            for tax in extraction.tax_levy_breakdown:
                type_code = TAX_CODE_MAP.get(tax.code, 'LEVY')
                type_id = line_type_ids.get(type_code)

                # Withholdings are deductions — store as negative
                amount = tax.amount
                if tax.code in ('WHT', 'WHVAT') and amount and amount > 0:
                    amount = -amount

                description = f"{tax.code}"
                if tax.rate is not None:
                    description += f" ({tax.rate*100:.1f}%)"

                cur.execute("""
                    INSERT INTO received_invoice_line_item (
                        received_invoice_header_id, invoice_line_item_type_id,
                        description, quantity, line_unit_price, line_total_amount
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    header_id, type_id,
                    description,
                    tax.base_amount,  # quantity = base amount the tax applies to
                    tax.rate,         # unit_price = tax rate
                    amount,
                ))
                line_count += 1

            conn.commit()
            log.info(f"  Phase C: {sage_id} — inserted invoice {extraction.invoice_number} "
                     f"(header_id={header_id}, {line_count} line items)")
            results.append({
                'sage_id': sage_id, 'status': 'created',
                'invoice_number': extraction.invoice_number,
                'header_id': header_id,
                'line_count': line_count,
            })

    return results


def _resolve_contract_info(
    project_id: int,
    currency_code: Optional[str],
    db_state: Dict,
) -> Optional[Dict]:
    """Look up contract_id, counterparty_id, and currency_id for a project."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id as contract_id, c.counterparty_id
            FROM contract c
            WHERE c.project_id = %s
            ORDER BY c.id
            LIMIT 1
        """, (project_id,))
        contract = cur.fetchone()
        if not contract:
            return None

        # Resolve currency_id from code
        currency_id = None
        if currency_code:
            for cid, code in db_state['currencies'].items():
                if code.upper() == currency_code.upper():
                    currency_id = cid
                    break

        # Fallback: use the clause_tariff currency
        if not currency_id:
            cur.execute("""
                SELECT currency_id FROM clause_tariff
                WHERE contract_id = %s AND is_current = true
                LIMIT 1
            """, (contract['contract_id'],))
            tariff = cur.fetchone()
            if tariff:
                currency_id = tariff['currency_id']

        return {
            'contract_id': contract['contract_id'],
            'counterparty_id': contract['counterparty_id'],
            'currency_id': currency_id,
        }


def _resolve_billing_period(billing_period_month: Optional[str]) -> Optional[int]:
    """Look up billing_period_id from YYYY-MM string."""
    if not billing_period_month:
        return None

    try:
        parts = billing_period_month.split('-')
        year, month = int(parts[0]), int(parts[1])
        start_date = date(year, month, 1)
    except (ValueError, IndexError):
        return None

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM billing_period
            WHERE start_date = %s
        """, (start_date,))
        row = cur.fetchone()
        return row['id'] if row else None


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse a date string (YYYY-MM-DD) to a date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Step 8: Invoice Calibration & Tax Rule Extraction')
    parser.add_argument('--dry-run', action='store_true', help='Do not write to DB')
    parser.add_argument('--no-cache', action='store_true', help='Force re-OCR (ignore cache)')
    parser.add_argument('--project', type=str, help='Process single project by SAGE ID')
    args = parser.parse_args()

    mode = 'DRY RUN' if args.dry_run else 'LIVE'
    log.info(f"Step 8: Invoice Calibration & Tax Rule Extraction ({mode})")
    log.info(f"Invoice dir: {INVOICE_DIR}")

    # Discover invoices
    invoices = discover_invoices(args.project)
    if not invoices:
        log.error("No invoices found. Exiting.")
        sys.exit(1)

    # Init DB
    init_connection_pool()
    db_state = load_db_state()

    # Process each invoice
    extractions = []
    all_checks = []
    all_discrepancies = []

    for inv in invoices:
        sage_id = inv['sage_id']
        log.info(f"Processing: {inv['filename']} (sage_id={sage_id})")

        # Get PDF bytes
        if inv['source'] == 'eml':
            pdf_bytes = inv['pdf_bytes']
        else:
            pdf_bytes = inv['path'].read_bytes()

        # OCR
        try:
            ocr_text = ocr_invoice(pdf_bytes, inv['filename'], use_cache=not args.no_cache)
        except Exception as e:
            log.error(f"  OCR failed for {sage_id}: {e}")
            all_discrepancies.append({
                'severity': 'critical', 'category': 'ocr_failure',
                'project': sage_id, 'field': 'ocr',
                'source_a': f'File: {inv["filename"]}',
                'source_b': f'Error: {str(e)[:200]}',
                'recommended_action': 'Check PDF file integrity',
                'status': 'open',
            })
            continue

        # Claude extraction
        try:
            extraction = extract_invoice_data(ocr_text, sage_id)
        except Exception as e:
            log.error(f"  Extraction failed for {sage_id}: {e}")
            all_discrepancies.append({
                'severity': 'critical', 'category': 'extraction_failure',
                'project': sage_id, 'field': 'extraction',
                'source_a': f'File: {inv["filename"]}',
                'source_b': f'Error: {str(e)[:200]}',
                'recommended_action': 'Review OCR output quality',
                'status': 'open',
            })
            continue

        ext_record = {
            'sage_id': sage_id,
            'filename': inv['filename'],
            'extraction': extraction,
        }
        extractions.append(ext_record)

        # Phase B: Validation checks
        checks = run_validation_checks(extraction, sage_id, db_state)
        for c in checks:
            c['project'] = sage_id
            c['filename'] = inv['filename']
        all_checks.extend(checks)

        log.info(f"  Extracted: {extraction.invoice_number}, {extraction.currency}, "
                 f"grand_total={extraction.grand_total}, "
                 f"{len(extraction.tax_levy_breakdown)} tax items, "
                 f"confidence={extraction.extraction_confidence}")
        log.info(f"  Checks: {len(checks)} ({sum(1 for c in checks if c['severity'] == 'critical')} critical)")

    # Phase A: Aggregate tax rules
    log.info("=" * 60)
    log.info("Phase A: Tax Rule Aggregation")
    tax_rules, tax_discrepancies = aggregate_tax_rules(extractions, db_state['projects'])
    all_discrepancies.extend(tax_discrepancies)

    # Insert tax rules
    created_rules = insert_tax_rules(tax_rules, db_state['tax_rules'], args.dry_run)
    log.info(f"  Tax rules created: {len(created_rules)}")

    # Phase C: Populate received_invoice tables
    log.info("=" * 60)
    log.info("Phase C: Received Invoice Population")
    phase_c_results = populate_received_invoices(extractions, db_state, args.dry_run)
    invoices_created = sum(1 for r in phase_c_results if r['status'] == 'created')
    invoices_skipped = sum(1 for r in phase_c_results if r['status'] in ('exists', 'skipped'))
    log.info(f"  Invoices created: {invoices_created}, skipped: {invoices_skipped}")

    # ── Gate Checks ──
    gates = []

    gates.append({
        'name': 'Invoices parsed successfully',
        'passed': len(extractions) > 0,
        'expected': '> 0 invoices parsed',
        'actual': f'{len(extractions)}/{len(invoices)} invoices parsed',
    })

    gates.append({
        'name': 'Tax rules created for missing countries',
        'passed': len(created_rules) > 0 or args.project is not None,
        'expected': '> 0 tax rules created (or single-project mode)',
        'actual': f'{len(created_rules)} tax rules created',
    })

    critical_checks = [c for c in all_checks if c['severity'] == 'critical']
    gates.append({
        'name': 'No critical validation failures',
        'passed': len(critical_checks) == 0,
        'expected': '0 critical checks',
        'actual': f'{len(critical_checks)} critical checks',
    })

    high_confidence = sum(1 for e in extractions if e['extraction'].extraction_confidence == 'high')
    gates.append({
        'name': 'Extraction confidence acceptable',
        'passed': high_confidence >= len(extractions) * 0.5 or len(extractions) <= 2,
        'expected': '>= 50% high confidence',
        'actual': f'{high_confidence}/{len(extractions)} high confidence',
    })

    for g in gates:
        status = 'PASS' if g['passed'] else 'FAIL'
        log.info(f"  Gate: {g['name']} → {status} ({g['actual']})")

    # ── Build Report ──
    status = 'pass'
    if any(c['severity'] == 'critical' for c in all_checks):
        status = 'critical'
    elif any(c['severity'] == 'warning' for c in all_checks):
        status = 'warnings'

    report = {
        'step': 8,
        'step_name': 'Invoice Calibration & Tax Rule Extraction',
        'mode': mode,
        'status': status,
        'summary': {
            'pdfs_discovered': len(invoices),
            'pdfs_parsed': len(extractions),
            'projects_covered': list(set(e['sage_id'] for e in extractions)),
            'tax_rules_created': len(created_rules),
            'received_invoices_created': invoices_created,
            'received_invoices_skipped': invoices_skipped,
            'check_counts': {
                'critical': sum(1 for c in all_checks if c['severity'] == 'critical'),
                'warning': sum(1 for c in all_checks if c['severity'] == 'warning'),
                'info': sum(1 for c in all_checks if c['severity'] == 'info'),
            },
        },
        'tax_rules_created': [
            {
                'country_code': r['country_code'],
                'project_id': r.get('project_id'),
                'name': r['name'],
                'rules_summary': _summarize_rules(r['rules']),
                'source_invoices': r.get('source_invoices', []),
            }
            for r in created_rules
        ],
        'invoice_extractions': [
            {
                'sage_id': e['sage_id'],
                'filename': e['filename'],
                'invoice_number': e['extraction'].invoice_number,
                'currency': e['extraction'].currency,
                'grand_total': e['extraction'].grand_total,
                'billing_period': e['extraction'].billing_period_month,
                'confidence': e['extraction'].extraction_confidence,
                'tax_codes': [t.code for t in e['extraction'].tax_levy_breakdown],
                'line_item_count': len(e['extraction'].line_items),
                'checks': [c for c in all_checks if c.get('project') == e['sage_id']],
            }
            for e in extractions
        ],
        'discrepancies': all_discrepancies + [
            {
                'severity': c['severity'],
                'category': f'validation_check_{c["check"]}',
                'project': c.get('project', ''),
                'field': c['field'],
                'source_a': c['message'],
                'source_b': '',
                'recommended_action': '',
                'status': 'open',
            }
            for c in all_checks
        ],
        'phase_c_received_invoices': phase_c_results,
        'gate_checks': gates,
    }

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f'step8_{date.today().isoformat()}.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    log.info(f"Report: {report_path}")

    log.info("=" * 60)
    log.info(f"Step 8 Complete ({mode})")

    close_connection_pool()


def _summarize_rules(rules: Dict) -> str:
    """Create a short summary of a rules JSONB for the report."""
    parts = []
    if rules.get('vat'):
        parts.append(f"VAT={rules['vat']['rate']*100:.0f}%")
    for levy in rules.get('levies', []):
        parts.append(f"{levy['code']}={levy['rate']*100:.1f}%")
    for wh in rules.get('withholdings', []):
        parts.append(f"{wh['code']}={wh['rate']*100:.1f}%")
    return ', '.join(parts)


if __name__ == '__main__':
    main()
