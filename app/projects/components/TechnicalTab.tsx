'use client'

import { ExternalLink } from 'lucide-react'
import { ProjectTableTab, type Column } from './ProjectTableTab'

interface TechnicalTabProps {
  project: Record<string, unknown>
  contracts: Record<string, unknown>[]
  assets: Record<string, unknown>[]
  meters: Record<string, unknown>[]
  assetColumns: Column[]
  meterColumns: Column[]
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

export function TechnicalTab({ project, contracts, assets, meters, assetColumns, meterColumns, projectId, onSaved, editMode }: TechnicalTabProps) {
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

  // Interconnection voltage from first contract that has it
  const interconnectionVoltage = contracts.find((c) => c.interconnection_voltage_kv != null)?.interconnection_voltage_kv

  // Billing meter aggregations
  const billingMeters = meters.filter((m) => {
    const code = (m.meter_type_code as string) ?? ''
    return code === 'REVENUE' || code === 'revenue'
  })
  const meterModels = unique(billingMeters.map((m) => m.model as string).filter(Boolean)).join(', ') || '—'
  const meterLocations = billingMeters.map((m) => m.location_description as string).filter(Boolean).join(', ') || '—'
  const meterSerials = billingMeters.map((m) => m.serial_number as string).filter(Boolean).join(', ') || '—'
  const meteringTypes = unique(billingMeters.map((m) => m.metering_type as string).filter(Boolean)).join(', ') || '—'

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
      <div>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Technical Summary</h3>
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
      </div>

      {/* Assets Table */}
      <div>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Assets</h3>
        <ProjectTableTab
          data={assets}
          columns={assetColumns}
          emptyMessage="No assets found"
          entity="assets"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </div>

      {/* Meters Table */}
      <div>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Meters</h3>
        <ProjectTableTab
          data={meters}
          columns={meterColumns}
          emptyMessage="No meters found"
          entity="meters"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </div>
    </div>
  )
}
