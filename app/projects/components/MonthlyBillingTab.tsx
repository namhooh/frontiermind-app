'use client'

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Upload, Download, Plus, Loader2, Check, X, ChevronDown, ChevronRight, Maximize2, Minimize2 } from 'lucide-react'
import { IS_DEMO } from '@/lib/demoMode'
import { toast } from 'sonner'
import {
  adminClient,
  type MonthlyBillingResponse,
  type MonthlyBillingProductColumn,
  type MeterBillingResponse,
  type MeterBillingMonth,
  type MeterReadingDetail,
  type ExpectedInvoiceSummary,
  type ExpectedInvoiceLineItem,
} from '@/lib/api/adminClient'
import { formatMonth, fmtNum, fmtCurrency, varianceClass } from '@/app/projects/utils/formatters'

// ---------------------------------------------------------------------------
// InlineNumberEdit — click-to-edit number cell for existing rows
// ---------------------------------------------------------------------------

function InlineNumberEdit({
  value,
  billingMonth,
  field,
  projectId,
  onSaved,
}: {
  value: number | null
  billingMonth: string
  field: 'actual_kwh' | 'forecast_kwh'
  projectId: number
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const startEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setDraft(value != null ? String(value) : '')
    setEditing(true)
  }, [value])

  const handleSave = useCallback(async () => {
    const num = draft.trim() === '' ? undefined : parseFloat(draft)
    // Skip save if unchanged
    if (num === value || (num === undefined && value == null)) {
      setEditing(false)
      return
    }
    if (IS_DEMO) {
      toast('Demo mode — changes are not saved', { duration: 3000 })
      setEditing(false)
      return
    }
    setSaving(true)
    setEditing(false)
    try {
      await adminClient.addManualBillingEntry(projectId, {
        billing_month: billingMonth,
        [field]: num,
      })
      toast('Field updated', { duration: 3000 })
      onSaved()
    } catch {
      toast.error('Save failed')
    } finally {
      setSaving(false)
    }
  }, [draft, value, projectId, billingMonth, field, onSaved])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); handleSave() }
    else if (e.key === 'Escape') setEditing(false)
  }, [handleSave])

  if (saving) {
    return <Loader2 className="h-3 w-3 animate-spin text-slate-400 ml-auto" />
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        step="any"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => handleSave()}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="w-24 text-xs text-right border border-blue-300 rounded px-1.5 py-0.5 outline-none ring-1 ring-blue-200 focus:ring-blue-400"
      />
    )
  }

  return (
    <span
      onClick={startEdit}
      className="cursor-pointer rounded px-1 -mx-1 bg-amber-50 hover:bg-amber-100 transition-colors"
      title="Click to edit"
    >
      {fmtNum(value)}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Shorten long billing product names for column headers */
function shortProductLabel(name: string): string {
  const lower = name.toLowerCase()
  if (lower.includes('emetered') || (lower.includes('metered') && !lower.includes('available'))) return 'E_Met'
  if (lower.includes('test') || lower.includes('early operating')) return 'E_Test'
  if (lower.includes('eavailable') || lower.includes('available')) return 'E_Avail'
  return name
}

/** Determine the energy category of a billing product for per-meter mapping */
function productEnergyCategory(p: MonthlyBillingProductColumn): 'metered' | 'available' | 'test' | null {
  // Prefer API-driven energy_category when available
  if (p.energy_category) {
    const cat = p.energy_category as 'metered' | 'available' | 'test'
    if (cat === 'metered' || cat === 'available' || cat === 'test') return cat
  }
  // Fallback: name/code heuristic
  const name = (p.product_name ?? '').toLowerCase()
  if (name.includes('eavailable') || name.includes('available')) return 'available'
  if (name.includes('test') || name.includes('early operating')) return 'test'
  if (name.includes('emetered') || (name.includes('metered') && !name.includes('available'))) return 'metered'
  return null
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MonthlyBillingTabProps {
  projectId?: number
  editMode?: boolean
}

// ---------------------------------------------------------------------------
// Unified billing row — merged from both API responses
// ---------------------------------------------------------------------------

interface UnifiedBillingRow {
  billing_month: string
  // From MonthlyBillingResponse
  actual_kwh: number | null
  forecast_kwh: number | null
  variance_pct: number | null
  product_amounts: Record<string, number | null>
  product_amounts_hard_ccy: Record<string, number | null>
  product_rates: Record<string, number | null>
  product_rates_hard_ccy: Record<string, number | null>
  total_billing_amount: number | null
  total_billing_amount_hard_ccy: number | null
  // From MeterBillingResponse
  meter_readings: MeterReadingDetail[]
  expected_invoice: ExpectedInvoiceSummary | null
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MonthlyBillingTab({ projectId, editMode }: MonthlyBillingTabProps) {
  const [data, setData] = useState<MonthlyBillingResponse | null>(null)
  const [meterData, setMeterData] = useState<MeterBillingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // Fullscreen state
  const [fullscreen, setFullscreen] = useState(false)

  // Import state
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)

  // Manual entry state
  const [showAddRow, setShowAddRow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState<{ billing_month: string; actual_kwh: string; forecast_kwh: string }>({
    billing_month: '',
    actual_kwh: '',
    forecast_kwh: '',
  })

  // Fetch data
  const fetchData = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const [resp, meterResp] = await Promise.all([
        adminClient.getMonthlyBilling(projectId),
        adminClient.getMeterBilling(projectId).catch(() => null),
      ])
      setData(resp)
      setMeterData(meterResp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load billing data')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Close add row when edit mode toggled off
  useEffect(() => {
    if (!editMode) setShowAddRow(false)
  }, [editMode])

  // Import handler
  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !projectId) return
    setImporting(true)
    try {
      const resp = await adminClient.importMonthlyBilling(projectId, file)
      toast.success(resp.message || `Imported ${resp.imported_rows} rows`)
      await fetchData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [projectId, fetchData])

  // Export handler
  const handleExport = useCallback(async () => {
    if (!projectId) return
    try {
      const blob = await adminClient.exportMonthlyBilling(projectId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `monthly_billing_project_${projectId}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    }
  }, [projectId])

  // Manual entry save
  const handleSaveManual = useCallback(async () => {
    if (!projectId) return
    if (IS_DEMO) { toast('Demo mode — changes are not saved', { duration: 3000 }); setShowAddRow(false); return }
    if (!draft.billing_month) {
      toast.error('Billing month is required')
      return
    }
    if (!draft.actual_kwh && !draft.forecast_kwh) {
      toast.error('At least one of actual or forecast kWh is required')
      return
    }
    setSaving(true)
    try {
      await adminClient.addManualBillingEntry(projectId, {
        billing_month: draft.billing_month,
        actual_kwh: draft.actual_kwh ? parseFloat(draft.actual_kwh) : undefined,
        forecast_kwh: draft.forecast_kwh ? parseFloat(draft.forecast_kwh) : undefined,
      })
      toast.success(`Saved ${draft.billing_month}`)
      setShowAddRow(false)
      setDraft({ billing_month: '', actual_kwh: '', forecast_kwh: '' })
      await fetchData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [projectId, draft, fetchData])

  // Toggle row expansion
  const toggleExpand = useCallback((month: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(month)) next.delete(month)
      else next.add(month)
      return next
    })
  }, [])

  // Merge monthly billing + meter billing into unified rows
  const products = data?.products ?? []
  const currency = data?.currency_code ?? null
  const hardCurrency = data?.hard_currency_code ?? meterData?.hard_currency_code ?? null
  const showHardCcy = hardCurrency != null && hardCurrency !== currency

  const unifiedRows = useMemo<UnifiedBillingRow[]>(() => {
    const rows = data?.rows ?? []
    const meterMonths = meterData?.months ?? []

    // Index meter months by billing_month
    const meterByMonth = new Map<string, MeterBillingMonth>()
    for (const mm of meterMonths) {
      meterByMonth.set(mm.billing_month, mm)
    }

    // Build unified rows from monthly billing rows
    const allMonths = new Set<string>()
    const result: UnifiedBillingRow[] = []

    for (const row of rows) {
      allMonths.add(row.billing_month)
      const mm = meterByMonth.get(row.billing_month)
      result.push({
        billing_month: row.billing_month,
        actual_kwh: row.actual_kwh,
        forecast_kwh: row.forecast_kwh,
        variance_pct: row.variance_pct,
        product_amounts: row.product_amounts,
        product_amounts_hard_ccy: row.product_amounts_hard_ccy ?? {},
        product_rates: row.product_rates,
        product_rates_hard_ccy: row.product_rates_hard_ccy ?? {},
        total_billing_amount: row.total_billing_amount,
        total_billing_amount_hard_ccy: row.total_billing_amount_hard_ccy ?? null,
        meter_readings: mm?.meter_readings ?? [],
        expected_invoice: mm?.expected_invoice ?? null,
      })
    }

    // Add any meter-only months not in monthly billing
    for (const mm of meterMonths) {
      if (!allMonths.has(mm.billing_month)) {
        result.push({
          billing_month: mm.billing_month,
          actual_kwh: mm.total_metered_kwh,
          forecast_kwh: null,
          variance_pct: null,
          product_amounts: {},
          product_amounts_hard_ccy: {},
          product_rates: {},
          product_rates_hard_ccy: {},
          total_billing_amount: mm.total_amount,
          total_billing_amount_hard_ccy: mm.total_amount_hard_ccy ?? null,
          meter_readings: mm.meter_readings,
          expected_invoice: mm.expected_invoice,
        })
      }
    }

    // Sort descending; exclude months before COD and after current month
    result.sort((a, b) => b.billing_month.localeCompare(a.billing_month))
    const currentMonth = new Date().toISOString().slice(0, 7) + '-01'
    const codMonth = data?.cod_date?.substring(0, 7)  // "YYYY-MM" or undefined
    return result.filter((r) => {
      if (r.billing_month > currentMonth) return false
      if (codMonth && r.billing_month < codMonth) return false
      return true
    })
  }, [data, meterData])

  // Group rows by calendar year (DESC)
  const yearGroups = useMemo(() => {
    const map = new Map<string, UnifiedBillingRow[]>()
    for (const row of unifiedRows) {
      const year = row.billing_month.substring(0, 4)
      if (!map.has(year)) map.set(year, [])
      map.get(year)!.push(row)
    }
    // Sort years DESC
    return [...map.entries()]
      .sort(([a], [b]) => b.localeCompare(a))
      .map(([year, rows]) => ({ year, rows }))
  }, [unifiedRows])

  // Year-group collapse state: most recent year expanded, rest collapsed
  const [collapsedYears, setCollapsedYears] = useState<Set<string>>(new Set())
  const yearGroupsInitRef = useRef(false)
  useEffect(() => {
    if (!yearGroupsInitRef.current && yearGroups.length > 0) {
      yearGroupsInitRef.current = true
      const initial = new Set<string>()
      yearGroups.slice(1).forEach(g => initial.add(g.year))
      setCollapsedYears(initial)
    }
  }, [yearGroups])

  const toggleYear = useCallback((year: string) => {
    setCollapsedYears(prev => {
      const next = new Set(prev)
      if (next.has(year)) next.delete(year)
      else next.add(year)
      return next
    })
  }, [])

  // Auto-expand the most recent (top) month on initial load
  const autoExpandedRef = useRef(false)
  useEffect(() => {
    if (!autoExpandedRef.current && unifiedRows.length > 0) {
      autoExpandedRef.current = true
      setExpanded(new Set([unifiedRows[0].billing_month]))
    }
  }, [unifiedRows])

  // Compute footer totals
  const totals = useMemo(() => {
    let actualKwh = 0
    let forecastKwh = 0
    let netDue = 0
    let netDueHard = 0
    let hasActual = false
    let hasForecast = false

    for (const row of unifiedRows) {
      if (row.actual_kwh != null) { actualKwh += row.actual_kwh; hasActual = true }
      if (row.forecast_kwh != null) { forecastKwh += row.forecast_kwh; hasForecast = true }
      // Net due: prefer invoice net_due, fallback to total_billing_amount
      if (row.expected_invoice) {
        netDue += row.expected_invoice.net_due
      } else if (row.total_billing_amount != null) {
        netDue += row.total_billing_amount
      }
      // Hard currency: prefer invoice-level FX conversion, fall back to monthly-billing
      if (row.expected_invoice?.net_due_hard_ccy != null) {
        netDueHard += row.expected_invoice.net_due_hard_ccy
      } else if (row.total_billing_amount_hard_ccy != null) {
        netDueHard += row.total_billing_amount_hard_ccy
      }
    }

    return {
      actual_kwh: hasActual ? actualKwh : null,
      forecast_kwh: hasForecast ? forecastKwh : null,
      net_due: netDue,
      net_due_hard: netDueHard,
    }
  }, [unifiedRows])

  // Determine how many product columns we have
  const productColCount = products.length
  // Total columns: expand chevron + month + actual + forecast + var% + product cols + levies + VAT + gross + W/H + net due
  const waterfallCols = 5 // levies, VAT, gross, W/H, net due
  const totalCols = 1 + 1 + 1 + 1 + 1 + productColCount + waterfallCols

  // Loading / error states
  if (!projectId) {
    return <p className="text-sm text-slate-400">Select a project first</p>
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }

  const hasData = unifiedRows.length > 0 || showAddRow

  return (
    <div className={`space-y-4 ${fullscreen ? 'fixed inset-0 z-50 bg-white overflow-auto p-6' : ''}`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-700">
            Billing
            {currency && <span className="ml-2 text-xs font-normal text-slate-400">({currency})</span>}
            {showHardCcy && <span className="text-xs font-normal text-slate-400"> / {hardCurrency}</span>}
            {data?.degradation_pct != null && (
              <>
                <span className="mx-1.5 text-slate-300">|</span>
                <span className="text-xs font-normal text-slate-400">
                  Degradation: {(data.degradation_pct * 100).toFixed(2)}%/yr
                </span>
              </>
            )}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {editMode && !IS_DEMO && (
            <button
              onClick={() => {
                setShowAddRow(true)
                setDraft({ billing_month: '', actual_kwh: '', forecast_kwh: '' })
              }}
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            >
              <Plus className="h-3 w-3" /> Add Month
            </button>
          )}
          <button
            onClick={() => setFullscreen((v) => !v)}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            title={fullscreen ? 'Exit full screen' : 'Full screen'}
          >
            {fullscreen ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </button>
          {!IS_DEMO && (
            <label className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 cursor-pointer">
              {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
              Import
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx"
                className="hidden"
                onChange={handleImport}
                disabled={importing}
              />
            </label>
          )}
          <button
            onClick={handleExport}
            disabled={unifiedRows.length === 0}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Download className="h-3 w-3" /> Export
          </button>
        </div>
      </div>

      {/* Table */}
      {!hasData ? (
        <div className="flex items-center justify-center h-32 text-sm text-slate-400">
          No billing data available. Import a file or add months manually.
        </div>
      ) : (
        <div className="overflow-x-auto border border-slate-200 rounded-lg">
          <table className="w-full text-sm">
            <thead>
              {/* Group header row */}
              <tr className="border-b border-slate-200">
                {/* Reference group */}
                <th colSpan={2} className="px-3 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 border-r-2 border-blue-200 text-center">
                  Reference
                </th>
                {/* Generation group */}
                <th colSpan={3} className="px-3 py-1.5 text-xs font-semibold text-green-700 bg-green-50 border-r-2 border-green-200 text-center">
                  Generation
                </th>
                {/* Billing group */}
                <th colSpan={productColCount + waterfallCols} className="px-3 py-1.5 text-xs font-semibold text-amber-700 bg-amber-50 text-center">
                  Billing{currency ? ` (${currency})` : ''}
                </th>
              </tr>
              {/* Column header row */}
              <tr className="bg-slate-50 border-b border-slate-200">
                {/* Reference */}
                <th className="w-6 px-1 py-2" />
                <th className="text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-blue-200">Month</th>
                {/* Generation */}
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Actual kWh</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Fcast kWh</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-green-200">Var %</th>
                {/* Product columns (shortened labels) */}
                {products.map((p) => (
                  <th key={p.product_code} className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap" title={p.product_name}>
                    {shortProductLabel(p.product_name)}
                  </th>
                ))}
                {/* Invoice waterfall */}
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Levies</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">VAT</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Gross</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">W/H</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Net Due</th>
              </tr>
            </thead>
            <tbody>
              {/* Add row (manual entry) */}
              {showAddRow && (
                <tr className="bg-blue-50/50 border-b border-slate-100">
                  <td className="px-1 py-1.5" />
                  <td className="px-3 py-1.5">
                    <input
                      type="month"
                      value={draft.billing_month}
                      onChange={(e) => setDraft((d) => ({ ...d, billing_month: e.target.value }))}
                      className="w-32 text-xs border border-slate-300 rounded px-1.5 py-1"
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="number"
                      placeholder="kWh"
                      value={draft.actual_kwh}
                      onChange={(e) => setDraft((d) => ({ ...d, actual_kwh: e.target.value }))}
                      className="w-24 text-xs text-right border border-slate-300 rounded px-1.5 py-1"
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="number"
                      placeholder="kWh"
                      value={draft.forecast_kwh}
                      onChange={(e) => setDraft((d) => ({ ...d, forecast_kwh: e.target.value }))}
                      className="w-24 text-xs text-right border border-slate-300 rounded px-1.5 py-1"
                    />
                  </td>
                  <td className="px-3 py-1.5" />
                  {products.map((p) => (
                    <td key={p.product_code} className="px-3 py-1.5" />
                  ))}
                  {/* waterfall empties */}
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={handleSaveManual}
                        disabled={saving}
                        className="p-1 rounded hover:bg-emerald-100 text-emerald-600"
                      >
                        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={() => setShowAddRow(false)}
                        className="p-1 rounded hover:bg-slate-100 text-slate-400"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              )}

              {/* Year-grouped data rows */}
              {yearGroups.map(({ year, rows: yearRows }) => {
                const isYearCollapsed = collapsedYears.has(year)
                const yearActual = yearRows.reduce((s, r) => s + (r.actual_kwh ?? 0), 0)
                const yearForecast = yearRows.reduce((s, r) => s + (r.forecast_kwh ?? 0), 0)
                const yearNetDue = yearRows.reduce((s, r) => {
                  if (r.expected_invoice) return s + r.expected_invoice.net_due
                  return s + (r.total_billing_amount ?? 0)
                }, 0)
                const yearNetDueHard = yearRows.reduce((s, r) => {
                  if (r.expected_invoice?.net_due_hard_ccy != null) return s + r.expected_invoice.net_due_hard_ccy
                  if (r.total_billing_amount_hard_ccy != null) return s + r.total_billing_amount_hard_ccy
                  return s
                }, 0)
                const hasActuals = yearRows.some(r => r.actual_kwh != null)

                return (
                  <React.Fragment key={year}>
                    {/* Year header row */}
                    <tr
                      className="border-b border-slate-200 bg-slate-100/80 cursor-pointer hover:bg-slate-100 select-none"
                      onClick={() => toggleYear(year)}
                    >
                      <td className="w-6 px-1 py-1.5 text-slate-400">
                        {isYearCollapsed
                          ? <ChevronRight className="h-3.5 w-3.5" />
                          : <ChevronDown className="h-3.5 w-3.5" />
                        }
                      </td>
                      <td className="px-3 py-1.5 font-semibold text-slate-700 text-xs border-r-2 border-blue-100">
                        {year}
                        <span className="ml-2 font-normal text-slate-400">{yearRows.length} mo</span>
                      </td>
                      <td className="px-3 py-1.5 text-right text-xs tabular-nums text-slate-600 font-medium">
                        {hasActuals ? fmtNum(yearActual) : '—'}
                      </td>
                      <td className="px-3 py-1.5 text-right text-xs tabular-nums text-slate-500">
                        {yearForecast > 0 ? fmtNum(yearForecast) : '—'}
                      </td>
                      <td className="px-3 py-1.5" />
                      {products.map((p) => (
                        <td key={p.product_code} className="px-3 py-1.5" />
                      ))}
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5 text-right text-xs tabular-nums font-semibold text-slate-700">
                        <div>
                          {yearNetDue > 0 ? fmtCurrency(yearNetDue, currency) : '—'}
                          {currency && yearNetDue > 0 && <span className="ml-1 font-normal text-slate-400">{currency}</span>}
                        </div>
                        {showHardCcy && yearNetDueHard > 0 && (
                          <div className="text-xs font-normal text-slate-500 tabular-nums">
                            {fmtCurrency(yearNetDueHard, hardCurrency)} {hardCurrency}
                          </div>
                        )}
                      </td>
                    </tr>
                    {/* Month rows (hidden when collapsed) */}
                    {!isYearCollapsed && yearRows.map((row) => (
                      <UnifiedRow
                        key={row.billing_month}
                        row={row}
                        products={products}
                        currency={currency}
                        hardCurrency={hardCurrency}
                        showHardCcy={showHardCcy}
                        isExpanded={expanded.has(row.billing_month)}
                        onToggle={() => toggleExpand(row.billing_month)}
                        totalCols={totalCols}
                        editMode={editMode}
                        projectId={projectId}
                        onSaved={fetchData}
                      />
                    ))}
                  </React.Fragment>
                )
              })}
            </tbody>

            {/* Footer totals */}
            {unifiedRows.length > 0 && (
              <tfoot>
                <tr className="bg-slate-50 border-t border-slate-200 font-medium">
                  <td className="px-1 py-2" />
                  <td className="px-3 py-2 text-slate-700">Total</td>
                  <td className="px-3 py-2 text-right text-slate-700 tabular-nums">{fmtNum(totals.actual_kwh)}</td>
                  <td className="px-3 py-2 text-right text-slate-700 tabular-nums">{fmtNum(totals.forecast_kwh)}</td>
                  <td className="px-3 py-2" />
                  {products.map((p) => (
                    <td key={p.product_code} className="px-3 py-2" />
                  ))}
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2 text-right">
                    <div className="font-semibold text-slate-800 tabular-nums">
                      {fmtCurrency(totals.net_due, currency)}
                      {currency && <span className="ml-1 text-xs font-normal text-slate-400">{currency}</span>}
                    </div>
                    {showHardCcy && totals.net_due_hard > 0 && (
                      <div className="text-xs text-slate-500 tabular-nums">
                        {fmtCurrency(totals.net_due_hard, hardCurrency)} {hardCurrency}
                      </div>
                    )}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// UnifiedRow — parent expandable row
// ---------------------------------------------------------------------------

function UnifiedRow({
  row,
  products,
  currency,
  hardCurrency,
  showHardCcy,
  isExpanded,
  onToggle,
  totalCols,
  editMode,
  projectId,
  onSaved,
}: {
  row: UnifiedBillingRow
  products: MonthlyBillingProductColumn[]
  currency: string | null
  hardCurrency: string | null
  showHardCcy: boolean
  isExpanded: boolean
  onToggle: () => void
  totalCols: number
  editMode?: boolean
  projectId?: number
  onSaved?: () => void
}) {
  const inv = row.expected_invoice
  const hasDetail = row.meter_readings.length > 0 || (inv?.line_items?.length ?? 0) > 0

  // Net due: from invoice, or fall back to total_billing_amount
  const netDue = inv ? inv.net_due : row.total_billing_amount
  // Hard currency: prefer invoice-level FX conversion, fall back to monthly-billing hard_ccy
  const netDueHard = inv?.net_due_hard_ccy ?? row.total_billing_amount_hard_ccy

  return (
    <>
      <tr
        className={`border-b border-slate-100 hover:bg-slate-50/50 ${hasDetail ? 'cursor-pointer' : ''}`}
        onClick={hasDetail ? onToggle : undefined}
      >
        {/* Expand chevron */}
        <td className="px-1 py-2 text-slate-400 w-6">
          {hasDetail && (
            isExpanded
              ? <ChevronDown className="h-3.5 w-3.5" />
              : <ChevronRight className="h-3.5 w-3.5" />
          )}
        </td>
        {/* Month */}
        <td className="px-3 py-2 text-slate-700 whitespace-nowrap">
          {formatMonth(row.billing_month)}
        </td>
        {/* Generation */}
        <td className="px-3 py-2 text-right tabular-nums text-slate-700">
          {editMode && projectId && onSaved ? (
            <InlineNumberEdit value={row.actual_kwh} billingMonth={row.billing_month} field="actual_kwh" projectId={projectId} onSaved={onSaved} />
          ) : fmtNum(row.actual_kwh)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-500">
          {editMode && projectId && onSaved ? (
            <InlineNumberEdit value={row.forecast_kwh} billingMonth={row.billing_month} field="forecast_kwh" projectId={projectId} onSaved={onSaved} />
          ) : fmtNum(row.forecast_kwh)}
        </td>
        <td className={`px-3 py-2 text-right tabular-nums ${varianceClass(row.variance_pct)}`}>
          {row.variance_pct != null ? `${row.variance_pct >= 0 ? '+' : ''}${row.variance_pct.toFixed(1)}%` : '—'}
        </td>
        {/* Product columns */}
        {products.map((p) => {
          const amount = row.product_amounts[p.product_code]
          return (
            <td key={p.product_code} className="px-3 py-2 text-right tabular-nums text-slate-600">
              {fmtCurrency(amount, currency)}
            </td>
          )
        })}
        {/* Invoice waterfall */}
        <td className="px-3 py-2 text-right tabular-nums text-slate-600">
          {inv ? fmtCurrency(inv.levies_total, currency) : '—'}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-600">
          {inv ? fmtCurrency(inv.vat_amount, currency) : '—'}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-600">
          {inv ? fmtCurrency(inv.invoice_total, currency) : '—'}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-red-600">
          {inv && inv.withholdings_total !== 0
            ? `(${fmtCurrency(Math.abs(inv.withholdings_total), currency)})`
            : '—'}
        </td>
        {/* Net Due (dual currency) */}
        <td className="px-3 py-2 text-right">
          <div className="font-semibold text-slate-800 tabular-nums whitespace-nowrap">
            {fmtCurrency(netDue, currency)}
            {currency && <span className="ml-1 text-xs font-normal text-slate-400">{currency}</span>}
          </div>
          {showHardCcy && netDueHard != null && (
            <div className="text-xs text-slate-500 tabular-nums whitespace-nowrap">
              {fmtCurrency(netDueHard, hardCurrency)} {hardCurrency}
            </div>
          )}
        </td>
      </tr>

      {/* Expanded detail rows: meters + levy/WHT breakdown */}
      {isExpanded && hasDetail && (
        <ExpandedDetailRows
          readings={row.meter_readings}
          expectedInvoice={inv}
          products={products}
          currency={currency}
          hardCurrency={hardCurrency}
          showHardCcy={showHardCcy}
          totalCols={totalCols}
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// ExpandedDetailRows — meter breakdown + levy/WHT breakdown
// ---------------------------------------------------------------------------

function ExpandedDetailRows({
  readings,
  expectedInvoice,
  products,
  currency,
  hardCurrency,
  showHardCcy,
  totalCols,
}: {
  readings: MeterReadingDetail[]
  expectedInvoice: ExpectedInvoiceSummary | null
  products: MonthlyBillingProductColumn[]
  currency: string | null
  hardCurrency: string | null
  showHardCcy: boolean
  totalCols: number
}) {
  const levyItems = expectedInvoice?.line_items
    .filter(li => li.line_item_type_code === 'LEVY')
    .sort((a, b) => a.sort_order - b.sort_order) ?? []
  const whItems = expectedInvoice?.line_items
    .filter(li => li.line_item_type_code === 'WITHHOLDING')
    .sort((a, b) => a.sort_order - b.sort_order) ?? []

  // Number of empty columns between name and waterfall: actual + forecast + var% + products
  const midEmpties = 3 + products.length

  // Shared sub-row cell class (matches parent px-3 py-2 but slightly compact)
  const sc = 'px-3 py-1.5'

  return (
    <>
      {/* Meter breakdown rows */}
      {readings.map((r, idx) => {
        const rate = r.rate
        // Build a lookup of persisted invoice line items for this meter
        const meterLineItems = expectedInvoice?.line_items.filter(
          li => li.meter_name === r.meter_name && (li.line_item_type_code === 'ENERGY' || li.line_item_type_code === 'AVAILABLE_ENERGY')
        ) ?? []
        return (
          <tr key={`meter-${r.meter_id}-${idx}`} className="bg-slate-50/80 border-b border-slate-100/50 text-xs">
            <td className="w-6 px-1 py-1.5" />
            <td className={`${sc} text-slate-500 whitespace-nowrap`}>
              {r.meter_name || `Meter ${r.meter_id}`}
              {rate != null && (
                <span className="ml-1.5 text-[10px] text-slate-400 tabular-nums">@{fmtNum(rate, 4)}/kWh</span>
              )}
            </td>
            {/* Total kWh (metered + available) — aligns with Actual kWh */}
            <td className={`${sc} text-right tabular-nums text-slate-500`}>
              {fmtNum(r.metered_kwh != null || r.available_kwh != null
                ? (r.metered_kwh ?? 0) + (r.available_kwh ?? 0)
                : null)}
            </td>
            {/* Forecast + Var% empty */}
            <td className={sc} />
            <td className={sc} />
            {/* Product amounts — prefer persisted invoice line items, fall back to qty * rate */}
            {products.map((p) => {
              const cat = productEnergyCategory(p)
              const typeCode = cat === 'available' ? 'AVAILABLE_ENERGY' : 'ENERGY'
              // Try to match a persisted line item for this meter + type
              const persistedLine = meterLineItems.find(li => li.line_item_type_code === typeCode)
              let amt: number | null = null
              if (persistedLine) {
                amt = persistedLine.line_total_amount
              } else {
                const qty = cat === 'available' ? r.available_kwh
                  : cat === 'metered' ? r.metered_kwh
                  : null
                amt = qty != null && rate != null ? qty * rate : null
              }
              return (
                <td key={p.product_code} className={`${sc} text-right tabular-nums text-slate-500`}>
                  {amt != null ? fmtCurrency(amt, currency) : <span className="text-slate-300">&mdash;</span>}
                </td>
              )
            })}
            {/* Waterfall empty (Levies, VAT, Gross, W/H) */}
            <td className={sc} />
            <td className={sc} />
            <td className={sc} />
            <td className={sc} />
            {/* Net Due */}
            <td className={`${sc} text-right`}>
              <span className="tabular-nums text-slate-500">{fmtCurrency(r.amount, currency)}</span>
              {showHardCcy && r.amount_hard_ccy != null && (
                <div className="text-[10px] text-slate-400 tabular-nums">
                  {fmtCurrency(r.amount_hard_ccy, hardCurrency)} {hardCurrency}
                </div>
              )}
            </td>
          </tr>
        )
      })}

      {/* Levy breakdown rows */}
      {levyItems.length > 0 && readings.length > 0 && (
        <tr><td colSpan={totalCols} className="h-px bg-slate-200/60" /></tr>
      )}
      {levyItems.map((li, i) => (
        <tr key={`levy-${i}`} className="bg-slate-50/80 border-b border-slate-100/50 text-xs">
          <td className="w-6 px-1 py-1.5" />
          <td className={`${sc} text-slate-500 whitespace-nowrap`}>
            {li.description}
          </td>
          {/* Empty: actual, forecast, var%, products */}
          {Array.from({ length: midEmpties }).map((_, j) => (
            <td key={j} className={sc} />
          ))}
          {/* Levies column */}
          <td className={`${sc} text-right tabular-nums text-slate-500`}>
            {fmtCurrency(li.line_total_amount, currency)}
          </td>
          {/* VAT, Gross, W/H, Net Due empty */}
          <td className={sc} />
          <td className={sc} />
          <td className={sc} />
          <td className={sc} />
        </tr>
      ))}

      {/* Withholding breakdown rows */}
      {whItems.length > 0 && (readings.length > 0 || levyItems.length > 0) && levyItems.length === 0 && (
        <tr><td colSpan={totalCols} className="h-px bg-slate-200/60" /></tr>
      )}
      {whItems.map((li, i) => (
        <tr key={`wh-${i}`} className="bg-slate-50/80 border-b border-slate-100/50 text-xs">
          <td className="w-6 px-1 py-1.5" />
          <td className={`${sc} text-slate-500 whitespace-nowrap`}>
            {li.description}
          </td>
          {/* Empty: actual, forecast, var%, products */}
          {Array.from({ length: midEmpties }).map((_, j) => (
            <td key={j} className={sc} />
          ))}
          {/* Levies, VAT, Gross empty */}
          <td className={sc} />
          <td className={sc} />
          <td className={sc} />
          {/* W/H column */}
          <td className={`${sc} text-right tabular-nums text-red-500`}>
            ({fmtCurrency(Math.abs(li.line_total_amount), currency)})
          </td>
          <td className={sc} />
        </tr>
      ))}
    </>
  )
}
