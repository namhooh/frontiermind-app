'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Upload, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  adminClient,
  type PlantPerformanceResponse,
  type PerformanceMonth,
} from '@/lib/api/adminClient'
import { formatMonth, fmtNum, fmtPct, fmtRatio, compClass } from '@/app/projects/utils/formatters'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PlantPerformanceTabProps {
  projectId?: number
  editMode?: boolean
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PlantPerformanceTab({ projectId }: PlantPerformanceTabProps) {
  const [data, setData] = useState<PlantPerformanceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'table' | 'charts'>('table')

  // Import state
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)

  // Fetch
  const fetchData = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const resp = await adminClient.getPlantPerformance(projectId)
      setData(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load performance data')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Import handler
  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !projectId) return
    setImporting(true)
    try {
      const resp = await adminClient.importPlantPerformance(projectId, file)
      toast.success(resp.message || `Imported ${resp.imported_rows} rows`)
      await fetchData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [projectId, fetchData])

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

  const months = data?.months ?? []
  const meters = data?.meters ?? []
  const capacity = data?.installed_capacity_kwp
  const degradation = data?.annual_degradation_pct

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <SummaryCard label="Installed Capacity" value={capacity ? `${fmtNum(capacity, 1)} kWp` : '—'} />
        <SummaryCard label="Degradation Rate" value={degradation != null ? `${(degradation * 100).toFixed(2)}%/yr` : '—'} />
        <SummaryCard
          label="Latest PR"
          value={months.length > 0 && months[0].actual_pr != null ? fmtPct(months[0].actual_pr) : '—'}
        />
        <SummaryCard
          label="Latest Availability"
          value={months.length > 0 && months[0].actual_availability_pct != null
            ? `${months[0].actual_availability_pct.toFixed(1)}%`
            : '—'
          }
        />
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setView('table')}
            className={`text-xs px-2.5 py-1.5 rounded border ${
              view === 'table'
                ? 'bg-slate-100 border-slate-300 text-slate-700'
                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
            }`}
          >
            Table
          </button>
          <button
            onClick={() => setView('charts')}
            className={`text-xs px-2.5 py-1.5 rounded border ${
              view === 'charts'
                ? 'bg-slate-100 border-slate-300 text-slate-700'
                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
            }`}
          >
            Charts
          </button>
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 cursor-pointer">
            {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
            Import Workbook
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv"
              className="hidden"
              onChange={handleImport}
              disabled={importing}
            />
          </label>
        </div>
      </div>

      {/* Content */}
      {view === 'table' ? (
        <PerformanceWorkbook months={months} meters={meters} />
      ) : (
        <PerformanceCharts months={months} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary Card
// ---------------------------------------------------------------------------

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 rounded-lg border border-slate-200 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-lg font-semibold text-slate-800 mt-0.5">{value}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Workbook Table — grouped header with per-meter columns
// ---------------------------------------------------------------------------

function PerformanceWorkbook({
  months,
  meters,
}: {
  months: PerformanceMonth[]
  meters: { meter_id: number; meter_name: string; energy_category: string }[]
}) {
  if (months.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-slate-400">
        No performance data available. Import an Operations workbook to get started.
      </div>
    )
  }

  const hasMeters = meters.length > 0

  return (
    <div className="overflow-x-auto border border-slate-200 rounded-lg">
      <table className="w-full text-sm">
        <thead>
          {/* Group header row */}
          <tr className="border-b border-slate-200">
            {/* Reference group */}
            <th colSpan={2} className="px-3 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 border-r-2 border-blue-200 text-center">
              Reference
            </th>
            {/* Forecast group */}
            <th colSpan={3} className="px-3 py-1.5 text-xs font-semibold text-green-700 bg-green-50 border-r-2 border-green-200 text-center">
              Forecast
            </th>
            {/* Per-meter group */}
            {hasMeters && (
              <th colSpan={meters.length * 2} className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-50 border-r-2 border-slate-300 text-center">
                Per-Meter kWh
              </th>
            )}
            {/* Available Energy (standalone) */}
            <th colSpan={1} className="px-3 py-1.5 text-xs font-semibold text-purple-700 bg-purple-50 border-r-2 border-purple-200 text-center">
              Available
            </th>
            {/* Aggregated group */}
            <th colSpan={4} className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-50 border-r-2 border-slate-300 text-center">
              Aggregated
            </th>
            {/* Comparison group */}
            <th colSpan={3} className="px-3 py-1.5 text-xs font-semibold text-amber-700 bg-amber-50 text-center">
              Comparison
            </th>
          </tr>
          {/* Column header row */}
          <tr className="bg-slate-50 border-b border-slate-200">
            {/* Reference */}
            <th className="text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap sticky left-0 bg-slate-50 z-10 border-r border-slate-200">Mon</th>
            <th className="text-center px-2 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-blue-200">OY</th>
            {/* Forecast */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">E (kWh)</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">GHI</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-green-200">PR</th>
            {/* Per-meter: M (metered) and A (available) for each */}
            {hasMeters && meters.map((m, i) => (
              <th key={`hdr-${m.meter_id}`} colSpan={2} className={`text-center px-1 py-2 font-medium text-slate-600 whitespace-nowrap text-xs ${i === meters.length - 1 ? 'border-r-2 border-slate-300' : 'border-r border-slate-100'}`}>
                {m.meter_name || `M${m.meter_id}`}
              </th>
            ))}
            {/* Available Energy (standalone) */}
            <th className="text-right px-2 py-2 font-medium text-purple-600 whitespace-nowrap border-r-2 border-purple-200">Avail</th>
            {/* Aggregated */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">Total E</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">GHI</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">PR</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-slate-300">A%</th>
            {/* Comparison */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">E</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">I</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">P</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m.billing_month} className="border-b border-slate-100 hover:bg-slate-50/50">
              {/* Reference */}
              <td className="px-3 py-2 text-slate-700 whitespace-nowrap sticky left-0 bg-white z-10 border-r border-slate-200">{formatMonth(m.billing_month)}</td>
              <td className="px-2 py-2 text-center text-slate-500 tabular-nums border-r-2 border-blue-100">{m.operating_year ?? '—'}</td>
              {/* Forecast */}
              <td className="px-2 py-2 text-right tabular-nums text-slate-500">{fmtNum(m.forecast_energy_kwh)}</td>
              <td className="px-2 py-2 text-right tabular-nums text-slate-500">{fmtNum(m.forecast_ghi_irradiance, 1)}</td>
              <td className="px-2 py-2 text-right tabular-nums text-slate-500 border-r-2 border-green-100">{fmtPct(m.forecast_pr)}</td>
              {/* Per-meter M|A */}
              {hasMeters && meters.map((meter, i) => {
                const md = m.meter_details?.find(d => d.meter_id === meter.meter_id)
                return (
                  <td key={`${m.billing_month}-${meter.meter_id}`} colSpan={2} className={`px-1 py-2 text-right tabular-nums text-xs text-slate-600 ${i === meters.length - 1 ? 'border-r-2 border-slate-200' : 'border-r border-slate-50'}`}>
                    {md?.metered_kwh != null ? fmtNum(md.metered_kwh) : '—'}
                    {md?.available_kwh != null && md.available_kwh > 0 && (
                      <span className="text-slate-400 ml-0.5">/{fmtNum(md.available_kwh)}</span>
                    )}
                  </td>
                )
              })}
              {/* Available Energy (standalone) */}
              <td className="px-2 py-2 text-right tabular-nums text-slate-600 border-r-2 border-purple-100">{fmtNum(m.total_available_kwh)}</td>
              {/* Aggregated */}
              <td className="px-2 py-2 text-right tabular-nums text-slate-700 font-medium">{fmtNum(m.total_energy_kwh)}</td>
              <td className="px-2 py-2 text-right tabular-nums text-slate-600">{fmtNum(m.actual_ghi_irradiance, 1)}</td>
              <td className="px-2 py-2 text-right tabular-nums text-slate-700 font-medium">{fmtPct(m.actual_pr)}</td>
              <td className="px-2 py-2 text-right tabular-nums text-slate-600 border-r-2 border-slate-200">
                {m.actual_availability_pct != null ? `${m.actual_availability_pct.toFixed(1)}%` : '—'}
              </td>
              {/* Comparison */}
              <td className={`px-2 py-2 text-right tabular-nums ${compClass(m.energy_comparison)}`}>
                {fmtRatio(m.energy_comparison)}
              </td>
              <td className={`px-2 py-2 text-right tabular-nums ${compClass(m.irr_comparison)}`}>
                {fmtRatio(m.irr_comparison)}
              </td>
              <td className={`px-2 py-2 text-right tabular-nums ${compClass(m.pr_comparison)}`}>
                {fmtRatio(m.pr_comparison)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Charts View
// ---------------------------------------------------------------------------

function PerformanceCharts({ months }: { months: PerformanceMonth[] }) {
  // Reverse for chronological order in charts
  const chartData = [...months].reverse().map((m) => ({
    month: formatMonth(m.billing_month),
    actual: m.total_energy_kwh,
    forecast: m.forecast_energy_kwh,
    pr: m.actual_pr != null ? m.actual_pr * 100 : null,
    forecast_pr: m.forecast_pr != null ? m.forecast_pr * 100 : null,
  }))

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-slate-400">
        No data to chart.
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Energy: Actual vs Forecast */}
      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-2">Energy: Actual vs Forecast (kWh)</h4>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip formatter={(v) => fmtNum(v as number)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="actual" name="Actual" fill="#3b82f6" radius={[2, 2, 0, 0]} />
              <Bar dataKey="forecast" name="Forecast" fill="#94a3b8" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* PR Trend */}
      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-2">Performance Ratio Trend (%)</h4>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v) => `${(v as number).toFixed(1)}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="pr" name="Actual PR" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} connectNulls />
              <Line type="monotone" dataKey="forecast_pr" name="Forecast PR" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 4" dot={{ r: 2 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
