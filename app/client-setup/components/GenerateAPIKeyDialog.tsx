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
  adminClient,
  type DataSourceResponse,
  type GenerateAPIKeyResponse,
} from '@/lib/api/adminClient'
import { OnboardingSummary, API_ENDPOINT, buildOnboardingSections } from './OnboardingSummary'

const AVAILABLE_SCOPES = [
  { value: 'meter_data', label: 'Meter Data' },
  { value: 'billing_reads', label: 'Billing Reads' },
  { value: 'fx_rates', label: 'FX Rates' },
  { value: 'reference_prices', label: 'Reference Prices (MRP)' },
  { value: 'invoice_export', label: 'Invoice Export' },
] as const

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
  const [keyType, setKeyType] = useState<'source' | 'org'>('source')
  const [dataSourceId, setDataSourceId] = useState<string>('')
  const [selectedScopes, setSelectedScopes] = useState<string[]>([])
  const [label, setLabel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<GenerateAPIKeyResponse | null>(null)
  const [keyCopied, setKeyCopied] = useState(false)

  function reset() {
    setKeyType('source')
    setDataSourceId('')
    setSelectedScopes([])
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

  function toggleScope(scope: string) {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    )
  }

  const canSubmit = keyType === 'org' || dataSourceId

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)

    try {
      const res = await adminClient.generateAPIKey(organizationId, {
        data_source_id: keyType === 'source' ? Number(dataSourceId) : null,
        label: label.trim() || undefined,
        scopes: keyType === 'org' && selectedScopes.length > 0 ? selectedScopes : null,
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
    const content = buildOnboardingSections({
      endpoint: API_ENDPOINT,
      apiKey: result.api_key,
      organizationId: result.organization_id,
      scopes: result.scopes,
      dataSourceId: result.data_source_id,
    })
    const blob = new Blob([content], { type: 'text/plain' })
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
            {/* Key type selector */}
            <div className="space-y-2">
              <Label>Key Type</Label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setKeyType('source')}
                  className={`px-3 py-1.5 text-sm rounded-md border ${
                    keyType === 'source'
                      ? 'border-slate-900 bg-slate-900 text-white'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  Data Source
                </button>
                <button
                  type="button"
                  onClick={() => setKeyType('org')}
                  className={`px-3 py-1.5 text-sm rounded-md border ${
                    keyType === 'org'
                      ? 'border-slate-900 bg-slate-900 text-white'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  Organization-wide
                </button>
              </div>
            </div>

            {keyType === 'source' ? (
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
            ) : (
              <div className="space-y-2">
                <Label>Scopes <span className="text-slate-400 font-normal">(optional — leave unchecked for all)</span></Label>
                <div className="flex flex-wrap gap-2">
                  {AVAILABLE_SCOPES.map((scope) => (
                    <label
                      key={scope.value}
                      className="flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-sm cursor-pointer hover:bg-slate-50"
                    >
                      <input
                        type="checkbox"
                        checked={selectedScopes.includes(scope.value)}
                        onChange={() => toggleScope(scope.value)}
                        className="rounded border-slate-300"
                      />
                      {scope.label}
                    </label>
                  ))}
                </div>
                <p className="text-xs text-slate-500">
                  When no scopes are selected, the key has access to all data types.
                </p>
              </div>
            )}

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
              <Button type="submit" disabled={submitting || !canSubmit}>
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
              scopes={result.scopes}
              dataSourceId={result.data_source_id}
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
