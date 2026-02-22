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
  clauses: Record<string, unknown>[]
  amendments: Record<string, unknown>[]
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
        headers: { 'Content-Type': 'application/json', 'X-Organization-ID': String(orgId) },
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
}

// ============================================================================
// Default Instance
// ============================================================================

export const adminClient = new AdminClient()
