'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/app/components/ui/button'

export const API_ENDPOINT =
  process.env.NEXT_PUBLIC_API_ENDPOINT ||
  'https://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com'

interface OnboardingSummaryProps {
  organizationId: number
  apiKey: string
}

export function OnboardingSummary({ organizationId, apiKey }: OnboardingSummaryProps) {
  const [copied, setCopied] = useState(false)

  const summaryText = `Organization ID: ${organizationId}\nAPI Key: ${apiKey}\nAPI Endpoint: ${API_ENDPOINT}`

  async function handleCopy() {
    await navigator.clipboard.writeText(summaryText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium uppercase tracking-wider text-slate-500">
          Onboarding Details
        </span>
        <Button variant="ghost" size="sm" onClick={handleCopy}>
          {copied ? <Check className="h-3.5 w-3.5 mr-1" /> : <Copy className="h-3.5 w-3.5 mr-1" />}
          {copied ? 'Copied' : 'Copy All'}
        </Button>
      </div>
      <pre className="text-sm font-mono text-slate-700 whitespace-pre-wrap break-all">
        {summaryText}
      </pre>
    </div>
  )
}
