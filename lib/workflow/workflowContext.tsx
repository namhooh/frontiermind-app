'use client'

/**
 * Workflow Context
 *
 * React context and provider for managing workflow state across the 5-step dashboard.
 */

import React, { createContext, useContext, useReducer, useCallback, useMemo } from 'react'
import type {
  WorkflowState,
  WorkflowAction,
  WorkflowStep,
  ClauseValidation,
  MeterDataStatus,
  MeterDataSummary,
  InvoicePreview,
} from './types'
import { initialWorkflowState } from './types'
import type { ContractParseResult, RuleEvaluationResult, GeneratedReport, FileFormat, InvoiceReportType } from '@/lib/api'

// ============================================================================
// Reducer
// ============================================================================

function workflowReducer(state: WorkflowState, action: WorkflowAction): WorkflowState {
  switch (action.type) {
    case 'SET_STEP':
      return { ...state, currentStep: action.step }

    case 'SET_CONTRACT_FILE':
      return { ...state, contractFile: action.file }

    case 'SET_PARSE_RESULT':
      return { ...state, parseResult: action.result }

    case 'SET_UPLOADING':
      return { ...state, isUploading: action.isUploading }

    case 'SET_UPLOAD_ERROR':
      return { ...state, uploadError: action.error }

    case 'SET_CLAUSE_VALIDATION':
      return { ...state, clauseValidation: action.validation }

    case 'SET_METER_DATA_STATUS':
      return { ...state, meterDataStatus: action.status }

    case 'SET_METER_DATA_SUMMARY':
      return { ...state, meterDataSummary: action.summary }

    case 'SET_METER_DATA_ERROR':
      return { ...state, meterDataError: action.error }

    case 'SET_USE_DUMMY_DATA':
      return { ...state, useDummyData: action.useDummy }

    case 'SET_INVOICE_PREVIEW':
      return { ...state, invoicePreview: action.preview }

    case 'SET_RULE_EVALUATION_RESULT':
      return { ...state, ruleEvaluationResult: action.result }

    case 'SET_GENERATING_INVOICE':
      return { ...state, isGeneratingInvoice: action.isGenerating }

    case 'SET_REPORT_DATA':
      return { ...state, reportData: action.report }

    case 'SET_GENERATING_REPORT':
      return { ...state, isGeneratingReport: action.isGenerating }

    case 'SET_REPORT_ERROR':
      return { ...state, reportError: action.error }

    case 'SET_REPORT_FORMAT':
      return { ...state, selectedReportFormat: action.format }

    case 'SET_REPORT_TYPE':
      return { ...state, selectedReportType: action.reportType }

    case 'RESET_REPORT_STATE':
      return {
        ...state,
        reportData: null,
        isGeneratingReport: false,
        reportError: null,
      }

    case 'RESET_WORKFLOW':
      return initialWorkflowState

    default:
      return state
  }
}

// ============================================================================
// Context Types
// ============================================================================

interface WorkflowContextValue {
  state: WorkflowState

  // Navigation
  setStep: (step: WorkflowStep) => void
  goToNextStep: () => void
  goToPreviousStep: () => void
  canProceedToStep: (step: WorkflowStep) => boolean

  // Step 1: Contract Upload
  setContractFile: (file: File | null) => void
  setParseResult: (result: ContractParseResult | null) => void
  setUploading: (isUploading: boolean) => void
  setUploadError: (error: string | null) => void

  // Step 2: Clause Validation
  setClauseValidation: (validation: ClauseValidation) => void

  // Step 3: Meter Data
  setMeterDataStatus: (status: MeterDataStatus) => void
  setMeterDataSummary: (summary: MeterDataSummary | null) => void
  setMeterDataError: (error: string | null) => void
  setUseDummyData: (useDummy: boolean) => void

  // Step 4: Invoice
  setInvoicePreview: (preview: InvoicePreview | null) => void
  setRuleEvaluationResult: (result: RuleEvaluationResult | null) => void
  setGeneratingInvoice: (isGenerating: boolean) => void

  // Step 5: Report
  setReportData: (report: GeneratedReport | null) => void
  setGeneratingReport: (isGenerating: boolean) => void
  setReportError: (error: string | null) => void
  setReportFormat: (format: FileFormat) => void
  setReportType: (reportType: InvoiceReportType) => void
  resetReportState: () => void

  // Reset
  resetWorkflow: () => void
}

// ============================================================================
// Context
// ============================================================================

const WorkflowContext = createContext<WorkflowContextValue | null>(null)

// ============================================================================
// Provider
// ============================================================================

interface WorkflowProviderProps {
  children: React.ReactNode
}

export function WorkflowProvider({ children }: WorkflowProviderProps) {
  const [state, dispatch] = useReducer(workflowReducer, initialWorkflowState)

  // Navigation
  const setStep = useCallback((step: WorkflowStep) => {
    dispatch({ type: 'SET_STEP', step })
  }, [])

  const goToNextStep = useCallback(() => {
    if (state.currentStep < 5) {
      dispatch({ type: 'SET_STEP', step: (state.currentStep + 1) as WorkflowStep })
    }
  }, [state.currentStep])

  const goToPreviousStep = useCallback(() => {
    if (state.currentStep > 1) {
      dispatch({ type: 'SET_STEP', step: (state.currentStep - 1) as WorkflowStep })
    }
  }, [state.currentStep])

  const canProceedToStep = useCallback(
    (step: WorkflowStep): boolean => {
      switch (step) {
        case 1:
          return true
        case 2:
          // Can only go to step 2 if contract is parsed
          return state.parseResult !== null
        case 3:
          // Can only go to step 3 if clauses are validated and has pricing clause
          return state.parseResult !== null && state.clauseValidation.hasPricingClause
        case 4:
          // Can only go to step 4 if meter data is loaded
          return state.meterDataStatus === 'success' && state.meterDataSummary !== null
        case 5:
          // Can only go to step 5 if invoice preview is generated
          return state.invoicePreview !== null
        default:
          return false
      }
    },
    [state.parseResult, state.clauseValidation, state.meterDataStatus, state.meterDataSummary, state.invoicePreview]
  )

  // Step 1: Contract Upload
  const setContractFile = useCallback((file: File | null) => {
    dispatch({ type: 'SET_CONTRACT_FILE', file })
  }, [])

  const setParseResult = useCallback((result: ContractParseResult | null) => {
    dispatch({ type: 'SET_PARSE_RESULT', result })
  }, [])

  const setUploading = useCallback((isUploading: boolean) => {
    dispatch({ type: 'SET_UPLOADING', isUploading })
  }, [])

  const setUploadError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_UPLOAD_ERROR', error })
  }, [])

  // Step 2: Clause Validation
  const setClauseValidation = useCallback((validation: ClauseValidation) => {
    dispatch({ type: 'SET_CLAUSE_VALIDATION', validation })
  }, [])

  // Step 3: Meter Data
  const setMeterDataStatus = useCallback((status: MeterDataStatus) => {
    dispatch({ type: 'SET_METER_DATA_STATUS', status })
  }, [])

  const setMeterDataSummary = useCallback((summary: MeterDataSummary | null) => {
    dispatch({ type: 'SET_METER_DATA_SUMMARY', summary })
  }, [])

  const setMeterDataError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_METER_DATA_ERROR', error })
  }, [])

  const setUseDummyData = useCallback((useDummy: boolean) => {
    dispatch({ type: 'SET_USE_DUMMY_DATA', useDummy })
  }, [])

  // Step 4: Invoice
  const setInvoicePreview = useCallback((preview: InvoicePreview | null) => {
    dispatch({ type: 'SET_INVOICE_PREVIEW', preview })
  }, [])

  const setRuleEvaluationResult = useCallback((result: RuleEvaluationResult | null) => {
    dispatch({ type: 'SET_RULE_EVALUATION_RESULT', result })
  }, [])

  const setGeneratingInvoice = useCallback((isGenerating: boolean) => {
    dispatch({ type: 'SET_GENERATING_INVOICE', isGenerating })
  }, [])

  // Step 5: Report
  const setReportData = useCallback((report: GeneratedReport | null) => {
    dispatch({ type: 'SET_REPORT_DATA', report })
  }, [])

  const setGeneratingReport = useCallback((isGenerating: boolean) => {
    dispatch({ type: 'SET_GENERATING_REPORT', isGenerating })
  }, [])

  const setReportError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_REPORT_ERROR', error })
  }, [])

  const setReportFormat = useCallback((format: FileFormat) => {
    dispatch({ type: 'SET_REPORT_FORMAT', format })
  }, [])

  const setReportType = useCallback((reportType: InvoiceReportType) => {
    dispatch({ type: 'SET_REPORT_TYPE', reportType })
  }, [])

  const resetReportState = useCallback(() => {
    dispatch({ type: 'RESET_REPORT_STATE' })
  }, [])

  // Reset
  const resetWorkflow = useCallback(() => {
    dispatch({ type: 'RESET_WORKFLOW' })
  }, [])

  const value = useMemo<WorkflowContextValue>(
    () => ({
      state,
      setStep,
      goToNextStep,
      goToPreviousStep,
      canProceedToStep,
      setContractFile,
      setParseResult,
      setUploading,
      setUploadError,
      setClauseValidation,
      setMeterDataStatus,
      setMeterDataSummary,
      setMeterDataError,
      setUseDummyData,
      setInvoicePreview,
      setRuleEvaluationResult,
      setGeneratingInvoice,
      setReportData,
      setGeneratingReport,
      setReportError,
      setReportFormat,
      setReportType,
      resetReportState,
      resetWorkflow,
    }),
    [
      state,
      setStep,
      goToNextStep,
      goToPreviousStep,
      canProceedToStep,
      setContractFile,
      setParseResult,
      setUploading,
      setUploadError,
      setClauseValidation,
      setMeterDataStatus,
      setMeterDataSummary,
      setMeterDataError,
      setUseDummyData,
      setInvoicePreview,
      setRuleEvaluationResult,
      setGeneratingInvoice,
      setReportData,
      setGeneratingReport,
      setReportError,
      setReportFormat,
      setReportType,
      resetReportState,
      resetWorkflow,
    ]
  )

  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>
}

// ============================================================================
// Hook
// ============================================================================

export function useWorkflow(): WorkflowContextValue {
  const context = useContext(WorkflowContext)
  if (!context) {
    throw new Error('useWorkflow must be used within a WorkflowProvider')
  }
  return context
}
