/**
 * API Client for Python Backend
 *
 * Task 4.2: Create API Client for Python Backend
 *
 * Features:
 * - Automatic retry on network errors
 * - Request/response logging
 * - Error handling with typed errors
 * - Progress tracking for uploads
 * - Authentication token injection
 * - Base URL from environment variable
 */

// ============================================================================
// Configuration
// ============================================================================

const API_BASE_URL =
  process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || 'http://localhost:8000'

const DEFAULT_RETRY_COUNT = 3
const DEFAULT_RETRY_DELAY_MS = 1000

// ============================================================================
// TypeScript Interfaces
// ============================================================================

/** PII entity detected in contract text */
export interface PIIEntity {
  entity_type: string
  start: number
  end: number
  score: number
  text: string
}

/** Extracted clause from contract */
export interface ExtractedClause {
  clause_id?: string
  clause_name: string
  section_reference: string

  // NEW fields (use these)
  category: string
  category_code: string
  category_confidence?: number

  // DEPRECATED fields (nullable for backward compat)
  clause_type?: string | null
  clause_category?: string | null

  raw_text: string
  summary?: string | null
  responsible_party: string
  beneficiary_party?: string | null
  normalized_payload: Record<string, unknown>
  extraction_confidence?: number
  confidence_score?: number // deprecated
  notes?: string | null
}

/** Clause from database with additional fields */
export interface Clause extends ExtractedClause {
  id: number
  contract_id: number
  clause_type_id?: number
  clause_category_id?: number
  clause_responsibleparty_id?: number
  project_id?: number
  created_at: string
  updated_at?: string
}

/** Contract metadata */
export interface Contract {
  id: number
  name: string
  description?: string
  file_location: string
  parsing_status: 'pending' | 'processing' | 'completed' | 'failed'
  parsing_started_at?: string
  parsing_completed_at?: string
  parsing_error?: string
  pii_detected_count?: number
  clauses_extracted_count?: number
  processing_time_seconds?: number
  project_id?: number
  organization_id?: number
  counterparty_id?: number
  contract_type_id?: number
  contract_status_id?: number
  created_at: string
  updated_at?: string
}

/** Options for parsing a contract */
export interface ParseContractOptions {
  file: File
  project_id?: number
  organization_id?: number
  counterparty_id?: number
  contract_type_id?: number
  contract_status_id?: number
  onProgress?: (progress: UploadProgress) => void
}

/** Upload progress information */
export interface UploadProgress {
  stage: 'uploading' | 'parsing' | 'detecting_pii' | 'extracting_clauses' | 'storing' | 'complete'
  percentage: number
  message: string
}

/** Result from contract parsing */
export interface ContractParseResult {
  success: boolean
  contract_id: number
  clauses_extracted: number
  pii_detected: number
  pii_anonymized: number
  processing_time: number
  clauses: ExtractedClause[]
  message: string
}

/** Rule evaluation result from a single rule */
export interface RuleResult {
  breach: boolean
  rule_type: string
  clause_id: number
  calculated_value?: number
  threshold_value?: number
  shortfall?: number
  ld_amount?: number
  details: Record<string, unknown>
}

/** Complete rule evaluation result for a period */
export interface RuleEvaluationResult {
  contract_id: number
  period_start: string
  period_end: string
  default_events: RuleResult[]
  ld_total: number
  notifications_generated: number
  processing_notes: string[]
}

/** Request body for evaluating rules */
export interface EvaluateRulesRequest {
  contract_id: number
  period_start: Date
  period_end: Date
}

/** Default event (contract breach) */
export interface DefaultEvent {
  id: number
  project_id: number
  contract_id: number
  contract_name: string
  time_occurred: string
  time_identified: string
  time_cured?: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: 'open' | 'cured' | 'closed'
  metadata_detail: Record<string, unknown>
  created_at: string
}

/** Filters for querying default events */
export interface DefaultFilters {
  project_id?: number
  contract_id?: number
  status?: 'open' | 'cured' | 'closed'
  time_start?: Date
  time_end?: Date
  limit?: number
  offset?: number
}

/** Result from curing a default event */
export interface CureDefaultResult {
  success: boolean
  message: string
  default_event_id: number
  rule_outputs: Array<{
    id: number
    rule_type: string
    ld_amount: number
    breach: boolean
    description: string
  }>
  total_ld: number
  invoice_updated: boolean
  notes: string[]
}

/** API client configuration options */
export interface APIClientConfig {
  baseUrl?: string
  retryCount?: number
  retryDelayMs?: number
  enableLogging?: boolean
  getAuthToken?: () => Promise<string | null>
}

// ============================================================================
// Error Handling
// ============================================================================

/** Custom error class for API errors */
export class ContractsAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string,
    public details?: string
  ) {
    super(message)
    this.name = 'ContractsAPIError'
  }
}

/** Check if an error is a network/transient error that should be retried */
function isRetryableError(error: unknown): boolean {
  if (error instanceof ContractsAPIError) {
    // Retry on server errors (5xx) but not client errors (4xx)
    return error.statusCode >= 500 && error.statusCode < 600
  }
  // Retry on network errors (fetch throws TypeError on network failure)
  return error instanceof TypeError
}

// ============================================================================
// Utility Functions
// ============================================================================

/** Sleep for a specified number of milliseconds */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Format date for API query parameters */
function formatDateForAPI(date: Date): string {
  return date.toISOString()
}

// ============================================================================
// API Client Class
// ============================================================================

/**
 * API Client for Python Backend
 *
 * Provides methods for:
 * - Contract parsing and retrieval
 * - Rules evaluation
 * - Default event management
 *
 * @example
 * ```typescript
 * const client = new APIClient({
 *   getAuthToken: async () => session?.access_token
 * })
 *
 * const result = await client.uploadContract({ file: pdfFile })
 * console.log(`Extracted ${result.clauses_extracted} clauses`)
 * ```
 */
export class APIClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>

  constructor(config: APIClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.retryCount = config.retryCount ?? DEFAULT_RETRY_COUNT
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
    this.getAuthToken = config.getAuthToken
  }

  // --------------------------------------------------------------------------
  // Private Methods
  // --------------------------------------------------------------------------

  /** Log request/response information */
  private log(level: 'info' | 'warn' | 'error', message: string, data?: unknown): void {
    if (!this.enableLogging) return

    const timestamp = new Date().toISOString()
    const prefix = `[APIClient ${timestamp}]`

    switch (level) {
      case 'info':
        console.log(prefix, message, data ?? '')
        break
      case 'warn':
        console.warn(prefix, message, data ?? '')
        break
      case 'error':
        console.error(prefix, message, data ?? '')
        break
    }
  }

  /** Get authorization headers if auth token is available */
  private async getAuthHeaders(): Promise<Record<string, string>> {
    if (!this.getAuthToken) return {}

    const token = await this.getAuthToken()
    if (!token) return {}

    return { Authorization: `Bearer ${token}` }
  }

  /** Execute a fetch request with retry logic */
  private async fetchWithRetry<T>(
    url: string,
    options: RequestInit,
    retryCount: number = this.retryCount
  ): Promise<T> {
    let lastError: unknown

    for (let attempt = 0; attempt <= retryCount; attempt++) {
      try {
        if (attempt > 0) {
          this.log('info', `Retry attempt ${attempt}/${retryCount} for ${url}`)
          await sleep(this.retryDelayMs * attempt) // Exponential backoff
        }

        this.log('info', `Request: ${options.method || 'GET'} ${url}`)

        const response = await fetch(url, options)
        const responseData = await response.json()

        if (!response.ok) {
          const error = new ContractsAPIError(
            responseData.detail?.message || responseData.message || 'Request failed',
            response.status,
            responseData.detail?.error || responseData.error,
            responseData.detail?.details || responseData.details
          )

          if (isRetryableError(error) && attempt < retryCount) {
            lastError = error
            this.log('warn', `Retryable error on attempt ${attempt + 1}`, {
              status: error.statusCode,
              message: error.message,
            })
            continue
          }

          throw error
        }

        this.log('info', `Response: ${response.status} OK`)
        return responseData as T
      } catch (error) {
        lastError = error

        if (isRetryableError(error) && attempt < retryCount) {
          this.log('warn', `Network error on attempt ${attempt + 1}`, error)
          continue
        }

        this.log('error', `Request failed: ${url}`, error)
        throw error
      }
    }

    throw lastError
  }

  // --------------------------------------------------------------------------
  // Contract Methods
  // --------------------------------------------------------------------------

  /**
   * Upload and parse a contract file.
   *
   * @param options - File and optional metadata
   * @returns Parsed contract result with extracted clauses
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const result = await client.uploadContract({
   *   file: selectedFile,
   *   project_id: 1,
   *   onProgress: (progress) => {
   *     console.log(`${progress.stage}: ${progress.percentage}%`)
   *   }
   * })
   * ```
   */
  async uploadContract(options: ParseContractOptions): Promise<ContractParseResult> {
    const { file, onProgress, ...metadata } = options

    // Report upload start
    onProgress?.({
      stage: 'uploading',
      percentage: 0,
      message: 'Uploading contract file...',
    })

    const formData = new FormData()
    formData.append('file', file)

    // Add optional metadata
    if (metadata.project_id) formData.append('project_id', metadata.project_id.toString())
    if (metadata.organization_id)
      formData.append('organization_id', metadata.organization_id.toString())
    if (metadata.counterparty_id)
      formData.append('counterparty_id', metadata.counterparty_id.toString())
    if (metadata.contract_type_id)
      formData.append('contract_type_id', metadata.contract_type_id.toString())
    if (metadata.contract_status_id)
      formData.append('contract_status_id', metadata.contract_status_id.toString())

    const authHeaders = await this.getAuthHeaders()
    const url = `${this.baseUrl}/api/contracts/parse`

    this.log('info', `Uploading contract: ${file.name}`, {
      size: file.size,
      type: file.type,
    })

    // Report progress stages (simulated since we can't get real progress from fetch)
    onProgress?.({
      stage: 'uploading',
      percentage: 30,
      message: 'File uploaded, starting processing...',
    })

    onProgress?.({
      stage: 'parsing',
      percentage: 40,
      message: 'Parsing document with OCR...',
    })

    onProgress?.({
      stage: 'detecting_pii',
      percentage: 55,
      message: 'Detecting and anonymizing PII...',
    })

    onProgress?.({
      stage: 'extracting_clauses',
      percentage: 70,
      message: 'Extracting clauses with AI...',
    })

    try {
      const result = await this.fetchWithRetry<ContractParseResult>(url, {
        method: 'POST',
        body: formData,
        headers: authHeaders,
      })

      onProgress?.({
        stage: 'complete',
        percentage: 100,
        message: `Complete! Extracted ${result.clauses_extracted} clauses.`,
      })

      return result
    } catch (error) {
      onProgress?.({
        stage: 'complete',
        percentage: 100,
        message: 'Processing failed',
      })
      throw error
    }
  }

  /**
   * Get contract metadata by ID.
   *
   * @param contractId - Contract ID
   * @returns Contract data
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const contract = await client.getContract(123)
   * console.log(`Status: ${contract.parsing_status}`)
   * ```
   */
  async getContract(contractId: number): Promise<Contract> {
    const authHeaders = await this.getAuthHeaders()
    const url = `${this.baseUrl}/api/contracts/${contractId}`

    const result = await this.fetchWithRetry<{ success: boolean; contract: Contract }>(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
    })

    return result.contract
  }

  /**
   * Get clauses for a contract.
   *
   * @param contractId - Contract ID
   * @param type - Optional clause type filter
   * @param minConfidence - Optional minimum confidence score filter
   * @returns List of clauses
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const clauses = await client.getClauses(123, 'availability', 0.8)
   * ```
   */
  async getClauses(
    contractId: number,
    type?: string,
    minConfidence?: number
  ): Promise<Clause[]> {
    const authHeaders = await this.getAuthHeaders()

    const params = new URLSearchParams()
    if (type) params.append('clause_type', type)
    if (minConfidence !== undefined) params.append('min_confidence', minConfidence.toString())

    const queryString = params.toString()
    const url = `${this.baseUrl}/api/contracts/${contractId}/clauses${queryString ? '?' + queryString : ''}`

    const result = await this.fetchWithRetry<{
      success: boolean
      contract_id: number
      clauses: Clause[]
    }>(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
    })

    return result.clauses
  }

  // --------------------------------------------------------------------------
  // Rules Engine Methods
  // --------------------------------------------------------------------------

  /**
   * Evaluate contract rules for a period.
   *
   * Runs the rules engine to detect breaches and calculate liquidated damages.
   *
   * @param contractId - Contract ID to evaluate
   * @param periodStart - Start of evaluation period
   * @param periodEnd - End of evaluation period
   * @returns Rule evaluation result with default events and LD totals
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const result = await client.evaluateRules(
   *   123,
   *   new Date('2024-11-01'),
   *   new Date('2024-12-01')
   * )
   * console.log(`Total LD: $${result.ld_total}`)
   * ```
   */
  async evaluateRules(
    contractId: number,
    periodStart: Date,
    periodEnd: Date
  ): Promise<RuleEvaluationResult> {
    const authHeaders = await this.getAuthHeaders()
    const url = `${this.baseUrl}/api/rules/evaluate`

    this.log('info', `Evaluating rules for contract ${contractId}`, {
      periodStart: periodStart.toISOString(),
      periodEnd: periodEnd.toISOString(),
    })

    const result = await this.fetchWithRetry<RuleEvaluationResult>(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
      body: JSON.stringify({
        contract_id: contractId,
        period_start: formatDateForAPI(periodStart),
        period_end: formatDateForAPI(periodEnd),
      }),
    })

    return result
  }

  /**
   * Get default events (contract breaches) with optional filters.
   *
   * @param filters - Optional filters for querying defaults
   * @returns List of default events
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const defaults = await client.getDefaults({
   *   contract_id: 123,
   *   status: 'open',
   *   limit: 20
   * })
   * ```
   */
  async getDefaults(filters?: DefaultFilters): Promise<DefaultEvent[]> {
    const authHeaders = await this.getAuthHeaders()

    const params = new URLSearchParams()
    if (filters?.project_id) params.append('project_id', filters.project_id.toString())
    if (filters?.contract_id) params.append('contract_id', filters.contract_id.toString())
    if (filters?.status) params.append('status', filters.status)
    if (filters?.time_start) params.append('time_start', formatDateForAPI(filters.time_start))
    if (filters?.time_end) params.append('time_end', formatDateForAPI(filters.time_end))
    if (filters?.limit) params.append('limit', filters.limit.toString())
    if (filters?.offset) params.append('offset', filters.offset.toString())

    const queryString = params.toString()
    const url = `${this.baseUrl}/api/rules/defaults${queryString ? '?' + queryString : ''}`

    this.log('info', 'Fetching default events', filters)

    const result = await this.fetchWithRetry<DefaultEvent[]>(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
    })

    return result
  }

  /**
   * Mark a default event as cured.
   *
   * Updates the status to 'cured' and returns LD information.
   *
   * @param defaultEventId - Default event ID to cure
   * @returns Cure result with LD amounts
   * @throws ContractsAPIError for API failures
   *
   * @example
   * ```typescript
   * const result = await client.cureDefault(12)
   * console.log(`Total LD for cured breach: $${result.total_ld}`)
   * ```
   */
  async cureDefault(defaultEventId: number): Promise<CureDefaultResult> {
    const authHeaders = await this.getAuthHeaders()
    const url = `${this.baseUrl}/api/rules/defaults/${defaultEventId}/cure`

    this.log('info', `Curing default event ${defaultEventId}`)

    const result = await this.fetchWithRetry<CureDefaultResult>(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
    })

    return result
  }
}

// ============================================================================
// Standalone Functions (Backward Compatibility)
// ============================================================================

// Default client instance for standalone functions
const defaultClient = new APIClient()

/**
 * Parse a contract file and extract clauses with PII protection.
 *
 * @deprecated Use `new APIClient().uploadContract()` instead for better control
 * @param options - File and optional metadata
 * @returns Parsed contract result with extracted clauses
 * @throws ContractsAPIError for API failures
 */
export async function parseContract(
  options: ParseContractOptions
): Promise<ContractParseResult> {
  return defaultClient.uploadContract(options)
}

/**
 * Get contract metadata by ID.
 *
 * @deprecated Use `new APIClient().getContract()` instead for better control
 * @param contractId - Contract ID
 * @returns Contract data
 * @throws ContractsAPIError for API failures
 */
export async function getContract(contractId: number): Promise<Contract> {
  return defaultClient.getContract(contractId)
}

/**
 * Get clauses for a contract.
 *
 * @deprecated Use `new APIClient().getClauses()` instead for better control
 * @param contractId - Contract ID
 * @param minConfidence - Optional minimum confidence score filter
 * @returns List of clauses
 * @throws ContractsAPIError for API failures
 */
export async function getContractClauses(
  contractId: number,
  minConfidence?: number
): Promise<Clause[]> {
  return defaultClient.getClauses(contractId, undefined, minConfidence)
}

/**
 * Evaluate contract rules for a period.
 *
 * @deprecated Use `new APIClient().evaluateRules()` instead for better control
 */
export async function evaluateRules(
  contractId: number,
  periodStart: Date,
  periodEnd: Date
): Promise<RuleEvaluationResult> {
  return defaultClient.evaluateRules(contractId, periodStart, periodEnd)
}

/**
 * Get default events with optional filters.
 *
 * @deprecated Use `new APIClient().getDefaults()` instead for better control
 */
export async function getDefaults(filters?: DefaultFilters): Promise<DefaultEvent[]> {
  return defaultClient.getDefaults(filters)
}
