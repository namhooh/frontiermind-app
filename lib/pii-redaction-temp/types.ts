/**
 * PII Redaction Temp - TypeScript Types
 */

export type PIIRedactionStep = 1 | 2 | 3

export type ProcessingStage =
  | 'idle'
  | 'uploading'
  | 'parsing'
  | 'detecting'
  | 'anonymizing'
  | 'complete'
  | 'error'

export interface PIIEntityDetail {
  entityType: string
  originalValue: string
  positionStart: number
  positionEnd: number
  confidence: number
}

export interface PIISummary {
  totalEntities: number
  entitiesByType: Record<string, number>
  entityDetails: PIIEntityDetail[]
}

export interface PIIRedactionResult {
  redactedText: string
  originalTextLength: number
  piiSummary: PIISummary
  processingTime: number
}

export interface PIIRedactionState {
  currentStep: PIIRedactionStep
  file: File | null
  fileName: string | null
  uploadError: string | null
  isProcessing: boolean
  processingStage: ProcessingStage
  processingError: string | null
  result: PIIRedactionResult | null
}

export const initialPIIRedactionState: PIIRedactionState = {
  currentStep: 1,
  file: null,
  fileName: null,
  uploadError: null,
  isProcessing: false,
  processingStage: 'idle',
  processingError: null,
  result: null,
}

export type PIIRedactionAction =
  | { type: 'SET_STEP'; step: PIIRedactionStep }
  | { type: 'SET_FILE'; file: File }
  | { type: 'CLEAR_FILE' }
  | { type: 'SET_UPLOAD_ERROR'; error: string }
  | { type: 'CLEAR_UPLOAD_ERROR' }
  | { type: 'SET_PROCESSING'; isProcessing: boolean }
  | { type: 'SET_PROCESSING_STAGE'; stage: ProcessingStage }
  | { type: 'SET_PROCESSING_ERROR'; error: string }
  | { type: 'SET_RESULT'; result: PIIRedactionResult }
  | { type: 'RESET' }
