/**
 * Ingest API Client
 *
 * Client for meter data ingestion API endpoints.
 * Supports presigned URL uploads and status checking.
 */

import { getApiBaseUrl } from './config'

const API_BASE_URL = getApiBaseUrl()

// ============================================================================
// Types
// ============================================================================

export interface PresignedUrlRequest {
  filename: string
  content_type: string
  project_id?: number
  metadata?: Record<string, string>
}

export interface PresignedUrlResponse {
  file_id: string
  upload_url: string
  expires_at: string
  bucket: string
  key: string
}

export interface IngestionStatusResponse {
  file_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  filename: string
  records_processed?: number
  records_total?: number
  error_message?: string
  started_at?: string
  completed_at?: string
}

export interface IngestClientConfig {
  baseUrl?: string
  enableLogging?: boolean
}

// ============================================================================
// Error Class
// ============================================================================

export class IngestAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorType?: string
  ) {
    super(message)
    this.name = 'IngestAPIError'
  }
}

// ============================================================================
// Client Class
// ============================================================================

export class IngestClient {
  private baseUrl: string
  private enableLogging: boolean

  constructor(config: IngestClientConfig = {}) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
  }

  private log(message: string, data?: unknown): void {
    if (!this.enableLogging) return
    console.log(`[IngestClient] ${message}`, data ?? '')
  }

  /**
   * Get a presigned URL for uploading meter data to S3.
   */
  async getPresignedUrl(request: PresignedUrlRequest): Promise<PresignedUrlResponse> {
    const url = `${this.baseUrl}/api/ingest/presigned-url`

    this.log('Requesting presigned URL', request)

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Request failed' }))
      throw new IngestAPIError(
        error.message || 'Failed to get presigned URL',
        response.status,
        error.error
      )
    }

    const data = await response.json()
    this.log('Got presigned URL', { file_id: data.file_id })
    return data
  }

  /**
   * Upload a file directly to S3 using a presigned URL.
   */
  async uploadToS3(url: string, file: File | Blob): Promise<void> {
    this.log('Uploading to S3', { size: file.size })

    const response = await fetch(url, {
      method: 'PUT',
      body: file,
      headers: {
        'Content-Type': file.type || 'text/csv',
      },
    })

    if (!response.ok) {
      throw new IngestAPIError(
        'Failed to upload file to S3',
        response.status
      )
    }

    this.log('Upload complete')
  }

  /**
   * Check the ingestion status for a file.
   */
  async checkStatus(fileId: string): Promise<IngestionStatusResponse> {
    const url = `${this.baseUrl}/api/ingest/status/${fileId}`

    this.log('Checking status', { fileId })

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Request failed' }))
      throw new IngestAPIError(
        error.message || 'Failed to check status',
        response.status,
        error.error
      )
    }

    const data = await response.json()
    this.log('Status response', data)
    return data
  }

  /**
   * Poll for ingestion completion.
   * Returns when status is 'completed' or 'failed'.
   */
  async waitForCompletion(
    fileId: string,
    options: { intervalMs?: number; timeoutMs?: number } = {}
  ): Promise<IngestionStatusResponse> {
    const { intervalMs = 2000, timeoutMs = 120000 } = options
    const startTime = Date.now()

    while (Date.now() - startTime < timeoutMs) {
      const status = await this.checkStatus(fileId)

      if (status.status === 'completed' || status.status === 'failed') {
        return status
      }

      await new Promise((resolve) => setTimeout(resolve, intervalMs))
    }

    throw new IngestAPIError('Ingestion timed out', 408, 'TIMEOUT')
  }
}
