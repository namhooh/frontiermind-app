'use client'

/**
 * ContractUploadStep
 *
 * Step 1: Upload and parse a contract document.
 * Wraps the existing ContractUpload component with workflow integration.
 */

import { useState, useCallback, useRef, useMemo } from 'react'
import { Upload, FileText, Loader2, AlertCircle, Check } from 'lucide-react'
import { useWorkflow } from '@/lib/workflow'
import {
  APIClient,
  ContractsAPIError,
  type UploadProgress,
} from '@/lib/api'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { cn } from '@/app/components/ui/cn'

type ProcessingStage =
  | 'idle'
  | 'uploading'
  | 'detecting-pii'
  | 'parsing'
  | 'extracting'
  | 'storing'
  | 'complete'
  | 'error'

const progressStageMap: Record<UploadProgress['stage'], ProcessingStage> = {
  uploading: 'uploading',
  parsing: 'parsing',
  detecting_pii: 'detecting-pii',
  extracting_clauses: 'extracting',
  storing: 'storing',
  complete: 'complete',
}

const friendlyErrorMessages: Record<string, string> = {
  ValidationError: 'Please upload a valid PDF or DOCX file',
  UnsupportedFileFormat: 'Please upload a valid PDF or DOCX file',
  FileTooLarge: 'File is too large. Maximum size is 10MB',
  EmptyFile: 'The uploaded file is empty',
  DocumentParsingError: "Could not extract text from document. Please ensure it's a valid PDF or DOCX",
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

const stages = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'detecting-pii', label: 'Detecting PII' },
  { key: 'parsing', label: 'Parsing Document' },
  { key: 'extracting', label: 'Extracting Clauses' },
  { key: 'storing', label: 'Storing in Database' },
]

export function ContractUploadStep() {
  const {
    state,
    setContractFile,
    setParseResult,
    setUploading,
    setUploadError,
    goToNextStep,
  } = useWorkflow()

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [stage, setStage] = useState<ProcessingStage>(
    state.parseResult ? 'complete' : 'idle'
  )
  const [localFile, setLocalFile] = useState<File | null>(state.contractFile)
  const [isDragActive, setIsDragActive] = useState(false)

  const apiClient = useMemo(
    () =>
      new APIClient({
        enableLogging: process.env.NODE_ENV === 'development',
      }),
    []
  )

  const validateFile = (file: File): string | null => {
    const allowedExtensions = ['.pdf', '.docx']
    const maxSize = 10 * 1024 * 1024

    const fileName = file.name.toLowerCase()
    const isValidExtension = allowedExtensions.some((ext) => fileName.endsWith(ext))

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

  const handleFileSelect = useCallback(
    (selectedFile: File) => {
      const validationError = validateFile(selectedFile)

      if (validationError) {
        setUploadError(validationError)
        setStage('error')
        setLocalFile(null)
        setContractFile(null)
        return
      }

      setLocalFile(selectedFile)
      setContractFile(selectedFile)
      setUploadError(null)
      setStage('idle')
      setParseResult(null)
    },
    [setContractFile, setUploadError, setParseResult]
  )

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

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragActive(false)

      const droppedFiles = e.dataTransfer.files
      if (droppedFiles && droppedFiles.length > 0) {
        handleFileSelect(droppedFiles[0])
      }
    },
    [handleFileSelect]
  )

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = e.target.files
      if (selectedFiles && selectedFiles.length > 0) {
        handleFileSelect(selectedFiles[0])
      }
    },
    [handleFileSelect]
  )

  const handleUpload = async () => {
    if (!localFile) return

    try {
      setStage('uploading')
      setUploading(true)
      setUploadError(null)

      const data = await apiClient.uploadContract({
        file: localFile,
        onProgress: (progress: UploadProgress) => {
          const uiStage = progressStageMap[progress.stage]
          if (uiStage) {
            setStage(uiStage)
          }
        },
      })

      setParseResult(data)
      setStage('complete')
      setUploading(false)
    } catch (err) {
      if (err instanceof ContractsAPIError) {
        setUploadError(getFriendlyError(err.errorType, err.message))
      } else if (err instanceof Error) {
        setUploadError(err.message)
      } else {
        setUploadError('An unexpected error occurred')
      }
      setStage('error')
      setUploading(false)
    }
  }

  const handleReset = () => {
    setLocalFile(null)
    setContractFile(null)
    setStage('idle')
    setParseResult(null)
    setUploadError(null)
    setIsDragActive(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const getStageIndex = (stageKey: string): number => {
    return stages.findIndex((s) => s.key === stageKey)
  }

  const currentStageIndex = getStageIndex(stage)

  // If already parsed, show success state
  if (state.parseResult && stage === 'complete') {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Check className="w-5 h-5 text-emerald-500" />
            Contract Uploaded
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4 p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
            <FileText className="w-10 h-10 text-emerald-500" />
            <div className="flex-1">
              <p className="font-medium text-slate-900">{localFile?.name || 'Contract File'}</p>
              <p className="text-sm text-slate-600">
                {state.parseResult.clauses_extracted} clauses extracted
              </p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {state.parseResult.clauses_extracted}
              </p>
              <p className="text-sm text-slate-600">Clauses</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {state.parseResult.pii_detected}
              </p>
              <p className="text-sm text-slate-600">PII Detected</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {state.parseResult.processing_time.toFixed(1)}s
              </p>
              <p className="text-sm text-slate-600">Processing Time</p>
            </div>
          </div>

          <div className="flex gap-3">
            <Button variant="outline" onClick={handleReset}>
              Upload Different Contract
            </Button>
            <Button onClick={goToNextStep}>
              Continue to Review Clauses
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload Contract</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Upload Area */}
        {(stage === 'idle' || stage === 'error') && (
          <>
            <div
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                'border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-all duration-300',
                isDragActive
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-slate-300 bg-white hover:border-blue-500'
              )}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx"
                onChange={handleFileInputChange}
                className="hidden"
              />

              <Upload className="w-12 h-12 mx-auto mb-4 text-slate-400" />
              <h3 className="text-lg font-semibold text-slate-900 mb-2">
                {isDragActive ? 'Drop file here' : 'Upload Contract'}
              </h3>
              <p className="text-slate-600 mb-4">
                Drag and drop a file here, or click to browse
              </p>
              <p className="text-sm text-slate-500 font-mono">
                Supported formats: PDF, DOCX (max 10MB)
              </p>
            </div>

            {/* Selected File Preview */}
            {localFile && stage === 'idle' && (
              <div className="border-2 border-slate-200 rounded-lg p-4 bg-white">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <FileText className="w-10 h-10 text-blue-500" />
                    <div>
                      <p className="font-semibold text-slate-900">{localFile.name}</p>
                      <p className="text-sm text-slate-600 font-mono">
                        {formatFileSize(localFile.size)}
                      </p>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button variant="outline" onClick={handleReset}>
                      Remove
                    </Button>
                    <Button onClick={handleUpload}>Start Parsing</Button>
                  </div>
                </div>
              </div>
            )}

            {/* Error Display */}
            {stage === 'error' && state.uploadError && (
              <div className="border border-red-200 rounded-lg p-4 bg-red-50">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
                  <div className="flex-1">
                    <h4 className="font-semibold text-red-900 mb-1">Upload Failed</h4>
                    <p className="text-red-700 text-sm">{state.uploadError}</p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleReset}
                      className="mt-3"
                    >
                      Try Again
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* Processing Status */}
        {stage !== 'idle' && stage !== 'error' && stage !== 'complete' && (
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-slate-900">Processing Contract</h3>

            <div className="space-y-3">
              {stages.map((stageConfig, idx) => {
                const isComplete = idx < currentStageIndex
                const isCurrent = stageConfig.key === stage
                const isPending = idx > currentStageIndex

                return (
                  <div key={stageConfig.key} className="flex items-center gap-3">
                    <div
                      className={cn(
                        'flex items-center justify-center w-8 h-8 rounded-full border-2',
                        isComplete && 'bg-emerald-500 border-emerald-500',
                        isCurrent && 'bg-blue-600 border-blue-600',
                        isPending && 'bg-slate-100 border-slate-300'
                      )}
                    >
                      {isComplete && <Check className="w-4 h-4 text-white" />}
                      {isCurrent && (
                        <Loader2 className="w-4 h-4 text-white animate-spin" />
                      )}
                      {isPending && (
                        <span className="text-xs text-slate-400">{idx + 1}</span>
                      )}
                    </div>

                    <span
                      className={cn(
                        'font-medium',
                        isComplete && 'text-emerald-600',
                        isCurrent && 'text-blue-600',
                        isPending && 'text-slate-400'
                      )}
                    >
                      {stageConfig.label}
                      {isCurrent && '...'}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
