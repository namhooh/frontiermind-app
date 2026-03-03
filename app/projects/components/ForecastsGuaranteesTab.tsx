'use client'

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { IS_DEMO } from '@/lib/demoMode'
import { ProjectTableTab, type Column } from './ProjectTableTab'
import { adminClient } from '@/lib/api/adminClient'
import { fmtNum } from '@/app/projects/utils/formatters'

interface ForecastsGuaranteesTabProps {
  forecasts: Record<string, unknown>[]
  guarantees: Record<string, unknown>[]
  forecastColumns: Column[]
  guaranteeColumns: Column[]
  tariffs?: Record<string, unknown>[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
}

function CollapsibleSection({ title, subtitle, defaultOpen = true, children }: { title: string; subtitle?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-3">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex-shrink-0 p-0.5 rounded hover:bg-slate-100 transition-colors group"
        >
          {open
            ? <ChevronDown className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />
            : <ChevronRight className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />}
        </button>
        <h3 className="text-sm font-medium text-slate-700 select-text cursor-text">{title}</h3>
      </div>
      {!open ? null : (
        <>
          {subtitle}
          {children}
        </>
      )}
    </div>
  )
}

const fmtNum2 = (v: number) => fmtNum(v, 2)

// Keys that should be summed; PR is averaged instead
const SUM_KEYS = ['forecast_energy_kwh', 'forecast_ghi_irradiance', 'forecast_poa_irradiance'] as const
const AVG_KEY = 'forecast_pr'

export function ForecastsGuaranteesTab({ forecasts: rawForecasts, guarantees, forecastColumns, guaranteeColumns, tariffs, projectId, onSaved, editMode }: ForecastsGuaranteesTabProps) {
  // Sort forecasts Jan → Dec
  const forecasts = useMemo(() =>
    [...rawForecasts].sort((a, b) => {
      const da = new Date(String(a.forecast_month ?? ''))
      const db = new Date(String(b.forecast_month ?? ''))
      return da.getTime() - db.getTime()
    }),
    [rawForecasts],
  )
  const fxRule = guarantees.find((g) => g.shortfall_cap_fx_rule != null)?.shortfall_cap_fx_rule
  const guaranteePct = guarantees.length > 0 ? Number(guarantees[0].guarantee_pct_of_p50) : null
  const shortfallCap = guarantees.length > 0 ? Number(guarantees[0].shortfall_cap_usd) : null
  const [applyingDegradation, setApplyingDegradation] = useState(false)

  // Extract degradation_pct from the primary tariff's logic_parameters
  const degradationPct = useMemo(() => {
    if (!tariffs?.length) return null
    const lp = (tariffs[0].logic_parameters ?? {}) as Record<string, unknown>
    return lp.degradation_pct != null ? Number(lp.degradation_pct) : null
  }, [tariffs])

  const handleApplyDegradation = async () => {
    if (!projectId) return
    setApplyingDegradation(true)
    try {
      const result = await adminClient.applyDegradation(projectId)
      toast.success(`Degradation applied to ${result.updated_rows} forecast rows`)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to apply degradation')
    } finally {
      setApplyingDegradation(false)
    }
  }

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
      <CollapsibleSection
        title="Production Forecasts"
        subtitle={editMode && !IS_DEMO && degradationPct != null ? (
          <div className="mb-3 ml-5.5">
            <button
              type="button"
              onClick={handleApplyDegradation}
              disabled={applyingDegradation}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors disabled:opacity-50"
            >
              {applyingDegradation && <Loader2 className="h-3 w-3 animate-spin" />}
              Apply Degradation ({(degradationPct * 100).toFixed(2)}%)
            </button>
          </div>
        ) : null}
      >
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
        subtitle={
          (guaranteePct != null || shortfallCap != null || fxRule) ? (
            <p className="text-xs text-slate-500 mb-3 ml-5.5">
              {[
                guaranteePct != null && `Guarantee: ${fmtNum2(guaranteePct)}%`,
                shortfallCap != null && `Shortfall Cap: $${fmtNum2(shortfallCap)}`,
                fxRule && `FX Rule: ${String(fxRule)}`,
              ].filter(Boolean).join(' · ')}
            </p>
          ) : null
        }
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
