'use client'

/**
 * ValidationBanner
 *
 * Displays validation status for required and optional items.
 * - Green checkmark for found items
 * - Yellow warning for missing optional items
 * - Red X for missing required items (blocks progress)
 */

import { Check, X, AlertTriangle } from 'lucide-react'
import type { ValidationItem } from '@/lib/workflow'
import { cn } from '@/app/components/ui/cn'

interface ValidationBannerProps {
  items: ValidationItem[]
  className?: string
}

export function ValidationBanner({ items, className }: ValidationBannerProps) {
  const hasBlockingIssues = items.some((item) => item.required && !item.found)

  return (
    <div
      className={cn(
        'rounded-lg border p-4',
        hasBlockingIssues
          ? 'bg-red-50 border-red-200'
          : 'bg-slate-50 border-slate-200',
        className
      )}
    >
      <div className="flex items-center gap-2 mb-3">
        {hasBlockingIssues ? (
          <>
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <span className="font-medium text-red-700">Missing Required Items</span>
          </>
        ) : (
          <>
            <Check className="w-5 h-5 text-emerald-500" />
            <span className="font-medium text-slate-700">Validation Status</span>
          </>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            {item.found ? (
              <div className="flex items-center justify-center w-5 h-5 rounded-full bg-emerald-100">
                <Check className="w-3 h-3 text-emerald-600" />
              </div>
            ) : item.required ? (
              <div className="flex items-center justify-center w-5 h-5 rounded-full bg-red-100">
                <X className="w-3 h-3 text-red-600" />
              </div>
            ) : (
              <div className="flex items-center justify-center w-5 h-5 rounded-full bg-amber-100">
                <AlertTriangle className="w-3 h-3 text-amber-600" />
              </div>
            )}
            <span
              className={cn(
                'text-sm',
                item.found && 'text-emerald-700',
                !item.found && item.required && 'text-red-700',
                !item.found && !item.required && 'text-amber-700'
              )}
            >
              {item.label}
              {item.required && !item.found && (
                <span className="text-xs ml-1">(Required)</span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
