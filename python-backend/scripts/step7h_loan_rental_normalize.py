#!/usr/bin/env python3
"""
Step 7h: Normalize Loan & Rental/Ancillary Data

Migrates loan repayment schedules and rental/ancillary charge data
from project.technical_specs JSONB into normalized tables:
  - clause_tariff rows for loan terms (energy_sale_type = LOAN)
  - loan_repayment rows for amortization schedule periods
  - rental_ancillary_charge rows for monthly BESS/rental/O&M charges

Also backfills clause_tariff.base_rate for non-energy tariffs where NULL.

Source data: project.technical_specs.loan_schedule and .rental_schedule
(populated by Step 7e/7f from Revenue Masterfile).

Data quality: Quarantines corrupt dates (ZL02), placeholder amounts (AMP01),
and cumulative/outlier amounts (AR01 tail). See quarantine_details in report.

═══════════════════════════════════════════════════════════════════════
LOAN FIELD MAPPING (Revenue Masterfile "Loans" tab → loan_repayment)
═══════════════════════════════════════════════════════════════════════

  ZL02 (amortization, ct#66, contract#96):
    Excel "Payment"         / JSONB "payment"          → scheduled_amount
    Excel "Principle"       / JSONB "principal"         → principal_amount
    Excel "Interest"        / JSONB "interest"          → interest_amount
    Excel "Closing Balance" / JSONB "closing_balance"   → closing_balance
    Start date: 2022-10-01 (derived)
    Data quality: needs_review (all date_paid values corrupt)

  GC001 (interest_income, ct#67, contract#16):
    Excel "Invoiced"           / JSONB "invoiced"            → scheduled_amount
    Excel "Capital Repayment"  / JSONB "capital_repayment"   → principal_amount
    Excel "Interest Income"    / JSONB "interest_income"     → interest_amount
    (no closing balance in source)
    Start date: 2016-06-01 (from JSONB dates)
    Data quality: ok

  iSAT01 (fixed_repayment, ct#68, no contract):
    No schedule rows. $61,632/mo in clause_tariff.base_rate + logic_parameters.
    Data quality: needs_review

═══════════════════════════════════════════════════════════════════════
RENTAL CHARGE MAPPING ("Rental and Ancillary" tab → rental_ancillary_charge)
═══════════════════════════════════════════════════════════════════════

  LOI01:  ct#14  → cl#209 (BESS_LEASE,             $2,000/mo)
  AR01:   ct#46  → cl#184 (EQUIPMENT_RENTAL_LEASE,  $9,050/mo)
  QMM01:  ct#33  → cl#262 (BESS_LEASE,             MGA 57,878/mo)
  TWG01:  ct#45  → cl#267 (EQUIPMENT_RENTAL_LEASE,  $306,250/mo)
  TWG01:  ct#31  → cl#266 (OTHER_SERVICE / O&M,     $39,583/mo)
  AMP01:  ct#65  → cl#181 (EQUIPMENT_RENTAL_LEASE,  SKIPPED — placeholder data)

  JSONB "amount" → scheduled_amount
  Quarantine: rows where amount > 3× base_rate flagged as 'quarantined'
"""

import json
import logging
import os
import sys
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger('step7h_loan_rental_normalize')

REPORT_DIR = Path(__file__).resolve().parent.parent / 'reports' / 'cbe-population'
ORG_ID = 1

# ── Loan project config ─────────────────────────────────────────────────────

LOAN_PROJECTS = {
    'ZL02': {
        'loan_variant': 'amortization',
        'clause_tariff_name': 'SL-ZL02 Loan Schedule',
        'contract_id': 96,      # LEASE contract
        'currency_id': 1,       # USD
    },
    'GC001': {
        'loan_variant': 'interest_income',
        'clause_tariff_name': 'KE-GC001 Loan Schedule',
        'contract_id': 16,      # LEASE contract
        'currency_id': 1,       # USD
    },
    'iSAT01': {
        'loan_variant': 'fixed_repayment',
        'clause_tariff_name': 'iSAT01 Loan Repayment',
        'contract_id': None,    # No contract yet
        'currency_id': 1,       # USD
    },
}

# ── Rental/ancillary charge resolution ───────────────────────────────────────

# Maps JSONB charge_type strings to resolution keys
CHARGE_TYPE_KEY_MAP = {
    'BESS Charge': 'BESS_LEASE',
    'Rental Fee': 'EQUIPMENT_RENTAL_LEASE',
    'O&M Fee': 'OTHER_SERVICE',
    'Rental + O&M': 'EQUIPMENT_RENTAL_LEASE',  # TWG01: primary charge; O&M handled separately
    'Lease Rental': 'EQUIPMENT_RENTAL_LEASE',
}

# Per-project resolution: clause_tariff_id, contract_line_id, base_rate for quarantine threshold
RENTAL_RESOLUTION = {
    'LOI01': {
        'BESS_LEASE': {'clause_tariff_id': 14, 'contract_line_id': 209, 'base_rate': 2000},
    },
    'AR01': {
        'EQUIPMENT_RENTAL_LEASE': {'clause_tariff_id': 46, 'contract_line_id': 184, 'base_rate': 9050},
    },
    'QMM01': {
        'BESS_LEASE': {'clause_tariff_id': 33, 'contract_line_id': 262, 'base_rate': 57878},
    },
    'TWG01': {
        'EQUIPMENT_RENTAL_LEASE': {'clause_tariff_id': 45, 'contract_line_id': 267, 'base_rate': 306250},
        'OTHER_SERVICE': {'clause_tariff_id': 31, 'contract_line_id': 266, 'base_rate': 39583},
    },
    'AMP01': None,  # Skip all — placeholder data
}

# ── clause_tariff backfill config ────────────────────────────────────────────

CLAUSE_TARIFF_BACKFILLS = [
    {'id': 65, 'sage_id': 'AMP01', 'base_rate': 4605,
     'lp_merge': {'billing_frequency': 'monthly', 'charge_indexation': '0.02'}},
    {'id': 14, 'sage_id': 'LOI01', 'base_rate': 2000,
     'lp_merge': {'billing_frequency': 'monthly', 'charge_indexation': 'US CPI'}},
    {'id': 31, 'sage_id': 'TWG01', 'base_rate': 39583,
     'lp_merge': {'billing_frequency': 'monthly'}},
]


def _resolve_billing_period_id(cur, billing_month_str):
    """Look up billing_period_id for a given month. Returns None if not found."""
    if not billing_month_str:
        return None
    cur.execute(
        "SELECT id FROM billing_period WHERE start_date = %s LIMIT 1",
        (billing_month_str,)
    )
    row = cur.fetchone()
    return row['id'] if row else None


def backfill_clause_tariffs(cur, dry_run):
    """Backfill clause_tariff.base_rate and logic_parameters from technical_specs."""
    log.info("── 7h-a: Backfilling clause_tariff.base_rate for empty non-energy rows ──")
    results = []

    for bf in CLAUSE_TARIFF_BACKFILLS:
        cur.execute("SELECT base_rate, logic_parameters FROM clause_tariff WHERE id = %s", (bf['id'],))
        row = cur.fetchone()
        if not row:
            log.warning(f"  clause_tariff #{bf['id']} not found — skipping")
            continue

        if row['base_rate'] is not None:
            log.info(f"  ct#{bf['id']} ({bf['sage_id']}): base_rate already set ({row['base_rate']}) — skipping")
            continue

        existing_lp = row['logic_parameters'] or {}
        merged_lp = {**existing_lp, **bf['lp_merge']}

        if not dry_run:
            cur.execute(
                "UPDATE clause_tariff SET base_rate = %s, logic_parameters = %s WHERE id = %s",
                (bf['base_rate'], json.dumps(merged_lp), bf['id'])
            )

        log.info(f"  ct#{bf['id']} ({bf['sage_id']}): set base_rate={bf['base_rate']}, merged lp keys={list(bf['lp_merge'].keys())}")
        results.append({
            'clause_tariff_id': bf['id'],
            'sage_id': bf['sage_id'],
            'base_rate': bf['base_rate'],
            'lp_merged': list(bf['lp_merge'].keys()),
        })

    return results


def create_loan_clause_tariffs(cur, db_projects, est_type_map, tt_type_map, dry_run):
    """Create clause_tariff rows for loan products."""
    log.info("── 7h-b: Creating loan clause_tariff rows ──")
    results = []
    loan_est_id = est_type_map.get('LOAN')
    finance_lease_tt_id = tt_type_map.get('FINANCE_LEASE')

    if not loan_est_id:
        log.error("  energy_sale_type 'LOAN' not found — cannot create loan clause_tariffs")
        return results

    for sage_id, cfg in LOAN_PROJECTS.items():
        proj = db_projects.get(sage_id)
        if not proj:
            log.warning(f"  {sage_id}: project not found in DB — skipping")
            continue

        # Check if loan clause_tariff already exists
        cur.execute("""
            SELECT id FROM clause_tariff
            WHERE project_id = %s AND energy_sale_type_id = %s AND is_current = true
        """, (proj['id'], loan_est_id))
        existing = cur.fetchone()
        if existing:
            log.info(f"  {sage_id}: loan clause_tariff already exists (ct#{existing['id']}) — skipping creation")
            results.append({
                'sage_id': sage_id,
                'clause_tariff_id': existing['id'],
                'action': 'exists',
            })
            continue

        # Build logic_parameters from merged sources
        specs = proj.get('technical_specs') or {}
        loan_json = specs.get('loan_schedule', {})
        lp = {
            'loan_variant': cfg['loan_variant'],
            'source': 'revenue_masterfile',
        }

        # Derive opening_balance for amortization variant
        if cfg['loan_variant'] == 'amortization' and loan_json.get('rows'):
            row0 = loan_json['rows'][0]
            closing = row0.get('closing_balance') or 0
            principal = row0.get('principal') or 0
            if closing and principal:
                lp['opening_balance'] = closing + principal

        # Fixed payment from PO Summary
        fixed_pmt = specs.get('loan_fixed_payment')
        if fixed_pmt:
            lp['fixed_payment'] = fixed_pmt

        # iSAT01 needs_review flag
        if sage_id == 'iSAT01':
            lp['needs_review'] = True

        base_rate = fixed_pmt if cfg['loan_variant'] == 'fixed_repayment' else None

        if not dry_run:
            cur.execute("""
                INSERT INTO clause_tariff (
                    organization_id, project_id, contract_id, name,
                    energy_sale_type_id, tariff_type_id, currency_id,
                    base_rate, logic_parameters, unit, is_current, version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, 1)
                RETURNING id
            """, (
                ORG_ID, proj['id'], cfg['contract_id'], cfg['clause_tariff_name'],
                loan_est_id, finance_lease_tt_id, cfg['currency_id'],
                base_rate, json.dumps(lp), 'USD/month',
            ))
            ct_id = cur.fetchone()['id']
        else:
            ct_id = f'(dry-run-{sage_id})'

        log.info(f"  {sage_id}: created loan clause_tariff ct#{ct_id} ({cfg['loan_variant']}, lp={lp})")
        results.append({
            'sage_id': sage_id,
            'clause_tariff_id': ct_id,
            'action': 'created',
            'loan_variant': cfg['loan_variant'],
            'logic_parameters': lp,
        })

    return results


def populate_loan_repayments(cur, db_projects, loan_ct_results, dry_run):
    """Insert loan_repayment rows from technical_specs.loan_schedule JSONB."""
    log.info("── 7h-c: Populating loan_repayment rows ──")
    total_inserted = 0
    total_quarantined = 0
    quarantine_details = []

    # Build clause_tariff_id lookup from creation results
    ct_lookup = {}
    for r in loan_ct_results:
        if r.get('clause_tariff_id') and r['sage_id'] in LOAN_PROJECTS:
            ct_lookup[r['sage_id']] = r['clause_tariff_id']

    for sage_id, cfg in LOAN_PROJECTS.items():
        ct_id = ct_lookup.get(sage_id)
        if not ct_id or str(ct_id).startswith('(dry-run'):
            log.info(f"  {sage_id}: no clause_tariff_id resolved — skipping repayment rows")
            continue

        proj = db_projects.get(sage_id)
        if not proj:
            continue

        specs = proj.get('technical_specs') or {}
        loan_json = specs.get('loan_schedule', {})
        rows = loan_json.get('rows', [])

        if not rows:
            log.info(f"  {sage_id}: no loan rows in technical_specs — skipping")
            continue

        # Determine start_date for billing_month derivation
        if cfg['loan_variant'] == 'interest_income':
            # GC001: dates are clean ISO strings in JSON
            start_date = None  # Use per-row dates
        else:
            # ZL02: derive start from first row (don't trust date_paid — corrupt Excel serials)
            # ZL02 loan starts Oct 2022 based on CBE docs
            start_date = date(2022, 10, 1)

        inserted = 0
        quarantined_count = 0

        for i, row in enumerate(rows):
            # Derive billing_month
            if cfg['loan_variant'] == 'interest_income':
                billing_month = row.get('date')  # ISO string from GC001
            elif start_date:
                billing_month = (start_date + relativedelta(months=i)).strftime('%Y-%m-%d')
            else:
                billing_month = None

            # Determine data quality
            data_quality = 'ok'
            if cfg['loan_variant'] == 'amortization':
                # ZL02: all date_paid values are corrupt
                data_quality = 'needs_review'
                quarantined_count += 1

            # Resolve billing_period_id
            bp_id = _resolve_billing_period_id(cur, billing_month) if billing_month else None

            # Map fields to unified columns (both variants use same target columns)
            if cfg['loan_variant'] == 'interest_income':
                scheduled_amount = row.get('invoiced')
                principal_amount = row.get('capital_repayment')
                interest_amount = row.get('interest_income')
                closing_balance = None
            else:
                scheduled_amount = row.get('payment')
                principal_amount = row.get('principal')
                interest_amount = row.get('interest')
                closing_balance = row.get('closing_balance')

            source_row_ref = f"Loans tab, {loan_json.get('loan_type', sage_id)}, row {3 + i + 1}"

            if not dry_run:
                cur.execute("""
                    INSERT INTO loan_repayment (
                        clause_tariff_id, organization_id,
                        billing_month, billing_period_id,
                        scheduled_amount, principal_amount, interest_amount, closing_balance,
                        data_quality, source, source_row_ref, source_metadata
                    ) VALUES (%s,%s, %s,%s, %s,%s,%s,%s, %s,%s,%s,%s)
                    ON CONFLICT (clause_tariff_id, billing_month) DO NOTHING
                """, (
                    ct_id, ORG_ID,
                    billing_month, bp_id,
                    scheduled_amount, principal_amount, interest_amount, closing_balance,
                    data_quality, 'revenue_masterfile', source_row_ref,
                    json.dumps(row, default=str),
                ))

            inserted += 1

        total_inserted += inserted
        total_quarantined += quarantined_count
        log.info(f"  {sage_id}: {inserted} loan_repayment rows (data_quality: {quarantined_count} needs_review)")

        if quarantined_count > 0:
            quarantine_details.append({
                'project': sage_id,
                'table': 'loan_repayment',
                'reason': 'corrupt date_paid (Excel serial dates)',
                'count': quarantined_count,
            })

    return total_inserted, total_quarantined, quarantine_details


def populate_rental_charges(cur, db_projects, dry_run):
    """Insert rental_ancillary_charge rows from technical_specs.rental_schedule JSONB."""
    log.info("── 7h-d: Populating rental_ancillary_charge rows ──")
    total_inserted = 0
    total_quarantined = 0
    total_skipped = 0
    quarantine_details = []

    for sage_id, resolution in RENTAL_RESOLUTION.items():
        proj = db_projects.get(sage_id)
        if not proj:
            log.warning(f"  {sage_id}: project not found — skipping")
            continue

        specs = proj.get('technical_specs') or {}
        rental_rows = specs.get('rental_schedule', [])

        if not rental_rows:
            log.info(f"  {sage_id}: no rental_schedule in technical_specs — skipping")
            continue

        # AMP01: skip all — placeholder data
        if resolution is None:
            total_skipped += len(rental_rows)
            log.info(f"  {sage_id}: SKIPPED all {len(rental_rows)} rows (placeholder amounts)")
            quarantine_details.append({
                'project': sage_id,
                'table': 'rental_ancillary_charge',
                'reason': 'placeholder amounts (1.0/2.0 = OY values)',
                'count': len(rental_rows),
            })
            continue

        inserted = 0
        quarantined = 0
        skipped = 0

        for i, row in enumerate(rental_rows):
            raw_charge_type = row.get('charge_type', '')
            resolution_key = CHARGE_TYPE_KEY_MAP.get(raw_charge_type)

            if not resolution_key:
                log.warning(f"  {sage_id}: unknown charge_type '{raw_charge_type}' — skipping row")
                skipped += 1
                continue

            # TWG01 special case: "Rental + O&M" rows map to EQUIPMENT_RENTAL_LEASE
            # O&M rows have a separate column in the Excel, but in JSONB they're combined
            res = resolution.get(resolution_key)
            if not res:
                log.warning(f"  {sage_id}: no resolution for {resolution_key} — skipping")
                skipped += 1
                continue

            amount = row.get('amount')
            billing_month = row.get('date')
            operating_year = row.get('operating_year')

            if amount is None or amount <= 0:
                skipped += 1
                continue

            # Quarantine check: amount > 3× base_rate
            base_rate = res['base_rate']
            data_quality = 'ok'
            if base_rate and amount > 3 * base_rate:
                data_quality = 'quarantined'
                quarantined += 1

            bp_id = _resolve_billing_period_id(cur, billing_month) if billing_month else None

            source_row_ref = f"Rental and Ancillary tab, {sage_id}, row {3 + i + 1}"

            if not dry_run:
                cur.execute("""
                    INSERT INTO rental_ancillary_charge (
                        clause_tariff_id, organization_id, contract_line_id,
                        billing_month, billing_period_id,
                        operating_year, scheduled_amount, billing_currency_id,
                        data_quality, source, source_row_ref, source_metadata
                    ) VALUES (%s,%s,%s, %s,%s, %s,%s,%s, %s,%s,%s,%s)
                    ON CONFLICT (clause_tariff_id, contract_line_id, billing_month) DO NOTHING
                """, (
                    res['clause_tariff_id'], ORG_ID, res['contract_line_id'],
                    billing_month, bp_id,
                    int(operating_year) if operating_year else None,
                    amount, res.get('billing_currency_id', 1),
                    data_quality, 'revenue_masterfile', source_row_ref,
                    json.dumps(row, default=str),
                ))

            inserted += 1

        total_inserted += inserted
        total_quarantined += quarantined
        total_skipped += skipped

        log.info(f"  {sage_id}: {inserted} rows inserted, {quarantined} quarantined, {skipped} skipped")

        if quarantined > 0:
            quarantine_details.append({
                'project': sage_id,
                'table': 'rental_ancillary_charge',
                'reason': f'amount > 3x base_rate ({base_rate})',
                'count': quarantined,
            })

    return total_inserted, total_quarantined, total_skipped, quarantine_details


def main():
    dry_run = '--dry-run' in sys.argv
    mode = 'DRY RUN' if dry_run else 'LIVE'
    log.info(f"Step 7h: Normalize Loan & Rental Data ({mode})")

    init_connection_pool()
    report = {
        'timestamp': datetime.now().isoformat(),
        'mode': mode,
        'clause_tariff_backfills': {'updated': 0, 'details': []},
        'loan_clause_tariffs': {'created': 0, 'details': []},
        'loan_repayments': {'inserted': 0, 'needs_review': 0, 'skipped': 0},
        'rental_ancillary_charges': {'inserted': 0, 'quarantined': 0, 'skipped': 0},
        'quarantine_details': [],
    }

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = '300s'")

            # Load projects
            cur.execute("""
                SELECT p.id, p.sage_id, p.technical_specs,
                       c.id as primary_contract_id
                FROM project p
                LEFT JOIN contract c ON c.project_id = p.id
                WHERE p.organization_id = %s
                ORDER BY p.sage_id, c.id
            """, (ORG_ID,))
            db_projects = {}
            for row in cur.fetchall():
                sid = row['sage_id']
                if sid not in db_projects:
                    db_projects[sid] = {
                        'id': row['id'],
                        'sage_id': sid,
                        'technical_specs': row['technical_specs'] or {},
                        'primary_contract_id': row['primary_contract_id'],
                    }

            # Load taxonomy maps
            cur.execute("SELECT id, code FROM energy_sale_type WHERE is_active = true")
            est_type_map = {row['code']: row['id'] for row in cur.fetchall()}

            cur.execute("SELECT id, code FROM tariff_type")
            tt_type_map = {row['code']: row['id'] for row in cur.fetchall()}

            log.info(f"DB state: {len(db_projects)} projects")

            # ── Step 7h-a: Backfill clause_tariff base_rates ──
            bf_results = backfill_clause_tariffs(cur, dry_run)
            report['clause_tariff_backfills'] = {'updated': len(bf_results), 'details': bf_results}

            # ── Step 7h-b: Create loan clause_tariff rows ──
            loan_ct_results = create_loan_clause_tariffs(
                cur, db_projects, est_type_map, tt_type_map, dry_run
            )
            created_count = sum(1 for r in loan_ct_results if r.get('action') == 'created')
            report['loan_clause_tariffs'] = {'created': created_count, 'details': loan_ct_results}

            # ── Step 7h-c: Populate loan_repayment rows ──
            lr_inserted, lr_quarantined, lr_quarantine = populate_loan_repayments(
                cur, db_projects, loan_ct_results, dry_run
            )
            report['loan_repayments'] = {
                'inserted': lr_inserted,
                'needs_review': lr_quarantined,
                'skipped': 0,
            }
            report['quarantine_details'].extend(lr_quarantine)

            # ── Step 7h-d: Populate rental_ancillary_charge rows ──
            rac_inserted, rac_quarantined, rac_skipped, rac_quarantine = populate_rental_charges(
                cur, db_projects, dry_run
            )
            report['rental_ancillary_charges'] = {
                'inserted': rac_inserted,
                'quarantined': rac_quarantined,
                'skipped': rac_skipped,
            }
            report['quarantine_details'].extend(rac_quarantine)

            if not dry_run:
                conn.commit()
                log.info("── Committed all changes ──")
            else:
                conn.rollback()
                log.info("── Dry run — rolled back ──")

    finally:
        close_connection_pool()

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"step7h_{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Report written to {report_file}")
    log.info("=" * 60)
    log.info(f"Summary:")
    log.info(f"  clause_tariff backfills: {report['clause_tariff_backfills']['updated']}")
    log.info(f"  loan clause_tariffs created: {report['loan_clause_tariffs']['created']}")
    log.info(f"  loan_repayment rows: {report['loan_repayments']['inserted']} ({report['loan_repayments']['needs_review']} needs_review)")
    log.info(f"  rental_ancillary_charge rows: {report['rental_ancillary_charges']['inserted']} ({report['rental_ancillary_charges']['quarantined']} quarantined, {report['rental_ancillary_charges']['skipped']} skipped)")
    log.info(f"  quarantine entries: {len(report['quarantine_details'])}")


if __name__ == '__main__':
    main()
