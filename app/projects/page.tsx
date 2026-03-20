'use client'

import { useState, useCallback, useEffect, useMemo, Suspense, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { ArrowLeft, Loader2, Pencil, PencilOff, PanelLeftClose, PanelLeftOpen, Clock } from 'lucide-react'
import { IS_DEMO } from '@/lib/demoMode'
import { SignOutButton } from '@/app/components/SignOutButton'
import { PendingChangesPanel } from './components/PendingChangesPanel'
import { toast } from 'sonner'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/app/components/ui/tabs'
import { adminClient, type ProjectDashboardResponse, type MRPObservation, type SubmissionTokenItem } from '@/lib/api/adminClient'
import { createClient } from '@/lib/supabase/client'
import { fmtNum } from './utils/formatters'
import { toOpts } from './utils/constants'
import { createClientResourceCache } from './utils/clientResourceCache'
import { ProjectSidebar } from './components/ProjectSidebar'
import type { Column } from './components/ProjectTableTab'
// ForecastsGuaranteesTab — content moved into TechnicalTab
import { PortfolioHome } from './components/PortfolioHome'
// import { SpreadsheetTab } from './components/SpreadsheetTab'

type DashboardTabValue = 'overview' | 'pricing-tariffs' | 'technical' | 'performance' | 'monthly-billing'

type CachedMrpData = {
  monthly: MRPObservation[]
  annual: MRPObservation[]
  tokens: SubmissionTokenItem[]
}

const PROJECT_DASHBOARD_CACHE_TTL_MS = 5 * 60 * 1000
const MRP_CACHE_TTL_MS = 5 * 60 * 1000

const projectDashboardCache = createClientResourceCache<ProjectDashboardResponse>(PROJECT_DASHBOARD_CACHE_TTL_MS)
const mrpDataCache = createClientResourceCache<CachedMrpData>(MRP_CACHE_TTL_MS)

function TabPanelFallback() {
  return (
    <div className="flex items-center justify-center h-40">
      <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
    </div>
  )
}

const ProjectOverviewTab = dynamic(
  () => import('./components/ProjectOverviewTab').then((mod) => mod.ProjectOverviewTab),
  { loading: TabPanelFallback },
)

const PricingTariffsTab = dynamic(
  () => import('./components/PricingTariffsTab').then((mod) => mod.PricingTariffsTab),
  { loading: TabPanelFallback },
)

const TechnicalTab = dynamic(
  () => import('./components/TechnicalTab').then((mod) => mod.TechnicalTab),
  { loading: TabPanelFallback },
)

const MonthlyBillingTab = dynamic(
  () => import('./components/MonthlyBillingTab').then((mod) => mod.MonthlyBillingTab),
  { loading: TabPanelFallback },
)

const PlantPerformanceTab = dynamic(
  () => import('./components/PlantPerformanceTab').then((mod) => mod.PlantPerformanceTab),
  { loading: TabPanelFallback },
)

// Stable format functions — defined outside component to avoid re-creation on every render
const MONTH_SHORT = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'] as const
const fmtMonthCol = (v: unknown) => {
  if (v == null) return '—'
  const d = new Date(String(v))
  if (isNaN(d.getTime())) return String(v)
  return `${MONTH_SHORT[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
}
const fmtNum2 = (v: unknown) => v == null ? '—' : fmtNum(Number(v), 2)
const fmtPR = (v: unknown) => v == null ? '—' : (Number(v) * 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDegradation = (v: unknown) => v == null ? '—' : Number(v).toFixed(5)
const fmtLocale2 = (v: unknown) => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsPageContent />
    </Suspense>
  )
}

function ProjectsPageContent() {
  const searchParams = useSearchParams()
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [dashboard, setDashboard] = useState<ProjectDashboardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [mrpMonthly, setMrpMonthly] = useState<MRPObservation[]>([])
  const [mrpAnnual, setMrpAnnual] = useState<MRPObservation[]>([])
  const [mrpTokens, setMrpTokens] = useState<SubmissionTokenItem[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [activeTab, setActiveTab] = useState<DashboardTabValue>('overview')
  const [mountedTabs, setMountedTabs] = useState<Set<DashboardTabValue>>(() => new Set(['overview']))
  const projectRequestRef = useRef(0)
  const [userRole, setUserRole] = useState<string>('viewer')
  const [userId, setUserId] = useState<string>('')
  const [pendingCount, setPendingCount] = useState(0)
  const [pendingPanelOpen, setPendingPanelOpen] = useState(false)
  const [orgId, setOrgId] = useState<number | undefined>()

  // Resolve org and user role from Supabase session
  useEffect(() => {
    async function resolveOrg() {
      if (IS_DEMO) {
        adminClient.setOrganizationId(1)
        setOrgId(1)
        return
      }
      try {
        const supabase = createClient()
        const { data: { user } } = await supabase.auth.getUser()
        if (user) {
          setUserId(user.id)
          const { data } = await supabase
            .from('role')
            .select('organization_id, role_type')
            .eq('user_id', user.id)
            .eq('is_active', true)
            .limit(1)
            .single()
          if (data) {
            adminClient.setOrganizationId(data.organization_id)
            setOrgId(data.organization_id)
            setUserRole(data.role_type)
          }
        }
      } catch {
        // Fallback: org 1 for dev
        if (process.env.NODE_ENV === 'development') { adminClient.setOrganizationId(1); setOrgId(1) }
      }
    }
    resolveOrg()
  }, [])

  const resetTabState = useCallback(() => {
    setActiveTab('overview')
    setMountedTabs(new Set<DashboardTabValue>(['overview']))
  }, [])

  const applyMrpData = useCallback((data: CachedMrpData) => {
    setMrpMonthly(data.monthly)
    setMrpAnnual(data.annual)
    setMrpTokens(data.tokens)
  }, [])

  const clearMrpData = useCallback(() => {
    setMrpMonthly([])
    setMrpAnnual([])
    setMrpTokens([])
  }, [])

  const loadProjectDashboard = useCallback(async (projectId: number, force = false) => {
    const cacheKey = String(projectId)
    if (force) projectDashboardCache.invalidate(cacheKey)
    if (force) {
      const fresh = await adminClient.getProjectDashboard(projectId)
      return projectDashboardCache.set(cacheKey, fresh)
    }
    return projectDashboardCache.getOrLoad(cacheKey, () => adminClient.getProjectDashboard(projectId))
  }, [])

  /** Fetch MRP post-COD data for a given project + org */
  const fetchMrpData = useCallback(async (pid: number, orgId: number, force = false) => {
    const cacheKey = `${pid}:${orgId}`
    if (force) mrpDataCache.invalidate(cacheKey)
    if (force) {
      const [, monthlyRes, annualRes, tokensRes] = await Promise.all([
        adminClient.refreshMRP(pid, orgId).catch(() => {}),
        adminClient.listMRPObservations(pid, orgId, { observation_type: 'monthly' })
          .catch(() => ({ observations: [] as MRPObservation[], total: 0 })),
        adminClient.listMRPObservations(pid, orgId, { observation_type: 'annual' })
          .catch(() => ({ observations: [] as MRPObservation[], total: 0 })),
        adminClient.listTokens(orgId, { project_id: pid, submission_type: 'mrp_upload', include_expired: true })
          .catch((err) => {
            console.error('Failed to fetch MRP tokens:', err)
            return { tokens: [] as SubmissionTokenItem[] }
          }),
      ])
      return mrpDataCache.set(cacheKey, {
        monthly: monthlyRes.observations.filter((o) => o.operating_year !== 0),
        annual: annualRes.observations,
        tokens: tokensRes.tokens,
      })
    }

    return mrpDataCache.getOrLoad(cacheKey, async () => {
      const [, monthlyRes, annualRes, tokensRes] = await Promise.all([
        adminClient.refreshMRP(pid, orgId).catch(() => {}),
        adminClient.listMRPObservations(pid, orgId, { observation_type: 'monthly' })
          .catch(() => ({ observations: [] as MRPObservation[], total: 0 })),
        adminClient.listMRPObservations(pid, orgId, { observation_type: 'annual' })
          .catch(() => ({ observations: [] as MRPObservation[], total: 0 })),
        adminClient.listTokens(orgId, { project_id: pid, submission_type: 'mrp_upload', include_expired: true })
          .catch((err) => {
            console.error('Failed to fetch MRP tokens:', err)
            return { tokens: [] as SubmissionTokenItem[] }
          }),
      ])
      return {
        monthly: monthlyRes.observations.filter((o) => o.operating_year !== 0),
        annual: annualRes.observations,
        tokens: tokensRes.tokens,
      }
    })
  }, [])

  // Pending change request count (org-wide, not per-project)
  const refreshPendingCount = useCallback(() => {
    if (!orgId) return
    adminClient.getChangeRequestSummary()
      .then((s) => setPendingCount(s.pending + s.conflicted))
      .catch(() => {})
  }, [orgId])

  useEffect(() => {
    refreshPendingCount()
  }, [refreshPendingCount])

  const refreshDashboard = useCallback(async (options?: { force?: boolean; includeMrp?: boolean }) => {
    if (!selectedProjectId) return
    try {
      const data = await loadProjectDashboard(selectedProjectId, options?.force)
      setDashboard(data)
      if (options?.includeMrp) {
        const orgId = data.project.organization_id as number
        const mrpData = await fetchMrpData(selectedProjectId, orgId, options.force)
        applyMrpData(mrpData)
      }
    } catch {
      // Silently fail on refresh — data shown is just stale
    }
    // Also refresh pending change count
    refreshPendingCount()
  }, [selectedProjectId, loadProjectDashboard, fetchMrpData, applyMrpData, refreshPendingCount])

  // Load project from URL ?id= on mount
  useEffect(() => {
    const idParam = searchParams.get('id')
    if (idParam) {
      const id = parseInt(idParam, 10)
      if (!isNaN(id)) handleSelectProject(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleSelectHome() {
    projectRequestRef.current += 1
    setSelectedProjectId(null)
    setDashboard(null)
    setError(null)
    clearMrpData()
    resetTabState()
    window.history.replaceState(null, '', '/projects')
  }

  async function handleSelectProject(projectId: number) {
    if (projectId === selectedProjectId) return
    const requestId = projectRequestRef.current + 1
    projectRequestRef.current = requestId
    setSelectedProjectId(projectId)
    window.history.replaceState(null, '', `/projects?id=${projectId}`)
    setError(null)
    clearMrpData()
    resetTabState()

    const cachedDashboard = projectDashboardCache.get(String(projectId))
    if (cachedDashboard) {
      setDashboard(cachedDashboard)
      setLoading(false)
    } else {
      setDashboard(null)
      setLoading(true)
    }

    try {
      const data = await loadProjectDashboard(projectId)
      if (projectRequestRef.current !== requestId) return
      setDashboard(data)
    } catch (e) {
      if (projectRequestRef.current !== requestId) return
      setError(e instanceof Error ? e.message : 'Failed to load project data')
      setDashboard(null)
    } finally {
      if (projectRequestRef.current === requestId) {
        setLoading(false)
      }
    }
  }

  const handleTabChange = useCallback((value: string) => {
    const nextTab = value as DashboardTabValue
    setActiveTab(nextTab)
    setMountedTabs((prev) => {
      if (prev.has(nextTab)) return prev
      const next = new Set(prev)
      next.add(nextTab)
      return next
    })
  }, [])

  useEffect(() => {
    if (activeTab !== 'pricing-tariffs' || !selectedProjectId || !dashboard) return
    const projectId = selectedProjectId
    const orgId = dashboard.project.organization_id as number | undefined
    if (!orgId) return
    const resolvedOrgId = orgId

    let cancelled = false

    async function loadPricingMrp() {
      try {
        const data = await fetchMrpData(projectId, resolvedOrgId)
        if (!cancelled) applyMrpData(data)
      } catch {
        if (!cancelled) clearMrpData()
      }
    }

    loadPricingMrp()
    return () => {
      cancelled = true
    }
  }, [activeTab, selectedProjectId, dashboard, fetchMrpData, applyMrpData, clearMrpData])

  // Build lookup options from dashboard response
  const lookups = dashboard?.lookups ?? {}
  const contractTypeOpts = useMemo(() => toOpts(lookups.contract_types), [lookups.contract_types])
  const contractStatusOpts = useMemo(() => toOpts(lookups.contract_statuses), [lookups.contract_statuses])
  const counterpartyOpts = useMemo(() => toOpts(lookups.counterparties), [lookups.counterparties])
  const assetTypeOpts = useMemo(() => toOpts(lookups.asset_types), [lookups.asset_types])
  const meterTypeOpts = useMemo(() => toOpts(lookups.meter_types), [lookups.meter_types])


  // Column definitions — memoized to prevent child re-renders
  const contractColumns: Column[] = useMemo(() => [
    { key: 'name', label: 'Name', editable: true, type: 'text' },
    { key: 'contract_type_name', label: 'Type', editable: true, type: 'select', editKey: 'contract_type_id', options: contractTypeOpts },
    { key: 'contract_status_name', label: 'Status', editable: true, type: 'select', editKey: 'contract_status_id', options: contractStatusOpts },
    { key: 'counterparty_name', label: 'Counterparty', editable: true, type: 'select', editKey: 'counterparty_id', options: counterpartyOpts },
    { key: 'effective_date', label: 'Effective Date', editable: true, type: 'date' },
    { key: 'end_date', label: 'End Date', editable: true, type: 'date' },
    { key: 'contract_term_years', label: 'Term (yr)', editable: true, type: 'number' },
    { key: 'payment_terms', label: 'Payment Terms', editable: true, type: 'text' },
    { key: 'has_amendments', label: 'Amendments', editable: true, type: 'boolean' },
  ], [contractTypeOpts, contractStatusOpts, counterpartyOpts])

  const assetColumns: Column[] = useMemo(() => [
    { key: 'asset_type_name', label: 'Type', editable: true, type: 'select', editKey: 'asset_type_id', options: assetTypeOpts },
    { key: 'name', label: 'Name', editable: true, type: 'text' },
    { key: 'model', label: 'Model', editable: true, type: 'text' },
    { key: 'capacity', label: 'Capacity', editable: true, type: 'number' },
    { key: 'capacity_unit', label: 'Unit', editable: true, type: 'text' },
    { key: 'quantity', label: 'Qty', editable: true, type: 'number' },
  ], [assetTypeOpts])

  const meterColumns: Column[] = useMemo(() => [
    { key: 'meter_type_name', label: 'Type', editable: true, type: 'select', editKey: 'meter_type_id', options: meterTypeOpts },
    { key: 'model', label: 'Model', editable: true, type: 'text' },
    { key: 'serial_number', label: 'Serial Number', editable: true, type: 'text' },
    { key: 'location_description', label: 'Location', editable: true, type: 'text' },
    { key: 'metering_type', label: 'Metering Type', editable: true, type: 'text' },
  ], [meterTypeOpts])

  const forecastColumns: Column[] = useMemo(() => [
    { key: 'operating_year', label: 'Op. Year', editable: false, type: 'number' },
    { key: 'forecast_month', label: 'Month', editable: true, type: 'date', editKey: 'forecast_month', format: fmtMonthCol, minWidth: 80 },
    { key: 'forecast_energy_kwh', label: 'Energy (kWh)', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_ghi_irradiance', label: 'GHI Irradiance', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_poa_irradiance', label: 'POA Irradiance', editable: true, type: 'number', format: fmtNum2 },
    { key: 'forecast_pr', label: 'PR GHI (%)', editable: true, type: 'number', format: fmtPR },
    { key: 'forecast_pr_poa', label: 'PR POA (%)', editable: true, type: 'number', format: fmtPR },
    { key: 'forecast_source', label: 'Source', editable: true, type: 'text' },
    { key: 'degradation_factor', label: 'Degr. Factor', editable: false, type: 'number', format: fmtDegradation },
  ], [])

  const guaranteeColumns: Column[] = useMemo(() => [
    { key: 'operating_year', label: 'Op. Year', editable: true, type: 'number' },
    { key: 'year_start_date', label: 'Start', editable: true, type: 'date' },
    { key: 'year_end_date', label: 'End', editable: true, type: 'date' },
    { key: 'p50_annual_kwh', label: 'P50 (kWh)', editable: true, type: 'number', format: fmtLocale2 },
    { key: 'guaranteed_kwh', label: 'Guaranteed (kWh)', editable: true, type: 'number', format: fmtLocale2 },
  ], [])

  const contactColumns: Column[] = useMemo(() => [
    { key: 'role', label: 'Title', editable: true, type: 'text' },
    { key: 'full_name', label: 'Full Name', editable: true, type: 'text' },
    { key: 'email', label: 'Email', editable: true, type: 'text' },
    { key: 'phone', label: 'Phone', editable: true, type: 'text' },
    { key: 'include_in_invoice_email', label: 'Invoice', editable: true, type: 'boolean' },
    { key: 'escalation_only', label: 'Escalation', editable: true, type: 'boolean' },
  ], [])

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

  const handlePricingSaved = useCallback(async () => {
    await refreshDashboard({ force: true, includeMrp: true })
  }, [refreshDashboard])

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">CrossBoundary Energy Project Dashboard</h1>
            <p className="text-sm text-slate-500 mt-1">
              View and edit onboarded project data, contracts, and technical details
            </p>
          </div>
          <div className="flex items-center gap-3">
            {userRole !== 'viewer' && (
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
            )}
            {pendingCount > 0 && (
              <button
                onClick={() => setPendingPanelOpen(true)}
                className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors"
              >
                <Clock className="h-3.5 w-3.5" />
                {pendingCount} pending
              </button>
            )}
            {!IS_DEMO && (
              <>
                <Link
                  href="/"
                  className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back to Home
                </Link>
                <SignOutButton />
              </>
            )}
          </div>
        </div>

        {/* Layout: Sidebar + Main Content */}
        <div className="flex gap-6">
          {/* Sidebar */}
          <div className={`shrink-0 transition-all duration-300 ${sidebarOpen ? 'w-64' : 'w-10'}`}>
            {sidebarOpen ? (
              <div className="w-64 bg-white rounded-lg border border-slate-200 p-3">
                <div className="flex justify-end mb-1">
                  <button
                    type="button"
                    onClick={() => setSidebarOpen(false)}
                    className="p-1 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                    title="Hide sidebar"
                  >
                    <PanelLeftClose className="h-4 w-4" />
                  </button>
                </div>
                <ProjectSidebar
                  selectedProjectId={selectedProjectId}
                  onSelectProject={handleSelectProject}
                  onSelectHome={handleSelectHome}
                  orgId={orgId}
                />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors"
                title="Show sidebar"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Main Content */}
          <div className="flex-1 min-w-0">
            {!selectedProjectId && !loading && (
              <PortfolioHome orgId={orgId} />
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
              <Tabs value={activeTab} onValueChange={handleTabChange}>
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="pricing-tariffs">Pricing & Tariffs</TabsTrigger>
                  <TabsTrigger value="technical">Technical</TabsTrigger>
                  <TabsTrigger value="performance">Performance</TabsTrigger>
                  <TabsTrigger value="monthly-billing">Billing</TabsTrigger>
                </TabsList>

                <div className="mt-4 bg-white rounded-lg border border-slate-200 p-6">
                  {mountedTabs.has('overview') && (
                    <TabsContent value="overview" forceMount className="data-[state=inactive]:hidden">
                      <ProjectOverviewTab
                        data={dashboard}
                        contractColumns={contractColumns}
                        projectId={projectId}
                        onSaved={refreshDashboard}
                        editMode={editMode}
                        contacts={dashboard.contacts}
                        contactColumns={contactColumns}
                        onAddContact={handleAddContact}
                        onRemoveContact={handleRemoveContact}
                      />
                    </TabsContent>
                  )}

                  {mountedTabs.has('pricing-tariffs') && (
                    <TabsContent value="pricing-tariffs" forceMount className="data-[state=inactive]:hidden">
                      <PricingTariffsTab
                        data={dashboard}
                        onSaved={handlePricingSaved}
                        editMode={editMode}
                        projectId={projectId}
                        mrpMonthly={mrpMonthly}
                        mrpAnnual={mrpAnnual}
                        mrpTokens={mrpTokens}
                      />
                    </TabsContent>
                  )}

                  {mountedTabs.has('technical') && (
                    <TabsContent value="technical" forceMount className="data-[state=inactive]:hidden">
                      <TechnicalTab
                        project={dashboard.project}
                        contracts={dashboard.contracts}
                        assets={dashboard.assets}
                        meters={dashboard.meters}
                        tariffs={dashboard.tariffs}
                        forecasts={dashboard.forecasts}
                        guarantees={dashboard.guarantees}
                        assetColumns={assetColumns}
                        meterColumns={meterColumns}
                        forecastColumns={forecastColumns}
                        guaranteeColumns={guaranteeColumns}
                        projectId={projectId}
                        onSaved={refreshDashboard}
                        editMode={editMode}
                      />
                    </TabsContent>
                  )}

                  {mountedTabs.has('performance') && (
                    <TabsContent value="performance" forceMount className="data-[state=inactive]:hidden">
                      <PlantPerformanceTab projectId={projectId} editMode={editMode} />
                    </TabsContent>
                  )}

                  {mountedTabs.has('monthly-billing') && (
                    <TabsContent value="monthly-billing" forceMount className="data-[state=inactive]:hidden">
                      <MonthlyBillingTab projectId={projectId} editMode={editMode} />
                    </TabsContent>
                  )}


                </div>
              </Tabs>
            )}
          </div>
        </div>
      </div>
      <PendingChangesPanel
        projectId={selectedProjectId ?? undefined}
        open={pendingPanelOpen}
        onClose={() => setPendingPanelOpen(false)}
        userRole={userRole}
        userId={userId}
        onChanged={() => {
          refreshPendingCount()
          if (selectedProjectId) refreshDashboard({ force: true })
        }}
      />
    </div>
  )
}
