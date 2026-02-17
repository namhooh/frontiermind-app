'use client'

/**
 * ReportsList
 *
 * Displays a list of generated reports with filtering and sorting.
 */

import { useState, useEffect, useCallback } from 'react'
import { FileText, Loader2, RefreshCw, Filter, X } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import { ReportCard } from './ReportCard'
import { ReportsAPIError } from '@/lib/api'
import type { ReportsClient } from '@/lib/api'
import type { GeneratedReport, ReportFilters, ReportStatus, InvoiceReportType } from '@/lib/api'

interface ReportsListProps {
  refreshTrigger?: number
  reportsClient: ReportsClient
}

const STATUS_OPTIONS: { value: ReportStatus | ''; label: string }[] = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const TYPE_OPTIONS: { value: InvoiceReportType | ''; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'invoice_to_client', label: 'Invoice to Client' },
  { value: 'invoice_expected', label: 'Expected Invoice' },
  { value: 'invoice_received', label: 'Received Invoice' },
  { value: 'invoice_comparison', label: 'Invoice Comparison' },
]

export function ReportsList({ refreshTrigger, reportsClient }: ReportsListProps) {
  const [reports, setReports] = useState<GeneratedReport[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<number | null>(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState<ReportStatus | ''>('')
  const [typeFilter, setTypeFilter] = useState<InvoiceReportType | ''>('')
  const [showFilters, setShowFilters] = useState(false)

  const fetchReports = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const filters: ReportFilters = {
        limit: 50,
        offset: 0,
      }

      if (statusFilter) {
        filters.status = statusFilter
      }
      if (typeFilter) {
        filters.report_type = typeFilter
      }

      const data = await reportsClient.listReports(filters)
      setReports(data)
    } catch (err) {
      if (err instanceof ReportsAPIError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to load reports')
      }
    } finally {
      setIsLoading(false)
    }
  }, [reportsClient, statusFilter, typeFilter])

  // Fetch reports on mount and when filters change
  useEffect(() => {
    fetchReports()
  }, [fetchReports, refreshTrigger])

  // Poll for processing reports
  useEffect(() => {
    const processingReports = reports.filter(
      (r) => r.report_status === 'pending' || r.report_status === 'processing'
    )

    if (processingReports.length === 0) return

    const interval = setInterval(() => {
      fetchReports()
    }, 5000)

    return () => clearInterval(interval)
  }, [reports, fetchReports])

  const handleDownload = async (reportId: number) => {
    setDownloadingId(reportId)
    try {
      const { url } = await reportsClient.getDownloadUrl(reportId)
      window.open(url, '_blank')
    } catch (err) {
      console.error('Download error:', err)
    } finally {
      setDownloadingId(null)
    }
  }

  const clearFilters = () => {
    setStatusFilter('')
    setTypeFilter('')
  }

  const hasFilters = statusFilter !== '' || typeFilter !== ''

  if (isLoading && reports.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-red-700">{error}</p>
        <Button variant="outline" size="sm" onClick={fetchReports} className="mt-3">
          Try Again
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
            className={showFilters ? 'bg-slate-100' : ''}
          >
            <Filter className="w-4 h-4 mr-2" />
            Filters
            {hasFilters && (
              <span className="ml-2 px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full">
                {(statusFilter ? 1 : 0) + (typeFilter ? 1 : 0)}
              </span>
            )}
          </Button>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="w-4 h-4 mr-1" />
              Clear
            </Button>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={fetchReports} disabled={isLoading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="flex items-center gap-4 p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2">
            <label className="text-sm text-slate-600">Status:</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ReportStatus | '')}
              className="h-9 px-3 rounded-md border border-slate-300 bg-white text-sm"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-slate-600">Type:</label>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as InvoiceReportType | '')}
              className="h-9 px-3 rounded-md border border-slate-300 bg-white text-sm"
            >
              {TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Reports List */}
      {reports.length === 0 ? (
        <div className="py-12 text-center">
          <FileText className="w-12 h-12 mx-auto mb-4 text-slate-300" />
          <p className="text-slate-500">No reports found.</p>
          {hasFilters && (
            <p className="text-sm text-slate-400 mt-2">
              Try adjusting your filters or generate a new report.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              onDownload={handleDownload}
              isDownloading={downloadingId === report.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
