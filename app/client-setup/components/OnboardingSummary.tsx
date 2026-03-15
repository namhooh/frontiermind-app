'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/app/components/ui/button'

export const API_ENDPOINT =
  process.env.NEXT_PUBLIC_API_ENDPOINT ||
  'https://api.frontiermind.co'

interface OnboardingParams {
  endpoint: string
  apiKey: string
  organizationId: number
  scopes?: string[] | null
  dataSourceId?: number | null
}

function shouldShow(scope: string, params: OnboardingParams): boolean {
  const { scopes, dataSourceId } = params
  if (!scopes || scopes.length === 0) return true
  if (!dataSourceId && scope !== 'billing_reads') return true
  return scopes.includes(scope)
}

export function buildOnboardingSections(params: OnboardingParams): string {
  const { endpoint, apiKey, organizationId } = params

  const lines: string[] = [
    '=== FrontierMind API Onboarding ===',
    '',
    `Organization ID: ${organizationId}`,
    `API Key: ${apiKey}`,
    `API Endpoint: ${endpoint}`,
    `Auth Header: Authorization: Bearer ${apiKey}`,
    '',
    '--- Available Endpoints ---',
    '',
  ]

  if (shouldShow('meter_data', params)) {
    lines.push('POST /api/ingest/upload              Upload meter data file (CSV/JSON)')
  }
  if (shouldShow('billing_reads', params)) {
    lines.push('POST /api/ingest/billing-reads       Push billing reads (JSON)')
  }
  if (shouldShow('fx_rates', params)) {
    lines.push('POST /api/ingest/fx-rates            Push FX rates (JSON)')
  }
  if (shouldShow('reference_prices', params)) {
    lines.push('POST /api/ingest/reference-prices    Push MRP reference prices (JSON)')
  }
  if (shouldShow('invoice_export', params)) {
    lines.push('GET  /api/export/expected-invoices   Export expected invoices (JSON)')
  }

  lines.push(
    '',
    '--- Notes ---',
    '- All requests require the auth header above',
    '- Max 5,000 entries per batch',
    '- Duplicate records are upserted (updated in place)',
    `- Full API docs: ${endpoint}/docs`,
  )

  return lines.join('\n')
}

interface OnboardingSummaryProps {
  organizationId: number
  apiKey: string
  scopes?: string[] | null
  dataSourceId?: number | null
}

export function OnboardingSummary({ organizationId, apiKey, scopes, dataSourceId }: OnboardingSummaryProps) {
  const [copied, setCopied] = useState(false)

  const summaryText = buildOnboardingSections({
    endpoint: API_ENDPOINT,
    apiKey,
    organizationId,
    scopes,
    dataSourceId,
  })

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
