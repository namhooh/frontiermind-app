/**
 * Notifications API Client
 *
 * API client for email notification management: templates, schedules,
 * email logs, submissions, and immediate sends.
 *
 * Follows the same patterns as reportsClient.ts.
 */

// ============================================================================
// Configuration
// ============================================================================

import { getApiBaseUrl } from './config'

const API_BASE_URL = getApiBaseUrl()

const DEFAULT_RETRY_COUNT = 3
const DEFAULT_RETRY_DELAY_MS = 1000

// ============================================================================
// Types
// ============================================================================

export type EmailScheduleType =
  | 'invoice_reminder'
  | 'invoice_initial'
  | 'invoice_escalation'
  | 'compliance_alert'
  | 'meter_data_missing'
  | 'report_ready'
  | 'custom'

export type EmailStatus =
  | 'pending'
  | 'sending'
  | 'delivered'
  | 'bounced'
  | 'failed'
  | 'suppressed'

import type { ReportFrequency as _ReportFrequency } from './types'
export type ReportFrequency = _ReportFrequency

// ============================================================================
// Interfaces - Entities
// ============================================================================

export interface EmailTemplate {
  id: number
  organization_id: number
  email_schedule_type: EmailScheduleType
  name: string
  description?: string
  subject_template: string
  body_html: string
  body_text?: string
  available_variables: string[]
  is_system: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface NotificationSchedule {
  id: number
  organization_id: number
  email_template_id: number
  name: string
  email_schedule_type: EmailScheduleType
  report_frequency: ReportFrequency
  day_of_month?: number
  time_of_day: string
  timezone: string
  conditions: Record<string, unknown>
  max_reminders?: number
  escalation_after?: number
  include_submission_link: boolean
  submission_fields?: string[]
  is_active: boolean
  last_run_at?: string
  last_run_status?: string
  last_run_error?: string
  next_run_at?: string
  project_id?: number
  contract_id?: number
  counterparty_id?: number
  created_at: string
  updated_at: string
}

export interface EmailLogEntry {
  id: number
  organization_id: number
  email_notification_schedule_id?: number
  email_template_id?: number
  recipient_email: string
  recipient_name?: string
  subject: string
  email_status: EmailStatus
  ses_message_id?: string
  reminder_count: number
  invoice_header_id?: number
  submission_token_id?: number
  error_message?: string
  sent_at?: string
  delivered_at?: string
  created_at: string
}

export interface SubmissionResponse {
  id: number
  organization_id: number
  submission_token_id: number
  response_data: Record<string, unknown>
  submitted_by_email?: string
  invoice_header_id?: number
  created_at: string
}

// ============================================================================
// Interfaces - Requests
// ============================================================================

export interface SendEmailRequest {
  template_id: number
  invoice_header_id?: number
  recipient_emails: string[]
  include_submission_link?: boolean
  submission_fields?: string[]
  extra_context?: Record<string, unknown>
}

export interface CreateEmailTemplateRequest {
  name: string
  email_schedule_type: EmailScheduleType
  subject_template: string
  body_html: string
  body_text?: string
  description?: string
  available_variables?: string[]
}

export interface UpdateEmailTemplateRequest {
  name?: string
  subject_template?: string
  body_html?: string
  body_text?: string
  description?: string
  available_variables?: string[]
  is_active?: boolean
}

export interface CreateScheduleRequest {
  name: string
  email_template_id: number
  email_schedule_type: EmailScheduleType
  report_frequency: ReportFrequency
  day_of_month?: number
  time_of_day?: string
  timezone?: string
  conditions?: Record<string, unknown>
  max_reminders?: number
  escalation_after?: number
  include_submission_link?: boolean
  submission_fields?: string[]
  project_id?: number
  contract_id?: number
  counterparty_id?: number
}

export interface UpdateScheduleRequest {
  name?: string
  email_template_id?: number
  report_frequency?: ReportFrequency
  day_of_month?: number
  time_of_day?: string
  timezone?: string
  conditions?: Record<string, unknown>
  max_reminders?: number
  escalation_after?: number
  include_submission_link?: boolean
  submission_fields?: string[]
  project_id?: number
  contract_id?: number
  counterparty_id?: number
  is_active?: boolean
}

export interface EmailLogFilters {
  invoice_header_id?: number
  schedule_id?: number
  email_status?: EmailStatus
  limit?: number
  offset?: number
}

// ============================================================================
// Interfaces - Responses
// ============================================================================

interface TemplateListResponse {
  success: boolean
  templates: EmailTemplate[]
  total: number
}

interface ScheduleListResponse {
  success: boolean
  schedules: NotificationSchedule[]
  total: number
}

interface EmailLogListResponse {
  success: boolean
  logs: EmailLogEntry[]
  total: number
}

interface SubmissionListResponse {
  success: boolean
  submissions: SubmissionResponse[]
  total: number
}

interface SendEmailAPIResponse {
  success: boolean
  emails_sent: number
  email_log_ids: number[]
  submission_token_id?: number
  message: string
}

interface SuccessResponse {
  success: boolean
  message: string
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface NotificationsClientConfig {
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

export class NotificationsAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string
  ) {
    super(message)
    this.name = 'NotificationsAPIError'
  }
}

function isRetryableError(error: unknown): boolean {
  if (error instanceof NotificationsAPIError) {
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

export class NotificationsClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>
  private organizationId?: number

  constructor(config: NotificationsClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.retryCount = config.retryCount ?? DEFAULT_RETRY_COUNT
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
    this.getAuthToken = config.getAuthToken
    this.organizationId = config.organizationId
  }

  private log(level: 'info' | 'warn' | 'error', message: string, data?: unknown): void {
    if (!this.enableLogging) return
    const prefix = `[NotificationsClient ${new Date().toISOString()}]`
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
        const responseData = await response.json()
        if (!response.ok) {
          const error = new NotificationsAPIError(
            responseData.detail?.message || responseData.message || 'Request failed',
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
  // Send Email
  // --------------------------------------------------------------------------

  async sendEmail(request: SendEmailRequest): Promise<{
    emailsSent: number
    emailLogIds: number[]
    submissionTokenId?: number
    message: string
  }> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/notifications/send`
    const result = await this.fetchWithRetry<SendEmailAPIResponse>(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
    })
    return {
      emailsSent: result.emails_sent,
      emailLogIds: result.email_log_ids,
      submissionTokenId: result.submission_token_id,
      message: result.message,
    }
  }

  // --------------------------------------------------------------------------
  // Template Methods
  // --------------------------------------------------------------------------

  async listTemplates(scheduleType?: EmailScheduleType, includeInactive = false): Promise<EmailTemplate[]> {
    const headers = await this.getHeaders()
    const params = new URLSearchParams()
    if (scheduleType) params.append('email_schedule_type', scheduleType)
    if (includeInactive) params.append('include_inactive', 'true')
    const qs = params.toString()
    const url = `${this.baseUrl}/api/notifications/templates${qs ? '?' + qs : ''}`
    const result = await this.fetchWithRetry<TemplateListResponse>(url, { method: 'GET', headers })
    return result.templates
  }

  async getTemplate(templateId: number): Promise<EmailTemplate> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<EmailTemplate>(
      `${this.baseUrl}/api/notifications/templates/${templateId}`,
      { method: 'GET', headers }
    )
  }

  async createTemplate(data: CreateEmailTemplateRequest): Promise<EmailTemplate> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<EmailTemplate>(
      `${this.baseUrl}/api/notifications/templates`,
      { method: 'POST', headers, body: JSON.stringify(data) }
    )
  }

  async updateTemplate(templateId: number, data: UpdateEmailTemplateRequest): Promise<EmailTemplate> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<EmailTemplate>(
      `${this.baseUrl}/api/notifications/templates/${templateId}`,
      { method: 'PUT', headers, body: JSON.stringify(data) }
    )
  }

  async deactivateTemplate(templateId: number): Promise<void> {
    const headers = await this.getHeaders()
    await this.fetchWithRetry<SuccessResponse>(
      `${this.baseUrl}/api/notifications/templates/${templateId}`,
      { method: 'DELETE', headers }
    )
  }

  // --------------------------------------------------------------------------
  // Schedule Methods
  // --------------------------------------------------------------------------

  async listSchedules(includeInactive = false): Promise<NotificationSchedule[]> {
    const headers = await this.getHeaders()
    const params = new URLSearchParams()
    if (includeInactive) params.append('include_inactive', 'true')
    const qs = params.toString()
    const url = `${this.baseUrl}/api/notifications/schedules${qs ? '?' + qs : ''}`
    const result = await this.fetchWithRetry<ScheduleListResponse>(url, { method: 'GET', headers })
    return result.schedules
  }

  async getSchedule(scheduleId: number): Promise<NotificationSchedule> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<NotificationSchedule>(
      `${this.baseUrl}/api/notifications/schedules/${scheduleId}`,
      { method: 'GET', headers }
    )
  }

  async createSchedule(data: CreateScheduleRequest): Promise<NotificationSchedule> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<NotificationSchedule>(
      `${this.baseUrl}/api/notifications/schedules`,
      { method: 'POST', headers, body: JSON.stringify(data) }
    )
  }

  async updateSchedule(scheduleId: number, data: UpdateScheduleRequest): Promise<NotificationSchedule> {
    const headers = await this.getHeaders()
    return this.fetchWithRetry<NotificationSchedule>(
      `${this.baseUrl}/api/notifications/schedules/${scheduleId}`,
      { method: 'PUT', headers, body: JSON.stringify(data) }
    )
  }

  async deactivateSchedule(scheduleId: number): Promise<void> {
    const headers = await this.getHeaders()
    await this.fetchWithRetry<SuccessResponse>(
      `${this.baseUrl}/api/notifications/schedules/${scheduleId}`,
      { method: 'DELETE', headers }
    )
  }

  async triggerSchedule(scheduleId: number): Promise<{ emailsSent: number; message: string }> {
    const headers = await this.getHeaders()
    const result = await this.fetchWithRetry<SendEmailAPIResponse>(
      `${this.baseUrl}/api/notifications/schedules/${scheduleId}/trigger`,
      { method: 'POST', headers }
    )
    return { emailsSent: result.emails_sent, message: result.message }
  }

  // --------------------------------------------------------------------------
  // Email Log Methods
  // --------------------------------------------------------------------------

  async listEmailLogs(filters?: EmailLogFilters): Promise<{ logs: EmailLogEntry[]; total: number }> {
    const headers = await this.getHeaders()
    const params = new URLSearchParams()
    if (filters?.invoice_header_id) params.append('invoice_header_id', filters.invoice_header_id.toString())
    if (filters?.schedule_id) params.append('schedule_id', filters.schedule_id.toString())
    if (filters?.email_status) params.append('email_status', filters.email_status)
    if (filters?.limit) params.append('limit', filters.limit.toString())
    if (filters?.offset) params.append('offset', filters.offset.toString())
    const qs = params.toString()
    const url = `${this.baseUrl}/api/notifications/email-log${qs ? '?' + qs : ''}`
    const result = await this.fetchWithRetry<EmailLogListResponse>(url, { method: 'GET', headers })
    return { logs: result.logs, total: result.total }
  }

  // --------------------------------------------------------------------------
  // Submission Methods
  // --------------------------------------------------------------------------

  async listSubmissions(invoiceHeaderId?: number, limit = 50, offset = 0): Promise<{
    submissions: SubmissionResponse[]
    total: number
  }> {
    const headers = await this.getHeaders()
    const params = new URLSearchParams()
    if (invoiceHeaderId) params.append('invoice_header_id', invoiceHeaderId.toString())
    params.append('limit', limit.toString())
    params.append('offset', offset.toString())
    const qs = params.toString()
    const url = `${this.baseUrl}/api/notifications/submissions${qs ? '?' + qs : ''}`
    const result = await this.fetchWithRetry<SubmissionListResponse>(url, { method: 'GET', headers })
    return { submissions: result.submissions, total: result.total }
  }
}
