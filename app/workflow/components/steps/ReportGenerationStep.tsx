'use client'

/**
 * ReportGenerationStep
 *
 * Step 5: Generate formal reports from the invoice preview.
 * Uses the backend Reports API to create downloadable reports in various formats.
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import {
  FileText,
  Loader2,
  AlertCircle,
  Check,
  ArrowLeft,
  Download,
  RefreshCw,
  FileSpreadsheet,
  File,
} from 'lucide-react'
import { useWorkflow } from '@/lib/workflow'
import {
  ReportsClient,
  ReportsAPIError,
  type FileFormat,
  type InvoiceReportType,
  type GeneratedReport,
} from '@/lib/api'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'

// ============================================================================
// Constants
// ============================================================================

const FORMAT_OPTIONS: { value: FileFormat; label: string; icon: typeof FileText; description: string }[] = [
  { value: 'pdf', label: 'PDF', icon: FileText, description: 'Professional document format' },
  { value: 'xlsx', label: 'Excel', icon: FileSpreadsheet, description: 'Spreadsheet with formulas' },
  { value: 'csv', label: 'CSV', icon: File, description: 'Plain data export' },
  { value: 'json', label: 'JSON', icon: File, description: 'Machine-readable format' },
]

const REPORT_TYPE_OPTIONS: { value: InvoiceReportType; label: string; description: string }[] = [
  { value: 'invoice_to_client', label: 'Invoice to Client', description: 'Standard client invoice report' },
  { value: 'invoice_expected', label: 'Expected Invoice', description: 'Expected invoice based on contract terms' },
  { value: 'invoice_received', label: 'Received Invoice', description: 'Invoice received from counterparty' },
  { value: 'invoice_comparison', label: 'Invoice Comparison', description: 'Compare expected vs received' },
]

// ============================================================================
// Helper Components
// ============================================================================

interface FormatSelectorProps {
  value: FileFormat
  onChange: (format: FileFormat) => void
  disabled?: boolean
}

function FormatSelector({ value, onChange, disabled }: FormatSelectorProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {FORMAT_OPTIONS.map((option) => {
        const Icon = option.icon
        const isSelected = value === option.value

        return (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            disabled={disabled}
            className={`
              p-4 rounded-lg border-2 transition-all text-left
              ${isSelected
                ? 'border-blue-500 bg-blue-50'
                : 'border-slate-200 hover:border-slate-300 bg-white'
              }
              ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
            `}
          >
            <Icon className={`w-5 h-5 mb-2 ${isSelected ? 'text-blue-600' : 'text-slate-400'}`} />
            <div className={`font-medium ${isSelected ? 'text-blue-900' : 'text-slate-700'}`}>
              {option.label}
            </div>
            <div className="text-xs text-slate-500 mt-1">{option.description}</div>
          </button>
        )
      })}
    </div>
  )
}

interface ReportTypeSelectorProps {
  value: InvoiceReportType
  onChange: (type: InvoiceReportType) => void
  disabled?: boolean
}

function ReportTypeSelector({ value, onChange, disabled }: ReportTypeSelectorProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {REPORT_TYPE_OPTIONS.map((option) => {
        const isSelected = value === option.value

        return (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            disabled={disabled}
            className={`
              p-4 rounded-lg border-2 transition-all text-left
              ${isSelected
                ? 'border-blue-500 bg-blue-50'
                : 'border-slate-200 hover:border-slate-300 bg-white'
              }
              ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
            `}
          >
            <div className={`font-medium ${isSelected ? 'text-blue-900' : 'text-slate-700'}`}>
              {option.label}
            </div>
            <div className="text-xs text-slate-500 mt-1">{option.description}</div>
          </button>
        )
      })}
    </div>
  )
}

interface ReportStatusDisplayProps {
  report: GeneratedReport
  onDownload: () => void
  isDownloading: boolean
}

function ReportStatusDisplay({ report, onDownload, isDownloading }: ReportStatusDisplayProps) {
  const statusConfig = {
    pending: { color: 'bg-yellow-100 text-yellow-800', label: 'Pending' },
    processing: { color: 'bg-blue-100 text-blue-800', label: 'Processing' },
    completed: { color: 'bg-emerald-100 text-emerald-800', label: 'Completed' },
    failed: { color: 'bg-red-100 text-red-800', label: 'Failed' },
  }

  const config = statusConfig[report.report_status]

  return (
    <div className="p-4 bg-slate-50 rounded-lg space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-medium text-slate-900">{report.name}</h4>
          <p className="text-sm text-slate-500">
            {report.report_type.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} &bull;{' '}
            {report.file_format.toUpperCase()}
          </p>
        </div>
        <Badge className={config.color}>{config.label}</Badge>
      </div>

      {report.report_status === 'completed' && (
        <div className="flex items-center justify-between pt-2 border-t border-slate-200">
          <div className="text-sm text-slate-600">
            {report.record_count !== undefined && (
              <span>{report.record_count} records</span>
            )}
            {report.file_size_bytes !== undefined && (
              <span className="ml-3">
                {(report.file_size_bytes / 1024).toFixed(1)} KB
              </span>
            )}
          </div>
          <Button
            onClick={onDownload}
            disabled={isDownloading}
            size="sm"
          >
            {isDownloading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Download className="w-4 h-4 mr-2" />
            )}
            Download
          </Button>
        </div>
      )}

      {report.report_status === 'failed' && report.processing_error && (
        <div className="p-3 bg-red-50 rounded border border-red-200">
          <p className="text-sm text-red-700">{report.processing_error}</p>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Main Component
// ============================================================================

export function ReportGenerationStep() {
  const {
    state,
    setReportData,
    setGeneratingReport,
    setReportError,
    setReportFormat,
    setReportType,
    resetReportState,
    goToPreviousStep,
    resetWorkflow,
  } = useWorkflow()

  const [isDownloading, setIsDownloading] = useState(false)
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null)

  const reportsClient = useMemo(
    () =>
      new ReportsClient({
        enableLogging: process.env.NODE_ENV === 'development',
        organizationId: state.organizationId || undefined,
      }),
    [state.organizationId]
  )

  const {
    invoicePreview,
    parseResult,
    meterDataSummary,
    reportData,
    isGeneratingReport,
    reportError,
    selectedReportFormat,
    selectedReportType,
  } = state

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval)
      }
    }
  }, [pollingInterval])

  // Poll for report completion
  const pollForCompletion = useCallback(
    async (reportId: number) => {
      try {
        const report = await reportsClient.getReport(reportId)
        setReportData(report)

        if (report.report_status === 'completed' || report.report_status === 'failed') {
          if (pollingInterval) {
            clearInterval(pollingInterval)
            setPollingInterval(null)
          }
          setGeneratingReport(false)

          if (report.report_status === 'failed') {
            setReportError(report.processing_error || 'Report generation failed')
          }
        }
      } catch (err) {
        console.error('Error polling for report status:', err)
      }
    },
    [reportsClient, pollingInterval, setReportData, setGeneratingReport, setReportError]
  )

  const handleGenerateReport = async () => {
    // For the demo, we need a billing_period_id. In a real app, this would come from the workflow state.
    // We'll use a placeholder value of 1 for now.
    const billingPeriodId = 1

    setGeneratingReport(true)
    setReportError(null)
    setReportData(null)

    try {
      const result = await reportsClient.generateReport({
        billing_period_id: billingPeriodId,
        report_type: selectedReportType,
        file_format: selectedReportFormat,
        name: `${invoicePreview?.invoiceNumber || 'Invoice'}_${selectedReportType}_${new Date().toISOString().slice(0, 10)}`,
        contract_id: parseResult?.contract_id,
        project_id: state.projectId || undefined,
      })

      // Start polling for completion
      const interval = setInterval(() => {
        pollForCompletion(result.reportId)
      }, 2000)
      setPollingInterval(interval)

      // Initial fetch
      pollForCompletion(result.reportId)
    } catch (err) {
      setGeneratingReport(false)
      if (err instanceof ReportsAPIError) {
        setReportError(err.message)
      } else if (err instanceof Error) {
        setReportError(err.message)
      } else {
        setReportError('Failed to generate report')
      }
    }
  }

  const handleDownload = async () => {
    if (!reportData?.id) return

    setIsDownloading(true)
    try {
      const { url } = await reportsClient.getDownloadUrl(reportData.id)
      // Open download URL in new tab
      window.open(url, '_blank')
    } catch (err) {
      console.error('Download error:', err)
      setReportError('Failed to get download URL')
    } finally {
      setIsDownloading(false)
    }
  }

  const handleRegenerate = () => {
    resetReportState()
  }

  // Missing prerequisites
  if (!invoicePreview) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <FileText className="w-12 h-12 mx-auto mb-4 text-slate-300" />
          <p className="text-slate-500">Invoice preview required.</p>
          <p className="text-sm text-slate-400 mt-2">
            Please complete the invoice generation step first.
          </p>
          <Button variant="outline" onClick={goToPreviousStep} className="mt-4">
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Invoice
          </Button>
        </CardContent>
      </Card>
    )
  }

  const isProcessing = isGeneratingReport || reportData?.report_status === 'processing'
  const isComplete = reportData?.report_status === 'completed'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Report Generation
          </span>
          {isComplete && (
            <div className="flex items-center gap-2">
              <Badge variant="success">Report Ready</Badge>
              <Button variant="outline" size="sm" onClick={handleRegenerate}>
                <RefreshCw className="w-4 h-4 mr-2" />
                New Report
              </Button>
            </div>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Invoice Summary */}
        <div className="p-4 bg-slate-50 rounded-lg">
          <h4 className="font-medium text-slate-900 mb-2">Invoice Summary</h4>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-500">Invoice Number:</span>{' '}
              <span className="font-medium">{invoicePreview.invoiceNumber}</span>
            </div>
            <div>
              <span className="text-slate-500">Total Amount:</span>{' '}
              <span className="font-medium">${invoicePreview.totalAmount.toLocaleString()}</span>
            </div>
            <div>
              <span className="text-slate-500">Billing Period:</span>{' '}
              <span className="font-medium">
                {invoicePreview.billingPeriod.start} - {invoicePreview.billingPeriod.end}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Line Items:</span>{' '}
              <span className="font-medium">{invoicePreview.lineItems.length}</span>
            </div>
          </div>
        </div>

        {/* Configuration - only show if not processing/complete */}
        {!reportData && !isGeneratingReport && (
          <>
            {/* Report Type Selection */}
            <div>
              <h4 className="font-medium text-slate-900 mb-3">Report Type</h4>
              <ReportTypeSelector
                value={selectedReportType}
                onChange={setReportType}
                disabled={isProcessing}
              />
            </div>

            {/* Format Selection */}
            <div>
              <h4 className="font-medium text-slate-900 mb-3">Output Format</h4>
              <FormatSelector
                value={selectedReportFormat}
                onChange={setReportFormat}
                disabled={isProcessing}
              />
            </div>
          </>
        )}

        {/* Loading State */}
        {isProcessing && !reportData && (
          <div className="py-12 text-center">
            <Loader2 className="w-12 h-12 mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-slate-600 font-medium">Generating report...</p>
            <p className="text-sm text-slate-400 mt-2">
              This may take a moment depending on report complexity
            </p>
          </div>
        )}

        {/* Report Status */}
        {reportData && (
          <ReportStatusDisplay
            report={reportData}
            onDownload={handleDownload}
            isDownloading={isDownloading}
          />
        )}

        {/* Processing indicator for polling */}
        {reportData?.report_status === 'processing' && (
          <div className="flex items-center justify-center gap-2 p-4">
            <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
            <span className="text-slate-600">Processing report...</span>
          </div>
        )}

        {/* Error State */}
        {reportError && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
              <div className="flex-1">
                <h4 className="font-semibold text-red-900 mb-1">Report Generation Failed</h4>
                <p className="text-red-700 text-sm">{reportError}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRegenerate}
                  className="mt-3"
                >
                  Try Again
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Generate Button - only show if not generated */}
        {!reportData && !isGeneratingReport && (
          <div className="pt-4 border-t">
            <Button
              onClick={handleGenerateReport}
              disabled={isProcessing}
              className="w-full"
            >
              {isProcessing ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <FileText className="w-4 h-4 mr-2" />
              )}
              Generate {selectedReportFormat.toUpperCase()} Report
            </Button>
          </div>
        )}

        {/* Success Banner */}
        {isComplete && (
          <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
            <div className="flex items-center gap-3">
              <Check className="w-6 h-6 text-emerald-500" />
              <div>
                <p className="font-medium text-emerald-900">Report Generated Successfully</p>
                <p className="text-sm text-emerald-700">
                  Your {reportData?.file_format.toUpperCase()} report is ready for download.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Navigation */}
        <div className="flex justify-between pt-4 border-t">
          <Button variant="outline" onClick={goToPreviousStep}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Invoice
          </Button>
          <Button variant="emerald" onClick={resetWorkflow}>
            Start New Workflow
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
