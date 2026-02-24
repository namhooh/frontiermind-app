'use client'

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Upload, Download, Plus, Loader2, Check, X, ChevronDown, ChevronRight } from 'lucide-react'
import { IS_DEMO } from '@/lib/demoMode'
import { toast } from 'sonner'
import {
  adminClient,
  type MonthlyBillingResponse,
  type MonthlyBillingRow,
  type MonthlyBillingProductColumn,
  type MeterBillingResponse,
  type MeterBillingMonth,
  type MeterReadingDetail,
  type MeterInfo,
  type ExpectedInvoiceSummary,
} from '@/lib/api/adminClient'
import { formatMonth, fmtNum, fmtCurrency, varianceClass } from '@/app/projects/utils/formatters'

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
          total_billing_amount_hard_ccy: null,
          meter_readings: mm.meter_readings,
          expected_invoice: mm.expected_invoice,
        })
      }
    }

    // Sort descending
    result.sort((a, b) => b.billing_month.localeCompare(a.billing_month))
    return result
  }, [data, meterData])

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
      if (row.total_billing_amount_hard_ccy != null) {
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

  // Deduplicated meter list for per-meter revenue columns
  const uniqueMeters = useMemo(() => {
    const seen = new Map<number, MeterInfo>()
    for (const m of meterData?.meters ?? []) {
      if (!seen.has(m.meter_id)) seen.set(m.meter_id, m)
    }
    return Array.from(seen.values())
  }, [meterData])

  // Determine how many product columns we have
  const productColCount = products.length
  const meterColCount = uniqueMeters.length
  // Total columns: expand chevron + month + actual + forecast + var% + product cols + meter cols + levies + VAT + gross + W/H + net due
  const waterfallCols = 5 // levies, VAT, gross, W/H, net due
  const totalCols = 1 + 1 + 1 + 1 + 1 + productColCount + meterColCount + waterfallCols

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
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-700">
            Monthly Billing
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
                <th colSpan={productColCount + meterColCount + waterfallCols} className="px-3 py-1.5 text-xs font-semibold text-amber-700 bg-amber-50 text-center">
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
                {/* Per-meter revenue columns */}
                {uniqueMeters.map((m, i) => (
                  <th key={`meter-hdr-${m.meter_id}`} className={`text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap ${i === uniqueMeters.length - 1 ? 'border-r border-slate-200' : ''}`}>
                    {m.meter_name || `Meter ${m.meter_id}`}
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
                  {uniqueMeters.map((m) => (
                    <td key={`meter-add-${m.meter_id}`} className="px-3 py-1.5" />
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

              {/* Data rows */}
              {unifiedRows.map((row) => (
                <UnifiedRow
                  key={row.billing_month}
                  row={row}
                  products={products}
                  meters={uniqueMeters}
                  currency={currency}
                  hardCurrency={hardCurrency}
                  showHardCcy={showHardCcy}
                  isExpanded={expanded.has(row.billing_month)}
                  onToggle={() => toggleExpand(row.billing_month)}
                  totalCols={totalCols}
                />
              ))}
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
                  {uniqueMeters.map((m) => (
                    <td key={`meter-total-${m.meter_id}`} className="px-3 py-2" />
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
  meters,
  currency,
  hardCurrency,
  showHardCcy,
  isExpanded,
  onToggle,
  totalCols,
}: {
  row: UnifiedBillingRow
  products: MonthlyBillingProductColumn[]
  meters: MeterInfo[]
  currency: string | null
  hardCurrency: string | null
  showHardCcy: boolean
  isExpanded: boolean
  onToggle: () => void
  totalCols: number
}) {
  const inv = row.expected_invoice
  const hasDetail = row.meter_readings.length > 0

  // Net due: from invoice, or fall back to total_billing_amount
  const netDue = inv ? inv.net_due : row.total_billing_amount
  const netDueHard = row.total_billing_amount_hard_ccy

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
          {inv && (
            <span className="ml-1.5 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1 py-0.5 rounded">
              v{inv.version_no}
            </span>
          )}
        </td>
        {/* Generation */}
        <td className="px-3 py-2 text-right tabular-nums text-slate-700">{fmtNum(row.actual_kwh)}</td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-500">{fmtNum(row.forecast_kwh)}</td>
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
        {/* Per-meter revenue columns */}
        {meters.map((m, i) => {
          const reading = row.meter_readings.find(r => r.meter_id === m.meter_id)
          return (
            <td key={`meter-${m.meter_id}`} className={`px-3 py-2 text-right tabular-nums text-slate-600 ${i === meters.length - 1 ? 'border-r border-slate-200' : ''}`}>
              {reading?.amount != null ? fmtCurrency(reading.amount, currency) : '—'}
              {showHardCcy && reading?.amount_hard_ccy != null && (
                <div className="text-[10px] text-slate-400 tabular-nums">
                  {fmtCurrency(reading.amount_hard_ccy, hardCurrency)}
                </div>
              )}
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

      {/* Expanded: per-meter detail */}
      {isExpanded && hasDetail && (
        <MeterDetailRows
          readings={row.meter_readings}
          products={products}
          meters={meters}
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
// MeterDetailRows — child rows showing per-meter breakdown
// ---------------------------------------------------------------------------

function MeterDetailRows({
  readings,
  products,
  meters,
  currency,
  hardCurrency,
  showHardCcy,
  totalCols,
}: {
  readings: MeterReadingDetail[]
  products: MonthlyBillingProductColumn[]
  meters: MeterInfo[]
  currency: string | null
  hardCurrency: string | null
  showHardCcy: boolean
  totalCols: number
}) {
  return (
    <tr>
      <td colSpan={totalCols} className="p-0">
        <div className="bg-slate-50/80 border-t border-slate-100">
          <table className="w-full text-xs">
            <tbody>
              {readings.map((r, idx) => (
                <tr key={`${r.meter_id}-${idx}`} className="border-b border-slate-100/50">
                  {/* Indent + meter name */}
                  <td className="w-6 px-1 py-1.5" />
                  <td className="px-3 py-1.5 text-slate-500 whitespace-nowrap">
                    {r.meter_name || `Meter ${r.meter_id}`}
                  </td>
                  {/* Metered kWh in actual column */}
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-500">
                    {fmtNum(r.metered_kwh)}
                  </td>
                  {/* Forecast + Var% empty for child rows */}
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  {/* Product amounts: show rate + amount per product */}
                  {products.map((p) => {
                    const isAvailableEnergy = p.product_code.toLowerCase().includes('available')
                    const qty = isAvailableEnergy ? r.available_kwh : r.metered_kwh
                    const rate = r.rate
                    const amt = qty != null && rate != null ? qty * rate : null

                    return (
                      <td key={p.product_code} className="px-3 py-1.5 text-right">
                        {amt != null ? (
                          <div>
                            <span className="tabular-nums text-slate-500">{fmtCurrency(amt, currency)}</span>
                            {rate != null && (
                              <div className="text-[10px] text-slate-400 tabular-nums">
                                @{fmtNum(rate, 4)}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                    )
                  })}
                  {/* Per-meter columns: highlight this meter's column */}
                  {meters.map((m) => (
                    <td key={`detail-meter-${m.meter_id}`} className="px-3 py-1.5 text-right">
                      {m.meter_id === r.meter_id ? (
                        <span className="tabular-nums text-slate-500">{fmtCurrency(r.amount, currency)}</span>
                      ) : null}
                    </td>
                  ))}
                  {/* Waterfall columns empty for child rows */}
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                  {/* Per-meter amount + hard ccy */}
                  <td className="px-3 py-1.5 text-right">
                    <span className="tabular-nums text-slate-500">{fmtCurrency(r.amount, currency)}</span>
                    {showHardCcy && r.amount_hard_ccy != null && (
                      <div className="text-[10px] text-slate-400 tabular-nums">
                        {fmtCurrency(r.amount_hard_ccy, hardCurrency)} {hardCurrency}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </td>
    </tr>
  )
}
