'use client'

import { useState } from 'react'
import { Check, Copy, AlertTriangle, Download } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/app/components/ui/dialog'
import { Button } from '@/app/components/ui/button'
import { Input } from '@/app/components/ui/input'
import { Label } from '@/app/components/ui/label'
import {
  AdminClient,
  type DataSourceResponse,
  type GenerateAPIKeyResponse,
} from '@/lib/api/adminClient'
import { OnboardingSummary, API_ENDPOINT } from './OnboardingSummary'

const client = new AdminClient()

interface GenerateAPIKeyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  organizationId: number
  dataSources: DataSourceResponse[]
  onCreated: () => void
}

export function GenerateAPIKeyDialog({
  open,
  onOpenChange,
  organizationId,
  dataSources,
  onCreated,
}: GenerateAPIKeyDialogProps) {
  const [dataSourceId, setDataSourceId] = useState<string>('')
  const [label, setLabel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<GenerateAPIKeyResponse | null>(null)
  const [keyCopied, setKeyCopied] = useState(false)

  function reset() {
    setDataSourceId('')
    setLabel('')
    setSubmitting(false)
    setError(null)
    setResult(null)
    setKeyCopied(false)
  }

  function handleClose(isOpen: boolean) {
    if (!isOpen) reset()
    onOpenChange(isOpen)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!dataSourceId) return

    setSubmitting(true)
    setError(null)

    try {
      const res = await client.generateAPIKey(organizationId, {
        data_source_id: Number(dataSourceId),
        label: label.trim() || undefined,
      })
      setResult(res)
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate API key')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCopyKey() {
    if (!result) return
    await navigator.clipboard.writeText(result.api_key)
    setKeyCopied(true)
    setTimeout(() => setKeyCopied(false), 2000)
  }

  function handleDownload() {
    if (!result) return
    const text = [
      '=== FrontierMind API Onboarding ===',
      '',
      `Organization ID: ${result.organization_id}`,
      `API Key: ${result.api_key}`,
      `API Endpoint: ${API_ENDPOINT}`,
      '',
      '--- Quick Start ---',
      '',
      'Push meter data:',
      `  curl -X POST ${API_ENDPOINT}/api/ingest/meter-data \\`,
      `    -H "Authorization: Bearer ${result.api_key}" \\`,
      '    -H "Content-Type: application/json" \\',
      '    -d \'{"readings": [...]}\'',
      '',
      'Upload a file (CSV/JSON):',
      `  curl -X POST ${API_ENDPOINT}/api/ingest/upload \\`,
      `    -H "Authorization: Bearer ${result.api_key}" \\`,
      '    -F "file=@meter_data.csv"',
    ].join('\n')

    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `onboarding-org-${result.organization_id}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className={result ? 'sm:max-w-xl' : undefined}>
        <DialogHeader>
          <DialogTitle>
            {result ? 'API Key Generated' : 'Generate API Key'}
          </DialogTitle>
          <DialogDescription>
            {result
              ? 'Save this key now — it will not be shown again.'
              : 'Create a new API key for data ingestion.'}
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ds-select">Data Source *</Label>
              <select
                id="ds-select"
                value={dataSourceId}
                onChange={(e) => setDataSourceId(e.target.value)}
                required
                className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400"
              >
                <option value="">Select a data source</option>
                {dataSources.map((ds) => (
                  <option key={ds.id} value={ds.id}>
                    {ds.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="key-label">Label</Label>
              <Input
                id="key-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Production Snowflake key"
              />
            </div>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleClose(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting || !dataSourceId}>
                {submitting ? 'Generating...' : 'Generate Key'}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3">
              <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
              <p className="text-sm text-amber-800">
                This key will not be shown again. Copy it now and share it securely with the client.
              </p>
            </div>

            <div className="space-y-1">
              <Label>API Key</Label>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-mono break-all">
                  {result.api_key}
                </code>
                <Button variant="outline" size="sm" onClick={handleCopyKey}>
                  {keyCopied ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
            </div>

            <OnboardingSummary
              organizationId={result.organization_id}
              apiKey={result.api_key}
            />

            <DialogFooter>
              <Button variant="outline" onClick={handleDownload}>
                <Download className="h-3.5 w-3.5 mr-1.5" />
                Download Onboarding Sheet
              </Button>
              <Button onClick={() => handleClose(false)}>Done</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
