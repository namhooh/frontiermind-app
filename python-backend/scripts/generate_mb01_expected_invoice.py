#!/usr/bin/env python3
"""
Generate expected invoice for MB01 Dec 2025 billing period.

1. Deactivates the incorrect MB01-specific tax rule override (missing WHVAT)
2. Calls the billing API's generate-expected-invoice endpoint logic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
load_dotenv()

from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(message)s')
log = logging.getLogger(__name__)

PROJECT_ID = 57
BILLING_MONTH = '2025-12'
DRY_RUN = '--dry-run' in sys.argv


def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal('0')
    return Decimal(str(v))


def _round_d(v: Decimal, precision: int = 2) -> Decimal:
    return v.quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)


def main():
    init_connection_pool(min_connections=1, max_connections=3)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '120s'")

        # ── Step 1: Fix MB01 tax rule override ──
        # Deactivate the incorrect override (id=18) so it falls back to KE country default
        cur.execute("""
            UPDATE billing_tax_rule SET is_active = false
            WHERE id = 18 AND project_id = 57
        """)
        log.info("Deactivated incorrect MB01 tax rule override (id=18)")

        # ── Step 2: Resolve project, contract, tariff ──
        cur.execute("""
            SELECT p.id, p.organization_id, p.country,
                   c.id AS contract_id, c.counterparty_id
            FROM project p
            JOIN contract c ON c.project_id = p.id
            WHERE p.id = %s LIMIT 1
        """, (PROJECT_ID,))
        proj = cur.fetchone()
        org_id = proj['organization_id']
        contract_id = proj['contract_id']

        # Billing period
        bm_date = date(2025, 12, 1)
        cur.execute("SELECT id FROM billing_period WHERE start_date = %s", (bm_date,))
        billing_period_id = cur.fetchone()['id']
        log.info(f"Billing period: id={billing_period_id} ({BILLING_MONTH})")

        # Clause tariff
        cur.execute("""
            SELECT ct.id, ct.base_rate, ct.currency_id, ct.logic_parameters,
                   cur.code AS currency_code
            FROM clause_tariff ct
            JOIN currency cur ON cur.id = ct.currency_id
            WHERE ct.project_id = %s AND ct.is_current = true
            LIMIT 1
        """, (PROJECT_ID,))
        tariff = cur.fetchone()
        clause_tariff_id = tariff['id']
        currency_id = tariff['currency_id']
        log.info(f"Tariff: id={clause_tariff_id}, currency={tariff['currency_code']}")

        # ── Step 3: Resolve effective rate ──
        cur.execute("""
            SELECT effective_rate_billing_ccy, effective_rate_hard_ccy
            FROM tariff_rate
            WHERE clause_tariff_id = %s
              AND calc_status IN ('computed', 'approved')
              AND period_start <= %s AND period_end >= %s
            ORDER BY rate_granularity = 'monthly' DESC, period_start DESC
            LIMIT 1
        """, (clause_tariff_id, bm_date, date(2025, 12, 31)))
        rate_row = cur.fetchone()
        rate = _to_decimal(rate_row['effective_rate_billing_ccy']).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP
        )
        log.info(f"Rate: {rate} {tariff['currency_code']}/kWh")

        # ── Step 4: Get meter_aggregate for Dec 2025 ──
        cur.execute("""
            SELECT ma.id AS meter_aggregate_id,
                   ma.contract_line_id, cl.product_desc, cl.energy_category,
                   COALESCE(ma.energy_kwh, ma.total_production, 0) AS metered_kwh,
                   COALESCE(ma.available_energy_kwh, 0) AS available_kwh
            FROM meter_aggregate ma
            JOIN contract_line cl ON cl.id = ma.contract_line_id
            WHERE cl.contract_id = %s
              AND ma.billing_period_id = %s
              AND cl.is_active = true
        """, (contract_id, billing_period_id))
        aggregates = cur.fetchall()
        log.info(f"Meter aggregates: {len(aggregates)} rows for Dec 2025")

        # ── Step 5: Resolve tax config ──
        # Prefer project-specific rule, fall back to country default
        cur.execute("""
            SELECT rules FROM billing_tax_rule
            WHERE organization_id = %s AND country_code = 'KE'
              AND is_active = true
              AND project_id = %s
              AND effective_start_date <= %s
              AND (effective_end_date IS NULL OR effective_end_date >= %s)
            ORDER BY effective_start_date DESC LIMIT 1
        """, (org_id, PROJECT_ID, bm_date, bm_date))
        tax_rule = cur.fetchone()
        if not tax_rule:
            # Fall back to country default (project_id IS NULL)
            cur.execute("""
                SELECT rules FROM billing_tax_rule
                WHERE organization_id = %s AND country_code = 'KE'
                  AND is_active = true AND project_id IS NULL
                  AND effective_start_date <= %s
                  AND (effective_end_date IS NULL OR effective_end_date >= %s)
                ORDER BY effective_start_date DESC LIMIT 1
            """, (org_id, bm_date, bm_date))
        tax_rule = cur.fetchone()
        tax_config = tax_rule['rules']
        log.info(f"Tax config: VAT={tax_config.get('vat', {}).get('rate')}, "
                 f"levies={len(tax_config.get('levies', []))}, "
                 f"withholdings={len(tax_config.get('withholdings', []))}")

        rounding_precision = tax_config.get('rounding_precision', 2)

        # ── Step 6: Build line items ──
        cur.execute("SELECT id, code FROM invoice_line_item_type")
        type_map = {r['code']: r['id'] for r in cur.fetchall()}

        line_items = []
        sort_counter = 1

        # Energy lines (metered only for now)
        for agg in aggregates:
            if agg['energy_category'] != 'metered':
                continue
            kwh = _to_decimal(agg['metered_kwh'])
            if kwh <= 0:
                continue
            line_total = _round_d(kwh * rate, rounding_precision)
            desc = agg['product_desc'] or f"Contract Line {agg['contract_line_id']}"
            line_items.append({
                'type_id': type_map.get('ENERGY'),
                'component_code': None,
                'description': desc,
                'quantity': kwh,
                'unit_price': rate,
                'basis_amount': None,
                'rate_pct': None,
                'line_total_amount': line_total,
                'amount_sign': 1,
                'sort_order': sort_counter,
                'contract_line_id': agg['contract_line_id'],
                'clause_tariff_id': clause_tariff_id,
                'meter_aggregate_id': agg['meter_aggregate_id'],
            })
            log.info(f"  Energy: {desc} — {kwh} kWh × {rate} = {line_total}")
            sort_counter += 1

        energy_subtotal = sum(li['line_total_amount'] for li in line_items)
        log.info(f"  Energy subtotal: {energy_subtotal}")

        # Levies
        levies_total = Decimal('0')
        for levy in tax_config.get('levies', []):
            levy_rate = _to_decimal(levy.get('rate', 0))
            levy_amount = _round_d(energy_subtotal * levy_rate, rounding_precision)
            levies_total += levy_amount
            line_items.append({
                'type_id': type_map.get('LEVY'),
                'component_code': levy['code'],
                'description': f"{levy['name']} ({float(levy_rate)*100:.1f}%)",
                'quantity': None,
                'unit_price': None,
                'basis_amount': energy_subtotal,
                'rate_pct': levy_rate,
                'line_total_amount': levy_amount,
                'amount_sign': 1,
                'sort_order': levy.get('sort_order', 10),
                'contract_line_id': None,
                'clause_tariff_id': None,
                'meter_aggregate_id': None,
            })
            log.info(f"  Levy: {levy['name']} — {levy_rate*100}% of {energy_subtotal} = {levy_amount}")

        subtotal_after_levies = energy_subtotal + levies_total

        # VAT
        vat_amount = Decimal('0')
        vat_config = tax_config.get('vat')
        if vat_config and _to_decimal(vat_config.get('rate', 0)) > 0:
            vat_rate = _to_decimal(vat_config['rate'])
            # Resolve basis
            basis_key = (vat_config.get('applies_to') or {}).get('base', 'energy_subtotal')
            if basis_key == 'subtotal_after_levies':
                vat_basis = subtotal_after_levies
            else:
                vat_basis = energy_subtotal
            vat_amount = _round_d(vat_basis * vat_rate, rounding_precision)
            line_items.append({
                'type_id': type_map.get('TAX'),
                'component_code': 'VAT',
                'description': f"VAT ({float(vat_rate)*100:.0f}%)",
                'quantity': None,
                'unit_price': None,
                'basis_amount': vat_basis,
                'rate_pct': vat_rate,
                'line_total_amount': vat_amount,
                'amount_sign': 1,
                'sort_order': vat_config.get('sort_order', 20),
                'contract_line_id': None,
                'clause_tariff_id': None,
                'meter_aggregate_id': None,
            })
            log.info(f"  VAT: {vat_rate*100}% of {vat_basis} = {vat_amount}")

        invoice_total = subtotal_after_levies + vat_amount

        # Withholdings
        withholdings_total = Decimal('0')
        for wh in tax_config.get('withholdings', []):
            wh_rate = _to_decimal(wh.get('rate', 0))
            basis_key = (wh.get('applies_to') or {}).get('base', 'energy_subtotal')
            if basis_key == 'subtotal_after_levies':
                wh_basis = subtotal_after_levies
            else:
                wh_basis = energy_subtotal
            wh_amount = _round_d(wh_basis * wh_rate, rounding_precision)
            withholdings_total += wh_amount
            line_items.append({
                'type_id': type_map.get('WITHHOLDING'),
                'component_code': wh['code'],
                'description': f"{wh['name']} ({float(wh_rate)*100:.0f}%)",
                'quantity': None,
                'unit_price': None,
                'basis_amount': wh_basis,
                'rate_pct': wh_rate,
                'line_total_amount': -wh_amount,  # negative
                'amount_sign': -1,
                'sort_order': wh.get('sort_order', 30),
                'contract_line_id': None,
                'clause_tariff_id': None,
                'meter_aggregate_id': None,
            })
            log.info(f"  Withholding: {wh['name']} — {wh_rate*100}% of {wh_basis} = -{wh_amount}")

        net_due = invoice_total - withholdings_total

        log.info(f"\n  Invoice Summary:")
        log.info(f"    Energy Subtotal:  {energy_subtotal}")
        log.info(f"    + Levies:         {levies_total}")
        log.info(f"    + VAT:            {vat_amount}")
        log.info(f"    = Invoice Total:  {invoice_total}")
        log.info(f"    - Withholdings:   {withholdings_total}")
        log.info(f"    = Net Due:        {net_due}")

        if DRY_RUN:
            log.info("[DRY RUN] Would insert expected invoice")
            return

        # ── Step 7: Insert expected_invoice_header ──
        source_metadata = {
            'generator': 'generate_mb01_expected_invoice.py',
            'calculation_steps': {
                'energy_subtotal': str(energy_subtotal),
                'levies_total': str(levies_total),
                'subtotal_after_levies': str(subtotal_after_levies),
                'vat_amount': str(vat_amount),
                'invoice_total': str(invoice_total),
                'withholdings_total': str(withholdings_total),
                'net_due': str(net_due),
            },
            'billing_taxes_snapshot': tax_config,
        }

        cur.execute("""
            INSERT INTO expected_invoice_header (
                project_id, contract_id, billing_period_id,
                counterparty_id, currency_id,
                invoice_direction, total_amount,
                version_no, is_current, generated_at,
                source_metadata
            ) VALUES (
                %s, %s, %s, %s, %s,
                'payable', %s,
                1, true, NOW(), %s
            )
            RETURNING id
        """, (
            PROJECT_ID, contract_id, billing_period_id,
            proj['counterparty_id'], currency_id,
            str(net_due),
            json.dumps(source_metadata, default=str),
        ))
        header_id = cur.fetchone()['id']
        log.info(f"Created expected_invoice_header id={header_id}")

        # ── Step 8: Insert line items ──
        for li in line_items:
            cur.execute("""
                INSERT INTO expected_invoice_line_item (
                    expected_invoice_header_id, invoice_line_item_type_id,
                    component_code, description,
                    quantity, line_unit_price,
                    basis_amount, rate_pct,
                    line_total_amount, amount_sign, sort_order,
                    contract_line_id, clause_tariff_id, meter_aggregate_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                header_id, li['type_id'],
                li['component_code'], li['description'],
                str(li['quantity']) if li['quantity'] is not None else None,
                str(li['unit_price']) if li['unit_price'] is not None else None,
                str(li['basis_amount']) if li['basis_amount'] is not None else None,
                str(li['rate_pct']) if li['rate_pct'] is not None else None,
                str(li['line_total_amount']),
                li['amount_sign'],
                li['sort_order'],
                li['contract_line_id'],
                li['clause_tariff_id'],
                li['meter_aggregate_id'],
            ))

        conn.commit()
        log.info(f"Inserted {len(line_items)} line items")

        # ── Verify ──
        cur.execute("""
            SELECT eili.description, ilit.code, eili.quantity,
                   eili.line_unit_price, eili.basis_amount,
                   eili.rate_pct, eili.line_total_amount, eili.amount_sign
            FROM expected_invoice_line_item eili
            LEFT JOIN invoice_line_item_type ilit ON eili.invoice_line_item_type_id = ilit.id
            WHERE eili.expected_invoice_header_id = %s
            ORDER BY eili.sort_order
        """, (header_id,))
        log.info("\nExpected Invoice Line Items:")
        log.info("%-45s %8s %12s %12s %12s" % ("Description", "Type", "Qty", "Rate", "Amount"))
        for row in cur.fetchall():
            log.info("%-45s %8s %12s %12s %12s" % (
                row['description'], row['code'],
                f"{row['quantity']:.2f}" if row['quantity'] else '',
                f"{row['line_unit_price']}" if row['line_unit_price'] else f"{row['rate_pct']}" if row['rate_pct'] else '',
                f"{row['line_total_amount']:.2f}",
            ))

if __name__ == '__main__':
    try:
        main()
    finally:
        close_connection_pool()
