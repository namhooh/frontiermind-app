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
  data_source_id: number | null
  auth_type: string
  label: string | null
  is_active: boolean
  last_used_at: string | null
  last_error: string | null
  error_count: number
  token_expires_at: string | null
  scopes: string[] | null
  created_at: string
  updated_at: string
}

export interface GenerateAPIKeyRequest {
  data_source_id?: number | null
  label?: string
  scopes?: string[] | null
}

export interface GenerateAPIKeyResponse {
  credential_id: number
  organization_id: number
  data_source_id: number | null
  api_key: string
  label: string | null
  scopes: string[] | null
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
  external_project_id: string | null
  sage_id: string | null
  country: string | null
  organization_id: number
  organization_name: string
}

export interface TariffFormulaVariable {
  symbol: string
  role: 'input' | 'output' | 'parameter' | 'intermediate'
  variable_type?: string
  description?: string
  unit?: string
  maps_to?: string | null
  lookup_key?: string | null
}

export interface TariffFormulaCondition {
  type: string
  compare?: string
  against?: string
  operator?: string
  then?: string
  else?: string
  description?: string
}

export interface TariffFormula {
  id: number
  clause_tariff_id: number
  formula_name: string
  formula_text: string
  formula_type: string
  variables: TariffFormulaVariable[]
  operations: string[]
  conditions: TariffFormulaCondition[]
  section_ref?: string | null
  extraction_confidence?: number | null
  extraction_metadata?: Record<string, unknown>
  is_current: boolean
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
  tariff_formulas: TariffFormula[]
  clauses: Record<string, unknown>[]
  amendments: Record<string, unknown>[]
  exchange_rates: Record<string, unknown>[]
  baseline_mrp: Record<string, unknown>[]
  contract_lines: Record<string, unknown>[]
  lookups: Record<string, { id: number; code?: string; name: string }[]>
}

// ============================================================================
// Portfolio Revenue Summary Types
// ============================================================================

export interface PortfolioMonthRow {
  billing_month: string
  project_count: number
  actual_kwh: number | null
  forecast_kwh: number | null
  weighted_avg_tariff_usd: number | null
  revenue_usd: number | null
  forecast_revenue_usd: number | null
}

export interface PortfolioProjectSummary {
  project_id: number
  project_name: string
  country: string | null
  customer_name: string | null
  industry: string | null
  total_actual_kwh: number | null
  total_forecast_kwh: number | null
  total_revenue_usd: number | null
  months_with_data: number
}

export interface PortfolioRevenueSummaryResponse {
  success: boolean
  months: PortfolioMonthRow[]
  projects: PortfolioProjectSummary[]
  summary: {
    total_actual_kwh: number | null
    total_forecast_kwh: number | null
    total_revenue_usd: number | null
    total_forecast_revenue_usd: number | null
  }
  data_coverage: {
    total_projects: number
    projects_with_meter_data: number
    projects_with_forecast: number
    projects_with_tariff: number
  }
}

// ============================================================================
// Inline Editing Types
// ============================================================================

export type PatchEntity = 'projects' | 'contracts' | 'tariffs' | 'assets' | 'meters' | 'forecasts' | 'guarantees' | 'contacts' | 'billing-products' | 'rate-periods' | 'exchange-rates'

export interface PatchEntityRequest {
  entity: PatchEntity
  entityId: number
  projectId?: number   // required for all except 'projects' and 'contacts'
  fields: Record<string, unknown>
}

export interface PatchEntityResponse {
  success: boolean
  id: number
  outcome: 'applied' | 'submitted' | 'partial'
  pending_approval?: string[]
  change_request_ids?: number[]
}

export interface ChangeRequest {
  id: number
  organization_id: number
  project_id: number
  target_table: string
  target_id: number
  field_name: string
  old_value: unknown
  new_value: unknown
  display_label: string | null
  policy_key: string
  change_request_status: 'pending' | 'conflicted' | 'approved' | 'rejected' | 'cancelled' | 'superseded'
  auto_approved: boolean
  requested_by: string
  requested_at: string
  request_note: string | null
  assigned_approver_id: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  requester_name: string | null
  reviewer_name: string | null
}

export interface ChangeRequestSummary {
  pending: number
  conflicted: number
}

// ============================================================================
// MRP (Market Reference Price) Types
// ============================================================================

export interface MRPObservation {
  id: number
  project_id: number
  operating_year: number
  period_start: string
  period_end: string
  observation_type: 'monthly' | 'annual'
  calculated_mrp_per_kwh: number | null
  total_variable_charges: number | null
  total_kwh_invoiced: number | null
  verification_status: 'pending' | 'jointly_verified' | 'disputed' | 'estimated'
  verified_at: string | null
  source_metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string | null
}

export interface MRPObservationsResponse {
  success: boolean
  observations: MRPObservation[]
  total: number
}

export interface AggregateMRPResponse {
  success: boolean
  observation_id: number
  annual_mrp_per_kwh: number
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

export interface MRPCollectionResponse {
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
// Manual MRP Entry Types
// ============================================================================

export interface ManualMRPRateEntry {
  billing_month: string // YYYY-MM
  mrp_per_kwh: number
  tariff_components?: Record<string, number>
  notes?: string
}

export interface ManualMRPBatchRequest {
  entries: ManualMRPRateEntry[]
  is_baseline: boolean
  currency_code?: string
}

export interface ManualMRPBatchResponse {
  success: boolean
  inserted_count: number
  observation_ids: number[]
  message: string
}

export interface AdminUploadResponse {
  success: boolean
  observation_id: number
  mrp_per_kwh: number
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
  energy_category: string | null
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
  product_amounts_hard_ccy: Record<string, number | null>
  product_rates_hard_ccy: Record<string, number | null>
  total_billing_amount: number | null
  total_billing_amount_hard_ccy: number | null
  expected_invoice: ExpectedInvoiceSummary | null
}

export interface MonthlyBillingResponse {
  success: boolean
  rows: MonthlyBillingRow[]
  products: MonthlyBillingProductColumn[]
  currency_code: string | null
  hard_currency_code: string | null
  degradation_pct: number | null
  cod_date: string | null
  summary: {
    actual_kwh: number
    forecast_kwh: number
    total_billing: number
    total_billing_hard: number
  }
  total_months: number | null
  months_returned: number | null
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
  rate_hard_ccy: number | null
  amount_hard_ccy: number | null
}

// ---------------------------------------------------------------------------
// Expected Invoice Types
// ---------------------------------------------------------------------------

export interface ExpectedInvoiceLineItem {
  line_item_type_code: string  // ENERGY, AVAILABLE_ENERGY, LEVY, TAX, WITHHOLDING
  component_code: string | null
  description: string
  quantity: number | null       // energy lines
  unit_price: number | null     // energy lines
  basis_amount: number | null   // tax lines
  rate_pct: number | null       // tax lines
  line_total_amount: number
  amount_sign: number           // 1 or -1
  sort_order: number
  meter_name: string | null
}

export interface ExpectedInvoiceSummary {
  header_id: number
  version_no: number
  energy_subtotal: number
  levies_total: number
  subtotal_after_levies: number
  vat_amount: number
  invoice_total: number
  withholdings_total: number
  net_due: number
  net_due_hard_ccy: number | null
  fx_rate: number | null
  line_items: ExpectedInvoiceLineItem[]
}

export interface MeterBillingMonth {
  billing_month: string
  meter_readings: MeterReadingDetail[]
  total_metered_kwh: number | null
  total_available_kwh: number | null
  total_energy_kwh: number | null
  total_amount: number | null
  total_amount_hard_ccy: number | null
  expected_invoice: ExpectedInvoiceSummary | null
}

export interface MeterBillingResponse {
  success: boolean
  meters: MeterInfo[]
  months: MeterBillingMonth[]
  currency_code: string | null
  hard_currency_code: string | null
  total_months: number | null
  months_returned: number | null
}

// ============================================================================
// Plant Performance Types
// ============================================================================

export interface MeterPerformanceDetail {
  meter_id: number
  meter_name: string | null
  metered_kwh: number | null
  available_kwh: number | null
  phase_number: number | null
  phase_cod_date: string | null
}

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
  forecast_pr_poa: number | null
  actual_pr: number | null
  actual_availability_pct: number | null
  energy_comparison: number | null
  irr_comparison: number | null
  pr_comparison: number | null
  comments: string | null
  meter_details: MeterPerformanceDetail[]
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
  meters: { meter_id: number; meter_name: string; energy_category: string; phase_number?: number | null; phase_cod_date?: string | null }[]
  total_months: number | null
  months_returned: number | null
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
// Team Management Interfaces
// ============================================================================

export interface TeamMember {
  id: number
  user_id: string
  organization_id: number
  role_type: 'admin' | 'approver' | 'editor' | 'viewer'
  name: string | null
  email: string | null
  department: string | null
  job_title: string | null
  status: 'invited' | 'active' | 'suspended' | 'deactivated'
  is_active: boolean
  invited_by: string | null
  invited_at: string | null
  accepted_at: string | null
}

export interface InviteMemberRequest {
  email: string
  full_name: string
  role_type: 'admin' | 'approver' | 'editor' | 'viewer'
  department?: string
  job_title?: string
}

export interface UpdateMemberRequest {
  role_type?: 'admin' | 'approver' | 'editor' | 'viewer'
  department?: string
  job_title?: string
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface AdminClientConfig {
  baseUrl?: string
  enableLogging?: boolean
  getAuthToken?: () => Promise<string | null>
}

// ============================================================================
// Admin Client Class
// ============================================================================

export class AdminClient {
  private baseUrl: string
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>
  private organizationId?: number

  constructor(config: AdminClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.enableLogging = config.enableLogging ?? false
    this.getAuthToken = config.getAuthToken
  }

  setOrganizationId(id: number): void {
    this.organizationId = id
  }

  private async getAuthHeaders(orgId?: number): Promise<Record<string, string>> {
    const headers: Record<string, string> = {}
    const effectiveOrgId = orgId ?? this.organizationId
    if (effectiveOrgId != null) headers['X-Organization-ID'] = String(effectiveOrgId)
    if (this.getAuthToken) {
      const token = await this.getAuthToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    }
    return headers
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
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/organizations`, { headers })
    const data = await this.handleResponse<{ organizations: OrganizationResponse[] }>(response)
    return data.organizations
  }

  async createOrganization(request: CreateOrganizationRequest): Promise<OrganizationResponse> {
    this.log('Creating organization', request)
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(`${this.baseUrl}/api/organizations`, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
    })
    return this.handleResponse<OrganizationResponse>(response)
  }

  // =========================================================================
  // Data Sources
  // =========================================================================

  async listDataSources(): Promise<DataSourceResponse[]> {
    this.log('Listing data sources')
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/data-sources`, { headers })
    const data = await this.handleResponse<{ data_sources: DataSourceResponse[] }>(response)
    return data.data_sources
  }

  // =========================================================================
  // Credentials
  // =========================================================================

  async listCredentials(organizationId: number): Promise<CredentialResponse[]> {
    this.log('Listing credentials', { organizationId })
    const headers = await this.getAuthHeaders(organizationId)
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials`,
      { headers }
    )
    return this.handleResponse<CredentialResponse[]>(response)
  }

  async generateAPIKey(
    organizationId: number,
    request: GenerateAPIKeyRequest
  ): Promise<GenerateAPIKeyResponse> {
    this.log('Generating API key', { organizationId, request })
    const headers = await this.getAuthHeaders(organizationId)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/generate-key`,
      {
        method: 'POST',
        headers,
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
    const headers = await this.getAuthHeaders(organizationId)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/${credentialId}`,
      {
        method: 'PUT',
        headers,
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
    const headers = await this.getAuthHeaders(organizationId)
    const params = organizationId != null ? `?organization_id=${organizationId}` : ''
    const response = await fetch(`${this.baseUrl}/api/projects${params}`, { headers })
    const data = await this.handleResponse<{ projects: ProjectListItem[] }>(response)
    return data.projects
  }

  async listProjectsGrouped(): Promise<ProjectGroupedItem[]> {
    this.log('Listing projects grouped by organization')
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/projects/grouped`, { headers })
    const data = await this.handleResponse<{ projects: ProjectGroupedItem[] }>(response)
    return data.projects
  }

  async getProjectDashboard(projectId: number): Promise<ProjectDashboardResponse> {
    this.log('Fetching project dashboard', { projectId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/projects/${projectId}/dashboard`, { headers })
    return this.handleResponse<ProjectDashboardResponse>(response)
  }

  async deleteCredential(credentialId: number, organizationId: number): Promise<void> {
    this.log('Deleting credential', { credentialId, organizationId })
    const headers = await this.getAuthHeaders(organizationId)
    const response = await fetch(
      `${this.baseUrl}/api/ingest/credentials/${credentialId}`,
      { method: 'DELETE', headers }
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

  async patchEntity(request: PatchEntityRequest): Promise<PatchEntityResponse> {
    this.log('Patching entity', request)
    const { entity, entityId, projectId, fields } = request
    const scopeParam = projectId != null ? `?project_id=${projectId}` : ''
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/${entity}/${entityId}${scopeParam}`,
      {
        method: 'PATCH',
        headers,
        body: JSON.stringify(fields),
      }
    )
    return this.handleResponse<PatchEntityResponse>(response)
  }

  async addBillingProduct(request: {
    contract_id: number
    billing_product_id: number
    is_primary?: boolean
    notes?: string
  }): Promise<{ success: boolean; id: number }> {
    this.log('Adding billing product', request)
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/billing-products`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  async removeBillingProduct(junctionId: number): Promise<{ success: boolean; id: number }> {
    this.log('Removing billing product', { junctionId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/billing-products/${junctionId}`,
      { method: 'DELETE', headers }
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
    const headers = await this.getAuthHeaders(request.organization_id)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/contacts`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  async removeContact(contactId: number): Promise<{ success: boolean; id: number }> {
    this.log('Removing contact', { contactId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/contacts/${contactId}`,
      { method: 'DELETE', headers }
    )
    return this.handleResponse<{ success: boolean; id: number }>(response)
  }

  // =========================================================================
  // MRP (Market Reference Price)
  // =========================================================================

  async refreshMRP(
    projectId: number,
    orgId: number
  ): Promise<{ success: boolean; refreshed_operating_years: number[] }> {
    this.log('Refreshing stale MRP annuals', { projectId, orgId })
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-refresh`,
      {
        method: 'POST',
        headers,
      }
    )
    return this.handleResponse<{ success: boolean; refreshed_operating_years: number[] }>(response)
  }

  async listMRPObservations(
    projectId: number,
    orgId: number,
    params?: { observation_type?: string; operating_year?: number; verification_status?: string }
  ): Promise<MRPObservationsResponse> {
    this.log('Listing MRP observations', { projectId, orgId, params })
    const searchParams = new URLSearchParams()
    if (params?.observation_type) searchParams.set('observation_type', params.observation_type)
    if (params?.operating_year != null) searchParams.set('operating_year', String(params.operating_year))
    if (params?.verification_status) searchParams.set('verification_status', params.verification_status)
    const qs = searchParams.toString()
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-observations${qs ? `?${qs}` : ''}`,
      { headers }
    )
    return this.handleResponse<MRPObservationsResponse>(response)
  }

  async aggregateMRP(
    projectId: number,
    orgId: number,
    body: { operating_year: number; include_pending: boolean }
  ): Promise<AggregateMRPResponse> {
    this.log('Aggregating MRP', { projectId, orgId, body })
    const headers = await this.getAuthHeaders(orgId)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-aggregate`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<AggregateMRPResponse>(response)
  }

  async verifyObservation(
    projectId: number,
    orgId: number,
    observationId: number,
    body: { verification_status: string; notes?: string }
  ): Promise<VerifyObservationResponse> {
    this.log('Verifying MRP observation', { projectId, orgId, observationId, body })
    const headers = await this.getAuthHeaders(orgId)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-observations/${observationId}`,
      {
        method: 'PATCH',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<VerifyObservationResponse>(response)
  }

  async deleteMRPObservation(
    projectId: number,
    orgId: number,
    observationId: number
  ): Promise<{ success: boolean; message: string }> {
    this.log('Deleting MRP observation', { projectId, orgId, observationId })
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-observations/${observationId}`,
      {
        method: 'DELETE',
        headers,
      }
    )
    return this.handleResponse<{ success: boolean; message: string }>(response)
  }

  async generateMRPToken(
    orgId: number,
    body: { project_id: number; operating_year: number; max_uses?: number }
  ): Promise<MRPCollectionResponse> {
    this.log('Generating MRP collection token', { orgId, body })
    const headers = await this.getAuthHeaders(orgId)
    headers['Content-Type'] = 'application/json'
    headers['X-Frontend-URL'] = typeof window !== 'undefined' ? window.location.origin : ''
    const response = await fetch(
      `${this.baseUrl}/api/notifications/mrp-collection`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<MRPCollectionResponse>(response)
  }

  async uploadMRPInvoice(
    projectId: number,
    orgId: number,
    formData: FormData
  ): Promise<AdminUploadResponse> {
    this.log('Uploading MRP invoice', { projectId, orgId })
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-upload`,
      {
        method: 'POST',
        headers,
        body: formData,
      }
    )
    return this.handleResponse<AdminUploadResponse>(response)
  }

  async submitManualMRPRates(
    projectId: number,
    orgId: number,
    body: ManualMRPBatchRequest
  ): Promise<ManualMRPBatchResponse> {
    this.log('Submitting manual MRP rates', { projectId, orgId, count: body.entries.length })
    const headers = await this.getAuthHeaders(orgId)
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/mrp-manual`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<ManualMRPBatchResponse>(response)
  }

  async revokeToken(
    orgId: number,
    tokenId: number
  ): Promise<{ success: boolean; message: string }> {
    this.log('Revoking submission token', { orgId, tokenId })
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/notifications/tokens/${tokenId}/revoke`,
      {
        method: 'POST',
        headers,
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
    const headers = await this.getAuthHeaders(orgId)
    const response = await fetch(
      `${this.baseUrl}/api/notifications/tokens${qs ? `?${qs}` : ''}`,
      { headers }
    )
    return this.handleResponse<SubmissionTokenListResponse>(response)
  }

  // =========================================================================
  // Spreadsheet
  // =========================================================================

  async getSpreadsheetTables(projectId: number): Promise<SpreadsheetTable[]> {
    this.log('Fetching spreadsheet tables', { projectId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/tables?project_id=${projectId}`,
      { headers }
    )
    const data = await this.handleResponse<SpreadsheetTablesResponse>(response)
    return data.tables
  }

  async querySpreadsheetData(request: SpreadsheetQueryRequest): Promise<SpreadsheetQueryResponse> {
    this.log('Querying spreadsheet data', request)
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/query`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<SpreadsheetQueryResponse>(response)
  }

  async saveSpreadsheetChanges(request: SpreadsheetSaveRequest): Promise<SpreadsheetSaveResponse> {
    this.log('Saving spreadsheet changes', request)
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/spreadsheet/save`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      }
    )
    return this.handleResponse<SpreadsheetSaveResponse>(response)
  }

  // =========================================================================
  // Monthly Billing
  // =========================================================================

  async getMonthlyBilling(projectId: number, opts?: { months?: number }): Promise<MonthlyBillingResponse> {
    this.log('Fetching monthly billing', { projectId, months: opts?.months })
    const params = new URLSearchParams()
    if (opts?.months !== undefined) params.set('months', String(opts.months))
    const qs = params.toString()
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing${qs ? `?${qs}` : ''}`,
      { headers }
    )
    return this.handleResponse<MonthlyBillingResponse>(response)
  }

  async importMonthlyBilling(projectId: number, file: File): Promise<MonthlyBillingImportResponse> {
    this.log('Importing monthly billing', { projectId, filename: file.name })
    const formData = new FormData()
    formData.append('file', file)
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/import`,
      { method: 'POST', headers, body: formData }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  async addManualBillingEntry(
    projectId: number,
    body: { billing_month: string; actual_kwh?: number; forecast_kwh?: number }
  ): Promise<MonthlyBillingImportResponse> {
    this.log('Adding manual billing entry', { projectId, body })
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/manual`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  // =========================================================================
  // Meter Billing
  // =========================================================================

  async getMeterBilling(projectId: number, opts?: { months?: number }): Promise<MeterBillingResponse> {
    this.log('Fetching meter billing', { projectId, months: opts?.months })
    const params = new URLSearchParams()
    if (opts?.months !== undefined) params.set('months', String(opts.months))
    const qs = params.toString()
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/meter-billing${qs ? `?${qs}` : ''}`,
      { headers }
    )
    return this.handleResponse<MeterBillingResponse>(response)
  }

  async generateExpectedInvoice(
    projectId: number,
    body: { billing_month: string; idempotency_key?: string; invoice_direction?: 'payable' | 'receivable' }
  ): Promise<Record<string, unknown>> {
    this.log('Generating expected invoice', { projectId, body })
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/billing/generate-expected-invoice`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<Record<string, unknown>>(response)
  }

  // =========================================================================
  // Plant Performance
  // =========================================================================

  async getPlantPerformance(projectId: number, opts?: { months?: number }): Promise<PlantPerformanceResponse> {
    this.log('Fetching plant performance', { projectId, months: opts?.months })
    const params = new URLSearchParams()
    if (opts?.months !== undefined) params.set('months', String(opts.months))
    const qs = params.toString()
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance${qs ? `?${qs}` : ''}`,
      { headers }
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
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance/manual`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  async importPlantPerformance(projectId: number, file: File): Promise<MonthlyBillingImportResponse> {
    this.log('Importing plant performance', { projectId, filename: file.name })
    const formData = new FormData()
    formData.append('file', file)
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/plant-performance/import`,
      { method: 'POST', headers, body: formData }
    )
    return this.handleResponse<MonthlyBillingImportResponse>(response)
  }

  // =========================================================================
  // Degradation
  // =========================================================================

  async applyDegradation(projectId: number): Promise<{ success: boolean; updated_rows: number; annual_degradation_pct: number }> {
    this.log('Applying degradation', { projectId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/apply-degradation`,
      { method: 'POST', headers }
    )
    return this.handleResponse<{ success: boolean; updated_rows: number; annual_degradation_pct: number }>(response)
  }

  // =========================================================================
  // Portfolio
  // =========================================================================

  async getPortfolioRevenueSummary(organizationId: number): Promise<PortfolioRevenueSummaryResponse> {
    this.log('Fetching portfolio revenue summary', { organizationId })
    const headers = await this.getAuthHeaders(organizationId)
    const response = await fetch(
      `${this.baseUrl}/api/portfolio/revenue-summary?organization_id=${organizationId}`,
      { headers }
    )
    return this.handleResponse<PortfolioRevenueSummaryResponse>(response)
  }

  async exportMonthlyBilling(projectId: number): Promise<Blob> {
    this.log('Exporting monthly billing', { projectId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(
      `${this.baseUrl}/api/projects/${projectId}/monthly-billing/export`,
      { headers }
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

  // ==========================================================================
  // Team Management
  // ==========================================================================

  async getMe(): Promise<TeamMember> {
    this.log('Getting current user membership')
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/team/me`, { headers })
    return this.handleResponse<TeamMember>(response)
  }

  async listTeamMembers(): Promise<TeamMember[]> {
    this.log('Listing team members')
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/team/members`, { headers })
    return this.handleResponse<TeamMember[]>(response)
  }

  async inviteTeamMember(body: InviteMemberRequest): Promise<TeamMember> {
    this.log('Inviting team member', body)
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(`${this.baseUrl}/api/team/invite`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
    return this.handleResponse<TeamMember>(response)
  }

  async updateTeamMember(memberId: number, body: UpdateMemberRequest): Promise<TeamMember> {
    this.log('Updating team member', { memberId, ...body })
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(`${this.baseUrl}/api/team/members/${memberId}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify(body),
    })
    return this.handleResponse<TeamMember>(response)
  }

  async deactivateTeamMember(memberId: number): Promise<TeamMember> {
    this.log('Deactivating team member', { memberId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/team/members/${memberId}/deactivate`, {
      method: 'POST',
      headers,
    })
    return this.handleResponse<TeamMember>(response)
  }

  async reactivateTeamMember(memberId: number): Promise<TeamMember> {
    this.log('Reactivating team member', { memberId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/team/members/${memberId}/reactivate`, {
      method: 'POST',
      headers,
    })
    return this.handleResponse<TeamMember>(response)
  }

  // ==========================================================================
  // Change Requests
  // ==========================================================================

  async getChangeRequestSummary(projectId: number): Promise<ChangeRequestSummary> {
    this.log('Getting change request summary', { projectId })
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/change-requests/summary?project_id=${projectId}`, { headers })
    return this.handleResponse<ChangeRequestSummary>(response)
  }

  async listChangeRequests(projectId: number, status?: string): Promise<ChangeRequest[]> {
    this.log('Listing change requests', { projectId, status })
    const headers = await this.getAuthHeaders()
    const params = new URLSearchParams({ project_id: String(projectId) })
    if (status) params.set('status', status)
    const response = await fetch(`${this.baseUrl}/api/change-requests?${params}`, { headers })
    return this.handleResponse<ChangeRequest[]>(response)
  }

  async approveChangeRequest(id: number, note?: string): Promise<{ success: boolean; status: string; id: number }> {
    this.log('Approving change request', { id })
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(`${this.baseUrl}/api/change-requests/${id}/approve`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ note }),
    })
    return this.handleResponse(response)
  }

  async rejectChangeRequest(id: number, note?: string): Promise<{ success: boolean; status: string; id: number }> {
    this.log('Rejecting change request', { id })
    const headers = await this.getAuthHeaders()
    headers['Content-Type'] = 'application/json'
    const response = await fetch(`${this.baseUrl}/api/change-requests/${id}/reject`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ note }),
    })
    return this.handleResponse(response)
  }

  async cancelChangeRequest(id: number): Promise<{ success: boolean; status: string; id: number }> {
    this.log('Cancelling change request', { id })
    const headers = await this.getAuthHeaders()
    const response = await fetch(`${this.baseUrl}/api/change-requests/${id}/cancel`, {
      method: 'POST',
      headers,
    })
    return this.handleResponse(response)
  }
}

// ============================================================================
// Default Instance
// ============================================================================

export const adminClient = new AdminClient({
  getAuthToken: async () => {
    if (typeof window === 'undefined') return null
    // Demo mode: use static demo token (no Supabase session exists)
    if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
      return process.env.NEXT_PUBLIC_DEMO_ACCESS_TOKEN ?? null
    }
    const { createClient } = await import('@/lib/supabase/client')
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token ?? null
  },
})

// Default org for initial page loads (overridden by auth resolution in projects/page.tsx)
if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'development') {
  adminClient.setOrganizationId(1)
}
