/**
 * Admin API Client
 *
 * API client for client onboarding and API key management.
 * Used by the /client-setup page to create organizations and generate API keys.
 */

// ============================================================================
// Configuration
// ============================================================================

import { getApiBaseUrl } from './config'

const API_BASE_URL = getApiBaseUrl()

// ============================================================================
// TypeScript Interfaces
// ============================================================================

export interface OrganizationResponse {
  id: number
  name: string
  country: string | null
  created_at: string | null
}

export interface CreateOrganizationRequest {
  name: string
  country?: string
}

export interface DataSourceResponse {
  id: number
  name: string
  description: string | null
}

export interface CredentialResponse {
  id: number
  organization_id: number
  data_source_id: number
  auth_type: string
  label: string | null
  is_active: boolean
  last_used_at: string | null
  last_error: string | null
  error_count: number
  token_expires_at: string | null
  created_at: string
  updated_at: string
}

export interface GenerateAPIKeyRequest {
  data_source_id: number
  label?: string
}

export interface GenerateAPIKeyResponse {
  credential_id: number
  organization_id: number
  data_source_id: number
  api_key: string
  label: string | null
  created_at: string
}

export interface UpdateCredentialRequest {
  is_active?: boolean
  label?: string
}

// ============================================================================
// Project Dashboard Types
// ============================================================================

export interface ProjectListItem {
  id: number
  name: string
  organization_id: number
}

export interface ProjectGroupedItem {
  id: number
  name: string
  organization_id: number
  organization_name: string
}

export interface ProjectDashboardResponse {
  success: boolean
  project: Record<string, unknown>
  contracts: Record<string, unknown>[]
  tariffs: Record<string, unknown>[]
  assets: Record<string, unknown>[]
  meters: Record<string, unknown>[]
  forecasts: Record<string, unknown>[]
  guarantees: Record<string, unknown>[]
  contacts: Record<string, unknown>[]
  documents: Record<string, unknown>[]
  billing_products: Record<string, unknown>[]
  rate_periods: Record<string, unknown>[]
  monthly_rates: Record<string, unknown>[]
  tariff_rates: Record<string, unknown>[]
  clauses: Record<string, unknown>[]
  amendments: Record<string, unknown>[]
  exchange_rates: Record<string, unknown>[]
  baseline_grp: Record<string, unknown>[]
  lookups: Record<string, { id: number; code?: string; name: string }[]>
}

// ============================================================================
// Inline Editing Types
// ============================================================================

export type PatchEntity = 'projects' | 'contracts' | 'tariffs' | 'assets' | 'meters' | 'forecasts' | 'guarantees' | 'contacts' | 'billing-products' | 'rate-periods'

export interface PatchEntityRequest {
  entity: PatchEntity
  entityId: number
  projectId?: number   // required for all except 'projects' and 'contacts'
  fields: Record<string, unknown>
}

// ============================================================================
// GRP (Grid Reference Price) Types
// ============================================================================

export interface GRPObservation {
  id: number
  project_id: number
  operating_year: number
  period_start: string
  period_end: string
  observation_type: 'monthly' | 'annual'
  calculated_grp_per_kwh: number | null
  total_variable_charges: number | null
  total_kwh_invoiced: number | null
  verification_status: 'pending' | 'jointly_verified' | 'disputed' | 'estimated'
  verified_at: string | null
  source_metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string | null
}

export interface GRPObservationsResponse {
  success: boolean
  observations: GRPObservation[]
  total: number
}

export interface AggregateGRPResponse {
  success: boolean
  observation_id: number
  annual_grp_per_kwh: number
  operating_year: number
  months_included: number
  months_excluded: number
  total_variable_charges: number
  total_kwh_invoiced: number
  message: string
}

export interface VerifyObservationResponse {
  success: boolean
  observation_id: number
  verification_status: string
  verified_at: string | null
  message: string
}

export interface GRPCollectionResponse {
  success: boolean
  token_id: number
  submission_url: string
  message: string
}

export interface SubmissionTokenItem {
  id: number
  organization_id: number
  project_id: number | null
  project_name: string | null
  submission_type: string | null
  submission_token_status: string
  max_uses: number
  use_count: number
  expires_at: string | null
  submission_url: string | null
  created_at: string | null
}

export interface SubmissionTokenListResponse {
  success: boolean
  tokens: SubmissionTokenItem[]
  total: number
}

// ============================================================================
// Manual GRP Entry Types
// ============================================================================

export interface ManualGRPRateEntry {
  billing_month: string // YYYY-MM
  grp_per_kwh: number
  tariff_components?: Record<string, number>
  notes?: string
}

export interface ManualGRPBatchRequest {
  entries: ManualGRPRateEntry[]
  is_baseline: boolean
  currency_code?: string
}

export interface ManualGRPBatchResponse {
  success: boolean
  inserted_count: number
  observation_ids: number[]
  message: string
}

export interface AdminUploadResponse {
  success: boolean
  observation_id: number
  grp_per_kwh: number
  total_variable_charges: number
  total_kwh_invoiced: number
  line_items_count: number
  extraction_confidence: string
  message: string
  billing_month_stored?: string
  period_mismatch?: { user_provided: string; extracted: string; resolution: string }
}

// ============================================================================
// Spreadsheet Types
// ============================================================================

export interface SpreadsheetColumnMeta {
  name: string
  type: string
  nullable: boolean
  has_default: boolean
}

export interface SpreadsheetTable {
  table_name: string
  columns: SpreadsheetColumnMeta[]
}

export interface SpreadsheetTablesResponse {
  success: boolean
  tables: SpreadsheetTable[]
}

export interface SpreadsheetQueryRequest {
  table: string
  project_id: number
  limit?: number
  offset?: number
}

export interface SpreadsheetQueryResponse {
  success: boolean
  columns: SpreadsheetColumnMeta[]
  rows: Record<string, unknown>[]
  total_count: number
}

export interface SpreadsheetCellChange {
  row_id: number
  column: string
  value: unknown
}

export interface SpreadsheetSaveRequest {
  table: string
  project_id: number
  changes: SpreadsheetCellChange[]
  deletions?: number[]
}

export interface SpreadsheetSaveResponse {
  success: boolean
  updated_count: number
  deleted_count?: number
}

// ============================================================================
// Monthly Billing Types
// ============================================================================

export interface MonthlyBillingProductColumn {
  billing_product_id: number
  product_code: string
  product_name: string
  clause_tariff_id: number | null
  tariff_name: string | null
  is_metered: boolean
}

export interface MonthlyBillingRow {
  billing_month: string
  billing_period_id: number | null
  actual_kwh: number | null
  forecast_kwh: number | null
  variance_kwh: number | null
  variance_pct: number | null
  product_amounts: Record<string, number | null>
  product_rates: Record<string, number | null>
  total_billing_amount: number | null
}

export interface MonthlyBillingResponse {
  success: boolean
  rows: MonthlyBillingRow[]
  products: MonthlyBillingProductColumn[]
  currency_code: string | null
  degradation_pct: number | null
  summary: {
    actual_kwh: number
    forecast_kwh: number
    total_billing: number
  }
}

export interface MonthlyBillingImportResponse {
  success: boolean
  imported_rows: number
  message: string
}

// ============================================================================
// Meter Billing Types
// ============================================================================

export interface MeterInfo {
  meter_id: number
  meter_name: string | null
  contract_line_number: number | null
  energy_category: string | null
  product_desc: string | null
}

export interface MeterReadingDetail {
  meter_id: number
  meter_name: string | null
  opening_reading: number | null
  closing_reading: number | null
  metered_kwh: number | null
  available_kwh: number | null
  rate: number | null
  amount: number | null
}

export interface MeterBillingMonth {
  billing_month: string
  meter_readings: MeterReadingDetail[]
  total_metered_kwh: number | null
  total_available_kwh: number | null
  total_energy_kwh: number | null
  total_amount: number | null
}

export interface MeterBillingResponse {
  success: boolean
  meters: MeterInfo[]
  months: MeterBillingMonth[]
  currency_code: string | null
}

// ============================================================================
// Plant Performance Types
// ============================================================================

export interface PerformanceMonth {
  billing_month: string
  operating_year: number | null
  total_metered_kwh: number | null
  total_available_kwh: number | null
  total_energy_kwh: number | null
  actual_ghi_irradiance: number | null
  actual_poa_irradiance: number | null
  forecast_energy_kwh: number | null
  forecast_ghi_irradiance: number | null
  forecast_poa_irradiance: number | null
  forecast_pr: number | null
  actual_pr: number | null
  actual_availability_pct: number | null
  energy_comparison: number | null
  irr_comparison: number | null
  pr_comparison: number | null
  comments: string | null
}

export interface PlantPerformanceResponse {
  success: boolean
  installed_capacity_kwp: number | null
  annual_degradation_pct: number | null
  months: PerformanceMonth[]
  summary: {
    total_metered_kwh: number
    total_available_kwh: number
    total_energy_kwh: number
  }
}

// ============================================================================
// Error Class
// ============================================================================

export class AdminAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string,
    public details?: string
  ) {
    super(message)
    this.name = 'AdminAPIError'
  }
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface AdminClientConfig {
  baseUrl?: string
  enableLogging?: boolean
}

// ============================================================================
// Admin Client Class
// ============================================================================

export class AdminClient {
  private baseUrl: string
  private enableLogging: boolean

  constructor(config: AdminClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.enableLogging = config.enableLogging ?? false
  }

  private log(message: string, data?: unknown): void {
    if (this.enableLogging) {
      console.log(`[AdminClient] ${message}`, data || '')
    }
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new AdminAPIError(
        errorBody.message || errorBody.detail?.message || errorBody.detail || `HTTP ${response.status}`,
        response.status,
        errorBody.error || errorBody.detail?.error,
        errorBody.details || errorBody.detail?.details
      )
    }
    return response.json()
  }

  // =========================================================================
  // Organizations
  // =========================================================================

  async listOrganizations(): Promise<OrganizationResponse[]> {
    this.log('Listing organizations')
    const response = await fetch(`${this.baseUrl}/api/organizations`)
    const data = await this.handleResponse<{ organizations: OrganizationResponse[] }>(response)
    return data.organizations
  }

  async createOrganization(request: CreateOrganizationRequest): Promise<OrganizationResponse> {
    this.log('Creating organization', request)
    const response = await fetch(`${this.baseUrl}/api/organizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
    return this.handleResponse<OrganizationResponse>(response)
  }

  // =========================================================================
  // Data Sources
  // =========================================================================

  async listDataSources(): Promise<DataSourceResponse[]> {
    this.log('Listing data sources')
    const response = await fetch(`${this.baseUrl}/api/data-sources`)
    const data = await this.handleResponse<{ data_sources: DataSourceResponse[] }>(response)
    return data.data_sources
  }

  // =========================================================================
  // Credentials
  // =========================================================================

  async listCredentials(organizationId: number): Promise<CredentialResponse[]> {
    this.log('Listing credentials', { organizationId })
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials?organization_id=${organizationId}`
    )
    return this.handleResponse<CredentialResponse[]>(response)
  }

  async generateAPIKey(
    organizationId: number,
    request: GenerateAPIKeyRequest
  ): Promise<GenerateAPIKeyResponse> {
    this.log('Generating API key', { organizationId, request })
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/generate-key?organization_id=${organizationId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<GenerateAPIKeyResponse>(response)
  }

  async updateCredential(
    credentialId: number,
    organizationId: number,
    request: UpdateCredentialRequest
  ): Promise<CredentialResponse> {
    this.log('Updating credential', { credentialId, organizationId, request })
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/${credentialId}?organization_id=${organizationId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<CredentialResponse>(response)
  }

  // =========================================================================
  // Projects Dashboard
  // =========================================================================

  async listProjects(organizationId?: number): Promise<ProjectListItem[]> {
    this.log('Listing projects', { organizationId })
    const params = organizationId != null ? `?organization_id=${organizationId}` : ''
    const response = await fetch(`${this.baseUrl}/api/projects${params}`)
    const data = await this.handleResponse<{ projects: ProjectListItem[] }>(response)
    return data.projects
  }

  async listProjectsGrouped(): Promise<ProjectGroupedItem[]> {
    this.log('Listing projects grouped by organization')
    const response = await fetch(`${this.baseUrl}/api/projects/grouped`)
    const data = await this.handleResponse<{ projects: ProjectGroupedItem[] }>(response)
    return data.projects
  }

  async getProjectDashboard(projectId: number): Promise<ProjectDashboardResponse> {
    this.log('Fetching project dashboard', { projectId })
    const response = await fetch(`${this.baseUrl}/api/projects/${projectId}/dashboard`)
    return this.handleResponse<ProjectDashboardResponse>(response)
  }

  async deleteCredential(credentialId: number, organizationId: number): Promise<void> {
    this.log('Deleting credential', { credentialId, organizationId })
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/${credentialId}?organization_id=${organizationId}`,
      { method: 'DELETE' }
    )
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new AdminAPIError(
        errorBody.message || errorBody.detail || `HTTP ${response.status}`,
        response.status
      )
    }
  }

  // =========================================================================
  // Inline Editing
  // =========================================================================

  async patchEntity(request: PatchEntityRequest): Promise<{ success: boolean; id: number }> {
    this.log('Patching entity', request)
    const { entity, entityId, projectId, fields } = request
    const scopeParam = projectId != null ? `?project_id=${projectId}` : ''
    const response = await fetch(
      `${this.baseUrl}/api/${entity}/${entityId}${scopeParam}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  async addBillingProduct(request: {
    contract_id: number
    billing_product_id: number
    is_primary?: boolean
    notes?: string
  }): Promise<{ success: boolean; id: number }> {
    this.log('Adding billing product', request)
    const response = await fetch(
      `${this.baseUrl}/api/billing-products`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  async removeBillingProduct(junctionId: number): Promise<{ success: boolean; id: number }> {
    this.log('Removing billing product', { junctionId })
    const response = await fetch(
      `${this.baseUrl}/api/billing-products/${junctionId}`,
      { method: 'DELETE' }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  // =========================================================================
  // Contacts
  // =========================================================================

  async addContact(request: {
    counterparty_id: number
    organization_id: number
    full_name?: string
    email?: string
    phone?: string
    role?: string
    include_in_invoice_email?: boolean
    escalation_only?: boolean
  }): Promise<{ success: boolean; id: number }> {
    this.log('Adding contact', request)
    const response = await fetch(
      `${this.baseUrl}/api/contacts`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  async removeContact(contactId: number): Promise<{ success: boolean; id: number }> {
    this.log('Removing contact', { contactId })
    const response = await fetch(
      `${this.baseUrl}/api/contacts/${contactId}`,
      { method: 'DELETE' }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  // =========================================================================
  // GRP (Grid Reference Price)
  // =========================================================================

  async refreshGRP(
    projectId: number,
    orgId: number
  ): Promise<{ success: boolean; refreshed_operating_years: number[] }> {
    this.log('Refreshing stale GRP annuals', { projectId, orgId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-refresh`,
      {
        method: 'POST',
        headers: { 'X-Organization-ID': String(orgId) },
      }
    )
    return this.handleResponse<{ success: boolean; refreshed_operating_years: number[] }>(response)
  }

  async listGRPObservations(
    projectId: number,
    orgId: number,
    params?: { observation_type?: string; operating_year?: number; verification_status?: string }
  ): Promise<GRPObservationsResponse> {
    this.log('Listing GRP observations', { projectId, orgId, params })
    const searchParams = new URLSearchParams()
    if (params?.observation_type) searchParams.set('observation_type', params.observation_type)
    if (params?.operating_year != null) searchParams.set('operating_year', String(params.operating_year))
    if (params?.verification_status) searchParams.set('verification_status', params.verification_status)
    const qs = searchParams.toString()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-observations${qs ? `?${qs}` : ''}`,
      { headers: { 'X-Organization-ID': String(orgId) } }
    )
    return this.handleResponse<GRPObservationsResponse>(response)
  }

  async aggregateGRP(
    projectId: number,
    orgId: number,
    body: { operating_year: number; include_pending: boolean }
  ): Promise<AggregateGRPResponse> {
    this.log('Aggregating GRP', { projectId, orgId, body })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-aggregate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Organization-ID': String(orgId) },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<AggregateGRPResponse>(response)
  }

  async verifyObservation(
    projectId: number,
    orgId: number,
    observationId: number,
    body: { verification_status: string; notes?: string }
  ): Promise<VerifyObservationResponse> {
    this.log('Verifying GRP observation', { projectId, orgId, observationId, body })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-observations/${observationId}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Organization-ID': String(orgId) },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<VerifyObservationResponse>(response)
  }

  async generateGRPToken(
    orgId: number,
    body: { project_id: number; operating_year: number; max_uses?: number }
  ): Promise<GRPCollectionResponse> {
    this.log('Generating GRP collection token', { orgId, body })
    const response = await fetch(
      `${this.baseUrl}/api/notifications/grp-collection`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Organization-ID': String(orgId),
          'X-Frontend-URL': typeof window !== 'undefined' ? window.location.origin : '',
        },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<GRPCollectionResponse>(response)
  }

  async uploadGRPInvoice(
    projectId: number,
    orgId: number,
    formData: FormData
  ): Promise<AdminUploadResponse> {
    this.log('Uploading GRP invoice', { projectId, orgId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-upload`,
      {
        method: 'POST',
        headers: { 'X-Organization-ID': String(orgId) },
        body: formData,
      }
    )
    return this.handleResponse<AdminUploadResponse>(response)
  }

  async submitManualGRPRates(
    projectId: number,
    orgId: number,
    body: ManualGRPBatchRequest
  ): Promise<ManualGRPBatchResponse> {
    this.log('Submitting manual GRP rates', { projectId, orgId, count: body.entries.length })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/grp-manual`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Organization-ID': String(orgId) },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<ManualGRPBatchResponse>(response)
  }

  async revokeToken(
    orgId: number,
    tokenId: number
  ): Promise<{ success: boolean; message: string }> {
    this.log('Revoking submission token', { orgId, tokenId })
    const response = await fetch(
      `${this.baseUrl}/api/notifications/tokens/${tokenId}/revoke`,
      {
        method: 'POST',
        headers: { 'X-Organization-ID': String(orgId) },
      }
    )
    return this.handleResponse<{ success: boolean; message: string }>(response)
  }

  async listTokens(
    orgId: number,
    params?: { project_id?: number; submission_type?: string; include_expired?: boolean }
  ): Promise<SubmissionTokenListResponse> {
    this.log('Listing submission tokens', { orgId, params })
    const searchParams = new URLSearchParams()
    if (params?.project_id != null) searchParams.set('project_id', String(params.project_id))
    if (params?.submission_type) searchParams.set('submission_type', params.submission_type)
    if (params?.include_expired) searchParams.set('include_expired', 'true')
    const qs = searchParams.toString()
    const response = await fetch(
      `${this.baseUrl}/api/notifications/tokens${qs ? `?${qs}` : ''}`,
      { headers: { 'X-Organization-ID': String(orgId) } }
    )
    return this.handleResponse<SubmissionTokenListResponse>(response)
  }

  // =========================================================================
  // Spreadsheet
  // =========================================================================

  async getSpreadsheetTables(projectId: number): Promise<SpreadsheetTable[]> {
    this.log('Fetching spreadsheet tables', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/tables?project_id=${projectId}`
    )
    const data = await this.handleResponse<SpreadsheetTablesResponse>(response)
    return data.tables
  }

  async querySpreadsheetData(request: SpreadsheetQueryRequest): Promise<SpreadsheetQueryResponse> {
    this.log('Querying spreadsheet data', request)
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/query`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<SpreadsheetQueryResponse>(response)
  }

  async saveSpreadsheetChanges(request: SpreadsheetSaveRequest): Promise<SpreadsheetSaveResponse> {
    this.log('Saving spreadsheet changes', request)
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/save`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<SpreadsheetSaveResponse>(response)
  }

  // =========================================================================
  // Monthly Billing
  // =========================================================================

  async getMonthlyBilling(projectId: number): Promise<MonthlyBillingResponse> {
    this.log('Fetching monthly billing', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing`
    )
    return this.handleResponse<MonthlyBillingResponse>(response)
  }

  async importMonthlyBilling(projectId: number, file: File): Promise<MonthlyBillingImportResponse> {
    this.log('Importing monthly billing', { projectId, filename: file.name })
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/import`,
      { method: 'POST', body: formData }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  async addManualBillingEntry(
    projectId: number,
    body: { billing_month: string; actual_kwh?: number; forecast_kwh?: number }
  ): Promise<MonthlyBillingImportResponse> {
    this.log('Adding manual billing entry', { projectId, body })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/manual`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  // =========================================================================
  // Meter Billing
  // =========================================================================

  async getMeterBilling(projectId: number): Promise<MeterBillingResponse> {
    this.log('Fetching meter billing', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/meter-billing`
    )
    return this.handleResponse<MeterBillingResponse>(response)
  }

  // =========================================================================
  // Plant Performance
  // =========================================================================

  async getPlantPerformance(projectId: number): Promise<PlantPerformanceResponse> {
    this.log('Fetching plant performance', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance`
    )
    return this.handleResponse<PlantPerformanceResponse>(response)
  }

  async addPlantPerformanceEntry(
    projectId: number,
    body: {
      billing_month: string
      operating_year?: number
      meter_readings?: { meter_id: number; energy_kwh?: number; available_energy_kwh?: number; opening_reading?: number; closing_reading?: number }[]
      ghi_irradiance_wm2?: number
      poa_irradiance_wm2?: number
      actual_availability_pct?: number
      comments?: string
    }
  ): Promise<MonthlyBillingImportResponse> {
    this.log('Adding plant performance entry', { projectId, body })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance/manual`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  async importPlantPerformance(projectId: number, file: File): Promise<MonthlyBillingImportResponse> {
    this.log('Importing plant performance', { projectId, filename: file.name })
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance/import`,
      { method: 'POST', body: formData }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  // =========================================================================
  // Degradation
  // =========================================================================

  async applyDegradation(projectId: number): Promise<{ success: boolean; updated_rows: number; annual_degradation_pct: number }> {
    this.log('Applying degradation', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/apply-degradation`,
      { method: 'POST' }
    )
    return this.handleResponse<{ success: boolean; updated_rows: number; annual_degradation_pct: number }>(response)
  }

  async exportMonthlyBilling(projectId: number): Promise<Blob> {
    this.log('Exporting monthly billing', { projectId })
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/export`
    )
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new AdminAPIError(
        errorBody.message || errorBody.detail || `HTTP ${response.status}`,
        response.status
      )
    }
    return response.blob()
  }
}

// ============================================================================
// Default Instance
// ============================================================================

export const adminClient = new AdminClient()
