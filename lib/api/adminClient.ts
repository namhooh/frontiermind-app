/**
 * Admin API Client
 *
 * API client for client onboarding and API key management.
 * Used by the /admin page to create organizations and generate API keys.
 */

// ============================================================================
// Configuration
// ============================================================================

const API_BASE_URL =
  process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:8000'

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
}

// ============================================================================
// Default Instance
// ============================================================================

export const adminClient = new AdminClient()
