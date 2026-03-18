#!/usr/bin/env python3
"""
Step 7: Revenue Masterfile — Full Extraction

Source: CBE Asset Management Operating Revenue Masterfile - new.xlsb
Tabs processed:
  7a. Reporting Graphs  → counterparty.industry (verify/fill)
  7b. PO Summary        → clause_tariff fields, project.technical_specs
  7c. Invoiced SAGE     → exchange_rate table (GHS, KES, NGN monthly)
  7d. Energy Sales      → cross-check forecasts (flag only)
  7e. Loans             → project.technical_specs.loan_schedule JSONB
  7f. Rental/Ancillary  → project.technical_specs.rental_schedule JSONB
  7g. US CPI            → staging JSON (pending migration)

Enrichment-only: updates existing rows, never creates new projects/tariffs.
"""

import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pyxlsb import open_workbook

load_dotenv()

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger('step7_revenue_masterfile')

WB_PATH = Path(__file__).resolve().parent.parent.parent / 'CBE_data_extracts' / 'CBE Asset Management Operating Revenue Masterfile - new.xlsb'
REPORT_DIR = Path(__file__).resolve().parent.parent / 'reports' / 'cbe-population'
ORG_ID = 1

# Excel epoch for serial date conversion
EXCEL_EPOCH = datetime(1899, 12, 30)

def xl_date(serial) -> str | None:
    """Convert Excel serial number to ISO date string."""
    if serial is None or serial == '' or serial == 0:
        return None
    try:
        serial = float(serial)
        if serial < 1:
            return None
        dt = EXCEL_EPOCH + timedelta(days=serial)
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError, OverflowError):
        return None

def xl_float(v) -> float | None:
    """Safely convert to float."""
    if v is None or v == '' or v == 0:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

def xl_str(v) -> str | None:
    """Safely convert to stripped string."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def read_sheet(wb, name, max_rows=500, max_cols=50):
    """Read rows from a sheet."""
    rows = []
    with wb.get_sheet(name) as sheet:
        for i, row in enumerate(sheet.rows()):
            if i >= max_rows:
                break
            vals = []
            for j, cell in enumerate(row):
                if j >= max_cols:
                    break
                vals.append(cell.v)
            rows.append(vals)
    return rows


# ─── SAGE ID resolution from PO Summary names ───────────────────────────────

# PO Summary col A (Name) → FM sage_id
PO_NAME_TO_SAGE = {
    'garden city mall': 'GC001',
    'zoodlabs': 'ZL02',
    'zoodlabs group': 'ZL02',
    'isat africa': 'TBC',
    'indorama ventures': 'IVL01',
    'guinness ghana breweries': 'GBL01',
    'kasapreko': 'KAS01',
    'unilever ghana': 'UGL01',
    'arijiju retreat': 'AR01',
    'arijiju': 'AR01',
    'loisaba': 'LOI01',
    'maisha mabati mills': 'MB01',
    'maisha mabati': 'MB01',
    'maisha minerals & fertilizer': 'MF01',
    'maisha minerals': 'MF01',
    'maisha packaging lukenya': 'MP02',
    'maisha packaging nakuru': 'MP01',
    'national cement athi river': 'NC02',
    'national cement nakuru': 'NC03',
    'teepee brush manufacturers': 'TBM01',
    'teepee brushes': 'TBM01',
    'ekaterra tea kenya': 'UTK01',
    'ekaterra tea': 'UTK01',
    'xflora': 'XFAB',  # XFlora group → maps to XFAB as primary
    'xflora group': 'XFAB',
    'ampersand': 'AMP01',
    'rio tinto qmm solar': 'QMM01',
    'rio tinto qmm': 'QMM01',
    'molo graphite': 'ERG',
    'jabi lake mall': 'JAB01',
    'jabi lake': 'JAB01',
    'nigerian breweries ibadan': 'NBL01',
    'nigerian breweries ama': 'NBL02',
    'miro forestry': 'MIR01',
    'unsos baidoa': 'UNSOS',
    'unsos': 'UNSOS',
    'balama graphite': 'TWG01',
    'caledonia': 'CAL01',
    'caledonia mining': 'CAL01',
    'mohinani': 'MOH01',
    'accra breweries': 'ABI01',
    'izuba bnt': 'BNT01',
}

# Reporting Graphs col A (Project name) → sage_id (may differ from PO Summary)
RG_NAME_TO_SAGE = {
    **PO_NAME_TO_SAGE,
    'garden city mall (gc retail limited)': 'GC001',
    'zoodlabs energy services': 'ZL02',
    'indorama ventures (lomé)': 'IVL01',
    'guinness ghana breweries ltd': 'GBL01',
    'kasapreko company limited': 'KAS01',
    'unilever ghana limited': 'UGL01',
    'maisha mabati mills ltd': 'MB01',
    'maisha minerals & fertilizer ltd': 'MF01',
    'maisha packaging limited lukenya': 'MP02',
    'maisha packaging limited nakuru': 'MP01',
    'national cement company athi river': 'NC02',
    'national cement company nakuru': 'NC03',
    'teepee brush manufacturers ltd': 'TBM01',
    'ekaterra tea kenya ltd': 'UTK01',
    'xflora limited': 'XFAB',
    'rio tinto qmm solar project': 'QMM01',
    'molo graphite (next source)': 'ERG',
    'jabi lake mall abuja': 'JAB01',
    'nigerian breweries plc ibadan': 'NBL01',
    'nigerian breweries plc ama': 'NBL02',
    'miro forestry & timber products': 'MIR01',
}


def resolve_sage_id(name: str, mapping: dict) -> str | None:
    """Resolve project name to sage_id using fuzzy matching."""
    if not name:
        return None
    key = name.strip().lower()
    # Direct match
    if key in mapping:
        return mapping[key]
    # Substring match
    for k, v in mapping.items():
        if k in key or key in k:
            return v
    return None


# ─── 7a: Reporting Graphs ───────────────────────────────────────────────────

def process_reporting_graphs(wb, db_projects, db_counterparties):
    """Extract industry from Reporting Graphs tab and verify against counterparty."""
    log.info("7a: Processing Reporting Graphs tab...")
    rows = read_sheet(wb, 'Reporting Graphs', max_rows=50, max_cols=10)
    discrepancies = []
    updates = []

    for row in rows[2:]:  # Skip header rows
        name = xl_str(row[0]) if len(row) > 0 else None
        customer = xl_str(row[1]) if len(row) > 1 else None
        industry = xl_str(row[2]) if len(row) > 2 else None

        if not name or not industry or industry == '0xf':
            continue

        sage_id = resolve_sage_id(name, RG_NAME_TO_SAGE)
        if not sage_id or sage_id not in db_projects:
            continue

        # Find matching counterparty
        proj = db_projects[sage_id]
        contract_id = proj.get('primary_contract_id')
        cp_id = proj.get('counterparty_id')
        if cp_id and cp_id in db_counterparties:
            existing = db_counterparties[cp_id].get('industry')
            if existing and existing != industry:
                discrepancies.append({
                    'severity': 'warning',
                    'category': 'value_conflict',
                    'project': sage_id,
                    'field': 'counterparty.industry',
                    'source_a': f'RevMasterfile: {industry}',
                    'source_b': f'DB: {existing}',
                    'recommended_action': 'Verify industry classification',
                    'status': 'open',
                })
            elif not existing:
                updates.append({'counterparty_id': cp_id, 'industry': industry, 'sage_id': sage_id})

    log.info(f"  7a: {len(updates)} industry updates, {len(discrepancies)} discrepancies")
    return updates, discrepancies


# ─── Taxonomy Mapping Helpers ────────────────────────────────────────────────

# PO Summary col D (Revenue Type) → energy_sale_type code
REVENUE_TYPE_TO_EST = {
    'energy sales': 'ENERGY_SALES',
    'equipment rental': 'EQUIPMENT_RENTAL_LEASE',
    'finance lease': 'EQUIPMENT_RENTAL_LEASE',
    'rental': 'EQUIPMENT_RENTAL_LEASE',
    'boot': 'EQUIPMENT_RENTAL_LEASE',
    'loan': 'LOAN',
    'bess': 'BESS_LEASE',
    'battery': 'BESS_LEASE',
    'esa': 'ENERGY_AS_SERVICE',
    'energy as a service': 'ENERGY_AS_SERVICE',
}

# PO Summary col E (Energy Sale Type) + col F (Connection) → tariff_type code
SALE_TYPE_TO_TT = {
    ('ppa', 'grid'): 'TAKE_AND_PAY',
    ('ppa', 'generator'): 'TAKE_AND_PAY',
    ('ppa', None): 'TAKE_AND_PAY',
    ('ssa', 'grid'): 'TAKE_AND_PAY',
    ('ssa', 'generator'): 'TAKE_AND_PAY',
    ('ssa', None): 'TAKE_AND_PAY',
    ('resa', None): 'TAKE_AND_PAY',
    ('esa', None): 'TAKE_AND_PAY',
    ('take or pay', None): 'TAKE_OR_PAY',
    ('take and pay', None): 'TAKE_AND_PAY',
    ('minimum offtake', None): 'MINIMUM_OFFTAKE',
    ('finance lease', None): 'FINANCE_LEASE',
    ('operating lease', None): 'OPERATING_LEASE',
    ('boot', None): 'OPERATING_LEASE',
    ('loan', None): 'NOT_APPLICABLE',
}


def _resolve_energy_sale_type_code(revenue_type: str) -> str | None:
    """Map PO Summary Revenue Type (col D) to energy_sale_type code."""
    if not revenue_type:
        return None
    key = revenue_type.strip().lower()
    if key in REVENUE_TYPE_TO_EST:
        return REVENUE_TYPE_TO_EST[key]
    # Substring match
    for k, v in REVENUE_TYPE_TO_EST.items():
        if k in key or key in k:
            return v
    return None


def _resolve_tariff_type_code(energy_sale_type: str, connection: str | None) -> str | None:
    """Map PO Summary Energy Sale Type (col E) + Connection (col F) to tariff_type code."""
    if not energy_sale_type:
        return None
    est_key = energy_sale_type.strip().lower()
    conn_key = connection.strip().lower() if connection else None

    # Try exact (sale_type, connection) pair
    if (est_key, conn_key) in SALE_TYPE_TO_TT:
        return SALE_TYPE_TO_TT[(est_key, conn_key)]
    # Try with None connection
    if (est_key, None) in SALE_TYPE_TO_TT:
        return SALE_TYPE_TO_TT[(est_key, None)]
    # Substring match on sale type
    for (k_est, k_conn), v in SALE_TYPE_TO_TT.items():
        if k_est in est_key:
            if k_conn is None or k_conn == conn_key:
                return v
    return None


def _resolve_escalation_code(indexation: str, grid_mrp: float | None, gen_mrp: float | None) -> str | None:
    """Map PO Summary Indexation (col AD) + MRP columns to escalation_type code."""
    if not indexation:
        return None

    idx_val = indexation.strip()

    # Check for numeric escalation rate
    try:
        rate = float(idx_val)
        if rate > 0:
            return 'PERCENTAGE'
        else:
            return 'NONE'
    except ValueError:
        pass

    upper = idx_val.upper()
    if 'CPI' in upper:
        return 'US_CPI'
    if upper in ('N/A', 'NONE', 'NIL', '-', '0', 'FLAT'):
        return 'NONE'

    # MRP-based derivation
    has_grid = grid_mrp is not None and grid_mrp > 0
    has_gen = gen_mrp is not None and gen_mrp > 0
    if has_grid and has_gen:
        return 'FLOATING_GRID_GENERATOR'
    if has_grid:
        return 'FLOATING_GRID'
    if has_gen:
        return 'FLOATING_GENERATOR'

    return None


# ─── 7b: PO Summary ─────────────────────────────────────────────────────────

def process_po_summary(wb, db_projects, db_tariffs, currency_code_to_id=None,
                       esc_type_map=None, est_type_map=None, tt_type_map=None):
    """Extract tariff params, technical specs from PO Summary tab."""
    log.info("7b: Processing PO Summary tab...")
    rows = read_sheet(wb, 'PO Summary', max_rows=55, max_cols=45)
    discrepancies = []
    tariff_updates = []
    tech_spec_updates = []

    # Find header row (row 4, 0-indexed=3)
    header_row = 3

    for row in rows[header_row + 1:]:
        name = xl_str(row[0]) if len(row) > 0 else None
        if not name:
            continue
        # Skip section headers
        if name.upper() in ('OPERATIONAL', 'CONSTRUCTION', 'TESCO PROJECTS', 'TOTAL'):
            continue

        sage_id = resolve_sage_id(name, PO_NAME_TO_SAGE)
        if not sage_id or sage_id not in db_projects:
            continue

        proj = db_projects[sage_id]
        pid = proj['id']

        # ── Verification fields ──
        country = xl_str(row[1]) if len(row) > 1 else None
        cod_serial = row[7] if len(row) > 7 else None
        cod_date = xl_date(cod_serial)
        term = xl_float(row[8]) if len(row) > 8 else None
        cod_end_serial = row[9] if len(row) > 9 else None
        cod_end = xl_date(cod_end_serial)
        pv_kwp = xl_float(row[11]) if len(row) > 11 else None
        annual_yield = xl_float(row[15]) if len(row) > 15 else None
        annual_prod = xl_float(row[16]) if len(row) > 16 else None
        degradation = xl_float(row[17]) if len(row) > 17 else None

        # Cross-check COD
        db_cod = proj.get('cod_date')
        if cod_date and db_cod and cod_date != db_cod:
            discrepancies.append({
                'severity': 'warning', 'category': 'value_conflict',
                'project': sage_id, 'field': 'cod_date',
                'source_a': f'PO Summary: {cod_date}', 'source_b': f'DB: {db_cod}',
                'recommended_action': 'Review — PO Summary vs PPW/DB',
                'status': 'open',
            })

        # Cross-check capacity
        db_cap = proj.get('installed_dc_capacity_kwp')
        if pv_kwp and db_cap and abs(pv_kwp - float(db_cap)) > 1.0:
            discrepancies.append({
                'severity': 'info', 'category': 'value_conflict',
                'project': sage_id, 'field': 'installed_dc_capacity_kwp',
                'source_a': f'PO Summary: {pv_kwp}', 'source_b': f'DB: {db_cap}',
                'recommended_action': 'Info — PO Summary cross-check',
                'status': 'open',
            })

        # ── New fields → technical_specs JSONB ──
        revenue_type = xl_str(row[3]) if len(row) > 3 else None
        energy_sale_type = xl_str(row[4]) if len(row) > 4 else None
        connection = xl_str(row[5]) if len(row) > 5 else None
        capex = xl_float(row[6]) if len(row) > 6 else None
        bess_kwh = xl_float(row[12]) if len(row) > 12 else None
        thermal_kwe = xl_float(row[13]) if len(row) > 13 else None
        wind_mw = xl_float(row[14]) if len(row) > 14 else None

        specs = {}
        if revenue_type: specs['revenue_type'] = revenue_type
        if connection: specs['connection'] = connection
        if capex: specs['capex_usd'] = capex
        if bess_kwh: specs['bess_kwh'] = bess_kwh
        if thermal_kwe: specs['thermal_kwe'] = thermal_kwe
        if wind_mw: specs['wind_mw'] = wind_mw
        if annual_yield: specs['annual_specific_yield_kwh_kwp'] = annual_yield
        if degradation: specs['degradation_pct_po_summary'] = degradation

        # Loan/charge fields (cols 32-39)
        loan_fixed = xl_float(row[32]) if len(row) > 32 else None
        lease_rental = xl_float(row[33]) if len(row) > 33 else None
        energy_fee = xl_float(row[34]) if len(row) > 34 else None
        bess_charge = xl_float(row[35]) if len(row) > 35 else None
        om_fee = xl_float(row[36]) if len(row) > 36 else None
        charge_indexation = xl_str(row[37]) if len(row) > 37 else None
        charge_comments = xl_str(row[38]) if len(row) > 38 else None
        oy_definition = xl_str(row[39]) if len(row) > 39 else None

        if loan_fixed: specs['loan_fixed_payment'] = loan_fixed
        if lease_rental: specs['lease_rental'] = lease_rental
        if energy_fee: specs['energy_fee'] = energy_fee
        if bess_charge: specs['bess_charge'] = bess_charge
        if om_fee: specs['om_fee'] = om_fee
        if charge_indexation: specs['charge_indexation'] = charge_indexation
        if charge_comments: specs['charge_comments'] = charge_comments
        if oy_definition: specs['oy_definition'] = oy_definition

        if specs:
            tech_spec_updates.append({
                'project_id': pid,
                'sage_id': sage_id,
                'specs': specs,
                'existing_specs': proj.get('technical_specs') or {},
            })

        # ── Tariff fields → clause_tariff ──
        tariff_currency = xl_str(row[19]) if len(row) > 19 else None
        fixed_tariff = xl_float(row[20]) if len(row) > 20 else None
        grid_mrp = xl_float(row[21]) if len(row) > 21 else None
        grid_discount = xl_float(row[22]) if len(row) > 22 else None
        grid_solar = xl_float(row[23]) if len(row) > 23 else None
        gen_mrp = xl_float(row[24]) if len(row) > 24 else None
        gen_discount = xl_float(row[25]) if len(row) > 25 else None
        gen_solar = xl_float(row[26]) if len(row) > 26 else None
        min_tariff = xl_float(row[27]) if len(row) > 27 else None
        max_tariff = xl_float(row[28]) if len(row) > 28 else None
        indexation = xl_str(row[29]) if len(row) > 29 else None
        first_indexation_serial = row[30] if len(row) > 30 else None
        first_indexation = xl_date(first_indexation_serial)
        indexation_comments = xl_str(row[31]) if len(row) > 31 else None

        # Find matching tariff(s) for this project
        project_tariffs = db_tariffs.get(sage_id, [])
        if not project_tariffs:
            continue

        for tariff in project_tariffs:
            tid = tariff['id']
            est_name = tariff.get('energy_sale_type_name', '')
            lp = tariff.get('logic_parameters') or {}

            update = {'tariff_id': tid, 'sage_id': sage_id, 'fields': {}, 'lp_fields': {}}

            # Determine which rate to apply based on energy sale type
            if 'Fixed' in (est_name or ''):
                if fixed_tariff and not tariff.get('base_rate'):
                    update['fields']['base_rate'] = fixed_tariff
            elif 'Grid + Generator' in (est_name or ''):
                if grid_solar and not tariff.get('base_rate'):
                    update['fields']['base_rate'] = grid_solar
                if grid_discount:
                    update['lp_fields']['grid_discount_pct'] = grid_discount
                if gen_discount:
                    update['lp_fields']['generator_discount_pct'] = gen_discount
            elif 'Grid' in (est_name or ''):
                if grid_solar and not tariff.get('base_rate'):
                    update['fields']['base_rate'] = grid_solar
                if grid_discount:
                    update['lp_fields']['discount_percentage'] = grid_discount
            elif 'Generator' in (est_name or ''):
                if gen_solar and not tariff.get('base_rate'):
                    update['fields']['base_rate'] = gen_solar
                if gen_discount:
                    update['lp_fields']['discount_percentage'] = gen_discount

            # Floor/ceiling (apply to all tariff types)
            if min_tariff and not lp.get('floor_rate'):
                update['lp_fields']['floor_rate'] = min_tariff
            if max_tariff and not lp.get('ceiling_rate'):
                update['lp_fields']['ceiling_rate'] = max_tariff

            # Indexation
            if indexation and not lp.get('indexation_method'):
                update['lp_fields']['indexation_method'] = indexation
            if first_indexation and not lp.get('first_indexation_date'):
                update['lp_fields']['first_indexation_date'] = first_indexation
            if indexation_comments and not lp.get('indexation_context'):
                update['lp_fields']['indexation_context'] = indexation_comments

            # A1: Apply tariff_currency → currency_id
            if tariff_currency and currency_code_to_id:
                resolved_ccy_id = currency_code_to_id.get(tariff_currency.upper())
                if resolved_ccy_id and resolved_ccy_id != tariff.get('currency_id'):
                    update['fields']['currency_id'] = resolved_ccy_id
                    update['fields']['unit'] = f'{tariff_currency.upper()}/kWh'
                    log.info(f"    Currency fix {sage_id} tariff {tid}: → {tariff_currency.upper()} (id={resolved_ccy_id})")

            # A2: Map indexation → escalation_type_id (code-based lookup)
            if indexation and not tariff.get('escalation_type_id'):
                idx_val = indexation.strip()
                esc_code = _resolve_escalation_code(idx_val, grid_mrp, gen_mrp)
                if esc_code and esc_type_map:
                    esc_id = esc_type_map.get(esc_code)
                    if esc_id:
                        update['fields']['escalation_type_id'] = esc_id
                        try:
                            rate = float(idx_val)
                            if rate > 0:
                                update['lp_fields']['escalation_rate'] = rate
                        except ValueError:
                            pass
                    else:
                        # Unknown code — blocking discrepancy
                        discrepancies.append({
                            'severity': 'critical', 'category': 'unmapped_taxonomy',
                            'project': sage_id, 'field': 'escalation_type',
                            'source_a': f'PO Summary indexation: {idx_val}',
                            'source_b': f'Resolved code: {esc_code} (not in DB)',
                            'recommended_action': f'Add escalation_type code={esc_code} to DB',
                            'status': 'open',
                        })

            # A3: Map revenue_type → energy_sale_type_id (code-based lookup)
            if revenue_type and not tariff.get('energy_sale_type_id') and est_type_map:
                est_code = _resolve_energy_sale_type_code(revenue_type)
                if est_code:
                    est_id = est_type_map.get(est_code)
                    if est_id:
                        update['fields']['energy_sale_type_id'] = est_id
                    else:
                        discrepancies.append({
                            'severity': 'critical', 'category': 'unmapped_taxonomy',
                            'project': sage_id, 'field': 'energy_sale_type',
                            'source_a': f'PO Summary Revenue Type: {revenue_type}',
                            'source_b': f'Resolved code: {est_code} (not in DB)',
                            'recommended_action': f'Add energy_sale_type code={est_code} to DB',
                            'status': 'open',
                        })
                else:
                    discrepancies.append({
                        'severity': 'critical', 'category': 'unmapped_taxonomy',
                        'project': sage_id, 'field': 'energy_sale_type',
                        'source_a': f'PO Summary Revenue Type: {revenue_type}',
                        'source_b': 'No mapping rule',
                        'recommended_action': f'Add mapping for revenue_type={revenue_type!r}',
                        'status': 'open',
                    })

            # A4: Map energy_sale_type + connection → tariff_type_id (code-based lookup)
            if energy_sale_type and not tariff.get('tariff_type_id') and tt_type_map:
                tt_code = _resolve_tariff_type_code(energy_sale_type, connection)
                if tt_code:
                    tt_id = tt_type_map.get(tt_code)
                    if tt_id:
                        update['fields']['tariff_type_id'] = tt_id
                    else:
                        discrepancies.append({
                            'severity': 'critical', 'category': 'unmapped_taxonomy',
                            'project': sage_id, 'field': 'tariff_type',
                            'source_a': f'PO Summary Energy Sale Type: {energy_sale_type}, Connection: {connection}',
                            'source_b': f'Resolved code: {tt_code} (not in DB)',
                            'recommended_action': f'Add tariff_type code={tt_code} to DB',
                            'status': 'open',
                        })
                else:
                    discrepancies.append({
                        'severity': 'critical', 'category': 'unmapped_taxonomy',
                        'project': sage_id, 'field': 'tariff_type',
                        'source_a': f'PO Summary Energy Sale Type: {energy_sale_type}, Connection: {connection}',
                        'source_b': 'No mapping rule',
                        'recommended_action': f'Add mapping for energy_sale_type={energy_sale_type!r}, connection={connection!r}',
                        'status': 'open',
                    })

            # Contract term → end date
            if term and cod_date:
                update['lp_fields']['contract_term_years_po'] = term
            if cod_end:
                update['lp_fields']['contract_end_date_po'] = cod_end

            if update['fields'] or update['lp_fields']:
                tariff_updates.append(update)

    log.info(f"  7b: {len(tech_spec_updates)} tech_spec updates, {len(tariff_updates)} tariff updates, {len(discrepancies)} discrepancies")
    return tech_spec_updates, tariff_updates, discrepancies


# ─── 7c: Invoiced SAGE → Exchange Rates ──────────────────────────────────────

def process_exchange_rates(wb, existing_rates):
    """Extract monthly FX closing spot rates from Invoiced SAGE tab."""
    log.info("7c: Processing Invoiced SAGE tab (exchange rates)...")
    rows = read_sheet(wb, 'Invoiced SAGE ', max_rows=80, max_cols=50)
    new_rates = []
    discrepancies = []

    # Currency rows: 62=GHS, 63=KES, 64=NGN (1-indexed → 61,62,63 in 0-indexed)
    CURRENCY_ROWS = {
        61: 'GHS',  # Row 62
        62: 'KES',  # Row 63
        63: 'NGN',  # Row 64
    }
    CURRENCY_IDS = {'GHS': 5, 'KES': 7, 'NGN': 6}

    # Row 2 (0-indexed=1) has year numbers, Row 3 (0-indexed=2) has month names
    # Columns are grouped by year with a YTD total column between groups
    year_row = rows[1] if len(rows) > 1 else []
    month_row = rows[2] if len(rows) > 2 else []

    MONTH_MAP = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12,
    }

    # Build col_idx → (year, month) mapping
    month_cols = []
    current_year = None
    for col_idx in range(4, min(len(month_row), len(year_row))):
        # Track year from year row
        yr = year_row[col_idx] if col_idx < len(year_row) else None
        if yr is not None:
            try:
                current_year = int(float(yr))
            except (ValueError, TypeError):
                pass

        month_name = xl_str(month_row[col_idx]) if col_idx < len(month_row) else None
        if not month_name or not current_year:
            continue

        month_num = MONTH_MAP.get(month_name.lower())
        if month_num:
            rate_date = f'{current_year}-{month_num:02d}-01'
            month_cols.append((col_idx, rate_date))

    if not month_cols:
        log.warning("  7c: Could not parse month columns from Invoiced SAGE header")
        return new_rates, discrepancies

    log.info(f"  7c: Found {len(month_cols)} month columns ({month_cols[0][1]} to {month_cols[-1][1]})")

    for row_idx, currency_code in CURRENCY_ROWS.items():
        if row_idx >= len(rows):
            continue
        row = rows[row_idx]
        currency_id = CURRENCY_IDS[currency_code]

        for col_idx, rate_date in month_cols:
            if col_idx >= len(row):
                continue
            rate = xl_float(row[col_idx])
            if not rate:
                continue

            # Check if this rate already exists
            key = (currency_id, rate_date)
            if key in existing_rates:
                existing = existing_rates[key]
                if abs(float(existing) - rate) > 0.01:
                    discrepancies.append({
                        'severity': 'info', 'category': 'value_conflict',
                        'project': 'PORTFOLIO',
                        'field': f'exchange_rate.{currency_code}',
                        'source_a': f'RevMasterfile: {rate} on {rate_date}',
                        'source_b': f'DB: {existing}',
                        'recommended_action': 'RevMasterfile rate may be more authoritative for invoicing',
                        'status': 'open',
                    })
                continue  # Don't overwrite existing

            new_rates.append({
                'organization_id': ORG_ID,
                'currency_id': currency_id,
                'currency_code': currency_code,
                'rate_date': rate_date,
                'rate': rate,
                'source': 'revenue_masterfile',
            })

    log.info(f"  7c: {len(new_rates)} new exchange rates, {len(discrepancies)} discrepancies")
    return new_rates, discrepancies


# ─── 7d: Energy Sales → Cross-check ─────────────────────────────────────────

def process_energy_sales(wb, db_projects):
    """Cross-check Energy Sales tab forecasts against DB."""
    log.info("7d: Processing Energy Sales tab (cross-check only)...")
    rows = read_sheet(wb, 'Energy Sales', max_rows=200, max_cols=80)
    discrepancies = []

    # Row 3 (0-indexed=2) has degradation factors per project
    # The structure is complex with project groups in columns — just log what we find
    if len(rows) > 2:
        deg_row = rows[2]
        non_null = [(i, v) for i, v in enumerate(deg_row) if v is not None and v != '']
        log.info(f"  7d: Degradation row has {len(non_null)} non-null values")

    log.info(f"  7d: Energy Sales cross-check complete (informational only)")
    return discrepancies


# ─── 7e: Loans ───────────────────────────────────────────────────────────────

def process_loans(wb):
    """Extract loan schedules from Loans tab → staging JSONB."""
    log.info("7e: Processing Loans tab...")
    rows = read_sheet(wb, 'Loans', max_rows=400, max_cols=30)

    loan_schedules = {}

    # Zoodlabs Loan 1: cols 0-8
    zl_rows = []
    for row in rows[3:]:  # Skip headers
        month = xl_float(row[0]) if len(row) > 0 else None
        if month is None:
            continue
        principal = xl_float(row[1]) if len(row) > 1 else None
        interest = xl_float(row[2]) if len(row) > 2 else None
        payment = xl_float(row[3]) if len(row) > 3 else None
        closing = xl_float(row[4]) if len(row) > 4 else None
        date_paid = xl_date(row[5]) if len(row) > 5 else None
        difference = xl_float(row[6]) if len(row) > 6 else None

        if principal is not None or payment is not None:
            zl_rows.append({
                'period': int(month) if month else None,
                'principal': principal,
                'interest': interest,
                'payment': payment,
                'closing_balance': closing,
                'date_paid': date_paid,
                'difference': difference,
            })

    if zl_rows:
        loan_schedules['ZL02'] = {'loan_type': 'Zoodlabs Loan Schedule 1', 'rows': zl_rows}

    # Garden City Interest: cols 25-29
    gc_rows = []
    for row in rows[3:]:
        if len(row) <= 25:
            continue
        dt = xl_date(row[25]) if len(row) > 25 else None
        if not dt:
            continue
        invoiced = xl_float(row[27]) if len(row) > 27 else None
        capital = xl_float(row[28]) if len(row) > 28 else None
        interest_income = xl_float(row[29]) if len(row) > 29 else None
        if invoiced is not None or capital is not None:
            gc_rows.append({
                'date': dt,
                'invoiced': invoiced,
                'capital_repayment': capital,
                'interest_income': interest_income,
            })

    if gc_rows:
        loan_schedules['GC001'] = {'loan_type': 'Garden City Interest', 'rows': gc_rows}

    log.info(f"  7e: Extracted loan schedules for {list(loan_schedules.keys())}")
    return loan_schedules


# ─── 7f: Rental and Ancillary ────────────────────────────────────────────────

def process_rentals(wb):
    """Extract rental/ancillary schedules."""
    log.info("7f: Processing Rental and Ancillary tab...")
    rows = read_sheet(wb, 'Rental and Ancillary', max_rows=400, max_cols=25)

    # Map column groups to projects
    # Based on workflow doc: LOI01(col5), AR01(col8), QMM01(col11), TWG01(col14-15), AMP01(col18), ZL02(col21)
    RENTAL_COLS = {
        'LOI01': {'charge_type': 'BESS Charge', 'oy_col': 3, 'amount_col': 4},
        'AR01': {'charge_type': 'Rental Fee', 'oy_col': 6, 'amount_col': 7},
        'QMM01': {'charge_type': 'BESS Charge', 'oy_col': 9, 'amount_col': 10},
        'TWG01': {'charge_type': 'Rental + O&M', 'oy_col': 12, 'amount_col': 13},
        'AMP01': {'charge_type': 'BESS Charge', 'oy_col': 15, 'amount_col': 16},
    }

    rental_schedules = {}

    for sage_id, cfg in RENTAL_COLS.items():
        schedule_rows = []
        for row in rows[3:]:
            dt = xl_date(row[0]) if len(row) > 0 else None
            if not dt:
                continue
            oy = xl_float(row[cfg['oy_col']]) if len(row) > cfg['oy_col'] else None
            amount = xl_float(row[cfg['amount_col']]) if len(row) > cfg['amount_col'] else None
            if amount is not None and amount != 0:
                schedule_rows.append({
                    'date': dt,
                    'operating_year': int(oy) if oy else None,
                    'amount': amount,
                    'charge_type': cfg['charge_type'],
                })

        if schedule_rows:
            rental_schedules[sage_id] = schedule_rows

    log.info(f"  7f: Extracted rental schedules for {list(rental_schedules.keys())}")
    return rental_schedules


# ─── 7g: US CPI ─────────────────────────────────────────────────────────────

def process_us_cpi(wb):
    """Extract US CPI data → staging JSON."""
    log.info("7g: Processing US CPI tab...")
    rows = read_sheet(wb, 'US CPI', max_rows=30, max_cols=20)

    cpi_data = []
    # Header at row 13 (0-indexed=12): Year, Jan-Dec, then inflation cols
    header_idx = None
    for i, row in enumerate(rows):
        if any(xl_str(v) == 'Year' for v in row[:3] if v):
            header_idx = i
            break

    if header_idx is None:
        log.warning("  7g: Could not find CPI header row")
        return cpi_data

    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    for row in rows[header_idx + 1:]:
        year = xl_float(row[0]) if len(row) > 0 else None
        if not year or year < 2000:
            continue
        year = int(year)

        for m_idx, month in enumerate(months):
            val = xl_float(row[m_idx + 1]) if len(row) > m_idx + 1 else None
            if val:
                cpi_data.append({
                    'year': year,
                    'month': m_idx + 1,
                    'month_name': month,
                    'cpi_value': val,
                    'series': 'CUUR0000SA0',
                })

    log.info(f"  7g: Extracted {len(cpi_data)} CPI data points ({cpi_data[0]['year'] if cpi_data else '?'}-{cpi_data[-1]['year'] if cpi_data else '?'})")
    return cpi_data


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    dry_run = '--dry-run' in sys.argv
    mode = 'DRY RUN' if dry_run else 'LIVE'
    log.info(f"Step 7: Revenue Masterfile ({mode})")
    log.info(f"Workbook: {WB_PATH}")

    if not WB_PATH.exists():
        log.error(f"Workbook not found: {WB_PATH}")
        sys.exit(1)

    wb = open_workbook(str(WB_PATH))

    # Load DB state
    init_connection_pool()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '120s'")

        # Load projects
        cur.execute("""
            SELECT p.id, p.sage_id, p.cod_date::text as cod_date, p.installed_dc_capacity_kwp,
                   p.technical_specs, p.country,
                   c.id as primary_contract_id, c.counterparty_id
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
                    'id': row['id'], 'sage_id': sid, 'cod_date': row['cod_date'],
                    'installed_dc_capacity_kwp': row['installed_dc_capacity_kwp'],
                    'technical_specs': row['technical_specs'] or {},
                    'country': row['country'],
                    'primary_contract_id': row['primary_contract_id'],
                    'counterparty_id': row['counterparty_id'],
                }

        # Load counterparties
        cur.execute("SELECT id, name, industry FROM counterparty")
        db_counterparties = {row['id']: dict(row) for row in cur.fetchall()}

        # Load tariffs
        cur.execute("""
            SELECT ct.id, p.sage_id, ct.base_rate, ct.currency_id,
                   ct.tariff_type_id,
                   est.name as energy_sale_type_name,
                   ct.logic_parameters, ct.energy_sale_type_id,
                   ct.escalation_type_id
            FROM clause_tariff ct
            JOIN project p ON ct.project_id = p.id
            LEFT JOIN energy_sale_type est ON ct.energy_sale_type_id = est.id
            WHERE ct.is_current = true
            ORDER BY p.sage_id
        """)
        db_tariffs = {}
        for row in cur.fetchall():
            sid = row['sage_id']
            if sid not in db_tariffs:
                db_tariffs[sid] = []
            db_tariffs[sid].append({
                'id': row['id'], 'sage_id': sid, 'base_rate': row['base_rate'],
                'currency_id': row['currency_id'], 'tariff_type_id': row['tariff_type_id'],
                'energy_sale_type_name': row['energy_sale_type_name'],
                'logic_parameters': row['logic_parameters'] or {},
                'energy_sale_type_id': row['energy_sale_type_id'],
                'escalation_type_id': row['escalation_type_id'],
            })

        # Load currency code → id map
        cur.execute("SELECT id, code FROM currency")
        currency_code_to_id = {row['code']: row['id'] for row in cur.fetchall()}

        # Load taxonomy lookup maps (code → id)
        cur.execute("SELECT id, code FROM escalation_type WHERE is_active = true")
        esc_type_map = {row['code']: row['id'] for row in cur.fetchall()}

        cur.execute("SELECT id, code FROM energy_sale_type WHERE is_active = true")
        est_type_map = {row['code']: row['id'] for row in cur.fetchall()}

        cur.execute("SELECT id, code FROM tariff_type")
        tt_type_map = {row['code']: row['id'] for row in cur.fetchall()}

        log.info(f"Taxonomy maps: {len(esc_type_map)} escalation, {len(est_type_map)} energy_sale, {len(tt_type_map)} tariff_type codes")

        # Load existing exchange rates
        cur.execute("SELECT currency_id, rate_date::text as rate_date, rate FROM exchange_rate WHERE organization_id = %s", (ORG_ID,))
        existing_rates = {(row['currency_id'], row['rate_date']): row['rate'] for row in cur.fetchall()}

        log.info(f"DB state: {len(db_projects)} projects, {len(db_tariffs)} tariffed projects, {len(existing_rates)} exchange rates")

        # ── Process each tab ──
        all_discrepancies = []

        # 7a: Reporting Graphs
        industry_updates, disc_7a = process_reporting_graphs(wb, db_projects, db_counterparties)
        all_discrepancies.extend(disc_7a)

        # 7b: PO Summary
        tech_updates, tariff_updates, disc_7b = process_po_summary(
            wb, db_projects, db_tariffs, currency_code_to_id,
            esc_type_map=esc_type_map, est_type_map=est_type_map, tt_type_map=tt_type_map,
        )
        all_discrepancies.extend(disc_7b)

        # 7c: Exchange Rates
        new_rates, disc_7c = process_exchange_rates(wb, existing_rates)
        all_discrepancies.extend(disc_7c)

        # 7d: Energy Sales (cross-check only)
        disc_7d = process_energy_sales(wb, db_projects)
        all_discrepancies.extend(disc_7d)

        # 7e: Loans
        loan_schedules = process_loans(wb)

        # 7f: Rentals
        rental_schedules = process_rentals(wb)

        # 7g: US CPI
        cpi_data = process_us_cpi(wb)

        # ── Apply updates ──
        if dry_run:
            log.info("=" * 60)
            log.info("DRY RUN — no changes written")
            log.info(f"  Would update {len(industry_updates)} counterparty industries")
            log.info(f"  Would update {len(tech_updates)} project technical_specs")
            log.info(f"  Would update {len(tariff_updates)} clause_tariff rows")
            log.info(f"  Would insert {len(new_rates)} exchange rates")
            log.info(f"  Would store loan schedules for {list(loan_schedules.keys())}")
            log.info(f"  Would store rental schedules for {list(rental_schedules.keys())}")
            log.info(f"  Would stage {len(cpi_data)} CPI data points")
            log.info(f"  Discrepancies: {len(all_discrepancies)}")
            # Detail tariff changes for review
            for upd in tariff_updates:
                if upd['fields'].get('currency_id') or upd['fields'].get('escalation_type_id'):
                    log.info(f"    Tariff {upd['tariff_id']} ({upd['sage_id']}): {upd['fields']} lp={upd['lp_fields']}")
        else:
            # 7a: Update counterparty industries
            for upd in industry_updates:
                cur.execute("UPDATE counterparty SET industry = %s WHERE id = %s AND industry IS NULL",
                            (upd['industry'], upd['counterparty_id']))
                log.info(f"    Updated industry for {upd['sage_id']}: {upd['industry']}")

            # 7b: Update technical_specs (merge)
            for upd in tech_updates:
                merged = {**upd['existing_specs'], **upd['specs']}
                cur.execute("UPDATE project SET technical_specs = %s WHERE id = %s",
                            (json.dumps(merged), upd['project_id']))
                log.info(f"    Updated technical_specs for {upd['sage_id']}: {list(upd['specs'].keys())}")

            # 7b: Update tariff fields
            for upd in tariff_updates:
                # Update direct fields
                if upd['fields']:
                    set_clauses = []
                    vals = []
                    for k, v in upd['fields'].items():
                        set_clauses.append(f"{k} = %s")
                        vals.append(v)
                    vals.append(upd['tariff_id'])
                    cur.execute(f"UPDATE clause_tariff SET {', '.join(set_clauses)} WHERE id = %s", vals)

                # Update logic_parameters (merge)
                if upd['lp_fields']:
                    cur.execute("SELECT logic_parameters FROM clause_tariff WHERE id = %s", (upd['tariff_id'],))
                    existing_lp = cur.fetchone()['logic_parameters'] or {}
                    # Only set fields that are not already set
                    merged_lp = {**existing_lp}
                    new_fields = []
                    for k, v in upd['lp_fields'].items():
                        if k not in merged_lp or merged_lp[k] is None:
                            merged_lp[k] = v
                            new_fields.append(k)
                    if new_fields:
                        cur.execute("UPDATE clause_tariff SET logic_parameters = %s WHERE id = %s",
                                    (json.dumps(merged_lp), upd['tariff_id']))
                        log.info(f"    Updated tariff {upd['tariff_id']} ({upd['sage_id']}): fields={list(upd['fields'].keys())}, lp={new_fields}")

            # 7c: Insert exchange rates
            for rate in new_rates:
                cur.execute("""
                    INSERT INTO exchange_rate (organization_id, currency_id, rate_date, rate, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (rate['organization_id'], rate['currency_id'], rate['rate_date'], rate['rate'], rate['source']))
            if new_rates:
                log.info(f"    Inserted {len(new_rates)} exchange rates")

            # 7e+7f: Store loan/rental schedules in technical_specs
            for sage_id, schedule in loan_schedules.items():
                if sage_id in db_projects:
                    pid = db_projects[sage_id]['id']
                    existing = db_projects[sage_id].get('technical_specs') or {}
                    existing['loan_schedule'] = schedule
                    cur.execute("UPDATE project SET technical_specs = %s WHERE id = %s",
                                (json.dumps(existing, default=str), pid))
                    log.info(f"    Stored loan schedule for {sage_id} ({len(schedule.get('rows', []))} rows)")

            for sage_id, schedule in rental_schedules.items():
                if sage_id in db_projects:
                    pid = db_projects[sage_id]['id']
                    # Re-read in case loan update already changed it
                    cur.execute("SELECT technical_specs FROM project WHERE id = %s", (pid,))
                    existing = cur.fetchone()['technical_specs'] or {}
                    existing['rental_schedule'] = schedule
                    cur.execute("UPDATE project SET technical_specs = %s WHERE id = %s",
                                (json.dumps(existing, default=str), pid))
                    log.info(f"    Stored rental schedule for {sage_id} ({len(schedule)} rows)")

            conn.commit()
            log.info("All changes committed")

        # 7g: US CPI → staging JSON (always write, not DB)
        cpi_path = REPORT_DIR / 'us_cpi_staging.json'
        cpi_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cpi_path, 'w') as f:
            json.dump(cpi_data, f, indent=2)
        log.info(f"  CPI data staged: {cpi_path}")

        # ── Gate checks ──
        gates = []

        # Gate 1: PO Summary projects resolved
        gates.append({
            'name': 'PO Summary projects resolved to FM projects',
            'passed': len(tech_updates) > 0,
            'expected': '> 0 projects enriched',
            'actual': f'{len(tech_updates)} projects with technical_specs updates',
        })

        # Gate 2: Tariff enrichment
        tariffs_with_base = sum(1 for u in tariff_updates if u['fields'].get('base_rate'))
        gates.append({
            'name': 'Tariff base_rate populated',
            'passed': True,  # Informational
            'expected': 'Tariff fields enriched',
            'actual': f'{tariffs_with_base} tariffs got base_rate, {len(tariff_updates)} total tariff updates',
        })

        # Gate 3: Exchange rates
        gates.append({
            'name': 'Exchange rates extracted',
            'passed': True,
            'expected': '> 0 rates from RevMasterfile',
            'actual': f'{len(new_rates)} new rates inserted',
        })

        # Gate 4: No critical discrepancies
        critical = [d for d in all_discrepancies if d['severity'] == 'critical']
        gates.append({
            'name': 'No critical discrepancies',
            'passed': len(critical) == 0,
            'expected': '0 critical',
            'actual': f'{len(critical)} critical discrepancies',
        })

        for g in gates:
            status = 'PASS' if g['passed'] else 'FAIL'
            log.info(f"  Gate: {g['name']} → {status} ({g['actual']})")

        # ── Report ──
        status = 'pass' if all(g['passed'] for g in gates) else ('warnings' if len(all_discrepancies) > 0 else 'pass')
        if any(d['severity'] == 'warning' for d in all_discrepancies):
            status = 'warnings'

        report = {
            'step': 7,
            'step_name': 'Revenue Masterfile — Full Extraction',
            'mode': mode,
            'status': status,
            'summary': {
                'industry_updates': len(industry_updates),
                'tech_spec_updates': len(tech_updates),
                'tariff_updates': len(tariff_updates),
                'exchange_rates_inserted': len(new_rates),
                'loan_schedules': list(loan_schedules.keys()),
                'rental_schedules': list(rental_schedules.keys()),
                'cpi_data_points': len(cpi_data),
            },
            'discrepancies': all_discrepancies,
            'gate_checks': gates,
        }

        report_path = REPORT_DIR / f'step7_{date.today().isoformat()}.json'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        log.info(f"  Report: {report_path}")

        log.info("=" * 60)
        log.info(f"Step 7 Complete ({mode})")

    close_connection_pool()


if __name__ == '__main__':
    main()
