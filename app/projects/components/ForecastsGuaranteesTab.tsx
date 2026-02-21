'use client'

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { ProjectTableTab, type Column } from './ProjectTableTab'

interface ForecastsGuaranteesTabProps {
  forecasts: Record<string, unknown>[]
  guarantees: Record<string, unknown>[]
  forecastColumns: Column[]
  guaranteeColumns: Column[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
}

function CollapsibleSection({ title, subtitle, defaultOpen = true, children }: { title: string; subtitle?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 w-full text-left group mb-3"
      >
        {open
          ? <ChevronDown className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />
          : <ChevronRight className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />}
        <h3 className="text-sm font-medium text-slate-700">{title}</h3>
      </button>
      {!open ? null : (
        <>
          {subtitle}
          {children}
        </>
      )}
    </div>
  )
}

const fmtNum2 = (v: number) => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Keys that should be summed; PR is averaged instead
const SUM_KEYS = ['forecast_energy_kwh', 'forecast_ghi_irradiance', 'forecast_poa_irradiance'] as const
const AVG_KEY = 'forecast_pr'

export function ForecastsGuaranteesTab({ forecasts, guarantees, forecastColumns, guaranteeColumns, projectId, onSaved, editMode }: ForecastsGuaranteesTabProps) {
  const fxRule = guarantees.find((g) => g.shortfall_cap_fx_rule != null)?.shortfall_cap_fx_rule

  const forecastFooter = useMemo(() => {
    if (forecasts.length === 0) return undefined
    const footer: Record<string, React.ReactNode> = {
      forecast_month: 'Annual',
    }
    for (const key of SUM_KEYS) {
      const total = forecasts.reduce((sum, r) => sum + (Number(r[key]) || 0), 0)
      footer[key] = fmtNum2(total)
    }
    // PR: weighted average would be ideal, but simple average matches the spec
    const prValues = forecasts.map((r) => Number(r[AVG_KEY])).filter((v) => !isNaN(v) && v > 0)
    if (prValues.length > 0) {
      const avg = prValues.reduce((s, v) => s + v, 0) / prValues.length
      footer[AVG_KEY] = `${fmtNum2(avg * 100)} (avg)`
    }
    return footer
  }, [forecasts])

  return (
    <div className="space-y-8">
      <CollapsibleSection title="Production Forecasts">
        <ProjectTableTab
          data={forecasts}
          columns={forecastColumns}
          emptyMessage="No forecasts found"
          entity="forecasts"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
          footerRow={forecastFooter}
        />
      </CollapsibleSection>

      <CollapsibleSection
        title="Production Guarantees (Required Energy Output)"
        subtitle={fxRule ? <p className="text-xs text-slate-500 mb-3 ml-5.5">FX Rule: {String(fxRule)}</p> : null}
      >
        <ProjectTableTab
          data={guarantees}
          columns={guaranteeColumns}
          emptyMessage="No guarantees found"
          entity="guarantees"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </CollapsibleSection>
    </div>
  )
}
