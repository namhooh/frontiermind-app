'use client'

import { Loader2 } from 'lucide-react'

interface TemplatePreviewProps {
  html: string
  loading?: boolean
}

export function TemplatePreview({ html, loading }: TemplatePreviewProps) {
  return (
    <div className="relative border border-slate-200 rounded-lg overflow-hidden bg-white" style={{ height: 400 }}>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
          <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
        </div>
      )}
      {html ? (
        <iframe
          srcDoc={html}
          sandbox="allow-same-origin"
          title="Template preview"
          className="w-full h-full border-0"
        />
      ) : (
        <div className="flex items-center justify-center h-full text-sm text-slate-400">
          No preview available
        </div>
      )}
    </div>
  )
}
