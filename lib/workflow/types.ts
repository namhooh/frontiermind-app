/**
 * Workflow Types
 *
 * TypeScript types for the 5-step workflow testing dashboard.
 */

import type { ContractParseResult, ExtractedClause, RuleEvaluationResult, GeneratedReport, FileFormat, InvoiceReportType } from '@/lib/api'

// ============================================================================
// Workflow State
// ============================================================================

export type WorkflowStep = 1 | 2 | 3 | 4 | 5

export type MeterDataStatus = 'pending' | 'uploading' | 'success' | 'error'

export interface MeterDataSummary {
  fileName: string
  totalRecords: number
  dateRange: {
    start: string
    end: string
  }
  totalEnergyMWh: number
  averageDailyMWh: number
  peakDayMWh: number
  availabilityPercentage: number
}

export interface InvoiceLineItem {
  description: string
  quantity: number
  unit: string
  rate: number
  amount: number
}

export interface InvoicePreview {
  invoiceNumber: string
  invoiceDate: string
  billingPeriod: {
    start: string
    end: string
  }
  seller: {
    name: string
    address?: string
  }
  buyer: {
    name: string
    address?: string
  }
  lineItems: InvoiceLineItem[]
  subtotal: number
  ldAdjustments: {
    description: string
    amount: number
    ruleType?: string
  }[]
  ldTotal: number
  totalAmount: number
  notes?: string[]
}

export interface ClauseValidation {
  hasPricingClause: boolean
  hasAvailabilityClause: boolean
  hasTerminationClause: boolean
  hasForceClause: boolean
}

export interface WorkflowState {
  // Current step
  currentStep: WorkflowStep

  // Step 1: Project/Organization Selection
  projectId: number | null
  organizationId: number | null

  // Step 1: Contract Upload
  contractFile: File | null
  parseResult: ContractParseResult | null
  isUploading: boolean
  uploadError: string | null

  // Step 2: Clause Review
  clauseValidation: ClauseValidation

  // Step 3: Meter Data Ingestion
  meterDataStatus: MeterDataStatus
  meterDataSummary: MeterDataSummary | null
  meterDataError: string | null
  useDummyData: boolean

  // Step 4: Invoice Generation
  invoicePreview: InvoicePreview | null
  ruleEvaluationResult: RuleEvaluationResult | null
  isGeneratingInvoice: boolean
  savedInvoiceId: number | null
  isSavingInvoice: boolean

  // Step 5: Report Generation
  reportData: GeneratedReport | null
  isGeneratingReport: boolean
  reportError: string | null
  selectedReportFormat: FileFormat
  selectedReportType: InvoiceReportType
}

// ============================================================================
// Workflow Actions
// ============================================================================

export type WorkflowAction =
  | { type: 'SET_STEP'; step: WorkflowStep }
  | { type: 'SET_PROJECT_ID'; projectId: number | null }
  | { type: 'SET_ORGANIZATION_ID'; organizationId: number | null }
  | { type: 'SET_CONTRACT_FILE'; file: File | null }
  | { type: 'SET_PARSE_RESULT'; result: ContractParseResult | null }
  | { type: 'SET_UPLOADING'; isUploading: boolean }
  | { type: 'SET_UPLOAD_ERROR'; error: string | null }
  | { type: 'SET_CLAUSE_VALIDATION'; validation: ClauseValidation }
  | { type: 'SET_METER_DATA_STATUS'; status: MeterDataStatus }
  | { type: 'SET_METER_DATA_SUMMARY'; summary: MeterDataSummary | null }
  | { type: 'SET_METER_DATA_ERROR'; error: string | null }
  | { type: 'SET_USE_DUMMY_DATA'; useDummy: boolean }
  | { type: 'SET_INVOICE_PREVIEW'; preview: InvoicePreview | null }
  | { type: 'SET_RULE_EVALUATION_RESULT'; result: RuleEvaluationResult | null }
  | { type: 'SET_GENERATING_INVOICE'; isGenerating: boolean }
  | { type: 'SET_SAVED_INVOICE_ID'; invoiceId: number | null }
  | { type: 'SET_SAVING_INVOICE'; isSaving: boolean }
  | { type: 'SET_REPORT_DATA'; report: GeneratedReport | null }
  | { type: 'SET_GENERATING_REPORT'; isGenerating: boolean }
  | { type: 'SET_REPORT_ERROR'; error: string | null }
  | { type: 'SET_REPORT_FORMAT'; format: FileFormat }
  | { type: 'SET_REPORT_TYPE'; reportType: InvoiceReportType }
  | { type: 'RESET_REPORT_STATE' }
  | { type: 'RESET_WORKFLOW' }

// ============================================================================
// Initial State
// ============================================================================

export const initialWorkflowState: WorkflowState = {
  currentStep: 1,

  // Step 1: Project/Organization
  projectId: null,
  organizationId: null,

  // Step 1: Contract Upload
  contractFile: null,
  parseResult: null,
  isUploading: false,
  uploadError: null,

  // Step 2
  clauseValidation: {
    hasPricingClause: false,
    hasAvailabilityClause: false,
    hasTerminationClause: false,
    hasForceClause: false,
  },

  // Step 3
  meterDataStatus: 'pending',
  meterDataSummary: null,
  meterDataError: null,
  useDummyData: false,

  // Step 4
  invoicePreview: null,
  ruleEvaluationResult: null,
  isGeneratingInvoice: false,
  savedInvoiceId: null,
  isSavingInvoice: false,

  // Step 5
  reportData: null,
  isGeneratingReport: false,
  reportError: null,
  selectedReportFormat: 'pdf',
  selectedReportType: 'invoice_to_client',
}

// ============================================================================
// Validation Banner Types
// ============================================================================

export interface ValidationItem {
  label: string
  found: boolean
  required?: boolean
}
