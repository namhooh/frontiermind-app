'use client'

import { useState, useCallback, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import StatCard from './StatCard'
import ClausesList from './ClausesList'
import {
  APIClient,
  ContractsAPIError,
  type ContractParseResult,
  type UploadProgress,
} from '@/lib/api'

type ProcessingStage =
  | 'idle'
  | 'uploading'
  | 'detecting-pii'
  | 'parsing'
  | 'extracting'
  | 'storing'
  | 'complete'
  | 'error'

// Map API progress stages to UI stages
const progressStageMap: Record<UploadProgress['stage'], ProcessingStage> = {
  uploading: 'uploading',
  parsing: 'parsing',
  detecting_pii: 'detecting-pii',
  extracting_clauses: 'extracting',
  storing: 'storing',
  complete: 'complete',
}

// Friendly error messages
const friendlyErrorMessages: Record<string, string> = {
  ValidationError: 'Please upload a valid PDF or DOCX file',
  UnsupportedFileFormat: 'Please upload a valid PDF or DOCX file',
  FileTooLarge: 'File is too large. Maximum size is 10MB',
  EmptyFile: 'The uploaded file is empty',
  DocumentParsingError: 'Could not extract text from document. Please ensure it\'s a valid PDF or DOCX',
  ClauseExtractionError: 'Failed to extract clauses. The contract may not contain recognizable clauses',
  ContractParserError: 'Processing failed. Please try again or contact support',
  InternalServerError: 'An unexpected error occurred. Please try again',
  DatabaseNotAvailable: 'Database storage is currently unavailable. Please try again later',
}

function getFriendlyError(errorType: string | undefined, message: string): string {
  if (errorType && friendlyErrorMessages[errorType]) {
    return friendlyErrorMessages[errorType]
  }
  return message
}

export default function ContractUpload() {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [stage, setStage] = useState<ProcessingStage>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ContractParseResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  // Create API client instance (memoized to avoid recreation on each render)
  const apiClient = useMemo(() => new APIClient({
    enableLogging: process.env.NODE_ENV === 'development',
  }), [])

  // File validation
  const validateFile = (file: File): string | null => {
    const allowedExtensions = ['.pdf', '.docx']
    const maxSize = 10 * 1024 * 1024 // 10MB

    const fileName = file.name.toLowerCase()
    const isValidExtension = allowedExtensions.some(ext => fileName.endsWith(ext))

    if (!isValidExtension) {
      return 'Please upload a PDF or DOCX file'
    }

    if (file.size > maxSize) {
      return `File is too large. Maximum size is ${maxSize / (1024 * 1024)}MB`
    }

    if (file.size === 0) {
      return 'File is empty'
    }

    return null
  }

  // Handle file selection
  const handleFileSelect = useCallback((selectedFile: File) => {
    const validationError = validateFile(selectedFile)

    if (validationError) {
      setError(validationError)
      setStage('error')
      setFile(null)
      return
    }

    setFile(selectedFile)
    setError(null)
    setStage('idle')
    setResult(null)
  }, [])

  // Drag and drop handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(false)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(false)

    const droppedFiles = e.dataTransfer.files
    if (droppedFiles && droppedFiles.length > 0) {
      handleFileSelect(droppedFiles[0])
    }
  }, [handleFileSelect])

  // Handle file input change
  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (selectedFiles && selectedFiles.length > 0) {
      handleFileSelect(selectedFiles[0])
    }
  }, [handleFileSelect])

  // Upload handler using APIClient
  const handleUpload = async () => {
    if (!file) return

    try {
      setStage('uploading')
      setError(null)

      const data = await apiClient.uploadContract({
        file,
        onProgress: (progress: UploadProgress) => {
          // Map API progress stage to UI stage
          const uiStage = progressStageMap[progress.stage]
          if (uiStage) {
            setStage(uiStage)
          }
        },
      })

      setResult(data)
      setStage('complete')
    } catch (err) {
      // Handle ContractsAPIError with friendly messages
      if (err instanceof ContractsAPIError) {
        setError(getFriendlyError(err.errorType, err.message))
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred')
      }
      setStage('error')
    }
  }

  // Reset handler
  const handleReset = () => {
    setFile(null)
    setStage('idle')
    setResult(null)
    setError(null)
    setIsDragActive(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // Format file size
  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // Processing stages configuration
  const stages = [
    { key: 'uploading', label: 'Uploading' },
    { key: 'detecting-pii', label: 'Detecting PII' },
    { key: 'parsing', label: 'Parsing Document' },
    { key: 'extracting', label: 'Extracting Clauses' },
    { key: 'storing', label: 'Storing in Database' },
  ]

  const getStageIndex = (stageKey: string): number => {
    return stages.findIndex(s => s.key === stageKey)
  }

  const currentStageIndex = getStageIndex(stage)

  return (
    <div className="space-y-8">
      {/* Upload Area */}
      {stage === 'idle' || stage === 'error' ? (
        <div>
          <div
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              border-2 border-dashed rounded-lg p-12 text-center cursor-pointer
              transition-all duration-300
              ${isDragActive
                ? 'border-emerald-500 bg-emerald-50'
                : 'border-stone-900 bg-white hover:border-emerald-500'
              }
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              onChange={handleFileInputChange}
              className="hidden"
            />

            <div className="text-6xl mb-4">📄</div>
            <h3 className="text-xl font-bold text-stone-900 mb-2">
              {isDragActive ? 'Drop file here' : 'Upload Contract'}
            </h3>
            <p className="text-stone-600 mb-4">
              Drag and drop a file here, or click to browse
            </p>
            <p className="text-sm text-stone-500" style={{ fontFamily: 'Space Mono, monospace' }}>
              Supported formats: PDF, DOCX (max 10MB)
            </p>
          </div>

          {/* Selected File Preview */}
          {file && stage === 'idle' && (
            <div className="mt-6 border-2 border-stone-900 rounded-lg p-6 bg-white shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="text-4xl">📄</div>
                  <div>
                    <div className="font-bold text-stone-900">{file.name}</div>
                    <div className="text-sm text-stone-600" style={{ fontFamily: 'Space Mono, monospace' }}>
                      {formatFileSize(file.size)}
                    </div>
                  </div>
                </div>

                <div className="flex space-x-3">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleReset()
                    }}
                    className="px-4 py-2 border-2 border-stone-900 bg-white text-stone-900 rounded-lg hover:bg-stone-50 transition-all duration-300"
                  >
                    Remove
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleUpload()
                    }}
                    className="px-6 py-2 bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-all duration-300"
                  >
                    Start Parsing
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Error Display */}
          {stage === 'error' && error && (
            <div className="mt-6 border-2 border-red-500 rounded-lg p-6 bg-red-50">
              <div className="flex items-start space-x-4">
                <div className="text-3xl">❌</div>
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-red-900 mb-2">
                    Upload Failed
                  </h3>
                  <p className="text-red-700 mb-4">{error}</p>
                  <button
                    onClick={handleReset}
                    className="px-6 py-2 border-2 border-stone-900 bg-white text-stone-900 rounded-lg hover:bg-stone-50 transition-all duration-300"
                  >
                    Try Again
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}

      {/* Processing Status */}
      {stage !== 'idle' && stage !== 'error' && stage !== 'complete' && (
        <div className="border-2 border-stone-900 rounded-lg p-8 bg-white shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
          <h2 className="text-2xl font-bold text-stone-900 mb-6">Processing Contract</h2>

          <div className="space-y-4">
            {stages.map((stageConfig, idx) => {
              const isComplete = idx < currentStageIndex
              const isCurrent = stageConfig.key === stage
              const isPending = idx > currentStageIndex

              return (
                <div key={stageConfig.key} className="flex items-center space-x-4">
                  {/* Status Icon */}
                  <div
                    className={`
                      flex items-center justify-center w-10 h-10 rounded-full border-2
                      ${isComplete ? 'bg-emerald-500 border-emerald-500' : ''}
                      ${isCurrent ? 'bg-stone-900 border-stone-900' : ''}
                      ${isPending ? 'bg-stone-200 border-stone-300' : ''}
                    `}
                  >
                    {isComplete && <span className="text-white text-xl">✓</span>}
                    {isCurrent && (
                      <div className="animate-spin rounded-full h-5 w-5 border-2 border-stone-200 border-t-white" />
                    )}
                    {isPending && <span className="text-stone-400">{idx + 1}</span>}
                  </div>

                  {/* Stage Label */}
                  <div className="flex-1">
                    <div
                      className={`
                        font-bold
                        ${isComplete ? 'text-emerald-600' : ''}
                        ${isCurrent ? 'text-stone-900' : ''}
                        ${isPending ? 'text-stone-400' : ''}
                      `}
                    >
                      {stageConfig.label}
                      {isCurrent && '...'}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Results Display */}
      {stage === 'complete' && result && (
        <div className="border-2 border-stone-900 rounded-lg p-6 bg-white shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
          <h2 className="text-2xl font-bold text-stone-900 mb-6">
            ✅ Parsing Complete
          </h2>

          <div className="grid grid-cols-2 gap-4 mb-6">
            <StatCard label="Contract ID" value={result.contract_id || 'N/A'} />
            <StatCard label="Clauses Extracted" value={result.clauses_extracted} />
            <StatCard label="PII Detected" value={result.pii_detected} />
            <StatCard label="Processing Time" value={`${result.processing_time.toFixed(2)}s`} />
          </div>

          <ClausesList clauses={result.clauses} />

          <div className="mt-6 flex space-x-4">
            {result.contract_id > 0 && (
              <button
                onClick={() => router.push(`/contracts/${result.contract_id}`)}
                className="px-6 py-3 bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-all duration-300"
              >
                View Contract Details →
              </button>
            )}
            <button
              onClick={handleReset}
              className="px-6 py-3 border-2 border-stone-900 bg-white text-stone-900 rounded-lg hover:bg-stone-50 transition-all duration-300"
            >
              Upload Another Contract
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
