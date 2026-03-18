'use client'

import { useState, useMemo, Fragment } from 'react'
import { ChevronRight, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { IS_DEMO } from '@/lib/demoMode'
import type { ProjectDashboardResponse, MRPObservation, SubmissionTokenItem, TariffFormula, TariffFormulaVariable } from '@/lib/api/adminClient'
import { adminClient } from '@/lib/api/adminClient'
import { CollapsibleSection } from './CollapsibleSection'
import { EditableCell } from './EditableCell'
import { FieldGrid, type FieldDef } from './shared/FieldGrid'
import { DetailField } from './shared/DetailField'
import { EmptyState } from './shared/EmptyState'
import { str, hasAnyValue, formatEscalationRules, groupProductsWithTariffs } from './shared/helpers'
import { MRPSection } from './MRPSection'
import { formatMonth } from '@/app/projects/utils/formatters'
import { toOpts } from '@/app/projects/utils/constants'

type R = Record<string, unknown>

/** Format a billing_month date; delegates to shared formatMonth with '' default. */
function formatBillingMonth(v: unknown): string {
  if (v == null) return ''
  return formatMonth(String(v)).replace('—', '')
}

/** Format a per-kWh rate to consistent 4 decimal places. */
function fmtRate(v: unknown): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  return n.toFixed(4)
}

// ---------------------------------------------------------------------------
// MRP-family escalation codes (REBASED_MARKET_PRICE + FLOATING sub-types)
const REBASED_CODES = new Set(['REBASED_MARKET_PRICE', 'FLOATING_GRID', 'FLOATING_GENERATOR', 'FLOATING_GRID_GENERATOR'])

// Static option sets for fields not backed by DB lookup tables
// ---------------------------------------------------------------------------

const ESCALATION_FREQUENCY_OPTS = [
  { value: 'Annually', label: 'Annually' },
  { value: 'Quarterly', label: 'Quarterly' },
  { value: 'Monthly', label: 'Monthly' },
  { value: 'After Year X', label: 'After Year X' },
]

const BILLING_FREQUENCY_OPTS = [
  { value: 'Monthly', label: 'Monthly' },
  { value: 'Quarterly', label: 'Quarterly' },
  { value: 'Semi-Annually', label: 'Semi-Annually' },
  { value: 'Annually', label: 'Annually' },
]

// Legacy codes (ENERGY, CAPACITY from migration 022) no longer exist after 059 — keep as safety filter
const HIDDEN_TARIFF_CODES = new Set(['ENERGY', 'CAPACITY'])

/** Country → local currency fallback map (last-resort when tariff_rates has no currency). */
const COUNTRY_TO_CURRENCY: Record<string, string> = {
  'Ghana': 'GHS', 'Kenya': 'KES', 'Nigeria': 'NGN', 'Sierra Leone': 'SLE',
  'Egypt': 'EGP', 'Madagascar': 'MGA', 'Rwanda': 'RWF', 'Somalia': 'SOS',
  'Mozambique': 'MZN', 'Zimbabwe': 'ZWL', 'DRC': 'CDF',
}

const TARIFF_COMPONENTS_TO_ADJUST_OPTS = [
  { value: 'Solar Tariff', label: 'Solar Tariff' },
  { value: 'Floor Tariff', label: 'Floor Tariff' },
  { value: 'Ceiling Tariff', label: 'Ceiling Tariff' },
  { value: 'Solar Tariff + Floor Tariff', label: 'Solar Tariff + Floor Tariff' },
  { value: 'Solar Tariff + Ceiling Tariff', label: 'Solar Tariff + Ceiling Tariff' },
  { value: 'Solar Tariff + Floor Tariff + Ceiling Tariff', label: 'Solar Tariff + Floor Tariff + Ceiling Tariff' },
]

/** Normalize legacy "Tarrif" misspellings and snake_case to match dropdown options. */
function normalizeTariffComponent(v: unknown): string | undefined {
  if (v == null) return undefined
  let s = String(v)
  // snake_case → Title Case (e.g. "floor_tariff" → "Floor Tariff")
  if (s.includes('_')) s = s.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ')
  // Fix misspelling "Tarrif" → "Tariff"
  s = s.replace(/Tarrif/gi, 'Tariff')
  // Capitalize first letter of each word for consistency
  s = s.replace(/\b[a-z]/g, c => c.toUpperCase())
  return s
}

/** Normalize legacy frequency values (lowercase/variant) to match dropdown options. */
const FREQUENCY_ALIASES: Record<string, string> = {
  'annual': 'Annually', 'annually': 'Annually',
  'quarterly': 'Quarterly', 'quarter': 'Quarterly',
  'monthly': 'Monthly', 'month': 'Monthly',
  'semi-annually': 'Semi-Annually', 'semi-annual': 'Semi-Annually',
  'semiannually': 'Semi-Annually', 'biannually': 'Semi-Annually',
}
function normalizeFrequency(v: unknown): string | undefined {
  if (v == null) return undefined
  const s = String(v).trim()
  return FREQUENCY_ALIASES[s.toLowerCase()] ?? s
}

// Component tariff suffixes / patterns to exclude from display (keep only MAIN tariffs)
const COMPONENT_SUFFIXES = ['-GRID_BASE', '-DISCOUNTED', '-FLOOR', '-CEILING']
const COMPONENT_INFIX_RE = /_(Discounted|Floor|Ceiling|Current_Grid)_/

const PAYMENT_TERMS_OPTS = [
  { value: '30EOM', label: '30EOM' },
  { value: '30NET', label: '30NET' },
  { value: '45EOM', label: '45EOM' },
  { value: '45NET', label: '45NET' },
  { value: '60EOM', label: '60EOM' },
  { value: '60NET', label: '60NET' },
  { value: '75EOM', label: '75EOM' },
  { value: '75NET', label: '75NET' },
  { value: '90EOM', label: '90EOM' },
  { value: '90NET', label: '90NET' },
]

// ---------------------------------------------------------------------------
// TariffDetailPanel — renders a single tariff's full detail block
// ---------------------------------------------------------------------------

function TariffDetailPanel({ t, pid, rate_periods, monthly_rates, onSaved, editMode, currencyOpts, hardCurrencyCode }: {
  t: R; pid: number; rate_periods: R[]; monthly_rates: R[]
  onSaved?: () => void; editMode?: boolean
  currencyOpts: { value: number | string; label: string }[]
  hardCurrencyCode?: string
}) {
  const lp = (t.logic_parameters ?? {}) as R
  const currentPeriod = rate_periods.find((rp) => rp.clause_tariff_id === t.id && rp.is_current)
  const currentMonthlyRate = (monthly_rates ?? []).find(
    (mr: R) => mr.clause_tariff_id === t.id && mr.is_current,
  )
  const localCurrency = currentMonthlyRate?.currency_code ? ` (${currentMonthlyRate.currency_code})` : ''
  const baseCurrency = t.currency_code ? ` (${t.currency_code})` : ''
  const hardCcy = hardCurrencyCode ? ` (${hardCurrencyCode})` : baseCurrency
  const isRebased = REBASED_CODES.has(String(t.escalation_type_code ?? ''))
  const monthSuffix = currentMonthlyRate?.billing_month ? ` — ${formatBillingMonth(currentMonthlyRate.billing_month)}` : ''
  const fxRate = currentMonthlyRate?.exchange_rate != null ? Number(currentMonthlyRate.exchange_rate) : null
  const effectiveLocal = currentMonthlyRate?.effective_tariff_local != null ? Number(currentMonthlyRate.effective_tariff_local) : null
  const effectiveUsd = effectiveLocal != null && fxRate ? effectiveLocal / fxRate : null

  return (
    <div className="mt-2">
      <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
        ...(currentMonthlyRate ? [[`Effective Rate${localCurrency}${monthSuffix}`, currentMonthlyRate.effective_tariff_local] as FieldDef] : []),
        ...(isRebased && fxRate != null ? [
          [`Exchange Rate${localCurrency}/${baseCurrency || ' (USD)'}${monthSuffix}`, fxRate] as FieldDef,
          [`Effective Rate${baseCurrency || ' (USD)'}${monthSuffix}`, effectiveUsd != null ? Number(effectiveUsd.toFixed(4)) : null] as FieldDef,
        ] : [
          [`Base Rate${baseCurrency}`, t.base_rate, { fieldKey: 'base_rate', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const }] as FieldDef,
        ]),
        ...(currentPeriod ? [['Contract Year', currentPeriod.contract_year, { fieldKey: 'contract_year', entity: 'rate-periods' as const, entityId: currentPeriod.id as number, type: 'number' as const }] as FieldDef] : []),
        ['Market Ref Currency', t.market_ref_currency_code, { fieldKey: 'market_ref_currency_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: currencyOpts, selectValue: t.market_ref_currency_id }],
        ['Solar Discount (%)', lp.discount_pct != null ? Number((Number(lp.discount_pct) * 100).toFixed(4)) : null, { fieldKey: 'lp_discount_pct', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const, scaleOnSave: 0.01 }],
        [`Floor Rate${hardCcy}`, lp.floor_rate, { fieldKey: 'lp_floor_rate', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const }],
        [`Ceiling Rate${hardCcy}`, lp.ceiling_rate, { fieldKey: 'lp_ceiling_rate', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const }],
        ['Annual Degradation (%)', lp.degradation_pct != null ? Number((Number(lp.degradation_pct) * 100).toFixed(4)) : null, { fieldKey: 'lp_degradation_pct', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const, scaleOnSave: 0.01 }],
      ]} />

      {/* Rate Calculation Basis */}
      {currentPeriod?.calculation_basis != null && (
        <div className="mt-2 py-1">
          <dt className="text-xs text-slate-400">Rate Calculation</dt>
          <dd className="text-sm text-slate-900 mt-0.5">
            {editMode && currentPeriod.id != null ? (
              <EditableCell
                value={currentPeriod.calculation_basis}
                fieldKey="calculation_basis"
                entity="rate-periods"
                entityId={currentPeriod.id as number}
                type="text"
                editMode={true}
                onSaved={onSaved}
              />
            ) : (
              <span className="whitespace-pre-line">{String(currentPeriod.calculation_basis)}</span>
            )}
          </dd>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Non-energy tariff helpers & panel
// ---------------------------------------------------------------------------

// Post-059: revenue/product type codes live in energy_sale_type (not tariff_type)
const NON_ENERGY_REVENUE_CODES = new Set(['EQUIPMENT_RENTAL_LEASE', 'BESS_LEASE', 'LOAN', 'OTHER_SERVICE'])

function isNonEnergyTariff(t: R): boolean {
  return NON_ENERGY_REVENUE_CODES.has(String(t.energy_sale_type_code ?? '').toUpperCase())
}

function NonEnergyTariffPanel({ t, pid, rate_periods, monthly_rates, onSaved, editMode, energySaleTypeOpts, escalationTypeOpts }: {
  t: R; pid: number; rate_periods: R[]; monthly_rates: R[]
  onSaved?: () => void; editMode?: boolean
  energySaleTypeOpts: { value: number | string; label: string }[]
  escalationTypeOpts: { value: number | string; label: string }[]
}) {
  const lp = (t.logic_parameters ?? {}) as R
  const currentMonthlyRate = (monthly_rates ?? []).find(
    (mr: R) => mr.clause_tariff_id === t.id && mr.is_current,
  )
  const localCurrency = currentMonthlyRate?.currency_code ? ` (${currentMonthlyRate.currency_code})` : ''
  const baseCurrency = t.currency_code ? ` (${t.currency_code})` : ''
  const currentPeriod = rate_periods.find((rp) => rp.clause_tariff_id === t.id && rp.is_current)

  return (
    <div className="mt-2">
      <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
        [`Rate per Unit${baseCurrency}`, t.base_rate, { fieldKey: 'base_rate', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const }],
        ...(t.unit != null ? [['Unit', t.unit, { fieldKey: 'unit', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'text' as const }] as FieldDef] : []),

        ['Revenue Type', t.energy_sale_type_name ?? t.energy_sale_type_code, { fieldKey: 'energy_sale_type_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: energySaleTypeOpts, selectValue: t.energy_sale_type_id }],
        ...(t.currency_code != null ? [['Currency', t.currency_code] as FieldDef] : []),
        ['Escalation Type', t.escalation_type_code, { fieldKey: 'escalation_type_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: escalationTypeOpts, selectValue: t.escalation_type_id }],
        ...(lp.escalation_value != null ? [['Escalation Value', lp.escalation_value, { fieldKey: 'lp_escalation_value', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'number' as const }] as FieldDef] : []),
        ...(t.valid_from != null ? [['Valid From', t.valid_from] as FieldDef] : []),
        ...(t.valid_to != null ? [['Valid To', t.valid_to] as FieldDef] : []),
        ...(currentMonthlyRate ? [[`Effective Rate${localCurrency}${currentMonthlyRate.billing_month ? ` — ${formatBillingMonth(currentMonthlyRate.billing_month)}` : ''}`, currentMonthlyRate.effective_tariff_local] as FieldDef] : []),
      ]} />

      {/* Escalation Rules */}
      {lp.escalation_rules != null && (
        <div className="mt-3 pt-3 border-t border-slate-50">
          <div className="text-xs font-medium text-slate-400 uppercase mb-2">Escalation Rules</div>
          <DetailField label="Escalation Rules" value={formatEscalationRules(lp.escalation_rules)} />
        </div>
      )}

      {/* Rate Calculation Basis */}
      {currentPeriod?.calculation_basis != null && (
        <div className="mt-2 py-1">
          <dt className="text-xs text-slate-400">Rate Calculation</dt>
          <dd className="text-sm text-slate-900 mt-0.5">
            {editMode && currentPeriod.id != null ? (
              <EditableCell
                value={currentPeriod.calculation_basis}
                fieldKey="calculation_basis"
                entity="rate-periods"
                entityId={currentPeriod.id as number}
                type="text"
                editMode={true}
                onSaved={onSaved}
              />
            ) : (
              <span className="whitespace-pre-line">{String(currentPeriod.calculation_basis)}</span>
            )}
          </dd>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// EscalationRulesTable — structured table for escalation_rules array
// ---------------------------------------------------------------------------

function EscalationRulesTable({ rules, logicParameters }: { rules: unknown; logicParameters?: R }) {
  if (!Array.isArray(rules) || rules.length === 0) return null
  const rows = rules as Record<string, unknown>[]

  // Map component names to their base rate values from logic_parameters
  const componentBaseRate = (component: unknown): number | null => {
    if (!logicParameters) return null
    const c = String(component ?? '').toLowerCase()
    if (c === 'min_solar_price') return logicParameters.floor_rate != null ? Number(logicParameters.floor_rate) : null
    if (c === 'max_solar_price') return logicParameters.ceiling_rate != null ? Number(logicParameters.ceiling_rate) : null
    return null
  }

  const typeBadge = (type: unknown) => {
    const t = String(type ?? '').toUpperCase()
    const colors = t === 'FIXED' ? 'bg-blue-50 text-blue-700 border-blue-200'
      : t === 'CPI' ? 'bg-amber-50 text-amber-700 border-amber-200'
      : 'bg-slate-100 text-slate-500 border-slate-200'
    return (
      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${colors}`}>
        {t || 'NONE'}
      </span>
    )
  }

  const hasBaseRates = rows.some((r) => componentBaseRate(r.component) != null)

  return (
    <div className="overflow-x-auto mt-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Component</th>
            {hasBaseRates && <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Base Rate</th>}
            <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Escalation Type</th>
            <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Escalation</th>
            <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">From Year</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, j) => {
            const base = componentBaseRate(r.component)
            const escVal = r.escalation_value ?? r.value
            return (
              <tr key={j} className="border-b border-slate-50 hover:bg-slate-50">
                <td className="px-3 py-1.5 text-slate-700 font-medium">{str(r.component)}</td>
                {hasBaseRates && <td className="px-3 py-1.5 text-right text-slate-700 tabular-nums font-medium">{base != null ? `$${base.toFixed(4)}` : '—'}</td>}
                <td className="px-3 py-1.5 text-right">{typeBadge(r.escalation_type ?? r.type)}</td>
                <td className="px-3 py-1.5 text-right text-slate-700 tabular-nums">{escVal != null ? `${(Number(escVal) * 100).toFixed(1)}%` : '—'}</td>
                <td className="px-3 py-1.5 text-right text-slate-600 tabular-nums">{r.start_year != null ? str(r.start_year) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// RateBoundsSchedule — computed year-by-year floor/ceiling rate schedule
// ---------------------------------------------------------------------------

function RateBoundsSchedule({ logicParameters, contractTermYears, codDate }: {
  logicParameters: R; contractTermYears: number; codDate: string | null
}) {
  const rules = logicParameters.escalation_rules
  if (!Array.isArray(rules) || rules.length === 0) return null

  const floorRate = logicParameters.floor_rate != null ? Number(logicParameters.floor_rate) : null
  const ceilingRate = logicParameters.ceiling_rate != null ? Number(logicParameters.ceiling_rate) : null
  if (floorRate == null && ceilingRate == null) return null

  // Find escalation rules per component
  const minRule = rules.find((r: R) => String(r.component ?? '').toLowerCase() === 'min_solar_price') as R | undefined
  const maxRule = rules.find((r: R) => String(r.component ?? '').toLowerCase() === 'max_solar_price') as R | undefined

  const minEscValue = minRule ? Number(minRule.escalation_value ?? minRule.value ?? 0) : 0
  const minStartYear = minRule ? Number(minRule.start_year ?? 2) : 2
  const maxEscValue = maxRule ? Number(maxRule.escalation_value ?? maxRule.value ?? 0) : 0
  const maxStartYear = maxRule ? Number(maxRule.start_year ?? 2) : 2

  // Compute period end dates from COD
  const cod = codDate ? new Date(codDate) : null

  const years = contractTermYears || 18
  const rows: { year: number; min: number | null; max: number | null; periodEnd: string | null; escalation: string }[] = []

  for (let y = 1; y <= years; y++) {
    const minExponent = y >= minStartYear ? y - minStartYear + 1 : 0
    const maxExponent = y >= maxStartYear ? y - maxStartYear + 1 : 0
    const min = floorRate != null ? floorRate * Math.pow(1 + minEscValue, minExponent) : null
    const max = ceilingRate != null ? ceilingRate * Math.pow(1 + maxEscValue, maxExponent) : null

    let periodEnd: string | null = null
    if (cod) {
      const end = new Date(cod)
      end.setUTCFullYear(end.getUTCFullYear() + y)
      end.setUTCDate(end.getUTCDate() - 1)
      periodEnd = end.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
    }

    const esc = y < minStartYear ? '—' : y === 1 ? '0.00%' : `${(minEscValue * 100).toFixed(2)}%`

    rows.push({ year: y, min, max, periodEnd, escalation: esc })
  }

  return (
    <div className="mt-4">
      <CollapsibleSection title={`Floor & Ceiling Rate Schedule (${years} years)`} defaultOpen={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-center px-4 py-2.5 font-medium">OY</th>
                {floorRate != null && <th className="text-right px-4 py-2.5 font-medium">Min (Floor)</th>}
                {ceilingRate != null && <th className="text-right px-4 py-2.5 font-medium">Max (Ceiling)</th>}
                {cod && <th className="text-right px-4 py-2.5 font-medium">Period End</th>}
                <th className="text-right px-4 py-2.5 font-medium">Escalation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.year} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5 text-center font-mono tabular-nums">{r.year}</td>
                  {floorRate != null && <td className="px-4 py-2.5 text-right font-mono tabular-nums">${r.min!.toFixed(4)}</td>}
                  {ceilingRate != null && <td className="px-4 py-2.5 text-right font-mono tabular-nums">${r.max!.toFixed(4)}</td>}
                  {cod && <td className="px-4 py-2.5 text-right font-mono tabular-nums">{r.periodEnd}</td>}
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums">{r.escalation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CPIEscalationSchedule — year-by-year CPI escalation from tariff_rate calc_detail
// ---------------------------------------------------------------------------

function CPIEscalationSchedule({ tariffRates, clauseTariffId, logicParameters, codDate }: {
  tariffRates: R[]; clauseTariffId: unknown; logicParameters: R; codDate: string | null
}) {
  const cpiRates = tariffRates.filter((tr) =>
    tr.clause_tariff_id === clauseTariffId &&
    tr.rate_granularity === 'annual' &&
    tr.formula_version === 'us_cpi_v1'
  ).sort((a, b) => Number(a.contract_year) - Number(b.contract_year))

  if (cpiRates.length === 0) return null

  const subtype = String(logicParameters.cpi_escalation_subtype ?? 'base_rate')
  const isFloorCeiling = subtype === 'floor_ceiling'

  return (
    <div className="mt-4">
      <CollapsibleSection title={`CPI Escalation Schedule (${cpiRates.length} years)`} defaultOpen={false}>
        <div className="mb-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
            {logicParameters.cpi_base_date != null && (
              <span>CPI Base: <span className="font-medium text-slate-700">{String(logicParameters.cpi_base_date).slice(0, 7)}</span></span>
            )}
            {logicParameters.cpi_base_value != null && (
              <span>Base Value: <span className="font-medium text-slate-700">{Number(logicParameters.cpi_base_value).toFixed(3)}</span></span>
            )}
            <span>Index: <span className="font-medium text-slate-700">CUUR0000SA0</span></span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-center px-4 py-2.5 font-medium">OY</th>
                <th className="text-right px-4 py-2.5 font-medium">Period</th>
                <th className="text-right px-4 py-2.5 font-medium">CPI Value</th>
                <th className="text-right px-4 py-2.5 font-medium">CPI Factor</th>
                {isFloorCeiling ? (<>
                  <th className="text-right px-4 py-2.5 font-medium">Floor (USD)</th>
                  <th className="text-right px-4 py-2.5 font-medium">Ceiling (USD)</th>
                </>) : (
                  <th className="text-right px-4 py-2.5 font-medium">Effective Rate</th>
                )}
                <th className="text-center px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {cpiRates.map((tr) => {
                const cd = (tr.calc_detail ?? {}) as R
                const cpiFactor = cd.cpi_factor != null ? Number(cd.cpi_factor) : null
                const currentCpi = cd.current_cpi_value != null ? Number(cd.current_cpi_value) : null
                const status = String(tr.calc_status ?? 'computed')
                const periodStr = tr.period_start
                  ? `${String(tr.period_start).slice(0, 10)}${tr.period_end ? ` — ${String(tr.period_end).slice(0, 10)}` : ''}`
                  : '—'

                return (
                  <tr key={tr.contract_year as number} className={`hover:bg-slate-50 ${tr.is_current ? 'bg-blue-50/40' : ''}`}>
                    <td className="px-4 py-2.5 text-center font-mono tabular-nums">{String(tr.contract_year)}</td>
                    <td className="px-4 py-2.5 text-right text-xs text-slate-500 tabular-nums">{periodStr}</td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums">{currentCpi != null ? currentCpi.toFixed(3) : '—'}</td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums">{cpiFactor != null ? cpiFactor.toFixed(4) : '—'}</td>
                    {isFloorCeiling ? (<>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums font-medium">
                        {cd.escalated_floor_usd != null ? `$${Number(cd.escalated_floor_usd).toFixed(4)}` : fmtRate(tr.effective_rate_contract_ccy)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums font-medium">
                        {cd.escalated_ceiling_usd != null ? `$${Number(cd.escalated_ceiling_usd).toFixed(4)}` : '—'}
                      </td>
                    </>) : (
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums font-medium">{fmtRate(tr.effective_rate_contract_ccy)}</td>
                    )}
                    <td className="px-4 py-2.5 text-center">
                      {status === 'pending' ? (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">Pending CPI</span>
                      ) : tr.is_current ? (
                        <span className="inline-block w-2 h-2 rounded-full bg-blue-500" title="Current" />
                      ) : (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-200">Computed</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ExcusedEventsList — bulleted list for excused_events
// ---------------------------------------------------------------------------

function ExcusedEventsList({ events }: { events: unknown }) {
  const items: string[] = Array.isArray(events)
    ? events.map(String)
    : typeof events === 'string'
      ? events.split('\n').filter(Boolean)
      : []
  if (items.length === 0) return null

  return (
    <div className="mt-2">
      <ul className="list-disc list-inside text-sm text-slate-700 space-y-0.5">
        {items.map((item, j) => <li key={j}>{item}</li>)}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AddProductRow — inline selector to add a billing product to a contract
// ---------------------------------------------------------------------------

function AddProductRow({ contractId, existingProductIds, billingProductOpts, onAdded }: {
  contractId: number
  existingProductIds: Set<number>
  billingProductOpts: { value: number | string; label: string }[]
  onAdded?: () => void
}) {
  const [adding, setAdding] = useState(false)
  const availableOpts = billingProductOpts.filter((o) => !existingProductIds.has(Number(o.value)))

  if (availableOpts.length === 0) return null

  return (
    <div className="border border-dashed border-slate-300 rounded-lg">
      {adding ? (
        <div className="px-4 py-3">
          <label className="text-xs text-slate-400 mb-1 block">Select a product to add</label>
          <select
            autoFocus
            className="w-full rounded border border-blue-300 bg-white px-2 py-1.5 text-sm text-slate-900 outline-none ring-1 ring-blue-200 focus:ring-blue-400"
            defaultValue=""
            onChange={async (e) => {
              const productId = Number(e.target.value)
              if (!productId) return
              try {
                await adminClient.addBillingProduct({ contract_id: contractId, billing_product_id: productId })
                const label = billingProductOpts.find((o) => Number(o.value) === productId)?.label ?? 'Product'
                toast.success(`Added ${label}`)
                setAdding(false)
                onAdded?.()
              } catch (err) {
                toast.error(err instanceof Error ? err.message : 'Failed to add product')
              }
            }}
            onBlur={() => setAdding(false)}
          >
            <option value="">— select product —</option>
            {availableOpts.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors rounded-lg"
        >
          <Plus className="h-4 w-4" />
          Add Product
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// BillingProductCard — expandable card for a product + its tariffs
// ---------------------------------------------------------------------------

/** Formula types relevant to each product category — show only directly relevant formulas. */
const ENERGY_PRODUCT_FORMULA_TYPES = new Set(['MRP_CALCULATION', 'MRP_BOUNDED', 'ENERGY_OUTPUT'])
const AVAILABLE_ENERGY_FORMULA_TYPES = new Set(['DEEMED_ENERGY'])
const MINIMUM_OFFTAKE_FORMULA_TYPES = new Set(['TAKE_OR_PAY'])

function BillingProductCard({ pw, pid, rate_periods, monthly_rates, contractLines, tariffFormulas, onSaved, editMode, isOpen, onToggle, onRemove, billingProductOpts, tariffTypeOpts, energySaleTypeOpts, escalationTypeOpts, currencyOpts, hardCurrencyCode }: {
  pw: { product: R; tariffs: R[] }; pid: number; rate_periods: R[]; monthly_rates: R[]
  contractLines: R[]
  tariffFormulas: TariffFormula[]
  onSaved?: () => void; editMode?: boolean; isOpen: boolean; onToggle: () => void; onRemove?: () => void
  billingProductOpts: { value: number | string; label: string }[]
  tariffTypeOpts: { value: number | string; label: string }[]
  energySaleTypeOpts: { value: number | string; label: string }[]
  escalationTypeOpts: { value: number | string; label: string }[]
  currencyOpts: { value: number | string; label: string }[]
  hardCurrencyCode?: string
}) {
  const bp = pw.product
  const allNonEnergy = pw.tariffs.length > 0 && pw.tariffs.every(isNonEnergyTariff)
  const isAvailableEnergy = /available/i.test(String(bp.product_name ?? ''))

  // Contract lines and meters associated with this billing product
  const { productMeters, productLineNumbers, phaseCodDates } = useMemo(() => {
    const bpId = bp.billing_product_id
    if (bpId == null) return { productMeters: [], productLineNumbers: [] as number[], phaseCodDates: [] as { lineNumber: number; desc: string; codDate: string }[] }
    const meterMap = new Map<number, { meter_id: number; meter_name: string; energy_category: string; lineNumbers: number[] }>()
    const headerLines: number[] = []
    const parentLineIds = new Set<number>()
    const codDates: { lineNumber: number; desc: string; codDate: string }[] = []
    for (const cl of contractLines) {
      if (cl.billing_product_id === bpId) {
        if (cl.phase_cod_date != null) {
          codDates.push({ lineNumber: cl.contract_line_number as number, desc: String(cl.product_desc ?? ''), codDate: String(cl.phase_cod_date) })
        }
        if (cl.meter_id != null) {
          const mid = cl.meter_id as number
          let entry = meterMap.get(mid)
          if (!entry) {
            entry = { meter_id: mid, meter_name: String(cl.meter_name ?? `Meter ${mid}`), energy_category: String(cl.energy_category ?? ''), lineNumbers: [] }
            meterMap.set(mid, entry)
          }
          if (cl.contract_line_number != null && !entry.lineNumbers.includes(cl.contract_line_number as number)) {
            entry.lineNumbers.push(cl.contract_line_number as number)
          }
          if (cl.parent_contract_line_id != null) parentLineIds.add(cl.parent_contract_line_id as number)
        } else {
          // Product-level header line (no meter)
          if (cl.contract_line_number != null) headerLines.push(cl.contract_line_number as number)
        }
      }
    }
    // Parent lines (no billing_product_id) that are parents of this product's meter lines
    if (parentLineIds.size > 0) {
      for (const cl of contractLines) {
        if (parentLineIds.has(cl.id as number) && cl.billing_product_id == null && cl.meter_id == null) {
          if (cl.contract_line_number != null && !headerLines.includes(cl.contract_line_number as number)) {
            headerLines.push(cl.contract_line_number as number)
          }
        }
      }
    }
    const meters = [...meterMap.values()]
    for (const m of meters) m.lineNumbers.sort((a, b) => a - b)
    headerLines.sort((a, b) => a - b)
    // Deduplicate phase COD dates by date value
    const uniqueCods = codDates.filter((v, i, a) => a.findIndex(x => x.codDate === v.codDate) === i)
    return { productMeters: meters, productLineNumbers: headerLines, phaseCodDates: uniqueCods }
  }, [contractLines, bp.billing_product_id])

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      {/* Collapsed header — always visible */}
      <div className="flex items-center">
        <div
          role="button"
          tabIndex={0}
          onClick={onToggle}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}
          className="flex-1 flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors cursor-pointer"
        >
          <ChevronRight className={`h-4 w-4 text-slate-400 shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono ${
            bp.is_primary ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'bg-slate-100 text-slate-600 border border-slate-200'
          }`}>
            {str(bp.product_code)}
          </span>
          <span className="text-sm font-medium text-slate-800 truncate">{str(bp.product_name)}</span>
          {productLineNumbers.length > 0 && (
            <span className="text-xs text-slate-400 font-mono">({productLineNumbers.join(', ')})</span>
          )}
          {bp.is_primary === true && (
            <span className="text-blue-500 text-[10px] uppercase font-semibold">Primary</span>
          )}
          {allNonEnergy && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">Non-Energy</span>
          )}
          <span className="ml-auto text-xs text-slate-400">{pw.tariffs.length} tariff{pw.tariffs.length !== 1 ? 's' : ''}</span>
        </div>
        {editMode && onRemove && !IS_DEMO && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRemove() }}
            className="px-3 py-3 text-slate-400 hover:text-red-600 transition-colors"
            title="Remove product"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Meter composition — always visible when meters are linked */}
      {productMeters.length > 0 && (
        <div className="px-4 py-2 border-t border-slate-100 bg-slate-50/50">
          <span className="text-xs text-slate-400 mr-2">Meters:</span>
          {productMeters.map((m, i) => (
            <span key={m.meter_id} className="text-xs text-slate-600">
              {i > 0 && <span className="text-slate-300 mx-1">&middot;</span>}
              {m.meter_name}
              {m.lineNumbers.length > 0 && (
                <span className="text-slate-400 font-mono ml-1">({m.lineNumbers.join(', ')})</span>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Phase COD dates — visible when contract lines have phase-specific CODs */}
      {phaseCodDates.length > 0 && (
        <div className="px-4 py-2 border-t border-slate-100 bg-slate-50/50">
          <span className="text-xs text-slate-400 mr-2">Phase COD:</span>
          {phaseCodDates.map((p, i) => (
            <span key={p.codDate} className="text-xs text-slate-600">
              {i > 0 && <span className="text-slate-300 mx-1">&middot;</span>}
              {p.desc ? `${p.desc}: ` : ''}{p.codDate}
            </span>
          ))}
        </div>
      )}

      {/* Expanded body */}
      {isOpen && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-100">
          {/* Product fields (editable in edit mode) */}
          {editMode ? (
            <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
              ['Product', bp.product_code, { fieldKey: 'billing_product_id', entity: 'billing-products' as const, entityId: bp.id as number, type: 'select' as const, options: billingProductOpts, selectValue: bp.billing_product_id }],
              ['Primary', bp.is_primary, { fieldKey: 'is_primary', entity: 'billing-products' as const, entityId: bp.id as number, type: 'boolean' as const }],
              ['Notes', bp.notes, { fieldKey: 'notes', entity: 'billing-products' as const, entityId: bp.id as number, type: 'text' as const }],
            ]} />
          ) : (
            bp.notes != null && (
              <div className="text-xs text-slate-500 mb-2">{str(bp.notes)}</div>
            )
          )}

          {/* Nested tariff detail panels — dispatch by type (hidden for Available Energy) */}
          {!isAvailableEnergy && (
            pw.tariffs.length === 0 ? (
              <div className="text-xs text-slate-400 italic mt-2">No matching tariffs</div>
            ) : (
              pw.tariffs.map((t, j) => (
                <div key={j} className={j > 0 ? 'mt-3 pt-3 border-t border-slate-100' : 'mt-2'}>
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-400 uppercase mb-1">
                    {str(t.energy_sale_type_name ?? t.energy_sale_type_code ?? 'Tariff')}
                    {t.contract_amendment_id != null && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200 normal-case">
                        v{t.version != null ? String(t.version) : '2'} &mdash; Amended
                      </span>
                    )}
                  </div>
                  {isNonEnergyTariff(t) ? (
                    <NonEnergyTariffPanel
                      t={t} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                      onSaved={onSaved} editMode={editMode}
                      energySaleTypeOpts={energySaleTypeOpts} escalationTypeOpts={escalationTypeOpts}
                    />
                  ) : (
                    <TariffDetailPanel
                      t={t} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                      onSaved={onSaved} editMode={editMode}
                      currencyOpts={currencyOpts} hardCurrencyCode={hardCurrencyCode}
                    />
                  )}
                </div>
              ))
            )
          )}

          {/* Billing Formulas — structured tariff_formula cards relevant to this product */}
          {(() => {
            const productCode = String(bp.product_code ?? '').toUpperCase()
            const isMinOfftake = /offtake|take.or.pay/i.test(String(bp.product_name ?? '')) || productCode === 'ENER004'
            const relevantTypes = isAvailableEnergy
              ? AVAILABLE_ENERGY_FORMULA_TYPES
              : isMinOfftake
                ? MINIMUM_OFFTAKE_FORMULA_TYPES
                : ENERGY_PRODUCT_FORMULA_TYPES
            const productFormulas = tariffFormulas.filter(tf => relevantTypes.has(tf.formula_type))
            if (productFormulas.length === 0) return null
            return (
              <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
                <div className="text-xs font-medium text-slate-400 uppercase mb-1">Billing Formulas</div>
                {productFormulas.map(tf => (
                  <FormulaCard key={tf.id} formula={tf} compact />
                ))}
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Formula Display
// ---------------------------------------------------------------------------

/** Human-readable label for formula_type codes. */
const FORMULA_TYPE_LABELS: Record<string, string> = {
  MRP_BOUNDED: 'Effective Rate (MRP Bounded)',
  MRP_CALCULATION: 'Payment Calculation',
  PERCENTAGE_ESCALATION: 'Rate Escalation',
  FIXED_ESCALATION: 'Fixed Escalation',
  CPI_ESCALATION: 'CPI Escalation',
  FLOOR_CEILING_ESCALATION: 'Floor/Ceiling Escalation',
  ENERGY_OUTPUT: 'Energy Output Definition',
  DEEMED_ENERGY: 'Deemed/Available Energy',
  ENERGY_DEGRADATION: 'Energy Degradation',
  ENERGY_GUARANTEE: 'Energy Guarantee',
  ENERGY_MULTIPHASE: 'Multi-Phase Energy',
  SHORTFALL_PAYMENT: 'Shortfall Payment',
  TAKE_OR_PAY: 'Take-or-Pay',
  FX_CONVERSION: 'FX Conversion',
}

/** Category colour badges for formula types. */
const FORMULA_CATEGORY_STYLE: Record<string, string> = {
  MRP_BOUNDED: 'bg-blue-50 text-blue-700 border-blue-200',
  MRP_CALCULATION: 'bg-blue-50 text-blue-700 border-blue-200',
  PERCENTAGE_ESCALATION: 'bg-violet-50 text-violet-700 border-violet-200',
  FIXED_ESCALATION: 'bg-violet-50 text-violet-700 border-violet-200',
  CPI_ESCALATION: 'bg-violet-50 text-violet-700 border-violet-200',
  FLOOR_CEILING_ESCALATION: 'bg-violet-50 text-violet-700 border-violet-200',
  ENERGY_OUTPUT: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  DEEMED_ENERGY: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  ENERGY_DEGRADATION: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  ENERGY_GUARANTEE: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  ENERGY_MULTIPHASE: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  SHORTFALL_PAYMENT: 'bg-amber-50 text-amber-700 border-amber-200',
  TAKE_OR_PAY: 'bg-amber-50 text-amber-700 border-amber-200',
  FX_CONVERSION: 'bg-slate-50 text-slate-600 border-slate-200',
}

/** Render a formula_text with math-friendly formatting. */
function FormulaText({ text }: { text: string }) {
  // Highlight operators and structural keywords
  const formatted = text
    .replace(/\bMAX\b/g, '<b>MAX</b>')
    .replace(/\bMIN\b/g, '<b>MIN</b>')
    .replace(/\bIF\b/gi, '<b>IF</b>')
    .replace(/\bThen:\s*/gi, '<b class="text-emerald-600">THEN</b> ')
    .replace(/\bElse:\s*/gi, '<b class="text-amber-600">ELSE</b> ')
    // Subscripts: E_metered → E<sub>metered</sub>
    .replace(/([A-Z])_([a-z]+(?:\([^)]*\))?)/g, '$1<sub>$2</sub>')
    // Summation symbol
    .replace(/∑/g, '<span class="text-lg leading-none">∑</span>')

  return (
    <div
      className="font-mono text-sm leading-relaxed bg-slate-50 border border-slate-200 rounded-md px-4 py-3 overflow-x-auto"
      dangerouslySetInnerHTML={{ __html: formatted }}
    />
  )
}

/** Single formula card. compact=true shows only header + formula text. */
function FormulaCard({ formula, compact = false }: { formula: TariffFormula; compact?: boolean }) {
  const badge = FORMULA_CATEGORY_STYLE[formula.formula_type] ?? 'bg-slate-50 text-slate-600 border-slate-200'
  const label = FORMULA_TYPE_LABELS[formula.formula_type] ?? formula.formula_type
  const inputs = formula.variables.filter(v => v.role === 'input')
  const outputs = formula.variables.filter(v => v.role === 'output')
  const conditions = formula.conditions ?? []

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-50 border-b border-slate-200">
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${badge}`}>
          {label}
        </span>
        <span className="text-sm font-medium text-slate-800">{formula.formula_name}</span>
        {formula.section_ref && (
          <span className="text-[10px] text-slate-400 ml-auto">{formula.section_ref}</span>
        )}
      </div>

      <div className="px-4 py-3 space-y-3">
        {/* Formula expression */}
        <FormulaText text={formula.formula_text} />

        {/* Conditions, variables, confidence — only in full mode */}
        {!compact && (<>
          {/* Conditions (if/then/else) */}
          {conditions.length > 0 && conditions[0].compare && (
            <div className="text-xs space-y-1 bg-amber-50/50 border border-amber-100 rounded px-3 py-2">
              {conditions.map((c, i) => (
                <div key={i}>
                  <span className="font-medium text-slate-600">Condition:</span>{' '}
                  <span className="font-mono text-slate-700">
                    {c.compare} {c.operator} {c.against}
                  </span>
                  {c.description && (
                    <div className="text-slate-500 mt-0.5">{c.description}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Variables table */}
          {(inputs.length > 0 || outputs.length > 0) && (
            <div className="text-xs space-y-1.5">
              <div className="text-slate-400 uppercase font-medium tracking-wide">Variables</div>
              <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-4 gap-y-1">
                {/* Header */}
                <div className="text-[10px] text-slate-400 font-medium">Symbol</div>
                <div className="text-[10px] text-slate-400 font-medium">Description</div>
                <div className="text-[10px] text-slate-400 font-medium">Source</div>
                <div className="text-[10px] text-slate-400 font-medium">Scope</div>
                {/* Outputs first */}
                {outputs.map((v, j) => (
                  <Fragment key={`o-${j}`}>
                    <span className="font-mono text-slate-800 font-medium">{v.symbol}</span>
                    <span className="text-slate-500">{v.description}{v.unit ? ` (${v.unit})` : ''}</span>
                    <span className="font-mono text-slate-400 text-[10px]">{v.maps_to ?? '—'}</span>
                    <span className="text-slate-400">{v.lookup_key ?? 'static'}</span>
                  </Fragment>
                ))}
                {/* Inputs */}
                {inputs.map((v, j) => (
                  <Fragment key={`i-${j}`}>
                    <span className="font-mono text-slate-700">{v.symbol}</span>
                    <span className="text-slate-500">{v.description}{v.unit ? ` (${v.unit})` : ''}</span>
                    <span className="font-mono text-slate-400 text-[10px]">{v.maps_to ?? '—'}</span>
                    <span className="text-slate-400">{v.lookup_key ?? 'static'}</span>
                  </Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Confidence */}
          {formula.extraction_confidence != null && (
            <div className="text-[10px] text-slate-400">
              Extraction confidence: {(formula.extraction_confidence * 100).toFixed(0)}%
            </div>
          )}
        </>)}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main PricingTariffsTab
// ---------------------------------------------------------------------------

interface PricingTariffsTabProps {
  data: ProjectDashboardResponse
  onSaved?: () => void
  editMode?: boolean
  projectId?: number
  mrpMonthly?: MRPObservation[]
  mrpAnnual?: MRPObservation[]
  mrpTokens?: SubmissionTokenItem[]
}

export function PricingTariffsTab({ data, onSaved, editMode, projectId, mrpMonthly = [], mrpAnnual = [], mrpTokens = [] }: PricingTariffsTabProps) {
  const { contracts, tariffs: rawTariffs, billing_products, rate_periods, monthly_rates, tariff_rates, tariff_formulas = [], exchange_rates, lookups } = data
  const pid = data.project.id as number

  // Filter out component tariffs — only show consolidated MAIN tariffs (MOH01 pattern).
  // Excludes legacy multi-tariff rows (GRID_BASE, DISCOUNTED, FLOOR, CEILING suffixes)
  // and older tariff-bridge component rows (_Discounted_Solar_, _Floor_Solar_, _Current_Grid_).
  const tariffs = useMemo(() => rawTariffs.filter((t: R) => {
    const gk = String(t.tariff_group_key ?? '')
    const lp = (t.logic_parameters ?? {}) as R
    if (COMPONENT_SUFFIXES.some(s => gk.endsWith(s))) return false
    if (lp.tariff_component != null) return false
    if (COMPONENT_INFIX_RE.test(gk)) return false
    return true
  }), [rawTariffs])

  const [openProducts, setOpenProducts] = useState<Set<unknown>>(new Set())
  const toggleProduct = (id: unknown) =>
    setOpenProducts((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const [expandedPeriods, setExpandedPeriods] = useState<Set<unknown>>(new Set())
  const togglePeriod = (id: unknown) =>
    setExpandedPeriods((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const currencyOpts = toOpts(lookups?.currencies)
  const tariffTypeOpts = toOpts(
    (lookups?.tariff_types ?? []).filter((t: { code?: string }) => !HIDDEN_TARIFF_CODES.has(t.code ?? ''))
  ).map((o) => ({ ...o, label: o.label.replace(/Boot/g, 'BOOT') }))
  const energySaleTypeOpts = toOpts(lookups?.energy_sale_types)
  const escalationTypeOpts = toOpts(lookups?.escalation_types)
  const billingProductOpts = (lookups?.billing_products ?? []).map((bp: { id: number; code?: string; name: string }) => ({
    value: bp.id,
    label: bp.code ? `${bp.code} - ${bp.name}` : bp.name,
  }))

  // Derive hard (USD) and billing currency codes from tariff_rates
  const hardCurrencyCode = ((tariff_rates ?? []) as R[]).find((tr) => tr.hard_currency_code != null)?.hard_currency_code as string | undefined
  const billingCurrencyCode = ((tariff_rates ?? []) as R[]).find((tr) => tr.billing_currency_code != null)?.billing_currency_code as string | undefined
  const isLocalCurrency = billingCurrencyCode != null && billingCurrencyCode !== 'USD'

  // Determine the local currency for this project's exchange rate display.
  // Fallback chain: tariff_rates → contract extraction_metadata → country lookup
  const projectFxCurrency: string | undefined = (() => {
    // 1. From tariff_rates (only populated for fully-onboarded projects like MOH01)
    const fromTariffLocal = ((tariff_rates ?? []) as R[]).find((tr) => tr.local_currency_code != null)?.local_currency_code as string | undefined
    const fromTariffBilling = billingCurrencyCode && billingCurrencyCode !== 'USD' ? billingCurrencyCode : undefined
    if (fromTariffLocal) return fromTariffLocal
    if (fromTariffBilling) return fromTariffBilling

    // 2. From contract extraction_metadata.billing_currency (set by migration 046)
    const primaryContract = contracts.find((c) => c.parent_contract_id == null)
    const metaCurrency = (primaryContract?.extraction_metadata as Record<string, unknown> | undefined)?.billing_currency as string | undefined
    if (metaCurrency && metaCurrency !== 'USD') return metaCurrency

    // 3. Country → local currency mapping (final fallback)
    const country = data.project.country as string | undefined
    if (country && COUNTRY_TO_CURRENCY[country]) {
      if (process.env.NODE_ENV === 'development') {
        console.warn(`PricingTariffsTab: using country fallback for FX currency: ${country} → ${COUNTRY_TO_CURRENCY[country]}`)
      }
    }
    return country ? COUNTRY_TO_CURRENCY[country] : undefined
  })()

  // Top-level first tariff/LP for MRP section (independent of contracts loop)
  const mrpFirstTariff = (() => {
    const c = contracts[0]
    if (!c) return undefined
    const ct = tariffs.filter((t) => t.contract_id === c.id)
    return (ct.find((t) => t.is_current === true) ?? ct[0]) as R | undefined
  })()
  const mrpFirstLp = (mrpFirstTariff?.logic_parameters ?? {}) as R

  return (
    <div className="space-y-4">
      {contracts.length === 0 && (<>
        <EmptyState>No contracts found</EmptyState>

        {/* MRP section renders even without contracts */}
        <MRPSection
          projectId={pid}
          orgId={data.project.organization_id as number}
          codDate={data.project.cod_date as string | null | undefined}
          firstTariff={mrpFirstTariff}
          firstLp={mrpFirstLp}
          baselineMrp={data.baseline_mrp ?? []}
          initialMonthly={mrpMonthly}
          initialAnnual={mrpAnnual}
          initialTokens={mrpTokens}
          onSaved={onSaved}
          editMode={editMode}
        />
      </>)}

      {/* Tariff & Rate Schedule */}
      <CollapsibleSection title="Tariff & Rate Schedule">
        {tariffs.length === 0 ? (
          <EmptyState>No tariffs found</EmptyState>
        ) : (
          <div className="space-y-5">
            {tariffs.map((t, i) => {
              const periods = rate_periods
                .filter((rp) => rp.clause_tariff_id === t.id)
                .sort((a, b) => Number(a.contract_year) - Number(b.contract_year))
              const isRebasedTariffHeader = REBASED_CODES.has(String(t.escalation_type_code ?? ''))
              const tariffMonthlyRates = (monthly_rates ?? [])
                    .filter((mr: R) => mr.clause_tariff_id === t.id)
                    .sort((a: R, b: R) => String(b.billing_month ?? '').localeCompare(String(a.billing_month ?? '')))
              const hasMonthlyTracking = tariffMonthlyRates.length > 0
              const latestMonthLabel = isRebasedTariffHeader && tariffMonthlyRates.length > 0
                ? formatBillingMonth(tariffMonthlyRates[0].billing_month)
                : null
              // For local-currency deterministic tariffs, enable FX expansion using exchange_rates
              const showFxConversion = isLocalCurrency && !hasMonthlyTracking
              const canExpand = hasMonthlyTracking || showFxConversion
              const fxRatesForPeriod = showFxConversion
                ? [...(exchange_rates ?? []) as R[]]
                    .filter((er) => er.currency_code === projectFxCurrency)
                    .sort((a, b) => String(b.rate_date ?? '').localeCompare(String(a.rate_date ?? '')))
                : []
              return (
                <div key={i} className={i > 0 ? 'pt-5 border-t border-slate-200' : ''}>
                  {/* Tariff summary line */}
                  <div className="flex items-baseline gap-3 mb-2">
                    <span className="text-sm font-medium text-slate-800">{str(t.name ?? t.energy_sale_type_name)}</span>
                    <span className="text-xs text-slate-400">
                      {[t.energy_sale_type_code, t.escalation_type_code].filter(Boolean).join(' / ')}
                    </span>
                    {t.contract_amendment_id != null && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                        v{t.version != null ? String(t.version) : '2'} &mdash; Amended
                      </span>
                    )}
                    <span className="text-xs text-slate-400 ml-auto">
                      {latestMonthLabel
                        ? `As of ${latestMonthLabel}`
                        : t.valid_from != null
                          ? `${str(t.valid_from)}${t.valid_to != null ? ` — ${str(t.valid_to)}` : ''}`
                          : ''}
                    </span>
                  </div>

                  {/* Rate periods table */}
                  {periods.length === 0 ? (
                    <div className="text-xs text-slate-400 italic pl-1">No rate periods</div>
                  ) : (() => {
                    const isRebasedTariff = REBASED_CODES.has(String(t.escalation_type_code ?? ''))
                    const tLp = (t.logic_parameters ?? {}) as R
                    const discPctDisplay = tLp.discount_pct != null ? `${Number((Number(tLp.discount_pct) * 100).toFixed(2)).toString().replace(/\.?0+$/, '')}%` : ''
                    const basisOverride = isRebasedTariff && discPctDisplay
                      ? `MRP per kWh less ${discPctDisplay} solar discount, bounded by floor/ceiling (USD), converted at monthly FX rate`
                      : null
                    return (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-slate-200">
                            {canExpand && <th className="w-6" />}
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Year</th>
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Period</th>
                            <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">{isLocalCurrency ? `Rate (${billingCurrencyCode})` : 'Rate'}</th>
                            {isLocalCurrency
                              ? <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Rate (USD)</th>
                              : <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Currency</th>}
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500 max-w-[160px]">Basis</th>
                            <th className="text-center px-3 py-1.5 text-xs font-medium text-slate-500">Current</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(() => {
                            const currentPeriod = periods.find((rp) => rp.is_current === true) ?? periods[periods.length - 1]
                            const currentYear = currentPeriod?.contract_year as number | undefined
                            const historicalPeriods = periods.filter((rp) =>
                              rp !== currentPeriod && currentYear != null && (rp.contract_year as number) < currentYear
                            )
                            const historyKey = `history-${t.id}`
                            const showHistory = expandedPeriods.has(historyKey)

                            const renderPeriodRow = (rp: R, j: number) => {
                            // Look up full tariff_rate row for USD rate
                            const matchingTr = ((tariff_rates ?? []) as R[]).find((tr) =>
                              tr.clause_tariff_id === rp.clause_tariff_id && tr.contract_year === rp.contract_year && tr.rate_granularity === 'annual')
                            const periodMonthlyRates = hasMonthlyTracking
                              ? (monthly_rates ?? [])
                                  .filter((mr: R) => mr.clause_tariff_id === rp.clause_tariff_id && mr.contract_year === rp.contract_year)
                                  .sort((a: R, b: R) => String(b.billing_month ?? '').localeCompare(String(a.billing_month ?? '')))
                              : []
                            const isExpanded = expandedPeriods.has(rp.id)
                            return (
                              <Fragment key={j}>
                              <tr
                                className={`border-b border-slate-50 ${rp.is_current ? 'bg-blue-50/40' : 'hover:bg-slate-50'} ${(periodMonthlyRates.length > 0 || showFxConversion) ? 'cursor-pointer' : ''}`}
                                onClick={(periodMonthlyRates.length > 0 || showFxConversion) ? () => togglePeriod(rp.id) : undefined}
                              >
                                {canExpand && (
                                  <td className="pl-2 py-1.5 w-6">
                                    {(periodMonthlyRates.length > 0 || showFxConversion) && (
                                      <ChevronRight className={`h-3.5 w-3.5 text-slate-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                    )}
                                  </td>
                                )}
                                <td className="px-3 py-1.5 text-slate-700 tabular-nums">
                                  {editMode && rp.id != null ? (
                                    <EditableCell value={rp.contract_year} fieldKey="contract_year" entity="rate-periods" entityId={rp.id as number} type="number" editMode onSaved={onSaved} />
                                  ) : str(rp.contract_year)}
                                </td>
                                <td className="px-3 py-1.5 text-slate-600 text-xs tabular-nums">
                                  {`${str(rp.period_start)}${rp.period_end ? ` — ${str(rp.period_end)}` : ''}`}
                                </td>
                                <td className="px-3 py-1.5 text-right text-slate-700 tabular-nums font-medium">
                                  {editMode && rp.id != null ? (
                                    <EditableCell value={rp.effective_rate_contract_ccy} fieldKey="effective_rate_contract_ccy" entity="rate-periods" entityId={rp.id as number} type="number" editMode onSaved={onSaved} />
                                  ) : fmtRate(rp.effective_rate_contract_ccy)}
                                </td>
                                {isLocalCurrency
                                  ? <td className="px-3 py-1.5 text-right text-slate-500 tabular-nums text-xs">{fmtRate(matchingTr?.effective_rate_hard_ccy)}</td>
                                  : <td className="px-3 py-1.5 text-slate-500 text-xs">{str(rp.currency_code)}</td>}
                                <td className="px-3 py-1.5 text-slate-500 text-xs whitespace-pre-line max-w-[160px] break-words">
                                  {editMode && rp.id != null ? (
                                    <EditableCell value={rp.calculation_basis} fieldKey="calculation_basis" entity="rate-periods" entityId={rp.id as number} type="text" editMode onSaved={onSaved} />
                                  ) : str(basisOverride ?? rp.calculation_basis)}
                                </td>
                                <td className="px-3 py-1.5 text-center">
                                  {rp.is_current === true && <span className="inline-block w-2 h-2 rounded-full bg-blue-500" title="Current" />}
                                </td>
                              </tr>
                              {/* Monthly sub-header + sub-rows */}
                              {isExpanded && periodMonthlyRates.length > 0 && (
                                <tr className="bg-slate-100/60">
                                  <td />{/* chevron col */}
                                  <td className="px-3 py-1 text-[10px] font-medium text-slate-400 uppercase tracking-wider">Month</td>
                                  <td className="px-3 py-1 text-[10px] font-medium text-slate-400 uppercase tracking-wider">Binding</td>
                                  <td className="px-3 py-1 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate ({billingCurrencyCode ?? 'LCY'})</td>
                                  <td className="px-3 py-1 text-[10px] font-medium text-slate-400 uppercase tracking-wider">FX Rate</td>
                                  <td className="px-3 py-1 text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate (USD)</td>
                                  <td className="px-3 py-1 text-center text-[10px] font-medium text-slate-400 uppercase tracking-wider">Current</td>
                                </tr>
                              )}
                              {isExpanded && periodMonthlyRates.map((mr: R, k: number) => {
                                const mrFx = mr.exchange_rate != null ? Number(mr.exchange_rate) : null
                                const mrLocal = mr.effective_tariff_local != null ? Number(mr.effective_tariff_local) : null
                                const mrUsd = mrLocal != null && mrFx ? mrLocal / mrFx : null
                                return (
                                  <tr key={`m-${k}`} className={`border-b border-slate-50 ${mr.is_current ? 'bg-blue-50/20' : 'bg-slate-50/50'}`}>
                                    <td />{/* chevron col */}
                                    <td className="px-3 py-1 text-xs text-slate-500 pl-6">
                                      {formatBillingMonth(mr.billing_month)}
                                    </td>
                                    <td className="px-3 py-1 text-xs text-slate-500 tabular-nums">
                                      {str(mr.rate_binding)}
                                    </td>
                                    <td className="px-3 py-1 text-right text-xs text-slate-600 tabular-nums">
                                      {fmtRate(mr.effective_tariff_local)}
                                    </td>
                                    <td className="px-3 py-1 text-xs text-slate-500 tabular-nums">
                                      {mrFx != null ? mrFx.toFixed(4) : '—'}
                                    </td>
                                    <td className="px-3 py-1 text-xs text-slate-500 tabular-nums">
                                      {mrUsd != null ? mrUsd.toFixed(4) : '—'}
                                    </td>
                                    <td className="px-3 py-1 text-center">
                                      {mr.is_current === true && <span className="inline-block w-2 h-2 rounded-full bg-blue-400" title="Current" />}
                                    </td>
                                  </tr>
                                )
                              })}
                              {/* Monthly FX conversion rows for deterministic local-currency tariffs */}
                              {isExpanded && showFxConversion && (() => {
                                const contractRate = Number(rp.effective_rate_contract_ccy)
                                if (isNaN(contractRate)) return null
                                const periodFx = fxRatesForPeriod.filter((er) => {
                                  const d = String(er.rate_date ?? '')
                                  return d >= String(rp.period_start ?? '') && (!rp.period_end || d <= String(rp.period_end))
                                })
                                if (periodFx.length === 0) return null
                                return (
                                  <>
                                    <tr className="bg-slate-100/60">
                                      <td />{/* chevron col */}
                                      <td className="px-3 py-1 text-[10px] font-medium text-slate-400 uppercase tracking-wider">Month</td>
                                      <td />
                                      <td className="px-3 py-1 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate ({billingCurrencyCode})</td>
                                      <td className="px-3 py-1 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider">FX Rate</td>
                                      <td className="px-3 py-1 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate (USD)</td>
                                      <td />
                                    </tr>
                                    {periodFx.map((er, k) => {
                                      const fx = Number(er.rate)
                                      const usd = fx > 0 ? contractRate / fx : null
                                      return (
                                        <tr key={`fx-${k}`} className="border-b border-slate-50 bg-slate-50/50">
                                          <td />{/* chevron col */}
                                          <td className="px-3 py-1 text-xs text-slate-500 pl-6">{formatBillingMonth(er.rate_date)}</td>
                                          <td />
                                          <td className="px-3 py-1 text-right text-xs text-slate-600 tabular-nums">{fmtRate(contractRate)}</td>
                                          <td className="px-3 py-1 text-right text-xs text-slate-500 tabular-nums">{fx.toFixed(4)}</td>
                                          <td className="px-3 py-1 text-right text-xs text-slate-600 tabular-nums font-medium">{usd != null ? usd.toFixed(4) : '—'}</td>
                                          <td />
                                        </tr>
                                      )
                                    })}
                                  </>
                                )
                              })()}
                              </Fragment>
                            )
                            }

                            return (
                              <>
                                {currentPeriod && renderPeriodRow(currentPeriod, 0)}
                                {historicalPeriods.length > 0 && (
                                  <tr
                                    className="border-b border-slate-100 cursor-pointer hover:bg-slate-50/80"
                                    onClick={() => togglePeriod(historyKey)}
                                  >
                                    <td colSpan={canExpand ? 7 : 6} className="px-3 py-1.5">
                                      <div className="flex items-center gap-1.5 text-xs text-slate-400">
                                        <ChevronRight className={`h-3 w-3 transition-transform ${showHistory ? 'rotate-90' : ''}`} />
                                        <span>{showHistory ? 'Hide' : 'Show'} {historicalPeriods.length} historical year{historicalPeriods.length !== 1 ? 's' : ''}</span>
                                      </div>
                                    </td>
                                  </tr>
                                )}
                                {showHistory && historicalPeriods.map((rp, j) => renderPeriodRow(rp, j + 1))}
                              </>
                            )
                          })()}
                        </tbody>
                      </table>
                    </div>
                    )
                  })()}
                </div>
              )
            })}
          </div>
        )}
      </CollapsibleSection>

      {/* Exchange Rates — filtered to project's currency, grouped by year */}
      {(() => {
        const filteredRates = projectFxCurrency
          ? (exchange_rates ?? []).filter((er) => er.currency_code === projectFxCurrency)
          : (exchange_rates ?? [])
        if (filteredRates.length === 0) return null

        const sorted = [...filteredRates].sort(
          (a, b) => String(b.rate_date ?? '').localeCompare(String(a.rate_date ?? ''))
        )
        // Group by year (descending)
        const byYear = new Map<number, typeof sorted>()
        for (const er of sorted) {
          const y = new Date(String(er.rate_date)).getFullYear()
          if (!byYear.has(y)) byYear.set(y, [])
          byYear.get(y)!.push(er)
        }
        const years = [...byYear.keys()].sort((a, b) => b - a)
        const latestYear = years[0]

        return (
        <CollapsibleSection title={`Exchange Rates${projectFxCurrency ? ` (USD → ${projectFxCurrency})` : ''}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="w-6" />
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Date</th>
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Currency</th>
                  <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Rate (USD → Local)</th>
                  <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">MoM Change</th>
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Source</th>
                </tr>
              </thead>
              <tbody>
                {years.map((year) => {
                  const yearRates = byYear.get(year)!
                  const yearKey = `fx-${year}`
                  const isYearExpanded = year === latestYear || expandedPeriods.has(yearKey)
                  return (
                    <Fragment key={year}>
                      <tr
                        className="border-b border-slate-100 bg-slate-50/80 cursor-pointer hover:bg-slate-100/80"
                        onClick={() => togglePeriod(yearKey)}
                      >
                        <td className="pl-2 py-1.5 w-6">
                          <ChevronRight className={`h-3.5 w-3.5 text-slate-400 transition-transform ${isYearExpanded ? 'rotate-90' : ''}`} />
                        </td>
                        <td colSpan={5} className="px-3 py-1.5 text-xs font-semibold text-slate-600">
                          {year}
                          <span className="ml-2 text-slate-400 font-normal">({yearRates.length} {yearRates.length === 1 ? 'month' : 'months'})</span>
                        </td>
                      </tr>
                      {isYearExpanded && yearRates.map((er, idx) => {
                        const rate = Number(er.rate)
                        const prevRate = idx < yearRates.length - 1 ? Number(yearRates[idx + 1].rate) : null
                        const momChange = prevRate != null && prevRate !== 0
                          ? ((rate - prevRate) / prevRate) * 100
                          : null
                        return (
                          <tr key={er.id as number} className={`border-b border-slate-50 ${idx === 0 && year === latestYear ? 'bg-blue-50/40' : 'hover:bg-slate-50'}`}>
                            <td />
                            <td className="px-3 py-1.5 text-slate-700 tabular-nums">{formatBillingMonth(er.rate_date)}</td>
                            <td className="px-3 py-1.5 text-slate-500 text-xs">{str(er.currency_code)}</td>
                            <td className="px-3 py-1.5 text-right text-slate-700 tabular-nums font-medium">
                              {editMode ? (
                                <EditableCell
                                  value={er.rate}
                                  fieldKey="rate"
                                  entity="exchange-rates"
                                  entityId={er.id as number}
                                  type="number"
                                  editMode={true}
                                  onSaved={onSaved}
                                  formatDisplay={(v) => v != null ? Number(v).toFixed(2) : '—'}
                                />
                              ) : rate.toFixed(2)}
                            </td>
                            <td className="px-3 py-1.5 text-right tabular-nums">
                              {momChange != null ? (
                                <span className={momChange > 0 ? 'text-red-600' : momChange < 0 ? 'text-green-600' : 'text-slate-400'}>
                                  {momChange > 0 ? '+' : ''}{momChange.toFixed(2)}%
                                </span>
                              ) : (
                                <span className="text-slate-300">—</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 text-slate-500 text-xs">
                              {editMode ? (
                                <EditableCell
                                  value={er.source}
                                  fieldKey="source"
                                  entity="exchange-rates"
                                  entityId={er.id as number}
                                  type="text"
                                  editMode={true}
                                  onSaved={onSaved}
                                />
                              ) : str(er.source)}
                            </td>
                          </tr>
                        )
                      })}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )})()}

      {contracts.filter((c) => c.parent_contract_id == null).map((c, i) => {
        const cid = c.id as number
        // Include tariffs from this contract AND its amendments
        const amendmentIds = new Set(contracts.filter((a) => a.parent_contract_id === c.id).map((a) => a.id))
        const contractTariffs = tariffs.filter((t) => t.contract_id === c.id || amendmentIds.has(t.contract_id))
        const currentTariff = contractTariffs.find((t) => t.is_current === true) as R | undefined
        const firstTariff = (currentTariff ?? contractTariffs[0]) as R | undefined
        const firstLp = (firstTariff?.logic_parameters ?? {}) as R
        const energySalesTariff = contractTariffs.find(
          (t) => String(t.energy_sale_type_code).toUpperCase() === 'ENERGY_SALES',
        )
        const { matched, unmatched } = groupProductsWithTariffs(billing_products, tariffs, c.id, amendmentIds)

        // Collect distinct tariff type names for tag badges
        const distinctTariffTypes = [
          ...new Set(contractTariffs.map((t) => t.energy_sale_type_name).filter(Boolean)),
        ] as string[]

        return (
          <div key={i}>
            {/* Section 1: Billing Information */}
            <CollapsibleSection title="Billing Information">
              <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                ...(firstTariff && firstLp.billing_frequency != null
                  ? [['Billing Frequency', normalizeFrequency(firstLp.billing_frequency), { fieldKey: 'lp_billing_frequency', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: BILLING_FREQUENCY_OPTS, selectValue: normalizeFrequency(firstLp.billing_frequency) }] as FieldDef]
                  : []),
                ...(billingCurrencyCode != null || firstTariff != null ? [['Billing Currency', billingCurrencyCode ?? firstTariff?.currency_code] as FieldDef] : []),
                ['Payment Terms', c.payment_terms, { fieldKey: 'payment_terms', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'select' as const, options: PAYMENT_TERMS_OPTS, selectValue: c.payment_terms }],
              ]} />
              {/* Source of Exchange Rate */}
              <div className="mt-2 py-1">
                <dt className="text-xs text-slate-400">Source of Exchange Rate</dt>
                <dd className="text-sm text-slate-900 mt-0.5">
                  {editMode && firstTariff ? (
                    <EditableCell
                      value={firstTariff.agreed_fx_rate_source}
                      fieldKey="agreed_fx_rate_source"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="text"
                      editMode={true}
                      onSaved={onSaved}
                    />
                  ) : (
                    <span className="whitespace-pre-line">{firstTariff?.agreed_fx_rate_source != null ? String(firstTariff.agreed_fx_rate_source) : '—'}</span>
                  )}
                </dd>
              </div>
            </CollapsibleSection>

            {/* Phase Breakdown — shown when logic_parameters has phases[] */}
            {(() => {
              const phases = firstLp.phases as { phase: number; kwp: number; cod_date: string; meter_serial?: string }[] | undefined
              if (!Array.isArray(phases) || phases.length === 0) return null
              return (
                <CollapsibleSection title="Phase Breakdown">
                  <div className="grid grid-cols-1 gap-2">
                    {phases.map((p, idx) => (
                      <div key={`phase-${p.phase ?? idx}`} className="flex items-center gap-4 px-3 py-2 bg-purple-50/50 rounded border border-purple-100">
                        <span className="text-xs font-semibold text-purple-700">Phase {p.phase}</span>
                        <span className="text-sm text-slate-700">{p.kwp.toLocaleString()} kWp</span>
                        <span className="text-xs text-slate-500">COD {p.cod_date}</span>
                        {p.meter_serial && <span className="text-xs text-slate-400">Meter: {p.meter_serial}</span>}
                      </div>
                    ))}
                  </div>
                </CollapsibleSection>
              )
            })()}

            {/* Section 3: Service & Product Classification */}
            <CollapsibleSection title="Service & Product Classification">
              <div className="space-y-3">
                {/* Tariff type badges / editable dropdowns */}
                {editMode ? (
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={
                    contractTariffs.map((t) => [
                      `Revenue Type${contractTariffs.length > 1 ? ` — ${str(t.name ?? t.energy_sale_type_name ?? 'Tariff')}` : ''}`,
                      t.energy_sale_type_code,
                      { fieldKey: 'energy_sale_type_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: energySaleTypeOpts, selectValue: t.energy_sale_type_id },
                    ] as FieldDef)
                  } />
                ) : (
                  <div className="flex flex-col py-1">
                    <dt className="text-xs text-slate-400">Revenue Type</dt>
                    <dd className="mt-1 flex flex-wrap gap-1.5">
                      {distinctTariffTypes.length > 0 ? (
                        distinctTariffTypes.map((name) => (
                          <span key={name} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
                            {name}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-slate-500">—</span>
                      )}
                    </dd>
                  </div>
                )}

                {/* Energy Sale Type (post-059: tariff_type is offtake/billing model) */}
                {energySalesTariff && (
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                    ['Energy Sale Type', energySalesTariff.tariff_type_name ?? energySalesTariff.tariff_type_code, { fieldKey: 'tariff_type_id', entity: 'tariffs' as const, entityId: energySalesTariff.id as number, projectId: pid, type: 'select' as const, options: tariffTypeOpts, selectValue: energySalesTariff.tariff_type_id }],
                  ]} />
                )}
              </div>
            </CollapsibleSection>

            {/* Products to be Billed */}
            <CollapsibleSection title="Products to be Billed">
              {matched.length === 0 && unmatched.length === 0 && !editMode ? (
                <EmptyState>No billing products or tariffs found</EmptyState>
              ) : (
                <div className="space-y-3">
                  {matched.map((pw) => (
                    <BillingProductCard
                      key={pw.product.id as number}
                      pw={pw} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                      contractLines={data.contract_lines ?? []}
                      tariffFormulas={tariff_formulas}
                      onSaved={onSaved} editMode={editMode}
                      isOpen={openProducts.has(pw.product.id)}
                      onToggle={() => toggleProduct(pw.product.id)}
                      onRemove={async () => {
                        try {
                          await adminClient.removeBillingProduct(pw.product.id as number)
                          toast.success(`Removed ${str(pw.product.product_name)}`)
                          onSaved?.()
                        } catch (e) {
                          toast.error(e instanceof Error ? e.message : 'Failed to remove product')
                        }
                      }}
                      billingProductOpts={billingProductOpts} tariffTypeOpts={tariffTypeOpts}
                      energySaleTypeOpts={energySaleTypeOpts} escalationTypeOpts={escalationTypeOpts}
                      currencyOpts={currencyOpts} hardCurrencyCode={hardCurrencyCode}
                    />
                  ))}

                  {/* Add Product (edit mode only) */}
                  {editMode && !IS_DEMO && (
                    <AddProductRow
                      contractId={cid}
                      existingProductIds={new Set(matched.map((pw) => pw.product.billing_product_id as number))}
                      billingProductOpts={billingProductOpts}
                      onAdded={onSaved}
                    />
                  )}

                  {/* Other Tariffs — not matched to any product */}
                  {unmatched.length > 0 && (
                    <div className="border border-slate-200 rounded-lg p-4">
                      <div className="text-xs font-medium text-slate-400 uppercase mb-3">Other Tariffs</div>
                      {unmatched.map((t, j) => (
                        <div key={j} className={j > 0 ? 'mt-4 pt-4 border-t border-slate-100' : ''}>
                          <div className="flex items-center gap-2 mb-1">
                            <div className="text-xs font-medium text-slate-500">
                              {str(t.energy_sale_type_name ?? t.energy_sale_type_code ?? 'Tariff')}
                            </div>
                            {isNonEnergyTariff(t) && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">Non-Energy</span>
                            )}
                          </div>
                          {isNonEnergyTariff(t) ? (
                            <NonEnergyTariffPanel
                              t={t} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                              onSaved={onSaved} editMode={editMode}
                              energySaleTypeOpts={energySaleTypeOpts} escalationTypeOpts={escalationTypeOpts}
                            />
                          ) : (
                            <TariffDetailPanel
                              t={t} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                              onSaved={onSaved} editMode={editMode}
                              currencyOpts={currencyOpts} hardCurrencyCode={hardCurrencyCode}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CollapsibleSection>

            {/* Section 4–7: Formula Parameters (visible only when data exists) */}
            {firstTariff != null && (<>
              {/* Section 4: Escalation Rules */}
              {(firstTariff.escalation_type_code != null || hasAnyValue(firstLp, ['escalation_frequency', 'escalation_start_date', 'tariff_components_to_adjust', 'escalation_rules', 'cpi_base_date'])) && (
                <CollapsibleSection title="Escalation Rules">
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                    ['Price Adjustment Type', firstTariff.escalation_type_code, { fieldKey: 'escalation_type_id', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: escalationTypeOpts, selectValue: firstTariff.escalation_type_id }],
                    ...(firstLp.escalation_frequency != null ? [['Escalation Frequency', normalizeFrequency(firstLp.escalation_frequency), { fieldKey: 'lp_escalation_frequency', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: ESCALATION_FREQUENCY_OPTS, selectValue: normalizeFrequency(firstLp.escalation_frequency) }] as FieldDef] : []),
                    ...(firstLp.escalation_start_date != null ? [['Escalation Start Date', firstLp.escalation_start_date, { fieldKey: 'lp_escalation_start_date', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'text' as const }] as FieldDef] : []),

                    ...(firstLp.tariff_components_to_adjust != null ? [['Energy Sales Tariff to Adjust', normalizeTariffComponent(firstLp.tariff_components_to_adjust), { fieldKey: 'lp_tariff_components_to_adjust', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: TARIFF_COMPONENTS_TO_ADJUST_OPTS, selectValue: normalizeTariffComponent(firstLp.tariff_components_to_adjust) }] as FieldDef] : []),

                  ]} />
                  {/* CPI-specific metadata fields */}
                  {String(firstTariff.escalation_type_code ?? '') === 'US_CPI' && firstLp.cpi_base_date != null && (
                    <FieldGrid fields={[
                      ['CPI Index', 'CUUR0000SA0 (US CPI-U All Items)'],
                      ['CPI Base Month', String(firstLp.cpi_base_date).slice(0, 7)],
                      ['CPI Base Value', firstLp.cpi_base_value != null ? Number(firstLp.cpi_base_value).toFixed(3) : '—'],
                      ['CPI Subtype', firstLp.cpi_escalation_subtype === 'floor_ceiling' ? 'Floor & Ceiling Escalation' : 'Base Rate Escalation'],
                    ]} />
                  )}
                  <EscalationRulesTable rules={firstLp.escalation_rules} logicParameters={firstLp} />
                  {/* CPI Escalation Schedule — from actual tariff_rate rows */}
                  {String(firstTariff.escalation_type_code ?? '') === 'US_CPI' && (
                    <CPIEscalationSchedule
                      tariffRates={(tariff_rates ?? []) as R[]}
                      clauseTariffId={firstTariff.id}
                      logicParameters={firstLp}
                      codDate={data.project.cod_date != null ? String(data.project.cod_date) : null}
                    />
                  )}
                  {/* RateBoundsSchedule — for non-CPI escalation with escalation_rules */}
                  {String(firstTariff.escalation_type_code ?? '') !== 'US_CPI' && (
                    <RateBoundsSchedule
                      logicParameters={firstLp}
                      contractTermYears={Number(c.contract_term_years ?? 0)}
                      codDate={data.project.cod_date != null ? String(data.project.cod_date) : null}
                    />
                  )}
                </CollapsibleSection>
              )}
            </>)}

            {/* Section 5: Market Reference Price — right after Escalation Rules */}
            <MRPSection
              projectId={pid}
              orgId={data.project.organization_id as number}
              codDate={data.project.cod_date as string | null | undefined}
              firstTariff={firstTariff}
              firstLp={firstLp}
              baselineMrp={data.baseline_mrp ?? []}
              initialMonthly={mrpMonthly}
              initialAnnual={mrpAnnual}
              initialTokens={mrpTokens}
              onSaved={onSaved}
              editMode={editMode}
            />

            {/* Available Energy — now displayed inside the ENER003 BillingProductCard */}

            {/* Section 7: Shortfall Formula */}
            {(() => {
              const shortfallFormulas = tariff_formulas.filter(tf => tf.formula_type === 'SHORTFALL_PAYMENT' || tf.formula_type === 'TAKE_OR_PAY')
              const hasLpShortfall = firstTariff != null && hasAnyValue(firstLp, ['shortfall_formula_type', 'shortfall_formula_text', 'shortfall_formula_variables'])
              if (shortfallFormulas.length === 0 && !hasLpShortfall) return null
              return (
                <CollapsibleSection title="Shortfall Formula">
                  {shortfallFormulas.length > 0 ? (
                    <div className="space-y-2">
                      {shortfallFormulas.map(tf => (
                        <FormulaCard key={tf.id} formula={tf} compact />
                      ))}
                    </div>
                  ) : firstTariff != null && (
                    /* Fallback: legacy logic_parameters display */
                    <div>
                      {firstLp.shortfall_formula_type != null && (
                        <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                          ['Shortfall Formula', firstLp.shortfall_formula_type, { fieldKey: 'lp_shortfall_formula_type', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'text' as const }],
                        ]} />
                      )}
                      {firstLp.shortfall_formula_text != null && (
                        <div className="py-1">
                          <dd className="text-sm text-slate-900">
                            <span className="whitespace-pre-line">{String(firstLp.shortfall_formula_text)}</span>
                          </dd>
                        </div>
                      )}
                      {(() => {
                        const vars = firstLp.shortfall_formula_variables as { symbol: string; definition: string; unit?: string }[] | undefined
                        const cap = firstLp.shortfall_formula_cap as string | undefined
                        if (!vars?.length && !cap) return null
                        return (
                          <div className="text-xs space-y-1.5 mt-3">
                            {vars && vars.length > 0 && (<>
                              <div className="text-slate-400 uppercase font-medium">Where:</div>
                              {vars.map((v, j) => (
                                <div key={j} className="flex gap-3">
                                  <span className="font-mono text-slate-700 shrink-0 w-28">{v.symbol}</span>
                                  <span className="text-slate-500">= {v.definition}{v.unit ? ` (${v.unit})` : ''}</span>
                                </div>
                              ))}
                            </>)}
                            {cap && (
                              <div className="mt-2 text-slate-500 italic">{cap}</div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  )}
                </CollapsibleSection>
              )
            })()}

            {/* Section 8: Non-Energy Service Lines */}
            {(() => {
              const nonEnergyTariffs = contractTariffs.filter(isNonEnergyTariff)
              return (
                <CollapsibleSection title="Non-Energy Service Lines">
                  {nonEnergyTariffs.length === 0 ? (
                    <EmptyState>No equipment rental, BESS lease, or loan repayment lines on this contract</EmptyState>
                  ) : (
                    <div className="space-y-3">
                      {nonEnergyTariffs.map((t, j) => {
                        const lp = (t.logic_parameters ?? {}) as R
                        const currentMr = (monthly_rates ?? []).find(
                          (mr: R) => mr.clause_tariff_id === t.id && mr.is_current,
                        )
                        const baseCurrency = t.currency_code ? ` (${t.currency_code})` : ''
                        const localCurrency = currentMr?.currency_code ? ` (${currentMr.currency_code})` : ''
                        return (
                          <div key={j} className={j > 0 ? 'pt-3 border-t border-slate-100' : ''}>
                            <div className="flex items-center gap-2 mb-2">
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                                {str(t.energy_sale_type_name ?? t.energy_sale_type_code)}
                              </span>
                            </div>
                            <FieldGrid fields={[
                              [`Rate per Unit${baseCurrency}`, t.base_rate],
                              ...(t.unit != null ? [['Unit', t.unit] as FieldDef] : []),
                              ...(t.escalation_type_code != null ? [['Escalation', t.escalation_type_code] as FieldDef] : []),
                              ...(lp.escalation_value != null ? [['Escalation Value', lp.escalation_value] as FieldDef] : []),
                              ...(currentMr ? [[`Effective Rate${localCurrency}${currentMr.billing_month ? ` — ${formatBillingMonth(currentMr.billing_month)}` : ''}`, currentMr.effective_tariff_local] as FieldDef] : []),
                            ]} />
                          </div>
                        )
                      })}
                    </div>
                  )}
                </CollapsibleSection>
              )
            })()}

            {/* Section 9: Contract Formulas — full reference (bottom of tab) */}
            {tariff_formulas.length > 0 && (
              <CollapsibleSection title={`Contract Formulas — Full Reference (${tariff_formulas.length})`}>
                <p className="text-xs text-slate-400 mb-3">All extracted pricing formulas for this project. These are the source of truth for the billing engine.</p>
                <div className="space-y-3">
                  {tariff_formulas.map((tf) => (
                    <FormulaCard key={tf.id} formula={tf} />
                  ))}
                </div>
              </CollapsibleSection>
            )}
          </div>
        )
      })}

    </div>
  )
}
