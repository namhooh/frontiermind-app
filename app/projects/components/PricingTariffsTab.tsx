'use client'

import { useState, useMemo, Fragment } from 'react'
import { ChevronRight, Plus, Trash2, Loader2, Copy, Upload, Link2, CheckCircle2, XCircle, Ban, AlertTriangle, Pencil, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, CardTitle, CardContent } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'
import { Button } from '@/app/components/ui/button'
import { Input } from '@/app/components/ui/input'
import { Label } from '@/app/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/app/components/ui/dialog'
import { IS_DEMO } from '@/lib/demoMode'
import type { ProjectDashboardResponse, GRPObservation, SubmissionTokenItem } from '@/lib/api/adminClient'
import { adminClient } from '@/lib/api/adminClient'
import { CollapsibleSection } from './CollapsibleSection'
import { EditableCell } from './EditableCell'
import { FieldGrid, type FieldDef } from './shared/FieldGrid'
import { DetailField } from './shared/DetailField'
import { EmptyState } from './shared/EmptyState'
import { str, hasAnyValue, formatEscalationRules, groupProductsWithTariffs } from './shared/helpers'

type R = Record<string, unknown>

/** Format a billing_month date (e.g. "2026-02-01") into "Feb 2026". */
function formatBillingMonth(v: unknown): string {
  if (v == null) return ''
  const d = new Date(String(v))
  if (isNaN(d.getTime())) return String(v)
  return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

// ---------------------------------------------------------------------------
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

const TARIFF_COMPONENTS_TO_ADJUST_OPTS = [
  { value: 'Solar Tariff', label: 'Solar Tariff' },
  { value: 'Floor Tariff', label: 'Floor Tariff' },
  { value: 'Ceiling Tariff', label: 'Ceiling Tariff' },
  { value: 'Solar Tariff + Floor Tariff', label: 'Solar Tariff + Floor Tariff' },
  { value: 'Solar Tariff + Ceiling Tariff', label: 'Solar Tariff + Ceiling Tariff' },
  { value: 'Solar Tariff + Floor Tariff + Ceiling Tariff', label: 'Solar Tariff + Floor Tariff + Ceiling Tariff' },
]

/** Normalize legacy "Tarrif" misspellings to "Tariff" so stored values match dropdown options. */
function normalizeTariffComponent(v: unknown): string | undefined {
  if (v == null) return undefined
  return String(v).replace(/Tarrif/g, 'Tariff')
}

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
  const isRebased = String(t.escalation_type_code ?? '') === 'REBASED_MARKET_PRICE'
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
          [`Effective Rate${baseCurrency || ' (USD)'}${monthSuffix}`, effectiveUsd != null ? Number(effectiveUsd.toFixed(6)) : null] as FieldDef,
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

const NON_ENERGY_TARIFF_CODES = new Set(['EQUIPMENT_RENTAL_LEASE', 'BESS_LEASE', 'LOAN'])

function isNonEnergyTariff(t: R): boolean {
  return NON_ENERGY_TARIFF_CODES.has(String(t.tariff_type_code ?? '').toUpperCase())
}

function NonEnergyTariffPanel({ t, pid, rate_periods, monthly_rates, onSaved, editMode, tariffTypeOpts, escalationTypeOpts }: {
  t: R; pid: number; rate_periods: R[]; monthly_rates: R[]
  onSaved?: () => void; editMode?: boolean
  tariffTypeOpts: { value: number | string; label: string }[]
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

        ['Service Type', t.tariff_type_code, { fieldKey: 'tariff_type_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: tariffTypeOpts, selectValue: t.tariff_type_id }],
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

function BillingProductCard({ pw, pid, rate_periods, monthly_rates, contractLines, onSaved, editMode, isOpen, onToggle, onRemove, billingProductOpts, tariffTypeOpts, energySaleTypeOpts, escalationTypeOpts, currencyOpts, hardCurrencyCode }: {
  pw: { product: R; tariffs: R[] }; pid: number; rate_periods: R[]; monthly_rates: R[]
  contractLines: R[]
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

  // Meters associated with this billing product via contract_lines
  const productMeters = useMemo(() => {
    const bpId = bp.billing_product_id
    if (bpId == null) return []
    const seen = new Set<number>()
    const result: { meter_id: number; meter_name: string; energy_category: string }[] = []
    for (const cl of contractLines) {
      if (cl.billing_product_id === bpId && cl.meter_id != null) {
        const mid = cl.meter_id as number
        if (!seen.has(mid)) {
          seen.add(mid)
          result.push({ meter_id: mid, meter_name: String(cl.meter_name ?? `Meter ${mid}`), energy_category: String(cl.energy_category ?? '') })
        }
      }
    }
    return result
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
                    {str(t.tariff_type_name ?? t.tariff_type_code ?? 'Tariff')}
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
                      tariffTypeOpts={tariffTypeOpts} escalationTypeOpts={escalationTypeOpts}
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

          {/* Pricing Formula — shown for non-Available-Energy products */}
          {!isAvailableEnergy && (() => {
            const tariffWithFormula = pw.tariffs.find((t) => {
              const lp = (t.logic_parameters ?? {}) as R
              return lp.pricing_formula_text != null
            })
            if (!tariffWithFormula) return null
            const lp = (tariffWithFormula.logic_parameters ?? {}) as R
            return (
              <div className="mt-3 pt-3 border-t border-slate-100">
                <div className="text-xs font-medium text-slate-400 uppercase mb-2">Pricing Formula</div>
                <div className="py-1">
                  <dd className="text-sm text-slate-900">
                    {editMode && tariffWithFormula.id != null ? (
                      <EditableCell
                        value={lp.pricing_formula_text as string | null ?? null}
                        fieldKey="lp_pricing_formula_text"
                        entity="tariffs"
                        entityId={tariffWithFormula.id as number}
                        projectId={pid}
                        type="text"
                        editMode={true}
                        onSaved={onSaved}
                      />
                    ) : (
                      <span className="whitespace-pre-line">{String(lp.pricing_formula_text).split('\n').map((line, i) => {
                        const trimmed = line.trim().toLowerCase()
                        const isMono = trimmed === 'or, if higher' || trimmed === 'but not exceeding'
                        return (
                          <Fragment key={i}>
                            {i > 0 && '\n'}
                            {isMono ? <span className="font-mono">{line}</span> : line}
                          </Fragment>
                        )
                      })}</span>
                    )}
                  </dd>
                </div>
              </div>
            )
          })()}

          {/* Available Energy Formula — only shown on the Available Energy product (ENER003) */}
          {(() => {
            const productName = String(bp.product_name ?? bp.product_code ?? '')
            if (!/available/i.test(productName)) return null
            const aeTariff = pw.tariffs.find((t) => (t.logic_parameters as R)?.available_energy_method != null)
            if (!aeTariff) return null
            const lp = (aeTariff.logic_parameters ?? {}) as R
            const formula = lp.available_energy_formula as string | undefined
            const variables = lp.available_energy_variables as { symbol: string; definition: string; unit?: string }[] | undefined

            return (
              <div className="mt-3 pt-3 border-t border-slate-100">
                <div className="text-xs font-medium text-slate-400 uppercase mb-2">Available Energy Calculation</div>
                <div className="py-1">
                  <dd className="text-sm text-slate-900">
                    {editMode && aeTariff.id != null ? (
                      <EditableCell
                        value={formula ?? null}
                        fieldKey="lp_available_energy_formula"
                        entity="tariffs"
                        entityId={aeTariff.id as number}
                        projectId={pid}
                        type="text"
                        editMode={true}
                        onSaved={onSaved}
                      />
                    ) : (
                      <span className="whitespace-pre-line">{formula ?? '—'}</span>
                    )}
                  </dd>
                </div>

                {/* Variable definitions */}
                {variables && variables.length > 0 && (
                  <div className="text-xs space-y-1.5 mt-3">
                    <div className="text-slate-400 uppercase font-medium">Where:</div>
                    {variables.map((v, j) => (
                      <div key={j} className="flex gap-3">
                        <span className="font-mono text-slate-700 shrink-0 w-28">{v.symbol}</span>
                        <span className="text-slate-500">= {v.definition}{v.unit ? ` (${v.unit})` : ''}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// GRPSection — parameters + observations (moved from standalone GRP tab)
// ---------------------------------------------------------------------------

function grpFormatPeriod(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

function grpFormatNumber(n: number | null | undefined): string {
  if (n == null) return '-'
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function grpFormatGRP(n: number | null | undefined): string {
  if (n == null) return '-'
  return n.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 })
}

function grpStatusBadge(s: string): 'success' | 'warning' | 'destructive' {
  if (s === 'jointly_verified') return 'success'
  if (s === 'pending' || s === 'estimated') return 'warning'
  return 'destructive'
}

function grpStatusLabel(s: string): string {
  if (s === 'jointly_verified') return 'Verified'
  if (s === 'pending') return 'Pending'
  if (s === 'disputed') return 'Disputed'
  if (s === 'estimated') return 'Estimated'
  return s
}

function GRPSection({
  projectId,
  orgId,
  codDate,
  firstTariff,
  firstLp,
  baselineGrp,
  initialMonthly,
  initialAnnual,
  initialTokens,
  onSaved,
  editMode,
}: {
  projectId: number
  orgId: number
  codDate?: string | null
  firstTariff: R | undefined
  firstLp: R
  baselineGrp: R[]
  initialMonthly: GRPObservation[]
  initialAnnual: GRPObservation[]
  initialTokens: SubmissionTokenItem[]
  onSaved?: () => void
  editMode?: boolean
}) {
  const pid = projectId
  const monthlyObs = initialMonthly
  const annualObs = initialAnnual
  const existingTokens = initialTokens

  const [showTokenDialog, setShowTokenDialog] = useState(false)
  const [showUploadDialog, setShowUploadDialog] = useState(false)

  const [tokenYear, setTokenYear] = useState(1)
  const [tokenMaxUses, setTokenMaxUses] = useState(12)
  const [tokenResult, setTokenResult] = useState<{ url: string; tokenId: number } | null>(null)
  const [tokenLoading, setTokenLoading] = useState(false)

  const [uploadMonth, setUploadMonth] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadLoading, setUploadLoading] = useState(false)


  // Dispute dialog state
  const [showDisputeDialog, setShowDisputeDialog] = useState(false)
  const [disputeObsId, setDisputeObsId] = useState<number | null>(null)
  const [disputeNotes, setDisputeNotes] = useState('')
  const [disputeLoading, setDisputeLoading] = useState(false)

  // Manual entry dialog state (for disputed observation correction)
  const [showManualEntryDialog, setShowManualEntryDialog] = useState(false)
  const [manualEntryPeriod, setManualEntryPeriod] = useState('')
  const [manualEntryGrp, setManualEntryGrp] = useState('')
  const [manualEntryLoading, setManualEntryLoading] = useState(false)
  const [manualEntryIsBaseline, setManualEntryIsBaseline] = useState(false)

  // Baseline GRP: derive sorted observations, component keys, and weighted average
  const baselineData = useMemo(() => {
    if (baselineGrp.length === 0) return null

    const sorted = [...baselineGrp].sort(
      (a, b) => new Date(String(b.period_start)).getTime() - new Date(String(a.period_start)).getTime()
    )

    const componentKeysSet = new Set<string>()
    for (const obs of sorted) {
      const tc = (obs.source_metadata as R | undefined)?.tariff_components as R | undefined
      if (tc) Object.keys(tc).forEach(k => componentKeysSet.add(k))
    }
    const componentKeys = [...componentKeysSet].sort()

    // Compute weighted-average GRP across baseline months
    let totalCharges = 0
    let totalKwh = 0
    let simpleSum = 0
    let simpleCount = 0
    for (const obs of sorted) {
      const charges = obs.total_variable_charges as number | null
      const kwh = obs.total_kwh_invoiced as number | null
      const grp = obs.calculated_grp_per_kwh as number | null
      if (charges != null && kwh != null && kwh > 0) {
        totalCharges += charges
        totalKwh += kwh
      }
      if (grp != null) {
        simpleSum += grp
        simpleCount++
      }
    }
    // Prefer weighted average; fall back to simple average
    const averageGrp = totalKwh > 0 ? totalCharges / totalKwh : simpleCount > 0 ? simpleSum / simpleCount : null
    const monthCount = sorted.length

    return { observations: sorted, componentKeys, averageGrp, monthCount }
  }, [baselineGrp])

  async function handleGenerateToken() {
    setTokenLoading(true)
    setTokenResult(null)
    try {
      const res = await adminClient.generateGRPToken(orgId, {
        project_id: pid,
        operating_year: tokenYear,
        max_uses: tokenMaxUses,
      })
      setTokenResult({ url: res.submission_url, tokenId: res.token_id })
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to generate token')
    } finally {
      setTokenLoading(false)
    }
  }

  async function handleUpload() {
    if (!uploadFile || !uploadMonth) return
    setUploadLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('billing_month', uploadMonth)
      const res = await adminClient.uploadGRPInvoice(pid, orgId, formData)
      const storedLabel = res.billing_month_stored ? formatBillingMonth(res.billing_month_stored) : ''
      toast.success(`GRP extracted: ${grpFormatGRP(res.grp_per_kwh)} /kWh (${res.extraction_confidence} confidence)${storedLabel ? ` — ${storedLabel}` : ''}`)
      if (res.period_mismatch) {
        const extracted = formatBillingMonth(res.period_mismatch.extracted)
        const userProvided = formatBillingMonth(res.period_mismatch.user_provided)
        toast.warning(`Billing period corrected: invoice shows ${extracted}, you entered ${userProvided}.`)
      }
      setShowUploadDialog(false)
      setUploadFile(null)
      setUploadMonth('')
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploadLoading(false)
    }
  }

  async function handleRevokeToken(tokenId: number) {
    try {
      await adminClient.revokeToken(orgId, tokenId)
      toast.success('Token revoked')
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to revoke token')
    }
  }

  async function handleVerify(observationId: number) {
    try {
      const res = await adminClient.verifyObservation(pid, orgId, observationId, {
        verification_status: 'jointly_verified',
      })
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Verification failed')
    }
  }

  function openDisputeDialog(observationId: number) {
    setDisputeObsId(observationId)
    setDisputeNotes('')
    setShowDisputeDialog(true)
  }

  async function handleDisputeSubmit() {
    if (!disputeObsId || !disputeNotes.trim()) return
    setDisputeLoading(true)
    try {
      const res = await adminClient.verifyObservation(pid, orgId, disputeObsId, {
        verification_status: 'disputed',
        notes: disputeNotes.trim(),
      })
      toast.success(res.message)
      setShowDisputeDialog(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Dispute failed')
    } finally {
      setDisputeLoading(false)
    }
  }

  async function handleDeleteObservation(observationId: number) {
    try {
      const res = await adminClient.deleteGRPObservation(pid, orgId, observationId)
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  function openManualEntryFor(obs: { period_start: string }, isBaseline = false) {
    // Pre-fill the manual entry dialog with the observation's period
    const d = new Date(obs.period_start)
    setManualEntryPeriod(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`)
    setManualEntryGrp('')
    setManualEntryIsBaseline(isBaseline)
    setShowManualEntryDialog(true)
  }

  async function handleManualEntrySubmit() {
    if (!manualEntryPeriod || !manualEntryGrp) return
    setManualEntryLoading(true)
    try {
      const res = await adminClient.submitManualGRPRates(pid, orgId, {
        entries: [{ billing_month: manualEntryPeriod, grp_per_kwh: parseFloat(manualEntryGrp) }],
        is_baseline: manualEntryIsBaseline,
      })
      toast.success(res.message)
      setShowManualEntryDialog(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Manual entry failed')
    } finally {
      setManualEntryLoading(false)
    }
  }

  const grpActions = (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => { setTokenResult(null); setShowTokenDialog(true) }}>
        <Link2 className="h-4 w-4" /> Generate Token
      </Button>
      <Button variant="outline" size="sm" onClick={() => setShowUploadDialog(true)}>
        <Upload className="h-4 w-4" /> Upload Invoice
      </Button>
    </div>
  )

  return (<>
    <CollapsibleSection title="Grid Reference Price" actions={grpActions}>
    <div className="space-y-4">
      {/* GRP Definition */}
      {firstTariff && (
        <div className="space-y-3">
          {/* Clause Text */}
          <div className="py-1">
            <dt className="text-xs text-slate-400 mb-1">Contractual Definition</dt>
            <dd className="text-sm text-slate-900">
              {editMode ? (
                <EditableCell
                  value={firstLp.grp_clause_text as string | null ?? null}
                  fieldKey="lp_grp_clause_text"
                  entity="tariffs"
                  entityId={firstTariff.id as number}
                  projectId={pid}
                  type="text"
                  editMode={true}
                  onSaved={onSaved}
                />
              ) : (
                <span className="whitespace-pre-line">{firstLp.grp_clause_text != null ? String(firstLp.grp_clause_text) : '—'}</span>
              )}
            </dd>
          </div>

          {/* GRP Parameters */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-xs text-slate-400">Calculation Method</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <EditableCell
                    value={firstLp.grp_method as string | null ?? null}
                    fieldKey="lp_grp_method"
                    entity="tariffs"
                    entityId={firstTariff.id as number}
                    projectId={pid}
                    type="select"
                    options={[
                      { value: 'utility_variable_charges_tou', label: 'Variable Charges (ToU)' },
                      { value: 'utility_total_charges', label: 'Total Charges (excl. tax)' },
                    ]}
                    editMode={true}
                    onSaved={onSaved}
                  />
                ) : (
                  firstLp.grp_method === 'utility_variable_charges_tou' ? 'Variable Charges (ToU)'
                  : firstLp.grp_method === 'utility_total_charges' ? 'Total Charges (excl. tax)'
                  : firstLp.grp_method != null ? String(firstLp.grp_method) : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Operating Window</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.grp_time_window_start as string | null ?? null}
                      fieldKey="lp_grp_time_window_start"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="text"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-slate-400">–</span>
                    <EditableCell
                      value={firstLp.grp_time_window_end as string | null ?? null}
                      fieldKey="lp_grp_time_window_end"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="text"
                      editMode={true}
                      onSaved={onSaved}
                    />
                  </span>
                ) : (
                  firstLp.grp_time_window_start != null && firstLp.grp_time_window_end != null
                    ? `${String(firstLp.grp_time_window_start)} – ${String(firstLp.grp_time_window_end)}`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Calculation Due</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.grp_calculation_due_days as number | null ?? null}
                      fieldKey="lp_grp_calculation_due_days"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="number"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-xs text-slate-400">days after month-end</span>
                  </span>
                ) : (
                  firstLp.grp_calculation_due_days != null
                    ? `${String(firstLp.grp_calculation_due_days)} days after month-end`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Verification Deadline</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.grp_verification_deadline_days as number | null ?? null}
                      fieldKey="lp_grp_verification_deadline_days"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="number"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-xs text-slate-400">days</span>
                  </span>
                ) : (
                  firstLp.grp_verification_deadline_days != null
                    ? `${String(firstLp.grp_verification_deadline_days)} days`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Exclusions</dt>
              <dd className="mt-0.5 flex flex-wrap gap-1">
                {editMode ? (
                  <>
                    <EditableCell
                      value={firstLp.grp_exclude_vat as boolean | null ?? false}
                      fieldKey="lp_grp_exclude_vat"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'VAT ✓' : 'VAT'}
                    />
                    <EditableCell
                      value={firstLp.grp_exclude_demand_charges as boolean | null ?? false}
                      fieldKey="lp_grp_exclude_demand_charges"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'Demand ✓' : 'Demand'}
                    />
                    <EditableCell
                      value={firstLp.grp_exclude_savings_charges as boolean | null ?? false}
                      fieldKey="lp_grp_exclude_savings_charges"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'Savings ✓' : 'Savings'}
                    />
                  </>
                ) : (
                  <>
                    {Boolean(firstLp.grp_exclude_vat) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">VAT</span>}
                    {Boolean(firstLp.grp_exclude_demand_charges) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">Demand</span>}
                    {Boolean(firstLp.grp_exclude_savings_charges) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">Savings</span>}
                    {!firstLp.grp_exclude_vat && !firstLp.grp_exclude_demand_charges && !firstLp.grp_exclude_savings_charges && (
                      <span className="text-slate-500">None</span>
                    )}
                  </>
                )}
              </dd>
            </div>
          </div>
        </div>
      )}

      {/* Current GRP — weighted average of pre-COD baseline months */}
      {baselineData && baselineData.averageGrp != null && (
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-600">Current Grid Reference Price</span>
            <span className="text-sm font-bold font-mono text-slate-900 tabular-nums">{grpFormatGRP(baselineData.averageGrp)} /kWh</span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Weighted average of {baselineData.monthCount} pre-COD month{baselineData.monthCount !== 1 ? 's' : ''} (total variable charges &divide; total kWh invoiced).
          </p>
        </div>
      )}

      {/* Post-COD GRP Observations */}
      <CollapsibleSection title="Monthly GRP Observations (Post-COD)" defaultOpen={false}>
          <div className="space-y-4">
            {/* Annual GRP Cards */}
            {annualObs.map(obs => {
              const meta = obs.source_metadata?.aggregation as Record<string, unknown> | undefined
              return (
                <Card key={obs.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-semibold">Annual GRP &mdash; Operating Year {obs.operating_year}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-4 gap-4 text-sm">
                      <div><span className="text-slate-500">GRP/kWh</span><p className="font-mono font-semibold">{grpFormatGRP(obs.calculated_grp_per_kwh)}</p></div>
                      <div><span className="text-slate-500">Total Charges</span><p className="font-mono">{grpFormatNumber(obs.total_variable_charges)}</p></div>
                      <div><span className="text-slate-500">Total kWh</span><p className="font-mono">{grpFormatNumber(obs.total_kwh_invoiced)}</p></div>
                      <div><span className="text-slate-500">Months Included</span><p className="font-mono">{meta?.months_included != null ? String(meta.months_included) : '-'}</p></div>
                    </div>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge variant={grpStatusBadge(obs.verification_status)}>{grpStatusLabel(obs.verification_status)}</Badge>
                      {obs.created_at && <span className="text-xs text-slate-400">Aggregated {new Date(obs.created_at).toLocaleDateString()}</span>}
                    </div>
                  </CardContent>
                </Card>
              )
            })}

            {/* Monthly Observations Table */}
            {monthlyObs.length === 0 ? (
              <div className="text-center py-8 text-sm text-slate-400">
                No monthly GRP observations yet. Upload an invoice or generate a collection token to get started.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium">Period</th>
                      <th className="text-right px-4 py-2.5 font-medium">GRP/kWh</th>
                      <th className="text-right px-4 py-2.5 font-medium">Variable Charges</th>
                      <th className="text-right px-4 py-2.5 font-medium">kWh Invoiced</th>
                      <th className="text-right px-4 py-2.5 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[...monthlyObs].sort((a, b) => new Date(b.period_start).getTime() - new Date(a.period_start).getTime()).map(obs => {
                      const verificationLog = (obs.source_metadata?.verification_log as Array<{ status: string; notes: string; timestamp: string }>) ?? []
                      const lastDispute = verificationLog.filter(l => l.status === 'disputed').at(-1)
                      const isDisputed = obs.verification_status === 'disputed'
                      return (
                        <Fragment key={obs.id}>
                          <tr className={`hover:bg-slate-50${isDisputed ? ' bg-red-50/50' : ''}`}>
                            <td className="px-4 py-2.5">{grpFormatPeriod(obs.period_start)}</td>
                            <td
                              className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}${editMode && !isDisputed ? ' cursor-pointer rounded bg-amber-50 hover:bg-amber-100 transition-colors' : ''}`}
                              onClick={editMode && !isDisputed ? () => openManualEntryFor(obs) : undefined}
                              title={editMode && !isDisputed ? 'Click to edit' : undefined}
                            >{grpFormatGRP(obs.calculated_grp_per_kwh)}</td>
                            <td className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}`}>{grpFormatNumber(obs.total_variable_charges)}</td>
                            <td className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}`}>{grpFormatNumber(obs.total_kwh_invoiced)}</td>
                            <td className="px-4 py-2.5 text-right">
                              {obs.verification_status === 'pending' && (
                                <div className="flex items-center justify-end gap-1">
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-green-700 hover:text-green-800" onClick={() => handleVerify(obs.id)}>
                                    <CheckCircle2 className="h-3.5 w-3.5" /> Verify
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => openDisputeDialog(obs.id)}>
                                    <XCircle className="h-3.5 w-3.5" /> Dispute
                                  </Button>
                                </div>
                              )}
                              {isDisputed && (
                                <div className="flex items-center justify-end gap-1">
                                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => {
                                    const token = existingTokens.find(t => t.submission_token_status === 'active')
                                    if (token?.submission_url) {
                                      navigator.clipboard.writeText(token.submission_url)
                                      toast.success('Collection URL copied — send to counterparty to re-upload')
                                    } else {
                                      toast.info('No active collection token. Generate one first.')
                                      setShowTokenDialog(true)
                                    }
                                  }}>
                                    <RotateCcw className="h-3.5 w-3.5" /> Re-upload
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openManualEntryFor(obs)}>
                                    <Pencil className="h-3.5 w-3.5" /> Manual
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => handleDeleteObservation(obs.id)}>
                                    <Trash2 className="h-3.5 w-3.5" /> Delete
                                  </Button>
                                </div>
                              )}
                            </td>
                          </tr>
                          {isDisputed && lastDispute && (
                            <tr className="bg-red-50/30">
                              <td colSpan={5} className="px-4 py-2">
                                <div className="flex items-start gap-2 text-xs">
                                  <AlertTriangle className="h-3.5 w-3.5 text-red-500 mt-0.5 shrink-0" />
                                  <div>
                                    <span className="font-medium text-red-700">Disputed</span>
                                    <span className="text-slate-600 ml-1">— {lastDispute.notes}</span>
                                    <span className="text-slate-400 ml-2">{new Date(lastDispute.timestamp).toLocaleDateString()}</span>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
      </CollapsibleSection>

      {/* Baseline GRP (Pre-COD) */}
      {baselineData && (
        <CollapsibleSection title="Baseline Grid Reference Price (Pre-COD)" defaultOpen={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">Period</th>
                  <th className="text-right px-4 py-2.5 font-medium">GRP/kWh</th>
                  {baselineData.componentKeys.map(key => (
                    <th key={key} className="text-right px-4 py-2.5 font-medium capitalize">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {baselineData.observations.map(obs => (
                  <tr key={obs.id as number} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5">{grpFormatPeriod(String(obs.period_start))}</td>
                    <td
                      className={`px-4 py-2.5 text-right font-mono font-medium${editMode ? ' cursor-pointer rounded bg-amber-50 hover:bg-amber-100 transition-colors' : ''}`}
                      onClick={editMode ? () => openManualEntryFor({ period_start: String(obs.period_start) }, true) : undefined}
                      title={editMode ? 'Click to edit' : undefined}
                    >{grpFormatGRP(obs.calculated_grp_per_kwh as number | null)}</td>
                    {baselineData.componentKeys.map(key => {
                      const tc = (obs.source_metadata as R | undefined)?.tariff_components as Record<string, number> | undefined
                      return (
                        <td key={key} className="px-4 py-2.5 text-right font-mono tabular-nums">
                          {tc?.[key] != null ? grpFormatGRP(tc[key]) : '-'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

    </div>
    </CollapsibleSection>

      {/* Generate Token Dialog — outside CollapsibleSection so it renders even when collapsed */}
      <Dialog open={showTokenDialog} onOpenChange={setShowTokenDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>GRP Collection Tokens</DialogTitle>
            <DialogDescription>Create a reusable link for the counterparty to upload utility invoices.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="grpTokenYear">Operating Year</Label>
              <Input id="grpTokenYear" type="number" min={1} value={tokenYear} onChange={e => setTokenYear(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="grpTokenMaxUses">Max Uploads</Label>
              <Input id="grpTokenMaxUses" type="number" min={1} max={24} value={tokenMaxUses} onChange={e => setTokenMaxUses(Number(e.target.value))} />
            </div>
            {tokenResult && (
              <div className="rounded-md border border-green-200 bg-green-50 p-3 space-y-2">
                <p className="text-xs text-green-700 font-medium">Token generated successfully</p>
                <div className="flex items-center gap-2">
                  <Input readOnly value={tokenResult.url} className="text-xs font-mono" />
                  <Button variant="outline" size="icon" className="shrink-0" onClick={() => { navigator.clipboard.writeText(tokenResult.url); toast.success('URL copied to clipboard') }}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
            <Button className="w-full" disabled={tokenLoading} onClick={handleGenerateToken}>
              {tokenLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {tokenResult ? 'Regenerate' : 'Generate Token'}
            </Button>

            {/* Existing Tokens */}
            {existingTokens.length > 0 && (
              <>
                <div className="border-t border-slate-200 pt-4">
                  <div className="text-xs font-medium text-slate-500 uppercase mb-2">Existing Tokens</div>
                  <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {existingTokens.map((tk) => {
                      const isActive = tk.submission_token_status === 'active'
                      const isExpired = tk.submission_token_status === 'expired' || (tk.expires_at && new Date(tk.expires_at) < new Date())
                      const isUsed = tk.submission_token_status === 'used'
                      const isRevoked = tk.submission_token_status === 'revoked'
                      const statusVariant: 'success' | 'warning' | 'destructive' = isActive ? 'success' : isUsed ? 'warning' : 'destructive'
                      const statusLabel = isActive ? 'Active' : isUsed ? 'Used' : isRevoked ? 'Revoked' : isExpired ? 'Expired' : tk.submission_token_status
                      const tokenStr = tk.submission_url ? (() => { try { return new URL(tk.submission_url).pathname.split('/').pop() ?? '' } catch { return '' } })() : ''
                      return (
                        <div key={tk.id} className="px-3 py-2.5 space-y-1.5">
                          <div className="flex items-center gap-2">
                            <Badge variant={statusVariant}>{statusLabel}</Badge>
                            <span className="text-xs text-slate-500 tabular-nums">{tk.use_count}/{tk.max_uses} uses</span>
                            {tk.expires_at && (
                              <span className="text-xs text-slate-400">
                                Expires {new Date(tk.expires_at).toLocaleDateString()}
                              </span>
                            )}
                            {isActive && !IS_DEMO && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="ml-auto h-6 text-xs text-red-600 hover:text-red-700 px-2"
                                onClick={() => handleRevokeToken(tk.id)}
                              >
                                <Ban className="h-3 w-3" /> Revoke
                              </Button>
                            )}
                          </div>
                          {tokenStr && (
                            <div className="flex items-center gap-1.5">
                              <code className="text-xs font-mono text-slate-500 truncate max-w-[180px]">{tokenStr}</code>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-xs px-1.5"
                                onClick={() => {
                                  navigator.clipboard.writeText(tokenStr)
                                  toast.success('Token copied')
                                }}
                              >
                                <Copy className="h-3 w-3" /> Token
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-xs px-1.5"
                                onClick={() => {
                                  navigator.clipboard.writeText(tk.submission_url!)
                                  toast.success('URL copied')
                                }}
                              >
                                <Link2 className="h-3 w-3" /> URL
                              </Button>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Upload Invoice Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Utility Invoice</DialogTitle>
            <DialogDescription>Upload a PDF or image of a utility invoice for GRP extraction via OCR.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="grpBillingMonth">Billing Month</Label>
              <Input id="grpBillingMonth" type="month" value={uploadMonth} onChange={e => setUploadMonth(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="grpInvoiceFile">Invoice File</Label>
              <Input id="grpInvoiceFile" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={e => setUploadFile(e.target.files?.[0] ?? null)} />
            </div>
            <Button className="w-full" disabled={uploadLoading || !uploadFile || !uploadMonth} onClick={handleUpload}>
              {uploadLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {uploadLoading ? 'Extracting...' : 'Upload & Extract'}
            </Button>
            {uploadLoading && <p className="text-xs text-slate-400 text-center">OCR extraction may take 20-30 seconds...</p>}
          </div>
        </DialogContent>
      </Dialog>

      {/* Dispute Dialog */}
      <Dialog open={showDisputeDialog} onOpenChange={setShowDisputeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dispute GRP Observation</DialogTitle>
            <DialogDescription>Provide a reason for disputing this observation. The disputed value will be excluded from annual GRP aggregation.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="disputeNotes">Reason for Dispute *</Label>
              <textarea
                id="disputeNotes"
                className="flex min-h-[80px] w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2"
                placeholder="e.g., GRP value extracted incorrectly — 209.5 vs expected ~2.0"
                value={disputeNotes}
                onChange={e => setDisputeNotes(e.target.value)}
              />
            </div>
            <Button
              className="w-full"
              variant="destructive"
              disabled={disputeLoading || !disputeNotes.trim()}
              onClick={handleDisputeSubmit}
            >
              {disputeLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Submit Dispute
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Manual Entry Dialog (for correcting disputed observation) */}
      <Dialog open={showManualEntryDialog} onOpenChange={setShowManualEntryDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enter Corrected GRP</DialogTitle>
            <DialogDescription>Manually enter the corrected GRP rate for this period. This will replace the disputed observation with an estimated value.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="manualEntryPeriod">Billing Month</Label>
              <Input id="manualEntryPeriod" type="month" value={manualEntryPeriod} onChange={e => setManualEntryPeriod(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manualEntryGrp">GRP per kWh</Label>
              <Input id="manualEntryGrp" type="number" step="0.0001" min="0" placeholder="e.g., 2.0350" value={manualEntryGrp} onChange={e => setManualEntryGrp(e.target.value)} />
            </div>
            <Button
              className="w-full"
              disabled={manualEntryLoading || !manualEntryPeriod || !manualEntryGrp}
              onClick={handleManualEntrySubmit}
            >
              {manualEntryLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Corrected Value
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
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
  grpMonthly?: GRPObservation[]
  grpAnnual?: GRPObservation[]
  grpTokens?: SubmissionTokenItem[]
}

export function PricingTariffsTab({ data, onSaved, editMode, projectId, grpMonthly = [], grpAnnual = [], grpTokens = [] }: PricingTariffsTabProps) {
  const { contracts, tariffs, billing_products, rate_periods, monthly_rates, tariff_rates, exchange_rates, lookups } = data
  const pid = data.project.id as number

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

  const toOpts = (items: { id: number; code?: string; name: string }[]) =>
    (items ?? []).map((t) => ({ value: t.id, label: t.name }))
  const currencyOpts = toOpts(lookups?.currencies)
  const HIDDEN_TARIFF_CODES = new Set(['ENERGY', 'CAPACITY'])
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
    const countryToCurrency: Record<string, string> = {
      'Ghana': 'GHS', 'Kenya': 'KES', 'Nigeria': 'NGN', 'Sierra Leone': 'SLE',
      'Egypt': 'EGP', 'Madagascar': 'MGA', 'Rwanda': 'RWF', 'Somalia': 'SOS',
      'Mozambique': 'MZN', 'Zimbabwe': 'ZWL', 'DRC': 'CDF',
    }
    const country = data.project.country as string | undefined
    return country ? countryToCurrency[country] : undefined
  })()

  // Top-level first tariff/LP for GRP section (independent of contracts loop)
  const grpFirstTariff = (() => {
    const c = contracts[0]
    if (!c) return undefined
    const ct = tariffs.filter((t) => t.contract_id === c.id)
    return (ct.find((t) => t.is_current === true) ?? ct[0]) as R | undefined
  })()
  const grpFirstLp = (grpFirstTariff?.logic_parameters ?? {}) as R

  return (
    <div className="space-y-4">
      {contracts.length === 0 && (<>
        <EmptyState>No contracts found</EmptyState>

        {/* GRP section renders even without contracts */}
        <GRPSection
          projectId={pid}
          orgId={data.project.organization_id as number}
          codDate={data.project.cod_date as string | null | undefined}
          firstTariff={grpFirstTariff}
          firstLp={grpFirstLp}
          baselineGrp={data.baseline_grp ?? []}
          initialMonthly={grpMonthly}
          initialAnnual={grpAnnual}
          initialTokens={grpTokens}
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
              const isRebasedTariffHeader = String(t.escalation_type_code ?? '') === 'REBASED_MARKET_PRICE'
              const tariffMonthlyRates = isRebasedTariffHeader
                ? (monthly_rates ?? [])
                    .filter((mr: R) => mr.clause_tariff_id === t.id)
                    .sort((a: R, b: R) => String(b.billing_month ?? '').localeCompare(String(a.billing_month ?? '')))
                : []
              const latestMonthLabel = tariffMonthlyRates.length > 0
                ? formatBillingMonth(tariffMonthlyRates[0].billing_month)
                : null
              return (
                <div key={i} className={i > 0 ? 'pt-5 border-t border-slate-200' : ''}>
                  {/* Tariff summary line */}
                  <div className="flex items-baseline gap-3 mb-2">
                    <span className="text-sm font-medium text-slate-800">{str(t.name ?? t.tariff_type_name)}</span>
                    <span className="text-xs text-slate-400">
                      {[t.tariff_type_code, t.escalation_type_code].filter(Boolean).join(' / ')}
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
                    const isRebasedTariff = String(t.escalation_type_code ?? '') === 'REBASED_MARKET_PRICE'
                    const tLp = (t.logic_parameters ?? {}) as R
                    const discPctDisplay = tLp.discount_pct != null ? `${Number((Number(tLp.discount_pct) * 100).toFixed(2)).toString().replace(/\.?0+$/, '')}%` : ''
                    const basisOverride = isRebasedTariff && discPctDisplay
                      ? `GRP per kWh less ${discPctDisplay} solar discount, bounded by floor/ceiling (USD), converted at monthly FX rate`
                      : null
                    return (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-slate-200">
                            {isRebasedTariff && <th className="w-6" />}
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Year</th>
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Period</th>
                            <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Rate</th>
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Currency</th>
                            <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500 max-w-[160px]">Basis</th>
                            <th className="text-center px-3 py-1.5 text-xs font-medium text-slate-500">Current</th>
                          </tr>
                        </thead>
                        <tbody>
                          {periods.map((rp, j) => {
                            const periodMonthlyRates = isRebasedTariff
                              ? (monthly_rates ?? [])
                                  .filter((mr: R) => mr.clause_tariff_id === rp.clause_tariff_id && mr.contract_year === rp.contract_year)
                                  .sort((a: R, b: R) => String(b.billing_month ?? '').localeCompare(String(a.billing_month ?? '')))
                              : []
                            const isExpanded = expandedPeriods.has(rp.id)
                            return (
                              <Fragment key={j}>
                              <tr
                                className={`border-b border-slate-50 ${rp.is_current ? 'bg-blue-50/40' : 'hover:bg-slate-50'} ${isRebasedTariff && periodMonthlyRates.length > 0 ? 'cursor-pointer' : ''}`}
                                onClick={isRebasedTariff && periodMonthlyRates.length > 0 ? () => togglePeriod(rp.id) : undefined}
                              >
                                {isRebasedTariff && (
                                  <td className="pl-2 py-1.5 w-6">
                                    {periodMonthlyRates.length > 0 && (
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
                                  {isRebasedTariff && periodMonthlyRates.length > 0
                                    ? `As of ${formatBillingMonth(periodMonthlyRates[0].billing_month)}`
                                    : `${str(rp.period_start)}${rp.period_end ? ` — ${str(rp.period_end)}` : ''}`}
                                </td>
                                <td className="px-3 py-1.5 text-right text-slate-700 tabular-nums font-medium">
                                  {editMode && rp.id != null ? (
                                    <EditableCell value={rp.effective_rate_contract_ccy} fieldKey="effective_rate_contract_ccy" entity="rate-periods" entityId={rp.id as number} type="number" editMode onSaved={onSaved} />
                                  ) : (() => {
                                    if (isRebasedTariff && periodMonthlyRates.length > 0) {
                                      const latestMr = periodMonthlyRates[0]
                                      const mrFx = latestMr.exchange_rate != null ? Number(latestMr.exchange_rate) : null
                                      const mrLocal = latestMr.effective_tariff_local != null ? Number(latestMr.effective_tariff_local) : null
                                      const latestUsd = mrLocal != null && mrFx ? mrLocal / mrFx : null
                                      return latestUsd != null ? (
                                        <span title={`Latest: ${formatBillingMonth(latestMr.billing_month)}`}>
                                          {latestUsd.toFixed(6)}
                                        </span>
                                      ) : str(rp.effective_rate_contract_ccy)
                                    }
                                    return str(rp.effective_rate_contract_ccy)
                                  })()}
                                </td>
                                <td className="px-3 py-1.5 text-slate-500 text-xs">{isRebasedTariff && periodMonthlyRates.length > 0 ? str(hardCurrencyCode ?? rp.currency_code) : str(rp.currency_code)}</td>
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
                                  <td className="px-3 py-1 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate (GHS)</td>
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
                                      {str(mr.effective_tariff_local)}
                                    </td>
                                    <td className="px-3 py-1 text-xs text-slate-500 tabular-nums">
                                      {mrFx != null ? mrFx.toFixed(2) : '—'}
                                    </td>
                                    <td className="px-3 py-1 text-xs text-slate-500 tabular-nums">
                                      {mrUsd != null ? mrUsd.toFixed(6) : '—'}
                                    </td>
                                    <td className="px-3 py-1 text-center">
                                      {mr.is_current === true && <span className="inline-block w-2 h-2 rounded-full bg-blue-400" title="Current" />}
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
                    )
                  })()}
                </div>
              )
            })}
          </div>
        )}
      </CollapsibleSection>

      {/* Exchange Rates — filtered to project's currency */}
      {(() => {
        const filteredRates = projectFxCurrency
          ? (exchange_rates ?? []).filter((er) => er.currency_code === projectFxCurrency)
          : (exchange_rates ?? [])
        return filteredRates.length > 0 && (
        <CollapsibleSection title={`Exchange Rates${projectFxCurrency ? ` (USD → ${projectFxCurrency})` : ''}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Date</th>
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Currency</th>
                  <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">Rate (USD → Local)</th>
                  <th className="text-right px-3 py-1.5 text-xs font-medium text-slate-500">MoM Change</th>
                  <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Source</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const sorted = [...filteredRates].sort(
                    (a, b) => String(b.rate_date ?? '').localeCompare(String(a.rate_date ?? ''))
                  )
                  return sorted.map((er, idx) => {
                    const rate = Number(er.rate)
                    const prevRate = idx < sorted.length - 1 ? Number(sorted[idx + 1].rate) : null
                    const momChange = prevRate != null && prevRate !== 0
                      ? ((rate - prevRate) / prevRate) * 100
                      : null
                    return (
                      <tr key={er.id as number} className={`border-b border-slate-50 ${idx === 0 ? 'bg-blue-50/40' : 'hover:bg-slate-50'}`}>
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
                  })
                })()}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )})()}

      {contracts.map((c, i) => {
        const cid = c.id as number
        const contractTariffs = tariffs.filter((t) => t.contract_id === c.id)
        const currentTariff = contractTariffs.find((t) => t.is_current === true) as R | undefined
        const firstTariff = (currentTariff ?? contractTariffs[0]) as R | undefined
        const firstLp = (firstTariff?.logic_parameters ?? {}) as R
        const energySalesTariff = contractTariffs.find(
          (t) => String(t.tariff_type_code).toUpperCase() === 'ENERGY_SALES',
        )
        const { matched, unmatched } = groupProductsWithTariffs(billing_products, tariffs, c.id)

        // Collect distinct tariff type names for tag badges
        const distinctTariffTypes = [
          ...new Set(contractTariffs.map((t) => t.tariff_type_name).filter(Boolean)),
        ] as string[]

        return (
          <div key={i}>
            {/* Section 1: Billing Information */}
            <CollapsibleSection title="Billing Information">
              <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                ...(firstTariff && firstLp.billing_frequency != null
                  ? [['Billing Frequency', firstLp.billing_frequency, { fieldKey: 'lp_billing_frequency', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: BILLING_FREQUENCY_OPTS, selectValue: firstLp.billing_frequency }] as FieldDef]
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

            {/* Section 3: Service & Product Classification */}
            <CollapsibleSection title="Service & Product Classification">
              <div className="space-y-3">
                {/* Tariff type badges / editable dropdowns */}
                {editMode ? (
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={
                    contractTariffs.map((t) => [
                      `Contract Service/Product Type${contractTariffs.length > 1 ? ` — ${str(t.name ?? t.tariff_type_name ?? 'Tariff')}` : ''}`,
                      t.tariff_type_code,
                      { fieldKey: 'tariff_type_id', entity: 'tariffs' as const, entityId: t.id as number, projectId: pid, type: 'select' as const, options: tariffTypeOpts, selectValue: t.tariff_type_id },
                    ] as FieldDef)
                  } />
                ) : (
                  <div className="flex flex-col py-1">
                    <dt className="text-xs text-slate-400">Contract Service/Product Type</dt>
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

                {/* Energy Sales Tariff Type */}
                {energySalesTariff && (
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                    ['Energy Sales Tariff Type', energySalesTariff.energy_sale_type_name, { fieldKey: 'energy_sale_type_id', entity: 'tariffs' as const, entityId: energySalesTariff.id as number, projectId: pid, type: 'select' as const, options: energySaleTypeOpts, selectValue: energySalesTariff.energy_sale_type_id }],
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
                              {str(t.tariff_type_name ?? t.tariff_type_code ?? 'Tariff')}
                            </div>
                            {isNonEnergyTariff(t) && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">Non-Energy</span>
                            )}
                          </div>
                          {isNonEnergyTariff(t) ? (
                            <NonEnergyTariffPanel
                              t={t} pid={pid} rate_periods={rate_periods} monthly_rates={monthly_rates}
                              onSaved={onSaved} editMode={editMode}
                              tariffTypeOpts={tariffTypeOpts} escalationTypeOpts={escalationTypeOpts}
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
              {(firstTariff.escalation_type_code != null || hasAnyValue(firstLp, ['escalation_frequency', 'escalation_start_date', 'tariff_components_to_adjust', 'escalation_rules'])) && (
                <CollapsibleSection title="Escalation Rules">
                  <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                    ['Price Adjustment Type', firstTariff.escalation_type_code, { fieldKey: 'escalation_type_id', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: escalationTypeOpts, selectValue: firstTariff.escalation_type_id }],
                    ...(firstLp.escalation_frequency != null ? [['Escalation Frequency', firstLp.escalation_frequency, { fieldKey: 'lp_escalation_frequency', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: ESCALATION_FREQUENCY_OPTS, selectValue: firstLp.escalation_frequency }] as FieldDef] : []),
                    ...(firstLp.escalation_start_date != null ? [['Escalation Start Date', firstLp.escalation_start_date, { fieldKey: 'lp_escalation_start_date', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'text' as const }] as FieldDef] : []),

                    ...(firstLp.tariff_components_to_adjust != null ? [['Energy Sales Tariff to Adjust', normalizeTariffComponent(firstLp.tariff_components_to_adjust), { fieldKey: 'lp_tariff_components_to_adjust', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'select' as const, options: TARIFF_COMPONENTS_TO_ADJUST_OPTS, selectValue: normalizeTariffComponent(firstLp.tariff_components_to_adjust) }] as FieldDef] : []),

                  ]} />
                  <EscalationRulesTable rules={firstLp.escalation_rules} logicParameters={firstLp} />
                  <RateBoundsSchedule
                    logicParameters={firstLp}
                    contractTermYears={Number(c.contract_term_years ?? 0)}
                    codDate={data.project.cod_date != null ? String(data.project.cod_date) : null}
                  />
                </CollapsibleSection>
              )}
            </>)}

            {/* Section 5: Grid Reference Price — right after Escalation Rules */}
            <GRPSection
              projectId={pid}
              orgId={data.project.organization_id as number}
              codDate={data.project.cod_date as string | null | undefined}
              firstTariff={firstTariff}
              firstLp={firstLp}
              baselineGrp={data.baseline_grp ?? []}
              initialMonthly={grpMonthly}
              initialAnnual={grpAnnual}
              initialTokens={grpTokens}
              onSaved={onSaved}
              editMode={editMode}
            />

            {/* Available Energy — now displayed inside the ENER003 BillingProductCard */}

            {firstTariff != null && (<>
              {/* Section 7: Shortfall & Excused Events */}
              {hasAnyValue(firstLp, ['shortfall_formula_type', 'shortfall_formula_text', 'shortfall_formula_variables']) && (
                <CollapsibleSection title="Shortfall Formula">
                  {firstLp.shortfall_formula_type != null && (
                    <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
                      ['Shortfall Formula', firstLp.shortfall_formula_type, { fieldKey: 'lp_shortfall_formula_type', entity: 'tariffs' as const, entityId: firstTariff.id as number, projectId: pid, type: 'text' as const }],
                    ]} />
                  )}
                  {firstLp.shortfall_formula_text != null && (
                    <div className="py-1">
                      <dd className="text-sm text-slate-900">
                        {editMode && firstTariff ? (
                          <EditableCell
                            value={firstLp.shortfall_formula_text as string | null ?? null}
                            fieldKey="lp_shortfall_formula_text"
                            entity="tariffs"
                            entityId={firstTariff.id as number}
                            projectId={pid}
                            type="text"
                            editMode={true}
                            onSaved={onSaved}
                          />
                        ) : (
                          <span className="whitespace-pre-line">{String(firstLp.shortfall_formula_text)}</span>
                        )}
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
                </CollapsibleSection>
              )}
            </>)}

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
                                {str(t.tariff_type_name ?? t.tariff_type_code)}
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
          </div>
        )
      })}

    </div>
  )
}
