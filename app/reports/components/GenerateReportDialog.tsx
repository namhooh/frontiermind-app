'use client'

/**
 * GenerateReportDialog
 *
 * Modal dialog for configuring and generating a new report.
 */

import { useState } from 'react'
import { X, FileText, Loader2 } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import { Input } from '@/app/components/ui/input'
import { Label } from '@/app/components/ui/label'
import type { FileFormat, InvoiceReportType, GenerateReportRequest } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface GenerateReportDialogProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (request: GenerateReportRequest) => Promise<void>
  isLoading?: boolean
}

// ============================================================================
// Constants
// ============================================================================

const FORMAT_OPTIONS: { value: FileFormat; label: string }[] = [
  { value: 'pdf', label: 'PDF' },
  { value: 'xlsx', label: 'Excel (XLSX)' },
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
]

const REPORT_TYPE_OPTIONS: { value: InvoiceReportType; label: string }[] = [
  { value: 'invoice_to_client', label: 'Invoice to Client' },
  { value: 'invoice_expected', label: 'Expected Invoice' },
  { value: 'invoice_received', label: 'Received Invoice' },
  { value: 'invoice_comparison', label: 'Invoice Comparison' },
]

// ============================================================================
// Component
// ============================================================================

export function GenerateReportDialog({
  isOpen,
  onClose,
  onSubmit,
  isLoading = false,
}: GenerateReportDialogProps) {
  const [formData, setFormData] = useState({
    name: '',
    reportType: 'invoice_to_client' as InvoiceReportType,
    fileFormat: 'pdf' as FileFormat,
    billingPeriodId: '1',
    contractId: '',
    projectId: '',
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const request: GenerateReportRequest = {
      billing_period_id: parseInt(formData.billingPeriodId, 10),
      report_type: formData.reportType,
      file_format: formData.fileFormat,
      name: formData.name || undefined,
      contract_id: formData.contractId ? parseInt(formData.contractId, 10) : undefined,
      project_id: formData.projectId ? parseInt(formData.projectId, 10) : undefined,
    }

    await onSubmit(request)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Generate Report
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div className="px-6 py-4 space-y-4">
            {/* Report Name */}
            <div className="space-y-2">
              <Label htmlFor="name">Report Name (Optional)</Label>
              <Input
                id="name"
                placeholder="e.g., January 2024 Invoice Report"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="bg-white border-slate-300 text-slate-900"
              />
            </div>

            {/* Report Type */}
            <div className="space-y-2">
              <Label htmlFor="reportType">Report Type</Label>
              <select
                id="reportType"
                value={formData.reportType}
                onChange={(e) =>
                  setFormData({ ...formData, reportType: e.target.value as InvoiceReportType })
                }
                className="w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {REPORT_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            {/* File Format */}
            <div className="space-y-2">
              <Label htmlFor="fileFormat">Output Format</Label>
              <select
                id="fileFormat"
                value={formData.fileFormat}
                onChange={(e) =>
                  setFormData({ ...formData, fileFormat: e.target.value as FileFormat })
                }
                className="w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {FORMAT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Billing Period ID */}
            <div className="space-y-2">
              <Label htmlFor="billingPeriodId">Billing Period ID</Label>
              <Input
                id="billingPeriodId"
                type="number"
                min="1"
                required
                value={formData.billingPeriodId}
                onChange={(e) => setFormData({ ...formData, billingPeriodId: e.target.value })}
                className="bg-white border-slate-300 text-slate-900"
              />
            </div>

            {/* Contract ID (Optional) */}
            <div className="space-y-2">
              <Label htmlFor="contractId">Contract ID (Optional)</Label>
              <Input
                id="contractId"
                type="number"
                min="1"
                placeholder="Leave empty for all contracts"
                value={formData.contractId}
                onChange={(e) => setFormData({ ...formData, contractId: e.target.value })}
                className="bg-white border-slate-300 text-slate-900"
              />
            </div>

            {/* Project ID (Optional) */}
            <div className="space-y-2">
              <Label htmlFor="projectId">Project ID (Optional)</Label>
              <Input
                id="projectId"
                type="number"
                min="1"
                placeholder="Leave empty for all projects"
                value={formData.projectId}
                onChange={(e) => setFormData({ ...formData, projectId: e.target.value })}
                className="bg-white border-slate-300 text-slate-900"
              />
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-3 px-6 py-4 border-t bg-slate-50">
            <Button type="button" variant="outline" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <FileText className="w-4 h-4 mr-2" />
                  Generate Report
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
