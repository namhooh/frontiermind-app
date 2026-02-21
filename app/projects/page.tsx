'use client'

import { useState, useCallback, useMemo } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Pencil, PencilOff } from 'lucide-react'
import { toast } from 'sonner'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/app/components/ui/tabs'
import { adminClient, type ProjectDashboardResponse } from '@/lib/api/adminClient'
import { ProjectSidebar } from './components/ProjectSidebar'
import { ProjectOverviewTab } from './components/ProjectOverviewTab'
import { ProjectTableTab, type Column } from './components/ProjectTableTab'
import { PricingTariffsTab } from './components/PricingTariffsTab'
import { TechnicalTab } from './components/TechnicalTab'
import { ForecastsGuaranteesTab } from './components/ForecastsGuaranteesTab'

export default function ProjectsPage() {
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [dashboard, setDashboard] = useState<ProjectDashboardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editMode, setEditMode] = useState(false)

  const refreshDashboard = useCallback(async () => {
    if (!selectedProjectId) return
    try {
      const data = await adminClient.getProjectDashboard(selectedProjectId)
      setDashboard(data)
    } catch {
      // Silently fail on refresh — data shown is just stale
    }
  }, [selectedProjectId])

  async function handleSelectProject(projectId: number) {
    if (projectId === selectedProjectId) return
    setSelectedProjectId(projectId)
    setLoading(true)
    setError(null)
    try {
      const data = await adminClient.getProjectDashboard(projectId)
      setDashboard(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load project data')
      setDashboard(null)
    } finally {
      setLoading(false)
    }
  }

  // Build lookup options from dashboard response
  const lookups = dashboard?.lookups ?? {}
  const toOpts = (items: { id: number; code?: string; name: string }[]) =>
    (items ?? []).map((t) => ({ value: t.id, label: t.name }))
  const contractTypeOpts = useMemo(() => toOpts(lookups.contract_types), [lookups.contract_types])
  const contractStatusOpts = useMemo(() => toOpts(lookups.contract_statuses), [lookups.contract_statuses])
  const counterpartyOpts = useMemo(() => toOpts(lookups.counterparties), [lookups.counterparties])
  const assetTypeOpts = useMemo(() => toOpts(lookups.asset_types), [lookups.asset_types])
  const meterTypeOpts = useMemo(() => toOpts(lookups.meter_types), [lookups.meter_types])


  // Column definitions with editable config
  const contractColumns: Column[] = [
    { key: 'name', label: 'Name', editable: true, type: 'text' },
    { key: 'contract_type_name', label: 'Type', editable: true, type: 'select', editKey: 'contract_type_id', options: contractTypeOpts },
    { key: 'contract_status_name', label: 'Status', editable: true, type: 'select', editKey: 'contract_status_id', options: contractStatusOpts },
    { key: 'counterparty_name', label: 'Counterparty', editable: true, type: 'select', editKey: 'counterparty_id', options: counterpartyOpts },
    { key: 'effective_date', label: 'Effective Date', editable: true, type: 'date' },
    { key: 'end_date', label: 'End Date', editable: true, type: 'date' },
    { key: 'contract_term_years', label: 'Term (yr)', editable: true, type: 'number' },
    { key: 'payment_terms', label: 'Payment Terms', editable: true, type: 'text' },
    { key: 'has_amendments', label: 'Amendments', editable: true, type: 'boolean' },
  ]

  const assetColumns: Column[] = [
    { key: 'asset_type_name', label: 'Type', editable: true, type: 'select', editKey: 'asset_type_id', options: assetTypeOpts },
    { key: 'name', label: 'Name', editable: true, type: 'text' },
    { key: 'model', label: 'Model', editable: true, type: 'text' },
    { key: 'capacity', label: 'Capacity', editable: true, type: 'number' },
    { key: 'capacity_unit', label: 'Unit', editable: true, type: 'text' },
    { key: 'quantity', label: 'Qty', editable: true, type: 'number' },
  ]

  const meterColumns: Column[] = [
    { key: 'meter_type_name', label: 'Type', editable: true, type: 'select', editKey: 'meter_type_id', options: meterTypeOpts },
    { key: 'model', label: 'Model', editable: true, type: 'text' },
    { key: 'serial_number', label: 'Serial Number', editable: true, type: 'text' },
    { key: 'location_description', label: 'Location', editable: true, type: 'text' },
    { key: 'metering_type', label: 'Metering Type', editable: true, type: 'text' },
  ]

  const MONTH_SHORT = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'] as const
  const fmtMonth = (v: unknown) => {
    if (v == null) return '—'
    const d = new Date(String(v))
    return isNaN(d.getTime()) ? String(v) : MONTH_SHORT[d.getUTCMonth()]
  }
  const fmtNum2 = (v: unknown) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const fmtPR = (v: unknown) => v == null ? '—' : (Number(v) * 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const forecastColumns: Column[] = [
    { key: 'forecast_month', label: 'Month', editable: true, type: 'date', editKey: 'forecast_month', format: fmtMonth },
    { key: 'forecast_energy_kwh', label: 'Energy (kWh)', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_ghi_irradiance', label: 'GHI Irradiance', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_poa_irradiance', label: 'POA Irradiance', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_pr', label: 'PR (%)', editable: true, type: 'number', format: fmtPR },
    { key: 'forecast_source', label: 'Source', editable: true, type: 'text' },
  ]

  const guaranteeColumns: Column[] = [
    { key: 'operating_year', label: 'Op. Year', editable: true, type: 'number' },
    { key: 'year_start_date', label: 'Start', editable: true, type: 'date' },
    { key: 'year_end_date', label: 'End', editable: true, type: 'date' },
    { key: 'p50_annual_kwh', label: 'P50 (kWh)', editable: true, type: 'number', format: (v) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    { key: 'guarantee_pct_of_p50', label: 'Guarantee %', editable: true, type: 'number', format: (v) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    { key: 'guaranteed_kwh', label: 'Guaranteed (kWh)', editable: true, type: 'number', format: (v) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    { key: 'shortfall_cap_usd', label: 'Shortfall Cap ($)', editable: true, type: 'number', format: (v) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
  ]

  const contactColumns: Column[] = [
    { key: 'full_name', label: 'Full Name', editable: true, type: 'text' },
    { key: 'email', label: 'Email', editable: true, type: 'text' },
    { key: 'phone', label: 'Phone', editable: true, type: 'text' },
    { key: 'role', label: 'Role', editable: true, type: 'text' },
    { key: 'include_in_invoice_email', label: 'Invoice', editable: true, type: 'boolean' },
    { key: 'escalation_only', label: 'Escalation', editable: true, type: 'boolean' },
  ]

  const projectId = selectedProjectId ?? undefined

  const handleAddContact = useCallback(async (fields: Record<string, unknown>) => {
    if (!dashboard) return
    const contracts = dashboard.contracts
    const counterpartyId = contracts[0]?.counterparty_id as number | undefined
    const organizationId = dashboard.project.organization_id as number
    if (!counterpartyId) {
      toast.error('No counterparty found — add a contract first')
      return
    }
    await adminClient.addContact({
      counterparty_id: counterpartyId,
      organization_id: organizationId,
      full_name: fields.full_name as string | undefined,
      email: fields.email as string | undefined,
      phone: fields.phone as string | undefined,
      role: fields.role as string | undefined,
      include_in_invoice_email: fields.include_in_invoice_email as boolean | undefined,
      escalation_only: fields.escalation_only as boolean | undefined,
    })
    await refreshDashboard()
  }, [dashboard, refreshDashboard])

  const handleRemoveContact = useCallback(async (id: number) => {
    await adminClient.removeContact(id)
    await refreshDashboard()
    toast('Contact removed', { duration: 3000 })
  }, [refreshDashboard])

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Project Dashboard</h1>
            <p className="text-sm text-slate-500 mt-1">
              View and edit onboarded project data, contracts, and technical details
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setEditMode(!editMode)}
              className={`inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border transition-colors ${
                editMode
                  ? 'bg-red-600 text-white border-red-600 hover:bg-red-700'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {editMode ? <PencilOff className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
              {editMode ? 'Finish Editing' : 'Edit'}
            </button>
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Home
            </Link>
          </div>
        </div>

        {/* Layout: Sidebar + Main Content */}
        <div className="flex gap-6">
          {/* Sidebar */}
          <div className="w-64 shrink-0">
            <div className="bg-white rounded-lg border border-slate-200 p-3">
              <ProjectSidebar
                selectedProjectId={selectedProjectId}
                onSelectProject={handleSelectProject}
              />
            </div>
          </div>

          {/* Main Content */}
          <div className="flex-1 min-w-0">
            {!selectedProjectId && (
              <div className="bg-white rounded-lg border border-slate-200 flex items-center justify-center h-64">
                <p className="text-sm text-slate-400">Select a project to view its data</p>
              </div>
            )}

            {selectedProjectId && loading && (
              <div className="bg-white rounded-lg border border-slate-200 flex items-center justify-center h-64">
                <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
              </div>
            )}

            {selectedProjectId && error && (
              <div className="bg-white rounded-lg border border-slate-200 p-6">
                <p className="text-sm text-red-600">{error}</p>
              </div>
            )}

            {selectedProjectId && !loading && !error && dashboard && (
              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="pricing-tariffs">Pricing & Tariffs</TabsTrigger>
                  <TabsTrigger value="technical">Technical</TabsTrigger>
                  <TabsTrigger value="forecasts-guarantees">Forecasts & Guarantees</TabsTrigger>
                  <TabsTrigger value="contacts">Contacts</TabsTrigger>
                </TabsList>

                <div className="mt-4 bg-white rounded-lg border border-slate-200 p-6">
                  <TabsContent value="overview">
                    <ProjectOverviewTab
                      data={dashboard}
                      contractColumns={contractColumns}
                      projectId={projectId}
                      onSaved={refreshDashboard}
                      editMode={editMode}
                    />
                  </TabsContent>

                  <TabsContent value="pricing-tariffs">
                    <PricingTariffsTab
                      data={dashboard}
                      onSaved={refreshDashboard}
                      editMode={editMode}
                      projectId={projectId}
                    />
                  </TabsContent>

                  <TabsContent value="technical">
                    <TechnicalTab
                      project={dashboard.project}
                      contracts={dashboard.contracts}
                      assets={dashboard.assets}
                      meters={dashboard.meters}
                      assetColumns={assetColumns}
                      meterColumns={meterColumns}
                      projectId={projectId}
                      onSaved={refreshDashboard}
                      editMode={editMode}
                    />
                  </TabsContent>

                  <TabsContent value="forecasts-guarantees">
                    <ForecastsGuaranteesTab
                      forecasts={dashboard.forecasts}
                      guarantees={dashboard.guarantees}
                      forecastColumns={forecastColumns}
                      guaranteeColumns={guaranteeColumns}
                      projectId={projectId}
                      onSaved={refreshDashboard}
                      editMode={editMode}
                    />
                  </TabsContent>


                  <TabsContent value="contacts">
                    <ProjectTableTab
                      data={dashboard.contacts}
                      columns={contactColumns}
                      emptyMessage="No contacts found"
                      entity="contacts"
                      onSaved={refreshDashboard}
                      editMode={editMode}
                      onAdd={handleAddContact}
                      onRemove={handleRemoveContact}
                      addLabel="Add Contact"
                    />
                  </TabsContent>


                </div>
              </Tabs>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
