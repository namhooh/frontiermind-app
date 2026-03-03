'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Upload, Plus, Loader2, Check, X, Maximize2, Minimize2, ChevronRight, ChevronDown } from 'lucide-react'
import { IS_DEMO } from '@/lib/demoMode'
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

export function PlantPerformanceTab({ projectId, editMode }: PlantPerformanceTabProps) {
  const [data, setData] = useState<PlantPerformanceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'table' | 'charts'>('table')

  // Fullscreen state
  const [fullscreen, setFullscreen] = useState(false)

  // Import state
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)

  // Manual entry state
  const [showAddRow, setShowAddRow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState<{
    billing_month: string; ghi: string; availability: string; comments: string
  }>({ billing_month: '', ghi: '', availability: '', comments: '' })

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

  // Close add row when edit mode toggled off
  useEffect(() => {
    if (!editMode) setShowAddRow(false)
  }, [editMode])

  // Manual entry save
  const handleSaveManual = useCallback(async () => {
    if (!projectId) return
    if (IS_DEMO) { toast('Demo mode — changes are not saved', { duration: 3000 }); setShowAddRow(false); return }
    if (!draft.billing_month) { toast.error('Billing month is required'); return }
    setSaving(true)
    try {
      await adminClient.addPlantPerformanceEntry(projectId, {
        billing_month: draft.billing_month,
        ghi_irradiance_wm2: draft.ghi ? parseFloat(draft.ghi) : undefined,
        actual_availability_pct: draft.availability ? parseFloat(draft.availability) : undefined,
        comments: draft.comments || undefined,
      })
      toast.success(`Saved ${draft.billing_month}`)
      setShowAddRow(false)
      setDraft({ billing_month: '', ghi: '', availability: '', comments: '' })
      await fetchData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [projectId, draft, fetchData])

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

  // Cap display at the current month — future forecast-only rows are hidden
  const currentMonth = new Date().toISOString().slice(0, 7) + '-01'
  const months = (data?.months ?? []).filter(m => m.billing_month <= currentMonth)
  const meters = data?.meters ?? []
  const capacity = data?.installed_capacity_kwp
  const degradation = data?.annual_degradation_pct

  return (
    <div className={`space-y-4 ${fullscreen ? 'fixed inset-0 z-50 bg-white overflow-auto p-6' : ''}`}>
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <SummaryCard label="Installed Capacity" value={capacity ? `${fmtNum(capacity, 1)} kWp` : '—'} />
        <SummaryCard label="Degradation Rate" value={degradation != null ? `${(degradation * 100).toFixed(2)}%/yr` : '—'} />
        <SummaryCard
          label="Latest PR"
          value={(() => {
            const m = months.find(m => m.actual_pr != null)
            return m ? fmtPct(m.actual_pr!) : '—'
          })()}
        />
        <SummaryCard
          label="Latest Availability"
          value={(() => {
            const m = months.find(m => m.actual_availability_pct != null)
            return m ? `${m.actual_availability_pct!.toFixed(1)}%` : '—'
          })()}
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
          {editMode && !IS_DEMO && (
            <button
              onClick={() => {
                setShowAddRow(true)
                setDraft({ billing_month: '', ghi: '', availability: '', comments: '' })
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
        <PerformanceWorkbook
          months={months}
          meters={meters}
          editMode={editMode}
          projectId={projectId}
          onSaved={fetchData}
          showAddRow={showAddRow}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          onSaveManual={handleSaveManual}
          onCancelAdd={() => setShowAddRow(false)}
        />
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

interface YearGroup {
  oy: number | null
  label: string
  months: PerformanceMonth[]
}

function groupByOperatingYear(months: PerformanceMonth[]): YearGroup[] {
  const map = new Map<number | null, PerformanceMonth[]>()
  for (const m of months) {
    const oy = m.operating_year ?? null
    if (!map.has(oy)) map.set(oy, [])
    map.get(oy)!.push(m)
  }
  // Sort groups: highest OY first (DESC), null last
  const groups: YearGroup[] = []
  const keys = [...map.keys()].sort((a, b) => {
    if (a == null && b == null) return 0
    if (a == null) return 1
    if (b == null) return -1
    return b - a
  })
  for (const oy of keys) {
    groups.push({
      oy,
      label: oy != null ? `OY${oy}` : 'Unknown',
      months: map.get(oy)!,
    })
  }
  return groups
}

function PerformanceWorkbook({
  months,
  meters,
  editMode,
  projectId,
  onSaved,
  showAddRow,
  draft,
  setDraft,
  saving,
  onSaveManual,
  onCancelAdd,
}: {
  months: PerformanceMonth[]
  meters: { meter_id: number; meter_name: string; energy_category: string }[]
  editMode?: boolean
  projectId?: number
  onSaved?: () => void
  showAddRow?: boolean
  draft?: { billing_month: string; ghi: string; availability: string; comments: string }
  setDraft?: (fn: (d: { billing_month: string; ghi: string; availability: string; comments: string }) => { billing_month: string; ghi: string; availability: string; comments: string }) => void
  saving?: boolean
  onSaveManual?: () => void
  onCancelAdd?: () => void
}) {
  const yearGroups = groupByOperatingYear(months)

  // Most recent year expanded by default, rest collapsed
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    const initial = new Set<string>()
    yearGroups.slice(1).forEach(g => initial.add(g.label))
    return initial
  })

  const toggleYear = useCallback((label: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }, [])

  if (months.length === 0 && !showAddRow) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-slate-400">
        No performance data available. Import an Operations workbook to get started.
      </div>
    )
  }

  const hasMeters = meters.length > 0
  const totalCols = 2 + 3 + (hasMeters ? meters.length : 0) + 1 + 4 + 3

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
              <th colSpan={meters.length} className="px-3 py-1.5 text-xs font-semibold text-purple-700 bg-purple-50 border-r-2 border-purple-200 text-center">
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
            {/* Per-meter column headers */}
            {hasMeters && meters.map((m, i) => (
              <th key={`hdr-${m.meter_id}`} className={`text-center px-1 py-2 font-medium text-slate-600 whitespace-nowrap text-xs ${i === meters.length - 1 ? 'border-r-2 border-purple-200' : 'border-r border-slate-100'}`}>
                {m.meter_name || `M${m.meter_id}`}
              </th>
            ))}
            {/* Available Energy (standalone) */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-purple-200">Avail</th>
            {/* Aggregated */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">Total E</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">GHI</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">PR</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap border-r-2 border-slate-300">Avail%</th>
            {/* Comparison */}
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">Energy</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">Irrad</th>
            <th className="text-right px-2 py-2 font-medium text-slate-600 whitespace-nowrap">PR</th>
          </tr>
        </thead>
        <tbody>
          {/* Add row (manual entry) */}
          {showAddRow && draft && setDraft && (
            <tr className="bg-blue-50/50 border-b border-slate-100">
              <td className="px-3 py-1.5 sticky left-0 bg-blue-50/50 z-10 border-r border-slate-200">
                <input
                  type="month"
                  value={draft.billing_month}
                  onChange={(e) => setDraft((d) => ({ ...d, billing_month: e.target.value }))}
                  className="w-32 text-xs border border-slate-300 rounded px-1.5 py-1"
                />
              </td>
              <td className="px-2 py-1.5" />
              {/* Forecast cols empty */}
              <td className="px-2 py-1.5" />
              <td className="px-2 py-1.5" />
              <td className="px-2 py-1.5" />
              {/* Per-meter cols empty */}
              {hasMeters && meters.map((m) => (
                <td key={`add-${m.meter_id}`} className="px-1 py-1.5" />
              ))}
              {/* Available empty */}
              <td className="px-2 py-1.5" />
              {/* Aggregated: Total E empty, GHI editable */}
              <td className="px-2 py-1.5" />
              <td className="px-2 py-1.5 text-right">
                <input
                  type="number"
                  step="any"
                  placeholder="GHI"
                  value={draft.ghi}
                  onChange={(e) => setDraft((d) => ({ ...d, ghi: e.target.value }))}
                  className="w-16 text-xs text-right border border-slate-300 rounded px-1.5 py-1"
                />
              </td>
              {/* PR empty */}
              <td className="px-2 py-1.5" />
              {/* A% editable */}
              <td className="px-2 py-1.5 text-right">
                <input
                  type="number"
                  step="any"
                  placeholder="A%"
                  value={draft.availability}
                  onChange={(e) => setDraft((d) => ({ ...d, availability: e.target.value }))}
                  className="w-16 text-xs text-right border border-slate-300 rounded px-1.5 py-1"
                />
              </td>
              {/* Comparison: save/cancel */}
              <td className="px-2 py-1.5" />
              <td className="px-2 py-1.5" />
              <td className="px-2 py-1.5 text-right">
                <div className="flex items-center justify-end gap-1">
                  <button onClick={onSaveManual} disabled={saving} className="p-1 rounded hover:bg-emerald-100 text-emerald-600">
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  </button>
                  <button onClick={onCancelAdd} className="p-1 rounded hover:bg-slate-100 text-slate-400">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          )}

          {/* Year-grouped data rows */}
          {yearGroups.map((group) => {
            const isCollapsed = collapsed.has(group.label)
            // Compute year-level summary for the collapsed row
            const totalEnergy = group.months.reduce((s, m) => s + (m.total_energy_kwh ?? 0), 0)
            const totalForecast = group.months.reduce((s, m) => s + (m.forecast_energy_kwh ?? 0), 0)
            const monthCount = group.months.length

            return (
              <YearGroupRows
                key={group.label}
                group={group}
                isCollapsed={isCollapsed}
                onToggle={() => toggleYear(group.label)}
                totalCols={totalCols}
                totalEnergy={totalEnergy}
                totalForecast={totalForecast}
                monthCount={monthCount}
                meters={meters}
                hasMeters={hasMeters}
                editMode={editMode}
                projectId={projectId}
                onSaved={onSaved}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Year Group Rows — collapsible year header + month rows
// ---------------------------------------------------------------------------

function YearGroupRows({
  group,
  isCollapsed,
  onToggle,
  totalCols,
  totalEnergy,
  totalForecast,
  monthCount,
  meters,
  hasMeters,
  editMode,
  projectId,
  onSaved,
}: {
  group: YearGroup
  isCollapsed: boolean
  onToggle: () => void
  totalCols: number
  totalEnergy: number
  totalForecast: number
  monthCount: number
  meters: { meter_id: number; meter_name: string; energy_category: string }[]
  hasMeters: boolean
  editMode?: boolean
  projectId?: number
  onSaved?: () => void
}) {
  const energyRatio = totalForecast > 0 ? totalEnergy / totalForecast : null

  return (
    <>
      {/* Year header row */}
      <tr
        className="border-b border-slate-200 bg-slate-100/80 cursor-pointer hover:bg-slate-100 select-none"
        onClick={onToggle}
      >
        <td
          className="px-3 py-1.5 font-semibold text-slate-700 text-xs sticky left-0 bg-slate-100/80 z-10 border-r border-slate-200"
        >
          <span className="inline-flex items-center gap-1">
            {isCollapsed
              ? <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
              : <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
            }
            {group.label}
          </span>
        </td>
        <td className="px-2 py-1.5 text-xs text-slate-500 border-r-2 border-blue-100">
          {monthCount} mo
        </td>
        {/* Forecast total */}
        <td className="px-2 py-1.5 text-right text-xs tabular-nums text-slate-500">
          {totalForecast > 0 ? fmtNum(totalForecast) : '—'}
        </td>
        <td className="px-2 py-1.5" />
        <td className="px-2 py-1.5 border-r-2 border-green-100" />
        {/* Per-meter cols */}
        {hasMeters && meters.map((m, i) => (
          <td key={`yr-${group.label}-${m.meter_id}`} className={`px-1 py-1.5 ${i === meters.length - 1 ? 'border-r-2 border-purple-100' : ''}`} />
        ))}
        {/* Available */}
        <td className="px-2 py-1.5 border-r-2 border-purple-100" />
        {/* Aggregated total */}
        <td className="px-2 py-1.5 text-right text-xs tabular-nums font-semibold text-slate-700">
          {totalEnergy > 0 ? fmtNum(totalEnergy) : '—'}
        </td>
        <td className="px-2 py-1.5" />
        <td className="px-2 py-1.5" />
        <td className="px-2 py-1.5 border-r-2 border-slate-200" />
        {/* Comparison: energy ratio */}
        <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${energyRatio != null ? compClass(energyRatio) : 'text-slate-400'}`}>
          {energyRatio != null ? fmtRatio(energyRatio) : '—'}
        </td>
        <td className="px-2 py-1.5" />
        <td className="px-2 py-1.5" />
      </tr>
      {/* Month rows (hidden when collapsed) */}
      {!isCollapsed && group.months.map((m) => (
        <PerformanceRow
          key={m.billing_month}
          m={m}
          meters={meters}
          hasMeters={hasMeters}
          editMode={editMode}
          projectId={projectId}
          onSaved={onSaved}
        />
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// InlinePerfEdit — click-to-edit cell for performance rows
// ---------------------------------------------------------------------------

function InlinePerfEdit({
  value,
  billingMonth,
  field,
  projectId,
  onSaved,
  decimals = 1,
}: {
  value: number | null
  billingMonth: string
  field: string
  projectId: number
  onSaved: () => void
  decimals?: number
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

  const startEdit = useCallback(() => {
    setDraft(value != null ? String(value) : '')
    setEditing(true)
  }, [value])

  const handleSave = useCallback(async () => {
    const num = draft.trim() === '' ? undefined : parseFloat(draft)
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
      await adminClient.addPlantPerformanceEntry(projectId, {
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

  if (saving) return <Loader2 className="h-3 w-3 animate-spin text-slate-400 ml-auto" />

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
        className="w-16 text-xs text-right border border-blue-300 rounded px-1 py-0.5 outline-none ring-1 ring-blue-200 focus:ring-blue-400"
      />
    )
  }

  const display = value != null ? (decimals === 0 ? fmtNum(value) : fmtNum(value, decimals)) : '—'
  return (
    <span
      onClick={startEdit}
      className="cursor-pointer rounded px-1 -mx-1 bg-amber-50 hover:bg-amber-100 transition-colors"
      title="Click to edit"
    >
      {display}
    </span>
  )
}

// ---------------------------------------------------------------------------
// PerformanceRow — single data row, supports inline editing
// ---------------------------------------------------------------------------

function PerformanceRow({
  m,
  meters,
  hasMeters,
  editMode,
  projectId,
  onSaved,
}: {
  m: PerformanceMonth
  meters: { meter_id: number; meter_name: string; energy_category: string }[]
  hasMeters: boolean
  editMode?: boolean
  projectId?: number
  onSaved?: () => void
}) {
  const canEdit = editMode && projectId != null && onSaved != null

  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/50">
      {/* Reference */}
      <td className="px-3 py-2 text-slate-700 whitespace-nowrap sticky left-0 bg-white z-10 border-r border-slate-200">{formatMonth(m.billing_month)}</td>
      <td className="px-2 py-2 text-center text-slate-500 tabular-nums border-r-2 border-blue-100">{m.operating_year ?? '—'}</td>
      {/* Forecast (read-only, edited in Technical tab) */}
      <td className="px-2 py-2 text-right tabular-nums text-slate-500">{fmtNum(m.forecast_energy_kwh)}</td>
      <td className="px-2 py-2 text-right tabular-nums text-slate-500">{fmtNum(m.forecast_ghi_irradiance, 1)}</td>
      <td className="px-2 py-2 text-right tabular-nums text-slate-500 border-r-2 border-green-100">{fmtPct(m.forecast_pr)}</td>
      {/* Per-meter metered kWh */}
      {hasMeters && meters.map((meter, i) => {
        const md = m.meter_details?.find(d => d.meter_id === meter.meter_id)
        return (
          <td key={`${m.billing_month}-${meter.meter_id}`} className={`px-1 py-2 text-right tabular-nums text-xs text-slate-600 ${i === meters.length - 1 ? 'border-r-2 border-purple-100' : 'border-r border-slate-50'}`}>
            {md?.metered_kwh != null ? fmtNum(md.metered_kwh) : '—'}
          </td>
        )
      })}
      {/* Available Energy (calculated, read-only) */}
      <td className="px-2 py-2 text-right tabular-nums text-slate-600 border-r-2 border-purple-100">{fmtNum(m.total_available_kwh)}</td>
      {/* Aggregated */}
      <td className="px-2 py-2 text-right tabular-nums text-slate-700 font-medium">{fmtNum(m.total_energy_kwh)}</td>
      <td className="px-2 py-2 text-right tabular-nums text-slate-600">
        {canEdit ? (
          <InlinePerfEdit value={m.actual_ghi_irradiance} billingMonth={m.billing_month} field="ghi_irradiance_wm2" projectId={projectId!} onSaved={onSaved!} />
        ) : fmtNum(m.actual_ghi_irradiance, 1)}
      </td>
      <td className="px-2 py-2 text-right tabular-nums text-slate-700 font-medium">{fmtPct(m.actual_pr)}</td>
      <td className="px-2 py-2 text-right tabular-nums text-slate-600 border-r-2 border-slate-200">
        {canEdit ? (
          <InlinePerfEdit value={m.actual_availability_pct} billingMonth={m.billing_month} field="actual_availability_pct" projectId={projectId!} onSaved={onSaved!} />
        ) : (m.actual_availability_pct != null ? `${m.actual_availability_pct.toFixed(1)}%` : '—')}
      </td>
      {/* Comparison (calculated, read-only) */}
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
