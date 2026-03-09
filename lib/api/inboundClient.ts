/**
 * Inbound Email API Client
 *
 * API client for inbound message review: listing, approving, rejecting
 * messages from unknown senders, and downloading attachments.
 *
 * Follows the same patterns as notificationsClient.ts.
 */

import { getApiBaseUrl } from './config'

const API_BASE_URL = getApiBaseUrl()

const DEFAULT_RETRY_COUNT = 3
const DEFAULT_RETRY_DELAY_MS = 1000

// ============================================================================
// Types
// ============================================================================

export type InboundMessageStatus =
  | 'received'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'noise'
  | 'auto_processed'
  | 'failed'

export type AttachmentProcessingStatus =
  | 'pending'
  | 'processing'
  | 'extracted'
  | 'failed'
  | 'skipped'

// ============================================================================
// Interfaces - Entities
// ============================================================================

export interface InboundAttachment {
  id: number
  filename?: string
  content_type?: string
  size_bytes?: number
  attachment_processing_status: AttachmentProcessingStatus
  extraction_result?: Record<string, unknown>
  reference_price_id?: number
  created_at: string
}

export interface InboundMessage {
  id: number
  organization_id: number
  channel: string
  subject?: string
  sender_email?: string
  sender_name?: string
  inbound_message_status: InboundMessageStatus
  classification_reason?: string
  failed_reason?: string
  attachment_count: number
  invoice_header_id?: number
  project_id?: number
  counterparty_id?: number
  outbound_message_id?: number
  created_at: string
  reviewed_by?: string
  reviewed_at?: string
  attachments: InboundAttachment[]
}

// ============================================================================
// Interfaces - Requests / Responses
// ============================================================================

export interface InboundMessageFilters {
  inbound_message_status?: InboundMessageStatus
  channel?: string
  project_id?: number
  limit?: number
  offset?: number
}

export interface ApproveRequest {
  reason?: string
  project_id?: number
  billing_month?: string
}

export interface RejectRequest {
  reason?: string
}

export interface AttachmentExtractionResult {
  success: boolean
  message: string
  status: string
  observation_id?: number
  mrp_per_kwh?: number
  confidence?: string
  billing_month?: string
  failed_reason?: string
}

export interface ApproveResponse {
  success: boolean
  message: string
  extraction_results: AttachmentExtractionResult[]
}

interface MessageListResponse {
  success: boolean
  messages: InboundMessage[]
  total: number
  limit: number
  offset: number
}

interface PresignedUrlResponse {
  success: boolean
  url: string
  filename?: string
}

interface SuccessResponse {
  success: boolean
  message: string
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface InboundClientConfig {
  baseUrl?: string
  retryCount?: number
  retryDelayMs?: number
  enableLogging?: boolean
  getAuthToken?: () => Promise<string | null>
  organizationId?: number
}

// ============================================================================
// Error Handling
// ============================================================================

export class InboundAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string
  ) {
    super(message)
    this.name = 'InboundAPIError'
  }
}

function isRetryableError(error: unknown): boolean {
  if (error instanceof InboundAPIError) {
    return error.statusCode >= 500 && error.statusCode < 600
  }
  return error instanceof TypeError
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ============================================================================
// Client Class
// ============================================================================

export class InboundClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>
  private organizationId?: number

  constructor(config: InboundClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.retryCount = config.retryCount ?? DEFAULT_RETRY_COUNT
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
    this.getAuthToken = config.getAuthToken
    this.organizationId = config.organizationId
  }

  private log(level: 'info' | 'warn' | 'error', message: string, data?: unknown): void {
    if (!this.enableLogging) return
    const prefix = `[InboundClient ${new Date().toISOString()}]`
    if (level === 'error') console.error(prefix, message, data ?? '')
    else if (level === 'warn') console.warn(prefix, message, data ?? '')
    else console.log(prefix, message, data ?? '')
  }

  private async getHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (this.getAuthToken) {
      const token = await this.getAuthToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    }
    if (this.organizationId) {
      headers['X-Organization-ID'] = this.organizationId.toString()
    }
    return headers
  }

  private async fetchWithRetry<T>(url: string, options: RequestInit, retryCount = this.retryCount): Promise<T> {
    let lastError: unknown
    for (let attempt = 0; attempt <= retryCount; attempt++) {
      try {
        if (attempt > 0) {
          this.log('info', `Retry ${attempt}/${retryCount} for ${url}`)
          await sleep(this.retryDelayMs * attempt)
        }
        this.log('info', `${options.method || 'GET'} ${url}`)
        const response = await fetch(url, options)
        const text = await response.text()
        let responseData: Record<string, unknown>
        try {
          responseData = JSON.parse(text)
        } catch {
          // Non-JSON response (e.g. plain-text "Internal Server Error")
          const error = new InboundAPIError(text || 'Request failed', response.status)
          if (isRetryableError(error) && attempt < retryCount) { lastError = error; continue }
          throw error
        }
        if (!response.ok) {
          const error = new InboundAPIError(
            responseData.detail?.message || (typeof responseData.detail === 'string' ? responseData.detail : null) || responseData.message || 'Request failed',
            response.status,
            responseData.detail?.error
          )
          if (isRetryableError(error) && attempt < retryCount) { lastError = error; continue }
          throw error
        }
        return responseData as T
      } catch (error) {
        lastError = error
        if (isRetryableError(error) && attempt < retryCount) continue
        this.log('error', `Request failed: ${url}`, error)
        throw error
      }
    }
    throw lastError
  }

  // --------------------------------------------------------------------------
  // Message Methods
  // --------------------------------------------------------------------------

  async listMessages(filters?: InboundMessageFilters): Promise<{ messages: InboundMessage[]; total: number }> {
    const headers = await this.getHeaders()
    const params = new URLSearchParams()
    if (filters?.inbound_message_status) params.append('inbound_message_status', filters.inbound_message_status)
    if (filters?.channel) params.append('channel', filters.channel)
    if (filters?.project_id) params.append('project_id', filters.project_id.toString())
    if (filters?.limit) params.append('limit', filters.limit.toString())
    if (filters?.offset) params.append('offset', filters.offset.toString())
    const qs = params.toString()
    const url = `${this.baseUrl}/api/inbound-email/messages${qs ? '?' + qs : ''}`
    const result = await this.fetchWithRetry<MessageListResponse>(url, { method: 'GET', headers })
    return { messages: result.messages, total: result.total }
  }

  async getMessage(messageId: number): Promise<InboundMessage> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<InboundMessage>(
      `${this.baseUrl}/api/inbound-email/messages/${messageId}`,
      { method: 'GET', headers }
    )
  }

  async approveMessage(messageId: number, body?: ApproveRequest): Promise<ApproveResponse> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<ApproveResponse>(
      `${this.baseUrl}/api/inbound-email/messages/${messageId}/approve`,
      { method: 'POST', headers, body: JSON.stringify(body ?? {}) }
    )
  }

  async rejectMessage(messageId: number, body?: RejectRequest): Promise<{ success: boolean; message: string }> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<SuccessResponse>(
      `${this.baseUrl}/api/inbound-email/messages/${messageId}/reject`,
      { method: 'POST', headers, body: JSON.stringify(body ?? {}) }
    )
  }

  // --------------------------------------------------------------------------
  // Attachment Methods
  // --------------------------------------------------------------------------

  async getAttachmentUrl(attachmentId: number): Promise<{ url: string; filename?: string }> {
    const headers = await this.getHeaders()
    const result = await this.fetchWithRetry<PresignedUrlResponse>(
      `${this.baseUrl}/api/inbound-email/attachments/${attachmentId}`,
      { method: 'GET', headers }
    )
    return { url: result.url, filename: result.filename }
  }
}
