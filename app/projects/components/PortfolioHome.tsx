'use client'

import { useState, useEffect, useCallback } from 'react'
import { Loader2, ChevronDown, ChevronRight, RefreshCw, AlertCircle } from 'lucide-react'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  adminClient,
  type PortfolioRevenueSummaryResponse,
  type PortfolioMonthRow,
} from '@/lib/api/adminClient'
import { formatMonth, fmtNum, fmtCurrency } from '@/app/projects/utils/formatters'

// TODO: Replace with value from auth context once user authentication is implemented.
const CURRENT_ORGANIZATION_ID = 1

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PortfolioHome() {
  const [data, setData] = useState<PortfolioRevenueSummaryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'table' | 'charts'>('table')
  const [showProjects, setShowProjects] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await adminClient.getPortfolioRevenueSummary(CURRENT_ORGANIZATION_ID)
      setData(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load portfolio data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const months = data?.months ?? []
  const projects = data?.projects ?? []
  const summary = data?.summary ?? { total_actual_kwh: null, total_forecast_kwh: null, total_revenue_usd: null, total_forecast_revenue_usd: null }
  const data_coverage = data?.data_coverage ?? { total_projects: 0, projects_with_meter_data: 0, projects_with_forecast: 0, projects_with_tariff: 0 }

  return (
    <div className="space-y-4">
      {/* Header + Summary Cards */}
      <div className="bg-white rounded-lg border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Portfolio Dashboard</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Aggregated monthly energy and revenue across all projects
            </p>
          </div>
          <div className="flex items-center gap-2">
            {data_coverage.total_projects > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                {data_coverage.projects_with_meter_data} of {data_coverage.total_projects} projects reporting
              </span>
            )}
            {error && (
              <button
                onClick={fetchData}
                disabled={loading}
                className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-200 text-slate-500 hover:bg-slate-50"
              >
                <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
                Retry
              </button>
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="flex items-center gap-2 mb-4 px-3 py-2 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-xs">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            <span>Unable to load live data — {error}</span>
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-4">
          <SummaryCard
            label="Total Energy (kWh)"
            actual={summary.total_actual_kwh}
            forecast={summary.total_forecast_kwh}
            formatValue={(v) => fmtNum(v)}
            loading={loading}
          />
          <SummaryCard
            label="Weighted Avg Tariff (USD/kWh)"
            actual={months.length > 0 ? months[0].weighted_avg_tariff_usd : null}
            formatValue={(v) => v != null ? `$${fmtCurrency(v)}` : '—'}
            hideVariance
            loading={loading}
          />
          <SummaryCard
            label="Total Revenue (USD)"
            actual={summary.total_revenue_usd}
            forecast={summary.total_forecast_revenue_usd}
            formatValue={(v) => v != null ? `$${fmtCurrency(v)}` : '—'}
            loading={loading}
          />
        </div>
      </div>

      {/* Monthly data: Table / Charts */}
      <div className="bg-white rounded-lg border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-4">
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
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-48">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : view === 'table' ? (
          <MonthlyTable months={months} />
        ) : (
          <PortfolioCharts months={months} />
        )}
      </div>

      {/* Per-project summary (collapsible) */}
      <div className="bg-white rounded-lg border border-slate-200">
        <button
          type="button"
          onClick={() => setShowProjects(!showProjects)}
          className="w-full flex items-center gap-2 px-6 py-4 text-left hover:bg-slate-50 transition-colors"
        >
          {showProjects ? (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-400" />
          )}
          <span className="text-sm font-medium text-slate-700">Per-Project Breakdown</span>
          <span className="text-xs text-slate-400 ml-auto">
            {loading ? '...' : `${projects.length} projects with data`}
          </span>
        </button>
        {showProjects && (
          <div className="px-6 pb-4">
            {loading ? (
              <div className="flex items-center justify-center h-16">
                <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
              </div>
            ) : (
              <ProjectTable projects={projects} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary Card
// ---------------------------------------------------------------------------

function SummaryCard({
  label,
  actual,
  forecast,
  formatValue,
  hideVariance,
  loading,
}: {
  label: string
  actual: number | null | undefined
  forecast?: number | null
  formatValue: (v: number | null | undefined) => string
  hideVariance?: boolean
  loading?: boolean
}) {
  const variancePct =
    !hideVariance && actual != null && forecast != null && forecast !== 0
      ? ((actual - forecast) / forecast) * 100
      : null

  return (
    <div className="bg-slate-50 rounded-lg border border-slate-200 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      {loading ? (
        <div className="h-7 mt-0.5 flex items-center">
          <div className="h-4 w-24 bg-slate-200 rounded animate-pulse" />
        </div>
      ) : (
        <p className="text-lg font-semibold text-slate-800 mt-0.5">
          {formatValue(actual)}
        </p>
      )}
      {!loading && !hideVariance && forecast != null && (
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-slate-400">Forecast: {formatValue(forecast)}</span>
          {variancePct != null && (
            <span className={`text-xs font-medium ${variancePct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
              {variancePct >= 0 ? '+' : ''}{variancePct.toFixed(1)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Monthly Table
// ---------------------------------------------------------------------------

function MonthlyTable({ months }: { months: PortfolioMonthRow[] }) {
  if (months.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-400">
        <p className="text-sm">No monthly data available</p>
        <p className="text-xs mt-1">Data will appear here once projects have meter readings and tariff rates</p>
      </div>
    )
  }

  // Compute totals for footer
  let totalActual = 0
  let totalForecast = 0
  let totalRevenue = 0
  let totalForecastRevenue = 0
  let weightedRateNum = 0
  let weightedRateDen = 0

  for (const m of months) {
    if (m.actual_kwh) totalActual += m.actual_kwh
    if (m.forecast_kwh) totalForecast += m.forecast_kwh
    if (m.revenue_usd) totalRevenue += m.revenue_usd
    if (m.forecast_revenue_usd) totalForecastRevenue += m.forecast_revenue_usd
    if (m.actual_kwh && m.weighted_avg_tariff_usd) {
      weightedRateNum += m.actual_kwh * m.weighted_avg_tariff_usd
      weightedRateDen += m.actual_kwh
    }
  }

  const totalWeightedRate = weightedRateDen > 0 ? weightedRateNum / weightedRateDen : null

  const variancePct = (actual: number | null, forecast: number | null) => {
    if (actual == null || forecast == null || forecast === 0) return null
    return ((actual - forecast) / forecast) * 100
  }

  const fmtVar = (pct: number | null) => {
    if (pct == null) return '—'
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`
  }

  const varClass = (pct: number | null) => {
    if (pct == null) return 'text-slate-400'
    if (pct > 0) return 'text-emerald-600'
    if (pct < 0) return 'text-red-600'
    return 'text-slate-600'
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="text-left py-2 px-2 text-slate-500 font-medium">Month</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium"># Projects</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Actual kWh</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Forecast kWh</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Var %</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Avg Tariff USD</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Revenue USD</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Forecast Rev USD</th>
            <th className="text-right py-2 px-2 text-slate-500 font-medium">Rev Var %</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => {
            const kwhVar = variancePct(m.actual_kwh, m.forecast_kwh)
            const revVar = variancePct(m.revenue_usd, m.forecast_revenue_usd)
            return (
              <tr key={m.billing_month} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2 px-2 text-slate-700 font-medium">{formatMonth(m.billing_month)}</td>
                <td className="text-right py-2 px-2 text-slate-600">{m.project_count}</td>
                <td className="text-right py-2 px-2 text-slate-700">{m.actual_kwh != null ? fmtNum(m.actual_kwh) : '—'}</td>
                <td className="text-right py-2 px-2 text-slate-500">{m.forecast_kwh != null ? fmtNum(m.forecast_kwh) : '—'}</td>
                <td className={`text-right py-2 px-2 ${varClass(kwhVar)}`}>{fmtVar(kwhVar)}</td>
                <td className="text-right py-2 px-2 text-slate-600">{m.weighted_avg_tariff_usd != null ? `$${fmtCurrency(m.weighted_avg_tariff_usd)}` : '—'}</td>
                <td className="text-right py-2 px-2 text-slate-700 font-medium">{m.revenue_usd != null ? `$${fmtCurrency(m.revenue_usd)}` : '—'}</td>
                <td className="text-right py-2 px-2 text-slate-500">{m.forecast_revenue_usd != null ? `$${fmtCurrency(m.forecast_revenue_usd)}` : '—'}</td>
                <td className={`text-right py-2 px-2 ${varClass(revVar)}`}>{fmtVar(revVar)}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-slate-300 bg-slate-50 font-medium">
            <td className="py-2 px-2 text-slate-700">Total</td>
            <td className="text-right py-2 px-2 text-slate-600">—</td>
            <td className="text-right py-2 px-2 text-slate-700">{fmtNum(totalActual)}</td>
            <td className="text-right py-2 px-2 text-slate-500">{totalForecast > 0 ? fmtNum(totalForecast) : '—'}</td>
            <td className={`text-right py-2 px-2 ${varClass(variancePct(totalActual, totalForecast || null))}`}>
              {fmtVar(variancePct(totalActual, totalForecast || null))}
            </td>
            <td className="text-right py-2 px-2 text-slate-600">{totalWeightedRate != null ? `$${fmtCurrency(totalWeightedRate)}` : '—'}</td>
            <td className="text-right py-2 px-2 text-slate-700">{totalRevenue > 0 ? `$${fmtCurrency(totalRevenue)}` : '—'}</td>
            <td className="text-right py-2 px-2 text-slate-500">{totalForecastRevenue > 0 ? `$${fmtCurrency(totalForecastRevenue)}` : '—'}</td>
            <td className={`text-right py-2 px-2 ${varClass(variancePct(totalRevenue || null, totalForecastRevenue || null))}`}>
              {fmtVar(variancePct(totalRevenue || null, totalForecastRevenue || null))}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

function PortfolioCharts({ months }: { months: PortfolioMonthRow[] }) {
  // Reverse for chronological order in charts
  const chartData = [...months].reverse().map((m) => ({
    month: formatMonth(m.billing_month),
    actual_kwh: m.actual_kwh,
    forecast_kwh: m.forecast_kwh,
    revenue: m.revenue_usd,
    forecast_revenue: m.forecast_revenue_usd,
    tariff: m.weighted_avg_tariff_usd,
  }))

  if (chartData.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-400">
        <p className="text-sm">No data to chart</p>
        <p className="text-xs mt-1">Charts will render once monthly data is available</p>
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
              <Bar dataKey="actual_kwh" name="Actual kWh" fill="#3b82f6" radius={[2, 2, 0, 0]} />
              <Bar dataKey="forecast_kwh" name="Forecast kWh" fill="#94a3b8" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Revenue */}
      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-2">Revenue (USD)</h4>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip formatter={(v) => `$${fmtCurrency(v as number)}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="revenue" name="Revenue" fill="#10b981" radius={[2, 2, 0, 0]} />
              <Bar dataKey="forecast_revenue" name="Forecast Revenue" fill="#94a3b8" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Tariff trend */}
      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-2">Weighted Avg Tariff Trend (USD/kWh)</h4>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v.toFixed(3)}`} domain={['auto', 'auto']} />
              <Tooltip formatter={(v) => `$${(v as number).toFixed(6)}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="tariff" name="Avg Tariff" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-Project Table
// ---------------------------------------------------------------------------

function ProjectTable({ projects }: { projects: PortfolioRevenueSummaryResponse['projects'] }) {
  if (projects.length === 0) {
    return (
      <div className="flex items-center justify-center h-16 text-sm text-slate-400">
        No project data yet
      </div>
    )
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-slate-200">
          <th className="text-left py-2 px-2 text-slate-500 font-medium">Project</th>
          <th className="text-left py-2 px-2 text-slate-500 font-medium">Country</th>
          <th className="text-right py-2 px-2 text-slate-500 font-medium">Total kWh</th>
          <th className="text-right py-2 px-2 text-slate-500 font-medium">Total Revenue USD</th>
          <th className="text-right py-2 px-2 text-slate-500 font-medium">Months</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => (
          <tr key={p.project_id} className="border-b border-slate-100 hover:bg-slate-50">
            <td className="py-2 px-2 text-slate-700 font-medium">{p.project_name}</td>
            <td className="py-2 px-2 text-slate-500">{p.country ?? '—'}</td>
            <td className="text-right py-2 px-2 text-slate-700">{p.total_actual_kwh != null ? fmtNum(p.total_actual_kwh) : '—'}</td>
            <td className="text-right py-2 px-2 text-slate-700">{p.total_revenue_usd != null ? `$${fmtCurrency(p.total_revenue_usd)}` : '—'}</td>
            <td className="text-right py-2 px-2 text-slate-500">{p.months_with_data}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
