'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
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
} from '@/lib/api/adminClient'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBillingMonth(v: string | null | undefined): string {
  if (!v) return '—'
  const d = new Date(v)
  if (isNaN(d.getTime())) return String(v)
  return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function fmtNum(v: number | null | undefined, decimals = 0): string {
  if (v == null) return '—'
  return v.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function fmtCurrency(v: number | null | undefined, currency?: string | null): string {
  if (v == null) return '—'
  const formatted = v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${formatted}` : formatted
}

function varianceClass(pct: number | null | undefined): string {
  if (pct == null) return ''
  if (pct > 0) return 'text-emerald-600'
  if (pct < 0) return 'text-red-600'
  return ''
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MonthlyBillingTabProps {
  projectId?: number
  editMode?: boolean
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MonthlyBillingTab({ projectId, editMode }: MonthlyBillingTabProps) {
  const [data, setData] = useState<MonthlyBillingResponse | null>(null)
  const [meterData, setMeterData] = useState<MeterBillingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [billingView, setBillingView] = useState<'summary' | 'meter'>('summary')

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

  const rows = data?.rows ?? []
  const products = data?.products ?? []
  const currency = data?.currency_code
  const summary = data?.summary

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-700">
            Monthly Billing
            {currency && <span className="ml-2 text-xs font-normal text-slate-400">({currency})</span>}
            {data?.degradation_pct != null && (
              <>
                <span className="mx-1.5 text-slate-300">|</span>
                <span className="text-xs font-normal text-slate-400">
                  Degradation: {(data.degradation_pct * 100).toFixed(2)}%/yr
                </span>
              </>
            )}
          </h3>
          {/* View toggle */}
          {meterData && meterData.meters.length > 0 && (
            <div className="flex items-center border border-slate-200 rounded overflow-hidden">
              <button
                onClick={() => setBillingView('summary')}
                className={`text-xs px-2.5 py-1 ${
                  billingView === 'summary'
                    ? 'bg-slate-100 text-slate-700'
                    : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                Summary
              </button>
              <button
                onClick={() => setBillingView('meter')}
                className={`text-xs px-2.5 py-1 border-l border-slate-200 ${
                  billingView === 'meter'
                    ? 'bg-slate-100 text-slate-700'
                    : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                Meter Breakdown
              </button>
            </div>
          )}
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
            disabled={rows.length === 0}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Download className="h-3 w-3" /> Export
          </button>
        </div>
      </div>

      {/* Meter Breakdown View */}
      {billingView === 'meter' && meterData && (
        meterData.months.length > 0 ? (
          <MeterBreakdownTable months={meterData.months} currency={meterData.currency_code} />
        ) : (
          <div className="flex items-center justify-center h-32 text-sm text-slate-400">
            No per-meter billing data available.
          </div>
        )
      )}

      {/* Summary Table */}
      {billingView === 'summary' && (rows.length === 0 && !showAddRow ? (
        <div className="flex items-center justify-center h-32 text-sm text-slate-400">
          No billing data available. Import a file or add months manually.
        </div>
      ) : (
        <div className="overflow-x-auto border border-slate-200 rounded-lg">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Month</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Actual (kWh)</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Forecast (kWh)</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Variance (kWh)</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Variance (%)</th>
                {products.map((p) => (
                  <th key={p.product_code} className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">
                    {p.product_name}
                  </th>
                ))}
                <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Total</th>
              </tr>
            </thead>
            <tbody>
              {/* Add row (manual entry) */}
              {showAddRow && (
                <tr className="bg-blue-50/50 border-b border-slate-100">
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
                  <td className="px-3 py-1.5" />
                  {products.map((p) => (
                    <td key={p.product_code} className="px-3 py-1.5" />
                  ))}
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
              {rows.map((row) => (
                <BillingRow key={row.billing_month} row={row} products={products} currency={currency} />
              ))}
            </tbody>

            {/* Footer totals */}
            {summary && rows.length > 0 && (
              <tfoot>
                <tr className="bg-slate-50 border-t border-slate-200 font-medium">
                  <td className="px-3 py-2 text-slate-700">Total</td>
                  <td className="px-3 py-2 text-right text-slate-700">{fmtNum(summary.actual_kwh)}</td>
                  <td className="px-3 py-2 text-right text-slate-700">{fmtNum(summary.forecast_kwh)}</td>
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2" />
                  {products.map((p) => (
                    <td key={p.product_code} className="px-3 py-2" />
                  ))}
                  <td className="px-3 py-2 text-right text-slate-700">{fmtCurrency(summary.total_billing, currency)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// BillingRow — single table row
// ---------------------------------------------------------------------------

function BillingRow({
  row,
  products,
  currency,
}: {
  row: MonthlyBillingRow
  products: MonthlyBillingProductColumn[]
  currency?: string | null
}) {
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/50">
      <td className="px-3 py-2 text-slate-700 whitespace-nowrap">{formatBillingMonth(row.billing_month)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-700">{fmtNum(row.actual_kwh)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-500">{fmtNum(row.forecast_kwh)}</td>
      <td className={`px-3 py-2 text-right tabular-nums ${varianceClass(row.variance_pct)}`}>
        {fmtNum(row.variance_kwh)}
      </td>
      <td className={`px-3 py-2 text-right tabular-nums ${varianceClass(row.variance_pct)}`}>
        {row.variance_pct != null ? `${row.variance_pct >= 0 ? '+' : ''}${row.variance_pct.toFixed(1)}%` : '—'}
      </td>
      {products.map((p) => {
        const amount = row.product_amounts[p.product_code]
        return (
          <td key={p.product_code} className="px-3 py-2 text-right tabular-nums text-slate-600">
            {fmtCurrency(amount, currency)}
          </td>
        )
      })}
      <td className="px-3 py-2 text-right tabular-nums font-medium text-slate-700">
        {fmtCurrency(row.total_billing_amount, currency)}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// MeterBreakdownTable — expandable per-month, per-meter detail
// ---------------------------------------------------------------------------

function MeterBreakdownTable({
  months,
  currency,
}: {
  months: MeterBillingMonth[]
  currency?: string | null
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (month: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(month)) next.delete(month)
      else next.add(month)
      return next
    })
  }

  return (
    <div className="overflow-x-auto border border-slate-200 rounded-lg">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200">
            <th className="text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap w-8" />
            <th className="text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Month / Meter</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Opening</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Closing</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Metered (kWh)</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Available (kWh)</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Rate</th>
            <th className="text-right px-3 py-2 font-medium text-slate-600 whitespace-nowrap">Amount</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => {
            const isOpen = expanded.has(m.billing_month)
            return (
              <MeterMonthRows
                key={m.billing_month}
                month={m}
                isOpen={isOpen}
                onToggle={() => toggle(m.billing_month)}
                currency={currency}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function MeterMonthRows({
  month,
  isOpen,
  onToggle,
  currency,
}: {
  month: MeterBillingMonth
  isOpen: boolean
  onToggle: () => void
  currency?: string | null
}) {
  return (
    <>
      {/* Summary row (clickable) */}
      <tr
        className="border-b border-slate-100 hover:bg-slate-50/50 cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-3 py-2 text-slate-400">
          {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </td>
        <td className="px-3 py-2 font-medium text-slate-700 whitespace-nowrap">
          {formatBillingMonth(month.billing_month)}
          <span className="ml-2 text-xs text-slate-400">({month.meter_readings.length} meters)</span>
        </td>
        <td className="px-3 py-2" />
        <td className="px-3 py-2" />
        <td className="px-3 py-2 text-right tabular-nums font-medium text-slate-700">
          {fmtNum(month.total_metered_kwh, 2)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-600">
          {month.total_available_kwh ? fmtNum(month.total_available_kwh, 2) : '—'}
        </td>
        <td className="px-3 py-2" />
        <td className="px-3 py-2 text-right tabular-nums font-medium text-slate-700">
          {fmtCurrency(month.total_amount, currency)}
        </td>
      </tr>

      {/* Per-meter detail rows */}
      {isOpen && month.meter_readings.map((r) => (
        <tr key={`${month.billing_month}-${r.meter_id}`} className="border-b border-slate-50 bg-slate-25">
          <td className="px-3 py-1.5" />
          <td className="px-3 py-1.5 pl-8 text-slate-600 text-xs whitespace-nowrap">
            {r.meter_name || `Meter ${r.meter_id}`}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-500">
            {r.opening_reading != null ? fmtNum(r.opening_reading, 3) : '—'}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-500">
            {r.closing_reading != null ? fmtNum(r.closing_reading, 3) : '—'}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-600">
            {fmtNum(r.metered_kwh, 2)}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-500">
            {r.available_kwh != null ? fmtNum(r.available_kwh, 2) : '—'}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-500">
            {r.rate != null ? fmtNum(r.rate, 4) : '—'}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums text-xs text-slate-600">
            {fmtCurrency(r.amount, currency)}
          </td>
        </tr>
      ))}
    </>
  )
}
