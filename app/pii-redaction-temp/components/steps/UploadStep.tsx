'use client'

import { useState, useCallback, useRef, useMemo } from 'react'
import { Upload, FileText, AlertCircle } from 'lucide-react'
import { usePIIRedaction } from '@/lib/pii-redaction-temp'
import { PIIRedactionTempClient, PIIRedactionAPIError } from '@/lib/api/piiRedactionTempClient'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { cn } from '@/app/components/ui/cn'

const ALLOWED_EXTENSIONS = ['.pdf', '.docx']
const MAX_FILE_SIZE = 10 * 1024 * 1024

export function UploadStep() {
  const {
    state,
    setFile,
    clearFile,
    setUploadError,
    clearUploadError,
    setProcessing,
    setProcessingStage,
    setProcessingError,
    setResult,
    setStep,
  } = usePIIRedaction()

  const [isDragActive, setIsDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // TODO: Replace with actual organization ID from auth context when available
  const apiClient = useMemo(() => new PIIRedactionTempClient({ organizationId: 1 }), [])

  const validateFile = (file: File): string | null => {
    const fileName = file.name.toLowerCase()
    const isValidExtension = ALLOWED_EXTENSIONS.some((ext) => fileName.endsWith(ext))

    if (!isValidExtension) {
      return 'Please upload a PDF or DOCX file'
    }

    if (file.size > MAX_FILE_SIZE) {
      return `File is too large. Maximum size is ${MAX_FILE_SIZE / (1024 * 1024)}MB`
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
        clearFile()
        return
      }

      setFile(selectedFile)
      clearUploadError()
    },
    [setFile, clearFile, setUploadError, clearUploadError]
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

  const handleStartProcessing = async () => {
    if (!state.file) return

    try {
      setProcessing(true)
      setProcessingStage('uploading')
      setStep(2)

      const result = await apiClient.redactDocument({
        file: state.file,
        onProgress: (stage) => {
          setProcessingStage(stage)
        },
      })

      setResult(result)
    } catch (err) {
      if (err instanceof PIIRedactionAPIError) {
        setProcessingError(err.message)
      } else if (err instanceof Error) {
        setProcessingError(err.message)
      } else {
        setProcessingError('An unexpected error occurred')
      }
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload Document</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Drop Zone */}
        <div
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all',
            isDragActive
              ? 'border-blue-500 bg-blue-50'
              : state.file
                ? 'border-emerald-300 bg-emerald-50'
                : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleFileInputChange}
            className="hidden"
          />

          {state.file ? (
            <div className="flex flex-col items-center gap-2">
              <FileText className="w-12 h-12 text-emerald-500" />
              <p className="font-medium text-slate-900">{state.file.name}</p>
              <p className="text-sm text-slate-500">{formatFileSize(state.file.size)}</p>
              <p className="text-xs text-slate-400">Click or drag to replace</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Upload className="w-12 h-12 text-slate-400" />
              <p className="font-medium text-slate-600">
                {isDragActive ? 'Drop file here' : 'Drag & drop your document here'}
              </p>
              <p className="text-sm text-slate-400">or click to browse</p>
              <p className="text-xs text-slate-400">PDF or DOCX, max 10MB</p>
            </div>
          )}
        </div>

        {/* Upload Error */}
        {state.uploadError && (
          <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
            <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-700">{state.uploadError}</p>
          </div>
        )}

        {/* Start Button */}
        <Button
          onClick={handleStartProcessing}
          disabled={!state.file}
          className="w-full"
          size="lg"
        >
          Start Processing
        </Button>
      </CardContent>
    </Card>
  )
}
