'use client'

/**
 * ReportStatusBadge
 *
 * Status indicator for report generation lifecycle.
 */

import { Loader2 } from 'lucide-react'
import { cn } from '@/app/components/ui/cn'
import type { ReportStatus } from '@/lib/api'

interface ReportStatusBadgeProps {
  status: ReportStatus
  className?: string
}

const statusConfig: Record<
  ReportStatus,
  { color: string; bgColor: string; label: string; showSpinner?: boolean }
> = {
  pending: {
    color: 'text-yellow-800',
    bgColor: 'bg-yellow-100',
    label: 'Pending',
  },
  processing: {
    color: 'text-blue-800',
    bgColor: 'bg-blue-100',
    label: 'Processing',
    showSpinner: true,
  },
  completed: {
    color: 'text-emerald-800',
    bgColor: 'bg-emerald-100',
    label: 'Completed',
  },
  failed: {
    color: 'text-red-800',
    bgColor: 'bg-red-100',
    label: 'Failed',
  },
}

export function ReportStatusBadge({ status, className }: ReportStatusBadgeProps) {
  const config = statusConfig[status]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium',
        config.bgColor,
        config.color,
        className
      )}
    >
      {config.showSpinner && <Loader2 className="w-3 h-3 animate-spin" />}
      {config.label}
    </span>
  )
}
