/**
 * API Client for PII Redaction Temp endpoint.
 */

import type { PIIRedactionResult, ProcessingStage } from '@/lib/pii-redaction-temp'

const API_BASE_URL =
  process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || 'http://localhost:8000'

export interface PIIRedactionTempClientConfig {
  baseUrl?: string
  organizationId: number
}

export class PIIRedactionAPIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public details?: string
  ) {
    super(message)
    this.name = 'PIIRedactionAPIError'
  }
}

export class PIIRedactionTempClient {
  private baseUrl: string
  private organizationId: number

  constructor(config: PIIRedactionTempClientConfig) {
    this.baseUrl = config.baseUrl || API_BASE_URL
    this.organizationId = config.organizationId
  }

  async redactDocument(options: {
    file: File
    onProgress?: (stage: ProcessingStage) => void
  }): Promise<PIIRedactionResult> {
    const { file, onProgress } = options

    onProgress?.('uploading')

    const formData = new FormData()
    formData.append('file', file)

    onProgress?.('parsing')

    const response = await fetch(`${this.baseUrl}/api/pii-redaction-temp/process`, {
      method: 'POST',
      headers: {
        'X-Organization-ID': this.organizationId.toString(),
      },
      body: formData,
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Request failed' }))
      throw new PIIRedactionAPIError(
        typeof errorData.detail === 'string' ? errorData.detail : 'Processing failed',
        response.status,
        JSON.stringify(errorData)
      )
    }

    onProgress?.('detecting')

    const data = await response.json()

    onProgress?.('anonymizing')

    // Map snake_case response to camelCase
    const result: PIIRedactionResult = {
      redactedText: data.redacted_text,
      originalTextLength: data.original_text_length,
      piiSummary: {
        totalEntities: data.pii_summary.total_entities,
        entitiesByType: data.pii_summary.entities_by_type,
        entityDetails: (data.pii_summary.entity_details || []).map(
          (d: { entity_type: string; original_value: string; position_start: number; position_end: number; confidence: number }) => ({
            entityType: d.entity_type,
            originalValue: d.original_value,
            positionStart: d.position_start,
            positionEnd: d.position_end,
            confidence: d.confidence,
          })
        ),
      },
      processingTime: data.processing_time,
    }

    onProgress?.('complete')

    return result
  }
}
