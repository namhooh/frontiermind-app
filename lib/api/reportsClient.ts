/**
 * Reports API Client
 *
 * API client for report generation and management.
 * Supports templates, on-demand generation, scheduled reports, and downloads.
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

const API_BASE_URL =
  process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || 'http://localhost:8000'

const DEFAULT_RETRY_COUNT = 3
const DEFAULT_RETRY_DELAY_MS = 1000

// ============================================================================
// TypeScript Enums
// ============================================================================

/** Report types for invoice-related reports */
export type InvoiceReportType =
  | 'invoice_to_client'
  | 'invoice_expected'
  | 'invoice_received'
  | 'invoice_comparison'

/** Supported output file formats */
export type FileFormat = 'csv' | 'xlsx' | 'json' | 'pdf'

/** Report generation lifecycle status */
export type ReportStatus = 'pending' | 'processing' | 'completed' | 'failed'

/** Frequency options for scheduled reports (from shared types) */
import type { ReportFrequency as _ReportFrequency } from './types'
export type ReportFrequency = _ReportFrequency

/** Identifies how a report was triggered */
export type GenerationSource = 'on_demand' | 'scheduled'

/** Delivery options for scheduled reports */
export type DeliveryMethod = 'email' | 's3' | 'both'

// ============================================================================
// TypeScript Interfaces - Entities
// ============================================================================

/** Report template configuration */
export interface ReportTemplate {
  id: number
  organization_id: number
  project_id?: number
  name: string
  description?: string
  report_type: InvoiceReportType
  file_format: FileFormat
  template_config: Record<string, unknown>
  include_charts: boolean
  include_summary: boolean
  include_line_items: boolean
  default_contract_id?: number
  logo_path?: string
  header_text?: string
  footer_text?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

/** Generated report metadata */
export interface GeneratedReport {
  id: number
  organization_id: number
  report_template_id?: number
  scheduled_report_id?: number
  generation_source: GenerationSource
  report_type: InvoiceReportType
  name: string
  report_status: ReportStatus
  project_id?: number
  contract_id?: number
  billing_period_id?: number
  file_format: FileFormat
  file_path?: string
  file_size_bytes?: number
  download_url?: string
  record_count?: number
  summary_data?: Record<string, unknown>
  download_count: number
  processing_time_ms?: number
  processing_error?: string
  invoice_direction?: string
  created_at: string
  expires_at?: string
}

/** Scheduled report configuration */
export interface ScheduledReport {
  id: number
  organization_id: number
  report_template_id: number
  name: string
  report_frequency: ReportFrequency
  day_of_month?: number
  time_of_day: string
  timezone: string
  project_id?: number
  contract_id?: number
  billing_period_id?: number
  recipients: RecipientInfo[]
  delivery_method: DeliveryMethod
  s3_destination?: string
  is_active: boolean
  next_run_at?: string
  last_run_at?: string
  last_run_status?: ReportStatus
  last_run_error?: string
  created_at: string
  updated_at: string
}

/** Email recipient information */
export interface RecipientInfo {
  email: string
  name?: string
}

/** Format availability info */
export interface FormatInfo {
  format: FileFormat
  available: boolean
}

/** Report type info */
export interface ReportTypeInfo {
  type: InvoiceReportType
  name: string
}

// ============================================================================
// TypeScript Interfaces - Requests
// ============================================================================

/** Request to generate a report */
export interface GenerateReportRequest {
  template_id?: number
  billing_period_id: number
  contract_id?: number
  project_id?: number
  file_format?: FileFormat
  report_type?: InvoiceReportType
  name?: string
}

/** Request to create a report template */
export interface CreateTemplateRequest {
  name: string
  description?: string
  report_type: InvoiceReportType
  file_format?: FileFormat
  template_config?: Record<string, unknown>
  include_charts?: boolean
  include_summary?: boolean
  include_line_items?: boolean
  project_id?: number
  default_contract_id?: number
  logo_path?: string
  header_text?: string
  footer_text?: string
}

/** Request to update a report template */
export interface UpdateTemplateRequest {
  name?: string
  description?: string
  file_format?: FileFormat
  template_config?: Record<string, unknown>
  include_charts?: boolean
  include_summary?: boolean
  include_line_items?: boolean
  default_contract_id?: number
  logo_path?: string
  header_text?: string
  footer_text?: string
  is_active?: boolean
}

/** Request to create a scheduled report */
export interface CreateScheduleRequest {
  name: string
  report_template_id: number
  report_frequency: ReportFrequency
  day_of_month?: number
  time_of_day?: string
  timezone?: string
  project_id?: number
  contract_id?: number
  billing_period_id?: number
  recipients?: RecipientInfo[]
  delivery_method?: DeliveryMethod
  s3_destination?: string
}

/** Request to update a scheduled report */
export interface UpdateScheduleRequest {
  name?: string
  report_frequency?: ReportFrequency
  day_of_month?: number
  time_of_day?: string
  timezone?: string
  project_id?: number
  contract_id?: number
  billing_period_id?: number
  recipients?: RecipientInfo[]
  delivery_method?: DeliveryMethod
  s3_destination?: string
  is_active?: boolean
}

/** Filters for querying generated reports */
export interface ReportFilters {
  template_id?: number
  report_type?: InvoiceReportType
  status?: ReportStatus
  billing_period_id?: number
  limit?: number
  offset?: number
}

// ============================================================================
// TypeScript Interfaces - Responses
// ============================================================================

/** Response for listing templates */
interface TemplateListResponse {
  success: boolean
  templates: ReportTemplate[]
  total: number
}

/** Response for listing generated reports */
interface GeneratedReportListResponse {
  success: boolean
  reports: GeneratedReport[]
  total: number
}

/** Response for listing scheduled reports */
interface ScheduledReportListResponse {
  success: boolean
  schedules: ScheduledReport[]
  total: number
}

/** Response for report generation request */
interface GenerateReportAPIResponse {
  success: boolean
  report_id: number
  status: ReportStatus
  message: string
}

/** Response with presigned download URL */
interface DownloadUrlResponse {
  success: boolean
  download_url: string
  filename: string
  expires_in_seconds: number
}

/** Response for formats endpoint */
interface FormatsResponse {
  success: boolean
  formats: FormatInfo[]
}

/** Response for types endpoint */
interface TypesResponse {
  success: boolean
  types: ReportTypeInfo[]
}

/** Generic success response */
interface SuccessResponse {
  success: boolean
  message: string
}

// ============================================================================
// Client Configuration
// ============================================================================

/** Reports API client configuration options */
export interface ReportsClientConfig {
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

/** Custom error class for Reports API errors */
export class ReportsAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string,
    public details?: string
  ) {
    super(message)
    this.name = 'ReportsAPIError'
  }
}

/** Check if an error is a network/transient error that should be retried */
function isRetryableError(error: unknown): boolean {
  if (error instanceof ReportsAPIError) {
    return error.statusCode >= 500 && error.statusCode < 600
  }
  return error instanceof TypeError
}

// ============================================================================
// Utility Functions
// ============================================================================

/** Sleep for a specified number of milliseconds */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ============================================================================
// Reports API Client Class
// ============================================================================

/**
 * Reports API Client
 *
 * Provides methods for:
 * - Report template management
 * - On-demand report generation
 * - Scheduled report management
 * - Report downloads
 *
 * @example
 * ```typescript
 * const client = new ReportsClient({
 *   getAuthToken: async () => session?.access_token
 * })
 *
 * // List templates
 * const templates = await client.listTemplates()
 *
 * // Generate a report
 * const result = await client.generateReport({
 *   billing_period_id: 12,
 *   report_type: 'invoice_to_client',
 *   file_format: 'pdf'
 * })
 *
 * // Poll for completion and download
 * const report = await client.getReport(result.reportId)
 * if (report.report_status === 'completed') {
 *   const downloadUrl = await client.getDownloadUrl(report.id)
 * }
 * ```
 */
export class ReportsClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>
  private organizationId?: number

  constructor(config: ReportsClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.retryCount = config.retryCount ?? DEFAULT_RETRY_COUNT
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
    this.getAuthToken = config.getAuthToken
    this.organizationId = config.organizationId
  }

  // --------------------------------------------------------------------------
  // Private Methods
  // --------------------------------------------------------------------------

  /** Log request/response information */
  private log(level: 'info' | 'warn' | 'error', message: string, data?: unknown): void {
    if (!this.enableLogging) return

    const timestamp = new Date().toISOString()
    const prefix = `[ReportsClient ${timestamp}]`

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

  /** Get authorization and organization headers */
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

    if (this.organizationId) {
      headers['X-Organization-ID'] = this.organizationId.toString()
    }

    return headers
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
          await sleep(this.retryDelayMs * attempt)
        }

        this.log('info', `Request: ${options.method || 'GET'} ${url}`)

        const response = await fetch(url, options)
        const responseData = await response.json()

        if (!response.ok) {
          const error = new ReportsAPIError(
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
  // Template Methods
  // --------------------------------------------------------------------------

  /**
   * List all report templates.
   *
   * @param projectId - Optional project ID filter
   * @param includeInactive - Include inactive templates
   * @returns List of report templates
   */
  async listTemplates(projectId?: number, includeInactive = false): Promise<ReportTemplate[]> {
    const headers = await this.getHeaders()

    const params = new URLSearchParams()
    if (projectId) params.append('project_id', projectId.toString())
    if (includeInactive) params.append('include_inactive', 'true')

    const queryString = params.toString()
    const url = `${this.baseUrl}/api/reports/templates${queryString ? '?' + queryString : ''}`

    const result = await this.fetchWithRetry<TemplateListResponse>(url, {
      method: 'GET',
      headers,
    })

    return result.templates
  }

  /**
   * Get a report template by ID.
   *
   * @param templateId - Template ID
   * @returns Report template
   */
  async getTemplate(templateId: number): Promise<ReportTemplate> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/templates/${templateId}`

    return this.fetchWithRetry<ReportTemplate>(url, {
      method: 'GET',
      headers,
    })
  }

  /**
   * Create a new report template.
   *
   * @param data - Template creation data
   * @returns Created template
   */
  async createTemplate(data: CreateTemplateRequest): Promise<ReportTemplate> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/templates`

    return this.fetchWithRetry<ReportTemplate>(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(data),
    })
  }

  /**
   * Update a report template.
   *
   * @param templateId - Template ID
   * @param data - Template update data
   * @returns Updated template
   */
  async updateTemplate(templateId: number, data: UpdateTemplateRequest): Promise<ReportTemplate> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/templates/${templateId}`

    return this.fetchWithRetry<ReportTemplate>(url, {
      method: 'PUT',
      headers,
      body: JSON.stringify(data),
    })
  }

  /**
   * Deactivate a report template (soft delete).
   *
   * @param templateId - Template ID
   */
  async deactivateTemplate(templateId: number): Promise<void> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/templates/${templateId}`

    await this.fetchWithRetry<SuccessResponse>(url, {
      method: 'DELETE',
      headers,
    })
  }

  // --------------------------------------------------------------------------
  // Report Generation Methods
  // --------------------------------------------------------------------------

  /**
   * Generate a report (async).
   *
   * The report is generated asynchronously. Use getReport() to poll for status.
   *
   * @param request - Report generation request
   * @returns Report ID and initial status
   *
   * @example
   * ```typescript
   * const result = await client.generateReport({
   *   billing_period_id: 12,
   *   report_type: 'invoice_to_client',
   *   file_format: 'pdf',
   *   name: 'January 2024 Invoice Report'
   * })
   * console.log(`Report ${result.reportId} is ${result.status}`)
   * ```
   */
  async generateReport(
    request: GenerateReportRequest
  ): Promise<{ reportId: number; status: ReportStatus; message: string }> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/generate`

    this.log('info', 'Generating report', request)

    const result = await this.fetchWithRetry<GenerateReportAPIResponse>(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
    })

    return {
      reportId: result.report_id,
      status: result.status,
      message: result.message,
    }
  }

  /**
   * List generated reports with optional filters.
   *
   * @param filters - Optional filters
   * @returns List of generated reports
   */
  async listReports(filters?: ReportFilters): Promise<GeneratedReport[]> {
    const headers = await this.getHeaders()

    const params = new URLSearchParams()
    if (filters?.template_id) params.append('template_id', filters.template_id.toString())
    if (filters?.report_type) params.append('report_type', filters.report_type)
    if (filters?.status) params.append('status', filters.status)
    if (filters?.billing_period_id)
      params.append('billing_period_id', filters.billing_period_id.toString())
    if (filters?.limit) params.append('limit', filters.limit.toString())
    if (filters?.offset) params.append('offset', filters.offset.toString())

    const queryString = params.toString()
    const url = `${this.baseUrl}/api/reports/generated${queryString ? '?' + queryString : ''}`

    const result = await this.fetchWithRetry<GeneratedReportListResponse>(url, {
      method: 'GET',
      headers,
    })

    return result.reports
  }

  /**
   * Get a generated report by ID.
   *
   * @param reportId - Report ID
   * @returns Generated report details
   */
  async getReport(reportId: number): Promise<GeneratedReport> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/generated/${reportId}`

    return this.fetchWithRetry<GeneratedReport>(url, {
      method: 'GET',
      headers,
    })
  }

  /**
   * Get a presigned download URL for a completed report.
   *
   * @param reportId - Report ID
   * @param expiry - URL expiry in seconds (default 300)
   * @returns Download URL and metadata
   */
  async getDownloadUrl(
    reportId: number,
    expiry = 300
  ): Promise<{ url: string; filename: string; expiresIn: number }> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/generated/${reportId}/download?expiry=${expiry}`

    const result = await this.fetchWithRetry<DownloadUrlResponse>(url, {
      method: 'GET',
      headers,
    })

    return {
      url: result.download_url,
      filename: result.filename,
      expiresIn: result.expires_in_seconds,
    }
  }

  /**
   * Poll for report completion.
   *
   * @param reportId - Report ID
   * @param maxWaitMs - Maximum wait time in milliseconds (default 60000)
   * @param pollIntervalMs - Polling interval in milliseconds (default 2000)
   * @returns Completed report
   * @throws ReportsAPIError if report fails or times out
   *
   * @example
   * ```typescript
   * const { reportId } = await client.generateReport({ ... })
   * const report = await client.waitForCompletion(reportId)
   * const { url } = await client.getDownloadUrl(reportId)
   * ```
   */
  async waitForCompletion(
    reportId: number,
    maxWaitMs = 60000,
    pollIntervalMs = 2000
  ): Promise<GeneratedReport> {
    const startTime = Date.now()

    while (Date.now() - startTime < maxWaitMs) {
      const report = await this.getReport(reportId)

      if (report.report_status === 'completed') {
        return report
      }

      if (report.report_status === 'failed') {
        throw new ReportsAPIError(
          report.processing_error || 'Report generation failed',
          500,
          'ReportGenerationFailed'
        )
      }

      await sleep(pollIntervalMs)
    }

    throw new ReportsAPIError(
      'Report generation timed out',
      408,
      'ReportGenerationTimeout'
    )
  }

  // --------------------------------------------------------------------------
  // Scheduled Report Methods
  // --------------------------------------------------------------------------

  /**
   * List scheduled reports.
   *
   * @param includeInactive - Include inactive schedules
   * @returns List of scheduled reports
   */
  async listSchedules(includeInactive = false): Promise<ScheduledReport[]> {
    const headers = await this.getHeaders()

    const params = new URLSearchParams()
    if (includeInactive) params.append('include_inactive', 'true')

    const queryString = params.toString()
    const url = `${this.baseUrl}/api/reports/scheduled${queryString ? '?' + queryString : ''}`

    const result = await this.fetchWithRetry<ScheduledReportListResponse>(url, {
      method: 'GET',
      headers,
    })

    return result.schedules
  }

  /**
   * Get a scheduled report by ID.
   *
   * @param scheduleId - Schedule ID
   * @returns Scheduled report
   */
  async getSchedule(scheduleId: number): Promise<ScheduledReport> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/scheduled/${scheduleId}`

    return this.fetchWithRetry<ScheduledReport>(url, {
      method: 'GET',
      headers,
    })
  }

  /**
   * Create a new scheduled report.
   *
   * @param data - Schedule creation data
   * @returns Created schedule
   */
  async createSchedule(data: CreateScheduleRequest): Promise<ScheduledReport> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/scheduled`

    return this.fetchWithRetry<ScheduledReport>(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(data),
    })
  }

  /**
   * Update a scheduled report.
   *
   * @param scheduleId - Schedule ID
   * @param data - Schedule update data
   * @returns Updated schedule
   */
  async updateSchedule(scheduleId: number, data: UpdateScheduleRequest): Promise<ScheduledReport> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/scheduled/${scheduleId}`

    return this.fetchWithRetry<ScheduledReport>(url, {
      method: 'PUT',
      headers,
      body: JSON.stringify(data),
    })
  }

  /**
   * Deactivate a scheduled report (soft delete).
   *
   * @param scheduleId - Schedule ID
   */
  async deactivateSchedule(scheduleId: number): Promise<void> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/scheduled/${scheduleId}`

    await this.fetchWithRetry<SuccessResponse>(url, {
      method: 'DELETE',
      headers,
    })
  }

  // --------------------------------------------------------------------------
  // Utility Methods
  // --------------------------------------------------------------------------

  /**
   * List available output formats.
   *
   * @returns List of formats with availability info
   */
  async listFormats(): Promise<FormatInfo[]> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/formats`

    const result = await this.fetchWithRetry<FormatsResponse>(url, {
      method: 'GET',
      headers,
    })

    return result.formats
  }

  /**
   * List available report types.
   *
   * @returns List of report types
   */
  async listReportTypes(): Promise<ReportTypeInfo[]> {
    const headers = await this.getHeaders()
    const url = `${this.baseUrl}/api/reports/types`

    const result = await this.fetchWithRetry<TypesResponse>(url, {
      method: 'GET',
      headers,
    })

    return result.types
  }
}

// ============================================================================
// Default Instance (for convenience)
// ============================================================================

const defaultClient = new ReportsClient()

/**
 * List report templates (convenience function).
 * @deprecated Use `new ReportsClient().listTemplates()` for better control
 */
export async function listTemplates(): Promise<ReportTemplate[]> {
  return defaultClient.listTemplates()
}

/**
 * Generate a report (convenience function).
 * @deprecated Use `new ReportsClient().generateReport()` for better control
 */
export async function generateReport(
  request: GenerateReportRequest
): Promise<{ reportId: number; status: ReportStatus; message: string }> {
  return defaultClient.generateReport(request)
}

/**
 * Get a report by ID (convenience function).
 * @deprecated Use `new ReportsClient().getReport()` for better control
 */
export async function getReport(reportId: number): Promise<GeneratedReport> {
  return defaultClient.getReport(reportId)
}

/**
 * List generated reports (convenience function).
 * @deprecated Use `new ReportsClient().listReports()` for better control
 */
export async function listReports(filters?: ReportFilters): Promise<GeneratedReport[]> {
  return defaultClient.listReports(filters)
}
