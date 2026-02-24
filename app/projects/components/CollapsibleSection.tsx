'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface CollapsibleSectionProps {
  title: string
  subtitle?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}

export function CollapsibleSection({ title, subtitle, defaultOpen = true, children }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors text-left select-text"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500 shrink-0" />
        )}
        <span className="text-sm font-semibold text-slate-900">{title}</span>
      </button>
      {open && (
        <div className="p-4">
          {subtitle}
          {children}
        </div>
      )}
    </div>
  )
}
