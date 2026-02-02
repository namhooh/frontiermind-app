'use client'

/**
 * PII Redaction Temp - React Context
 */

import React, { createContext, useContext, useReducer, useCallback, useMemo } from 'react'
import type {
  PIIRedactionState,
  PIIRedactionAction,
  PIIRedactionStep,
  PIIRedactionResult,
  ProcessingStage,
} from './types'
import { initialPIIRedactionState } from './types'

function piiRedactionReducer(
  state: PIIRedactionState,
  action: PIIRedactionAction
): PIIRedactionState {
  switch (action.type) {
    case 'SET_STEP':
      return { ...state, currentStep: action.step }
    case 'SET_FILE':
      return { ...state, file: action.file, fileName: action.file.name, uploadError: null }
    case 'CLEAR_FILE':
      return { ...state, file: null, fileName: null }
    case 'SET_UPLOAD_ERROR':
      return { ...state, uploadError: action.error }
    case 'CLEAR_UPLOAD_ERROR':
      return { ...state, uploadError: null }
    case 'SET_PROCESSING':
      return { ...state, isProcessing: action.isProcessing }
    case 'SET_PROCESSING_STAGE':
      return { ...state, processingStage: action.stage }
    case 'SET_PROCESSING_ERROR':
      return { ...state, processingError: action.error, isProcessing: false, processingStage: 'error' }
    case 'SET_RESULT':
      return {
        ...state,
        result: action.result,
        isProcessing: false,
        processingStage: 'complete',
        currentStep: 3,
      }
    case 'RESET':
      return initialPIIRedactionState
    default:
      return state
  }
}

interface PIIRedactionContextValue {
  state: PIIRedactionState
  setStep: (step: PIIRedactionStep) => void
  setFile: (file: File) => void
  clearFile: () => void
  setUploadError: (error: string) => void
  clearUploadError: () => void
  setProcessing: (isProcessing: boolean) => void
  setProcessingStage: (stage: ProcessingStage) => void
  setProcessingError: (error: string) => void
  setResult: (result: PIIRedactionResult) => void
  reset: () => void
}

const PIIRedactionContext = createContext<PIIRedactionContextValue | null>(null)

export function PIIRedactionProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(piiRedactionReducer, initialPIIRedactionState)

  const setStep = useCallback((step: PIIRedactionStep) => {
    dispatch({ type: 'SET_STEP', step })
  }, [])

  const setFile = useCallback((file: File) => {
    dispatch({ type: 'SET_FILE', file })
  }, [])

  const clearFile = useCallback(() => {
    dispatch({ type: 'CLEAR_FILE' })
  }, [])

  const setUploadError = useCallback((error: string) => {
    dispatch({ type: 'SET_UPLOAD_ERROR', error })
  }, [])

  const clearUploadError = useCallback(() => {
    dispatch({ type: 'CLEAR_UPLOAD_ERROR' })
  }, [])

  const setProcessing = useCallback((isProcessing: boolean) => {
    dispatch({ type: 'SET_PROCESSING', isProcessing })
  }, [])

  const setProcessingStage = useCallback((stage: ProcessingStage) => {
    dispatch({ type: 'SET_PROCESSING_STAGE', stage })
  }, [])

  const setProcessingError = useCallback((error: string) => {
    dispatch({ type: 'SET_PROCESSING_ERROR', error })
  }, [])

  const setResult = useCallback((result: PIIRedactionResult) => {
    dispatch({ type: 'SET_RESULT', result })
  }, [])

  const reset = useCallback(() => {
    dispatch({ type: 'RESET' })
  }, [])

  const value = useMemo(
    () => ({
      state,
      setStep,
      setFile,
      clearFile,
      setUploadError,
      clearUploadError,
      setProcessing,
      setProcessingStage,
      setProcessingError,
      setResult,
      reset,
    }),
    [state, setStep, setFile, clearFile, setUploadError, clearUploadError, setProcessing, setProcessingStage, setProcessingError, setResult, reset]
  )

  return (
    <PIIRedactionContext.Provider value={value}>
      {children}
    </PIIRedactionContext.Provider>
  )
}

export function usePIIRedaction(): PIIRedactionContextValue {
  const context = useContext(PIIRedactionContext)
  if (!context) {
    throw new Error('usePIIRedaction must be used within a PIIRedactionProvider')
  }
  return context
}
