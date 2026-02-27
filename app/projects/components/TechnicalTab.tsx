'use client'

import { useMemo, useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { IS_DEMO } from '@/lib/demoMode'
import { adminClient } from '@/lib/api/adminClient'
import { ProjectTableTab, type Column } from './ProjectTableTab'
import { CollapsibleSection } from './CollapsibleSection'

interface TechnicalTabProps {
  project: Record<string, unknown>
  contracts: Record<string, unknown>[]
  assets: Record<string, unknown>[]
  meters: Record<string, unknown>[]
  tariffs: Record<string, unknown>[]
  forecasts: Record<string, unknown>[]
  guarantees: Record<string, unknown>[]
  assetColumns: Column[]
  meterColumns: Column[]
  forecastColumns: Column[]
  guaranteeColumns: Column[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
}

function formatNumber(v: unknown): string {
  if (v == null || v === '') return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
}

function unique(arr: string[]): string[] {
  return [...new Set(arr)]
}

function getLocationUrl(raw: unknown): string | null {
  if (!raw || typeof raw !== 'string') return null
  if (raw.startsWith('http')) return raw
  const coords = raw.trim()
  return `https://www.google.com/maps?q=${encodeURIComponent(coords)}`
}

const fmtNum2 = (v: number) => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const SUM_KEYS = ['forecast_energy_kwh', 'forecast_ghi_irradiance', 'forecast_poa_irradiance'] as const
const AVG_KEY = 'forecast_pr'

export function TechnicalTab({ project, contracts, assets, meters, tariffs, forecasts: rawForecasts, guarantees, assetColumns, meterColumns, forecastColumns, guaranteeColumns, projectId, onSaved, editMode }: TechnicalTabProps) {
  // Derive summary values from project + assets + contracts
  const pvModules = assets.filter((a) => {
    const code = (a.asset_type_code as string) ?? ''
    return code === 'pv_module' || code === 'PV_MODULE'
  })
  const inverters = assets.filter((a) => {
    const code = (a.asset_type_code as string) ?? ''
    return code === 'inverter' || code === 'INVERTER'
  })

  const dcCapacity = project.installed_dc_capacity_kwp
  const acCapacity = project.installed_ac_capacity_kw
  const locationRaw = project.installation_location_url as string | null
  const locationUrl = getLocationUrl(locationRaw)

  const pvQty = pvModules.reduce((sum, a) => sum + (Number(a.quantity) || 0), 0)
  const pvModels = pvModules.map((a) => a.model as string).filter(Boolean).join(', ') || '—'
  const invQty = inverters.reduce((sum, a) => sum + (Number(a.quantity) || 0), 0)
  const invModels = inverters.map((a) => a.model as string).filter(Boolean).join(', ') || '—'

  // Annual Specific Yield from first tariff's logic_parameters
  const lp = (tariffs[0]?.logic_parameters as Record<string, unknown>) ?? {}
  const annualSpecificYield = typeof lp.annual_specific_yield === 'number' ? lp.annual_specific_yield : null

  // Interconnection voltage from project.technical_specs JSONB
  const techSpecs = (project.technical_specs as Record<string, unknown>) ?? {}
  const interconnectionVoltage = techSpecs.interconnection_voltage_kv

  // Billing meter aggregations
  const billingMeters = meters.filter((m) => {
    const code = (m.meter_type_code as string) ?? ''
    return code === 'REVENUE' || code === 'revenue'
  })
  const meterModels = unique(billingMeters.map((m) => m.model as string).filter(Boolean)).join(', ') || '—'
  const meterLocations = billingMeters.map((m) => m.location_description as string).filter(Boolean).join(', ') || '—'
  const meterSerials = billingMeters.map((m) => m.serial_number as string).filter(Boolean).join(', ') || '—'
  const meteringTypes = unique(billingMeters.map((m) => m.metering_type as string).filter(Boolean)).join(', ') || '—'

  // Forecasts: sort Jan → Dec
  const forecasts = useMemo(() =>
    [...rawForecasts].sort((a, b) => {
      const da = new Date(String(a.forecast_month ?? ''))
      const db = new Date(String(b.forecast_month ?? ''))
      return da.getTime() - db.getTime()
    }),
    [rawForecasts],
  )

  // Guarantees subtitle info
  const fxRule = guarantees.find((g) => g.shortfall_cap_fx_rule != null)?.shortfall_cap_fx_rule
  const guaranteePct = guarantees.length > 0 ? Number(guarantees[0].guarantee_pct_of_p50) : null
  const shortfallCap = guarantees.length > 0 ? Number(guarantees[0].shortfall_cap_usd) : null

  // Degradation
  const [applyingDegradation, setApplyingDegradation] = useState(false)
  const degradationPct = useMemo(() => {
    if (!tariffs?.length) return null
    const lpObj = (tariffs[0].logic_parameters ?? {}) as Record<string, unknown>
    return lpObj.degradation_pct != null ? Number(lpObj.degradation_pct) : null
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
    const footer: Record<string, React.ReactNode> = { forecast_month: 'Annual' }
    for (const key of SUM_KEYS) {
      const total = forecasts.reduce((sum, r) => sum + (Number(r[key]) || 0), 0)
      footer[key] = fmtNum2(total)
    }
    const prValues = forecasts.map((r) => Number(r[AVG_KEY])).filter((v) => !isNaN(v) && v > 0)
    if (prValues.length > 0) {
      const avg = prValues.reduce((s, v) => s + v, 0) / prValues.length
      footer[AVG_KEY] = `${fmtNum2(avg * 100)} (avg)`
    }
    return footer
  }, [forecasts])

  const summaryRows: { label: string; detail: string; value: React.ReactNode; indent?: boolean }[] = [
    {
      label: 'Installed DC capacity',
      detail: 'Installed capacity in kWp',
      value: `${formatNumber(dcCapacity)} kWp`,
    },
    {
      label: 'Number of PV modules',
      detail: '# of modules',
      value: formatNumber(pvQty || null),
      indent: true,
    },
    {
      label: 'PV module model(s)',
      detail: 'Comma separated',
      value: pvModels,
      indent: true,
    },
    {
      label: 'Installed AC capacity',
      detail: 'Installed capacity in kW of inverters',
      value: `${formatNumber(acCapacity)} kW`,
    },
    {
      label: 'Number of inverter modules',
      detail: '# of inverter modules',
      value: formatNumber(invQty || null),
      indent: true,
    },
    {
      label: 'Inverter make and model(s)',
      detail: 'Comma separated',
      value: invModels,
      indent: true,
    },
    {
      label: 'Annual Specific Yield',
      detail: 'Contract Year 1 yield per kWp',
      value: annualSpecificYield != null ? `${formatNumber(annualSpecificYield)} kWh/kWp` : '—',
    },
    {
      label: 'Installation location',
      detail: 'Google Maps URL',
      value: locationUrl ? (
        <a href={locationUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline">
          {locationRaw}
          <ExternalLink className="h-3 w-3" />
        </a>
      ) : '—',
    },
    {
      label: 'Interconnection voltage(s)',
      detail: 'Voltage in kV',
      value: interconnectionVoltage != null ? `${formatNumber(interconnectionVoltage)} kV` : '—',
    },
    {
      label: 'Billing meter model(s)',
      detail: 'Comma separated',
      value: meterModels,
    },
    {
      label: 'Billing meter location(s)',
      detail: 'Comma separated',
      value: meterLocations,
      indent: true,
    },
    {
      label: 'Billing meter serial number(s)',
      detail: 'SN #',
      value: meterSerials,
      indent: true,
    },
    {
      label: 'Type of metering for billing',
      detail: 'Net or export only',
      value: meteringTypes,
      indent: true,
    },
  ]

  return (
    <div className="space-y-8">
      {/* Technical Summary */}
      <CollapsibleSection title="Technical Summary">
        <div className="border border-slate-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-4 py-2 font-medium text-slate-600 w-1/3">Description</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600 w-1/3">Guidance</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600 w-1/3">Value</th>
              </tr>
            </thead>
            <tbody>
              {summaryRows.map((row) => (
                <tr key={row.label} className="border-b border-slate-100 last:border-b-0">
                  <td className={`px-4 py-2.5 text-slate-800 ${row.indent ? 'pl-8 text-slate-600' : 'font-medium'}`}>
                    {row.indent ? `- ${row.label}` : row.label}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{row.detail}</td>
                  <td className="px-4 py-2.5 text-slate-900 font-mono text-xs">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* Assets Table */}
      <CollapsibleSection title="Assets">
        <ProjectTableTab
          data={assets}
          columns={assetColumns}
          emptyMessage="No assets found"
          entity="assets"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </CollapsibleSection>

      {/* Meters Table */}
      <CollapsibleSection title="Meters">
        <ProjectTableTab
          data={meters}
          columns={meterColumns}
          emptyMessage="No meters found"
          entity="meters"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </CollapsibleSection>

      {/* Production Forecasts */}
      <CollapsibleSection
        title="Production Forecasts"
        subtitle={editMode && !IS_DEMO && degradationPct != null ? (
          <div className="mb-3">
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
        ) : undefined}
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

      {/* Production Guarantees */}
      <CollapsibleSection
        title="Production Guarantees (Required Energy Output)"
        subtitle={
          (guaranteePct != null || shortfallCap != null || fxRule) ? (
            <p className="text-xs text-slate-500 mb-3">
              {[
                guaranteePct != null && `Guarantee: ${fmtNum2(guaranteePct)}%`,
                shortfallCap != null && `Shortfall Cap: $${fmtNum2(shortfallCap)}`,
                fxRule && `FX Rule: ${String(fxRule)}`,
              ].filter(Boolean).join(' · ')}
            </p>
          ) : undefined
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
