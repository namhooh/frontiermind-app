/**
 * Invoices API Client
 *
 * API client for invoice management.
 * Supports creating invoices from workflow data.
 *
 * Features:
 * - Automatic retry on network errors
 * - Request/response logging
 * - Error handling with typed errors
 * - TypeScript interfaces matching backend models
 */

// ============================================================================
// Configuration
// ============================================================================

import { getApiBaseUrl } from './config'

const API_BASE_URL = getApiBaseUrl()

const DEFAULT_RETRY_COUNT = 3
const DEFAULT_RETRY_DELAY_MS = 1000

// ============================================================================
// TypeScript Interfaces - Request/Response
// ============================================================================

/** Line item data for invoice creation */
export interface InvoiceLineItemRequest {
  description: string
  quantity: number
  unit: string
  rate: number
  amount: number
  invoice_line_item_type_id?: number
  meter_aggregate_id?: number
}

/** Invoice header data for creation */
export interface InvoiceDataRequest {
  invoice_number?: string
  invoice_date: string
  due_date?: string
  total_amount: number
  status?: string
}

/** Input for creating a default event with an invoice */
export interface DefaultEventInput {
  description: string
  rule_type: string
  calculated_value: number
  threshold_value: number
  shortfall: number
  ld_amount: number
  time_start: string
  time_end: string
}

/** Request body for creating an invoice */
export interface CreateInvoiceRequest {
  project_id: number
  organization_id: number
  contract_id: number
  billing_period_id: number
  invoice_data: InvoiceDataRequest
  line_items: InvoiceLineItemRequest[]
  default_events?: DefaultEventInput[]
}

/** Response for invoice creation */
export interface CreateInvoiceResponse {
  success: boolean
  invoice_id: number
  message: string
}

// ============================================================================
// Error Class
// ============================================================================

export class InvoicesAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string,
    public details?: string
  ) {
    super(message)
    this.name = 'InvoicesAPIError'
  }
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface InvoicesClientConfig {
  baseUrl?: string
  retryCount?: number
  retryDelayMs?: number
  enableLogging?: boolean
  getAuthToken?: () => Promise<string | null>
}

// ============================================================================
// Invoices Client Class
// ============================================================================

/**
 * API client for invoice management.
 *
 * @example
 * ```typescript
 * const client = new InvoicesClient()
 *
 * const result = await client.createInvoice({
 *   project_id: 1,
 *   organization_id: 1,
 *   contract_id: 1,
 *   billing_period_id: 1,
 *   invoice_data: {
 *     invoice_date: '2026-01-26',
 *     total_amount: 12500.00,
 *   },
 *   line_items: [{ description: 'Energy', quantity: 500, unit: 'MWh', rate: 25, amount: 12500 }]
 * })
 * ```
 */
export class InvoicesClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>

  constructor(config: InvoicesClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.retryCount = config.retryCount ?? DEFAULT_RETRY_COUNT
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS
    this.enableLogging = config.enableLogging ?? false
    this.getAuthToken = config.getAuthToken
  }

  private log(message: string, data?: unknown): void {
    if (this.enableLogging) {
      console.log(`[InvoicesClient] ${message}`, data || '')
    }
  }

  private async sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  private async getHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    if (this.getAuthToken) {
      const token = await this.getAuthToken()
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }
    }

    return headers
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new InvoicesAPIError(
        errorBody.message || errorBody.detail?.message || `HTTP ${response.status}`,
        response.status,
        errorBody.error || errorBody.detail?.error,
        errorBody.details || errorBody.detail?.details
      )
    }
    return response.json()
  }

  private async fetchWithRetry<T>(
    url: string,
    options: RequestInit
  ): Promise<T> {
    let lastError: Error | null = null

    for (let attempt = 0; attempt < this.retryCount; attempt++) {
      try {
        this.log(`Attempt ${attempt + 1}/${this.retryCount}: ${options.method || 'GET'} ${url}`)
        const response = await fetch(url, options)
        return await this.handleResponse<T>(response)
      } catch (error) {
        lastError = error as Error

        // Don't retry on client errors (4xx)
        if (error instanceof InvoicesAPIError && error.statusCode >= 400 && error.statusCode < 500) {
          throw error
        }

        // Retry on network errors and server errors
        if (attempt < this.retryCount - 1) {
          this.log(`Retrying after error: ${lastError.message}`)
          await this.sleep(this.retryDelayMs * (attempt + 1))
        }
      }
    }

    throw lastError || new InvoicesAPIError('Request failed', 500)
  }

  // =========================================================================
  // API Methods
  // =========================================================================

  /**
   * Create an invoice from workflow data.
   *
   * @param request - Invoice creation request with header and line items
   * @returns Created invoice ID and status
   * @throws InvoicesAPIError for API failures
   *
   * @example
   * ```typescript
   * const result = await client.createInvoice({
   *   project_id: 1,
   *   organization_id: 1,
   *   contract_id: 1,
   *   billing_period_id: 1,
   *   invoice_data: {
   *     invoice_date: '2026-01-26',
   *     total_amount: 12500.00,
   *   },
   *   line_items: [
   *     { description: 'Energy delivery', quantity: 500, unit: 'MWh', rate: 25, amount: 12500 }
   *   ]
   * })
   * console.log(`Created invoice ${result.invoice_id}`)
   * ```
   */
  async createInvoice(request: CreateInvoiceRequest): Promise<CreateInvoiceResponse> {
    const url = `${this.baseUrl}/api/invoices`
    const headers = await this.getHeaders()

    this.log('Creating invoice', request)

    const response = await this.fetchWithRetry<CreateInvoiceResponse>(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
    })

    this.log('Invoice created', response)
    return response
  }
}

// ============================================================================
// Default Client Instance
// ============================================================================

const defaultClient = new InvoicesClient()

/**
 * Create an invoice from workflow data.
 *
 * @param request - Invoice creation request
 * @returns Created invoice ID and status
 */
export async function createInvoice(
  request: CreateInvoiceRequest
): Promise<CreateInvoiceResponse> {
  return defaultClient.createInvoice(request)
}
