'use client'

/**
 * ReportCard
 *
 * Individual report row/card for the reports list.
 */

import { Download, FileText, FileSpreadsheet, File, AlertCircle } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import { ReportStatusBadge } from './ReportStatusBadge'
import type { GeneratedReport, FileFormat } from '@/lib/api'

interface ReportCardProps {
  report: GeneratedReport
  onDownload: (reportId: number) => void
  isDownloading?: boolean
}

const formatIcons: Record<FileFormat, typeof FileText> = {
  pdf: FileText,
  xlsx: FileSpreadsheet,
  csv: File,
  json: File,
}

function formatDate(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatBytes(bytes?: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatReportType(type: string): string {
  return type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())
}

export function ReportCard({ report, onDownload, isDownloading }: ReportCardProps) {
  const Icon = formatIcons[report.file_format]
  const canDownload = report.report_status === 'completed'

  return (
    <div className="flex items-center justify-between p-4 bg-white border border-slate-200 rounded-lg hover:border-slate-300 transition-colors">
      <div className="flex items-center gap-4">
        {/* Icon */}
        <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-slate-100">
          <Icon className="w-5 h-5 text-slate-600" />
        </div>

        {/* Info */}
        <div>
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-slate-900">{report.name}</h4>
            <ReportStatusBadge status={report.report_status} />
          </div>
          <div className="flex items-center gap-3 mt-1 text-sm text-slate-500">
            <span>{formatReportType(report.report_type)}</span>
            <span>&bull;</span>
            <span>{report.file_format.toUpperCase()}</span>
            <span>&bull;</span>
            <span>{formatDate(report.created_at)}</span>
            {report.file_size_bytes && (
              <>
                <span>&bull;</span>
                <span>{formatBytes(report.file_size_bytes)}</span>
              </>
            )}
          </div>

          {/* Error message if failed */}
          {report.report_status === 'failed' && report.processing_error && (
            <div className="flex items-center gap-2 mt-2 text-sm text-red-600">
              <AlertCircle className="w-4 h-4" />
              <span>{report.processing_error}</span>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2">
        {canDownload && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onDownload(report.id)}
            disabled={isDownloading}
          >
            <Download className="w-4 h-4 mr-2" />
            Download
          </Button>
        )}
      </div>
    </div>
  )
}
