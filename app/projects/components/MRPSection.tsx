'use client'

import { useState, useMemo, Fragment } from 'react'
import { Loader2, Copy, Upload, Link2, CheckCircle2, XCircle, Ban, AlertTriangle, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, CardTitle, CardContent } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'
import { Button } from '@/app/components/ui/button'
import { Input } from '@/app/components/ui/input'
import { Label } from '@/app/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/app/components/ui/dialog'
import { IS_DEMO } from '@/lib/demoMode'
import type { MRPObservation, SubmissionTokenItem } from '@/lib/api/adminClient'
import { adminClient } from '@/lib/api/adminClient'
import { CollapsibleSection } from './CollapsibleSection'
import { EditableCell } from './EditableCell'
import { formatMonth } from '@/app/projects/utils/formatters'

type R = Record<string, unknown>

/** Format a billing_month date; delegates to shared formatMonth with '' default. */
function formatBillingMonth(v: unknown): string {
  if (v == null) return ''
  return formatMonth(String(v)).replace('—', '')
}

// ---------------------------------------------------------------------------
// MRPSection — parameters + observations
// ---------------------------------------------------------------------------

function mrpFormatPeriod(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

function mrpFormatNumber(n: number | null | undefined): string {
  if (n == null) return '-'
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function mrpFormatMRP(n: number | null | undefined): string {
  if (n == null) return '-'
  return n.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 })
}

function mrpStatusBadge(s: string): 'success' | 'warning' | 'destructive' {
  if (s === 'jointly_verified') return 'success'
  if (s === 'pending' || s === 'estimated') return 'warning'
  return 'destructive'
}

function mrpStatusLabel(s: string): string {
  if (s === 'jointly_verified') return 'Verified'
  if (s === 'pending') return 'Pending'
  if (s === 'disputed') return 'Disputed'
  if (s === 'estimated') return 'Estimated'
  return s
}

/** Token dialog state grouped into a single object. */
interface TokenDialogState {
  show: boolean
  year: number
  maxUses: number
  result: { url: string; tokenId: number } | null
  loading: boolean
}

export function MRPSection({
  projectId,
  orgId,
  codDate,
  firstTariff,
  firstLp,
  baselineMrp,
  initialMonthly,
  initialAnnual,
  initialTokens,
  onSaved,
  editMode,
}: {
  projectId: number
  orgId: number
  codDate?: string | null
  firstTariff: R | undefined
  firstLp: R
  baselineMrp: R[]
  initialMonthly: MRPObservation[]
  initialAnnual: MRPObservation[]
  initialTokens: SubmissionTokenItem[]
  onSaved?: () => void
  editMode?: boolean
}) {
  const pid = projectId
  const monthlyObs = initialMonthly
  const annualObs = initialAnnual
  const existingTokens = initialTokens

  const [tokenState, setTokenState] = useState<TokenDialogState>({
    show: false, year: 1, maxUses: 12, result: null, loading: false,
  })
  const [showUploadDialog, setShowUploadDialog] = useState(false)

  const [uploadMonth, setUploadMonth] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadLoading, setUploadLoading] = useState(false)


  // Dispute dialog state
  const [showDisputeDialog, setShowDisputeDialog] = useState(false)
  const [disputeObsId, setDisputeObsId] = useState<number | null>(null)
  const [disputeNotes, setDisputeNotes] = useState('')
  const [disputeLoading, setDisputeLoading] = useState(false)

  // Manual entry dialog state (for disputed observation correction)
  const [showManualEntryDialog, setShowManualEntryDialog] = useState(false)
  const [manualEntryPeriod, setManualEntryPeriod] = useState('')
  const [manualEntryMrp, setManualEntryMrp] = useState('')
  const [manualEntryLoading, setManualEntryLoading] = useState(false)
  const [manualEntryIsBaseline, setManualEntryIsBaseline] = useState(false)

  // Baseline MRP: derive sorted observations, component keys, and weighted average
  const baselineData = useMemo(() => {
    if (baselineMrp.length === 0) return null

    const sorted = [...baselineMrp].sort(
      (a, b) => new Date(String(b.period_start)).getTime() - new Date(String(a.period_start)).getTime()
    )

    // Check if data is pre-COD (operating_year=0) or fallback (most recent months)
    const isPreCod = sorted.every(obs => (obs.operating_year as number | undefined) === 0)

    const componentKeysSet = new Set<string>()
    for (const obs of sorted) {
      const tc = (obs.source_metadata as R | undefined)?.tariff_components as R | undefined
      if (tc) Object.keys(tc).forEach(k => componentKeysSet.add(k))
    }
    const componentKeys = [...componentKeysSet].sort()

    // Compute weighted-average MRP across baseline months
    let totalCharges = 0
    let totalKwh = 0
    let simpleSum = 0
    let simpleCount = 0
    for (const obs of sorted) {
      const charges = obs.total_variable_charges as number | null
      const kwh = obs.total_kwh_invoiced as number | null
      const mrp = obs.calculated_mrp_per_kwh as number | null
      if (charges != null && kwh != null && kwh > 0) {
        totalCharges += charges
        totalKwh += kwh
      }
      if (mrp != null) {
        simpleSum += mrp
        simpleCount++
      }
    }
    // Prefer weighted average; fall back to simple average
    const averageMrp = totalKwh > 0 ? totalCharges / totalKwh : simpleCount > 0 ? simpleSum / simpleCount : null
    const monthCount = sorted.length

    return { observations: sorted, componentKeys, averageMrp, monthCount, isPreCod }
  }, [baselineMrp])

  // Sort monthly observations (memoized, not inline in JSX)
  const sortedMonthlyObs = useMemo(
    () => [...monthlyObs].sort((a, b) => new Date(b.period_start).getTime() - new Date(a.period_start).getTime()),
    [monthlyObs],
  )

  async function handleGenerateToken() {
    setTokenState(s => ({ ...s, loading: true, result: null }))
    try {
      const res = await adminClient.generateMRPToken(orgId, {
        project_id: pid,
        operating_year: tokenState.year,
        max_uses: tokenState.maxUses,
      })
      setTokenState(s => ({ ...s, result: { url: res.submission_url, tokenId: res.token_id }, loading: false }))
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to generate token')
      setTokenState(s => ({ ...s, loading: false }))
    }
  }

  async function handleUpload() {
    if (!uploadFile || !uploadMonth) return
    setUploadLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('billing_month', uploadMonth)
      const res = await adminClient.uploadMRPInvoice(pid, orgId, formData)
      const storedLabel = res.billing_month_stored ? formatBillingMonth(res.billing_month_stored) : ''
      toast.success(`MRP extracted: ${mrpFormatMRP(res.mrp_per_kwh)} /kWh (${res.extraction_confidence} confidence)${storedLabel ? ` — ${storedLabel}` : ''}`)
      if (res.period_mismatch) {
        const extracted = formatBillingMonth(res.period_mismatch.extracted)
        const userProvided = formatBillingMonth(res.period_mismatch.user_provided)
        toast.warning(`Billing period corrected: invoice shows ${extracted}, you entered ${userProvided}.`)
      }
      setShowUploadDialog(false)
      setUploadFile(null)
      setUploadMonth('')
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploadLoading(false)
    }
  }

  async function handleRevokeToken(tokenId: number) {
    try {
      await adminClient.revokeToken(orgId, tokenId)
      toast.success('Token revoked')
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to revoke token')
    }
  }

  async function handleVerify(observationId: number) {
    try {
      const res = await adminClient.verifyObservation(pid, orgId, observationId, {
        verification_status: 'jointly_verified',
      })
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Verification failed')
    }
  }

  function openDisputeDialog(observationId: number) {
    setDisputeObsId(observationId)
    setDisputeNotes('')
    setShowDisputeDialog(true)
  }

  async function handleDisputeSubmit() {
    if (!disputeObsId || !disputeNotes.trim()) return
    setDisputeLoading(true)
    try {
      const res = await adminClient.verifyObservation(pid, orgId, disputeObsId, {
        verification_status: 'disputed',
        notes: disputeNotes.trim(),
      })
      toast.success(res.message)
      setShowDisputeDialog(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Dispute failed')
    } finally {
      setDisputeLoading(false)
    }
  }

  async function handleDeleteObservation(observationId: number) {
    try {
      const res = await adminClient.deleteMRPObservation(pid, orgId, observationId)
      toast.success(res.message)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  function openManualEntryFor(obs: { period_start: string }, isBaseline = false) {
    // Pre-fill the manual entry dialog with the observation's period
    const d = new Date(obs.period_start)
    setManualEntryPeriod(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`)
    setManualEntryMrp('')
    setManualEntryIsBaseline(isBaseline)
    setShowManualEntryDialog(true)
  }

  async function handleManualEntrySubmit() {
    if (!manualEntryPeriod || !manualEntryMrp) return
    setManualEntryLoading(true)
    try {
      const res = await adminClient.submitManualMRPRates(pid, orgId, {
        entries: [{ billing_month: manualEntryPeriod, mrp_per_kwh: parseFloat(manualEntryMrp) }],
        is_baseline: manualEntryIsBaseline,
      })
      toast.success(res.message)
      setShowManualEntryDialog(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Manual entry failed')
    } finally {
      setManualEntryLoading(false)
    }
  }

  const mrpActions = (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => setTokenState(s => ({ ...s, show: true, result: null }))}>
        <Link2 className="h-4 w-4" /> Generate Token
      </Button>
      <Button variant="outline" size="sm" onClick={() => setShowUploadDialog(true)}>
        <Upload className="h-4 w-4" /> Upload Invoice
      </Button>
    </div>
  )

  return (<>
    <CollapsibleSection title="Market Reference Price" actions={mrpActions}>
    <div className="space-y-4">
      {/* MRP Definition */}
      {firstTariff && (
        <div className="space-y-3">
          {/* Clause Text */}
          <div className="py-1">
            <dt className="text-xs text-slate-400 mb-1">Contractual Definition</dt>
            <dd className="text-sm text-slate-900">
              {editMode ? (
                <EditableCell
                  value={firstLp.mrp_clause_text as string | null ?? null}
                  fieldKey="lp_mrp_clause_text"
                  entity="tariffs"
                  entityId={firstTariff.id as number}
                  projectId={pid}
                  type="text"
                  editMode={true}
                  onSaved={onSaved}
                />
              ) : (
                <span className="whitespace-pre-line">{firstLp.mrp_clause_text != null ? String(firstLp.mrp_clause_text) : '—'}</span>
              )}
            </dd>
          </div>

          {/* MRP Parameters */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-xs text-slate-400">Calculation Method</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <EditableCell
                    value={firstLp.mrp_method as string | null ?? null}
                    fieldKey="lp_mrp_method"
                    entity="tariffs"
                    entityId={firstTariff.id as number}
                    projectId={pid}
                    type="select"
                    options={[
                      { value: 'utility_variable_charges_tou', label: 'Variable Charges (ToU)' },
                      { value: 'utility_total_charges', label: 'Total Charges (excl. tax)' },
                    ]}
                    editMode={true}
                    onSaved={onSaved}
                  />
                ) : (
                  firstLp.mrp_method === 'utility_variable_charges_tou' ? 'Variable Charges (ToU)'
                  : firstLp.mrp_method === 'utility_total_charges' ? 'Total Charges (excl. tax)'
                  : firstLp.mrp_method != null ? String(firstLp.mrp_method) : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Operating Window</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.mrp_time_window_start as string | null ?? null}
                      fieldKey="lp_mrp_time_window_start"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="text"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-slate-400">–</span>
                    <EditableCell
                      value={firstLp.mrp_time_window_end as string | null ?? null}
                      fieldKey="lp_mrp_time_window_end"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="text"
                      editMode={true}
                      onSaved={onSaved}
                    />
                  </span>
                ) : (
                  firstLp.mrp_time_window_start != null && firstLp.mrp_time_window_end != null
                    ? `${String(firstLp.mrp_time_window_start)} – ${String(firstLp.mrp_time_window_end)}`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Calculation Due</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.mrp_calculation_due_days as number | null ?? null}
                      fieldKey="lp_mrp_calculation_due_days"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="number"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-xs text-slate-400">days after month-end</span>
                  </span>
                ) : (
                  firstLp.mrp_calculation_due_days != null
                    ? `${String(firstLp.mrp_calculation_due_days)} days after month-end`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Verification Deadline</dt>
              <dd className="text-slate-800 font-medium mt-0.5">
                {editMode ? (
                  <span className="flex items-center gap-1">
                    <EditableCell
                      value={firstLp.mrp_verification_deadline_days as number | null ?? null}
                      fieldKey="lp_mrp_verification_deadline_days"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="number"
                      editMode={true}
                      onSaved={onSaved}
                    />
                    <span className="text-xs text-slate-400">days</span>
                  </span>
                ) : (
                  firstLp.mrp_verification_deadline_days != null
                    ? `${String(firstLp.mrp_verification_deadline_days)} days`
                    : '—'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">Exclusions</dt>
              <dd className="mt-0.5 flex flex-wrap gap-1">
                {editMode ? (
                  <>
                    <EditableCell
                      value={firstLp.mrp_exclude_vat as boolean | null ?? false}
                      fieldKey="lp_mrp_exclude_vat"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'VAT ✓' : 'VAT'}
                    />
                    <EditableCell
                      value={firstLp.mrp_exclude_demand_charges as boolean | null ?? false}
                      fieldKey="lp_mrp_exclude_demand_charges"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'Demand ✓' : 'Demand'}
                    />
                    <EditableCell
                      value={firstLp.mrp_exclude_savings_charges as boolean | null ?? false}
                      fieldKey="lp_mrp_exclude_savings_charges"
                      entity="tariffs"
                      entityId={firstTariff.id as number}
                      projectId={pid}
                      type="boolean"
                      editMode={true}
                      onSaved={onSaved}
                      formatDisplay={(v) => v ? 'Savings ✓' : 'Savings'}
                    />
                  </>
                ) : (
                  <>
                    {Boolean(firstLp.mrp_exclude_vat) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">VAT</span>}
                    {Boolean(firstLp.mrp_exclude_demand_charges) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">Demand</span>}
                    {Boolean(firstLp.mrp_exclude_savings_charges) && <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">Savings</span>}
                    {!firstLp.mrp_exclude_vat && !firstLp.mrp_exclude_demand_charges && !firstLp.mrp_exclude_savings_charges && (
                      <span className="text-slate-500">None</span>
                    )}
                  </>
                )}
              </dd>
            </div>
          </div>
        </div>
      )}

      {/* Current MRP — weighted average of baseline or most recent months */}
      {baselineData && baselineData.averageMrp != null && (
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-600">Current Market Reference Price</span>
            <span className="text-sm font-bold font-mono text-slate-900 tabular-nums">{mrpFormatMRP(baselineData.averageMrp)} /kWh</span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Weighted average of {baselineData.monthCount} {baselineData.isPreCod ? 'pre-COD' : 'most recent'} month{baselineData.monthCount !== 1 ? 's' : ''} (total variable charges &divide; total kWh invoiced).
          </p>
        </div>
      )}

      {/* Post-COD MRP Observations */}
      <CollapsibleSection title="Monthly MRP Observations (Post-COD)" defaultOpen={false}>
          {(() => {
            // Determine which columns have data across all observations
            const allObs = [...monthlyObs, ...annualObs]
            const hasCharges = allObs.some(o => o.total_variable_charges != null)
            const hasKwh = allObs.some(o => o.total_kwh_invoiced != null)
            const hasActions = monthlyObs.some(o => o.verification_status === 'pending' || o.verification_status === 'disputed')
            const hasSource = monthlyObs.some(o => o.source_metadata?.entry_method != null)
            const visibleColCount = 2 + (hasCharges ? 1 : 0) + (hasKwh ? 1 : 0) + (hasActions ? 1 : 0) + (hasSource ? 1 : 0)

            return (
          <div className="space-y-4">
            {/* Annual MRP Cards */}
            {annualObs.map(obs => {
              const meta = obs.source_metadata?.aggregation as Record<string, unknown> | undefined
              const cardFields: { label: string; value: string }[] = [
                { label: 'MRP/kWh', value: mrpFormatMRP(obs.calculated_mrp_per_kwh) },
              ]
              if (hasCharges) cardFields.push({ label: 'Total Charges', value: mrpFormatNumber(obs.total_variable_charges) })
              if (hasKwh) cardFields.push({ label: 'Total kWh', value: mrpFormatNumber(obs.total_kwh_invoiced) })
              cardFields.push({ label: 'Months Included', value: meta?.months_included != null ? String(meta.months_included) : '-' })
              return (
                <Card key={obs.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-semibold">Annual MRP &mdash; Operating Year {obs.operating_year}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className={`grid gap-4 text-sm`} style={{ gridTemplateColumns: `repeat(${cardFields.length}, minmax(0, 1fr))` }}>
                      {cardFields.map(f => (
                        <div key={f.label}><span className="text-slate-500">{f.label}</span><p className={`font-mono${f.label === 'MRP/kWh' ? ' font-semibold' : ''}`}>{f.value}</p></div>
                      ))}
                    </div>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge variant={mrpStatusBadge(obs.verification_status)}>{mrpStatusLabel(obs.verification_status)}</Badge>
                      {obs.created_at && <span className="text-xs text-slate-400">Aggregated {new Date(obs.created_at).toLocaleDateString()}</span>}
                    </div>
                  </CardContent>
                </Card>
              )
            })}

            {/* Monthly Observations Table */}
            {sortedMonthlyObs.length === 0 ? (
              <div className="text-center py-8 text-sm text-slate-400">
                No monthly MRP observations yet. Upload an invoice or generate a collection token to get started.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium">Period</th>
                      <th className="text-right px-4 py-2.5 font-medium">MRP/kWh</th>
                      {hasCharges && <th className="text-right px-4 py-2.5 font-medium">Variable Charges</th>}
                      {hasKwh && <th className="text-right px-4 py-2.5 font-medium">kWh Invoiced</th>}
                      {hasSource && <th className="text-right px-4 py-2.5 font-medium">Source</th>}
                      {hasActions && <th className="text-right px-4 py-2.5 font-medium">Actions</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {sortedMonthlyObs.map(obs => {
                      const verificationLog = (obs.source_metadata?.verification_log as Array<{ status: string; notes: string; timestamp: string }>) ?? []
                      const lastDispute = verificationLog.filter(l => l.status === 'disputed').at(-1)
                      const isDisputed = obs.verification_status === 'disputed'
                      const entryMethod = obs.source_metadata?.entry_method as string | undefined
                      return (
                        <Fragment key={obs.id}>
                          <tr className={`hover:bg-slate-50${isDisputed ? ' bg-red-50/50' : ''}`}>
                            <td className="px-4 py-2.5">{mrpFormatPeriod(obs.period_start)}</td>
                            <td
                              className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}${editMode && !isDisputed ? ' cursor-pointer rounded bg-amber-50 hover:bg-amber-100 transition-colors' : ''}`}
                              onClick={editMode && !isDisputed ? () => openManualEntryFor(obs) : undefined}
                              title={editMode && !isDisputed ? 'Click to edit' : undefined}
                            >{mrpFormatMRP(obs.calculated_mrp_per_kwh)}</td>
                            {hasCharges && <td className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}`}>{mrpFormatNumber(obs.total_variable_charges)}</td>}
                            {hasKwh && <td className={`px-4 py-2.5 text-right font-mono${isDisputed ? ' line-through text-slate-400' : ''}`}>{mrpFormatNumber(obs.total_kwh_invoiced)}</td>}
                            {hasSource && (
                              <td className="px-4 py-2.5 text-right">
                                <span className="text-xs text-slate-400">{entryMethod === 'excel_import' ? 'Excel' : entryMethod === 'manual' ? 'Manual' : entryMethod === 'invoice_extraction' ? 'Invoice' : entryMethod ?? '-'}</span>
                              </td>
                            )}
                            {hasActions && (
                            <td className="px-4 py-2.5 text-right">
                              {obs.verification_status === 'pending' && (
                                <div className="flex items-center justify-end gap-1">
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-green-700 hover:text-green-800" onClick={() => handleVerify(obs.id)}>
                                    <CheckCircle2 className="h-3.5 w-3.5" /> Verify
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => openDisputeDialog(obs.id)}>
                                    <XCircle className="h-3.5 w-3.5" /> Dispute
                                  </Button>
                                </div>
                              )}
                              {isDisputed && (
                                <div className="flex items-center justify-end gap-1">
                                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => {
                                    const token = existingTokens.find(t => t.submission_token_status === 'active')
                                    if (token?.submission_url) {
                                      navigator.clipboard.writeText(token.submission_url)
                                      toast.success('Collection URL copied — send to counterparty to re-upload')
                                    } else {
                                      toast.info('No active collection token. Generate one first.')
                                      setTokenState(s => ({ ...s, show: true }))
                                    }
                                  }}>
                                    <RotateCcw className="h-3.5 w-3.5" /> Re-upload
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openManualEntryFor(obs)}>
                                    <Pencil className="h-3.5 w-3.5" /> Manual
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => handleDeleteObservation(obs.id)}>
                                    <Trash2 className="h-3.5 w-3.5" /> Delete
                                  </Button>
                                </div>
                              )}
                            </td>
                            )}
                          </tr>
                          {isDisputed && lastDispute && (
                            <tr className="bg-red-50/30">
                              <td colSpan={visibleColCount} className="px-4 py-2">
                                <div className="flex items-start gap-2 text-xs">
                                  <AlertTriangle className="h-3.5 w-3.5 text-red-500 mt-0.5 shrink-0" />
                                  <div>
                                    <span className="font-medium text-red-700">Disputed</span>
                                    <span className="text-slate-600 ml-1">— {lastDispute.notes}</span>
                                    <span className="text-slate-400 ml-2">{new Date(lastDispute.timestamp).toLocaleDateString()}</span>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
            )
          })()}
      </CollapsibleSection>

      {/* Baseline MRP (Pre-COD) — only show when actual pre-COD observations exist */}
      {baselineData && baselineData.isPreCod && (
        <CollapsibleSection title="Baseline Market Reference Price (Pre-COD)" defaultOpen={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">Period</th>
                  <th className="text-right px-4 py-2.5 font-medium">MRP/kWh</th>
                  {baselineData.componentKeys.map(key => (
                    <th key={key} className="text-right px-4 py-2.5 font-medium capitalize">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {baselineData.observations.map(obs => (
                  <tr key={obs.id as number} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5">{mrpFormatPeriod(String(obs.period_start))}</td>
                    <td
                      className={`px-4 py-2.5 text-right font-mono font-medium${editMode ? ' cursor-pointer rounded bg-amber-50 hover:bg-amber-100 transition-colors' : ''}`}
                      onClick={editMode ? () => openManualEntryFor({ period_start: String(obs.period_start) }, true) : undefined}
                      title={editMode ? 'Click to edit' : undefined}
                    >{mrpFormatMRP(obs.calculated_mrp_per_kwh as number | null)}</td>
                    {baselineData.componentKeys.map(key => {
                      const tc = (obs.source_metadata as R | undefined)?.tariff_components as Record<string, number> | undefined
                      return (
                        <td key={key} className="px-4 py-2.5 text-right font-mono tabular-nums">
                          {tc?.[key] != null ? mrpFormatMRP(tc[key]) : '-'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

    </div>
    </CollapsibleSection>

      {/* Generate Token Dialog — outside CollapsibleSection so it renders even when collapsed */}
      <Dialog open={tokenState.show} onOpenChange={(v) => setTokenState(s => ({ ...s, show: v }))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>MRP Collection Tokens</DialogTitle>
            <DialogDescription>Create a reusable link for the counterparty to upload utility invoices.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="mrpTokenYear">Operating Year</Label>
              <Input id="mrpTokenYear" type="number" min={1} value={tokenState.year} onChange={e => setTokenState(s => ({ ...s, year: Number(e.target.value) }))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mrpTokenMaxUses">Max Uploads</Label>
              <Input id="mrpTokenMaxUses" type="number" min={1} max={24} value={tokenState.maxUses} onChange={e => setTokenState(s => ({ ...s, maxUses: Number(e.target.value) }))} />
            </div>
            {tokenState.result && (
              <div className="rounded-md border border-green-200 bg-green-50 p-3 space-y-2">
                <p className="text-xs text-green-700 font-medium">Token generated successfully</p>
                <div className="flex items-center gap-2">
                  <Input readOnly value={tokenState.result.url} className="text-xs font-mono" />
                  <Button variant="outline" size="icon" className="shrink-0" onClick={() => { navigator.clipboard.writeText(tokenState.result!.url); toast.success('URL copied to clipboard') }}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
            <Button className="w-full" disabled={tokenState.loading} onClick={handleGenerateToken}>
              {tokenState.loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {tokenState.result ? 'Regenerate' : 'Generate Token'}
            </Button>

            {/* Existing Tokens */}
            {existingTokens.length > 0 && (
              <>
                <div className="border-t border-slate-200 pt-4">
                  <div className="text-xs font-medium text-slate-500 uppercase mb-2">Existing Tokens</div>
                  <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {existingTokens.map((tk) => {
                      const isActive = tk.submission_token_status === 'active'
                      const isExpired = tk.submission_token_status === 'expired' || (tk.expires_at && new Date(tk.expires_at) < new Date())
                      const isUsed = tk.submission_token_status === 'used'
                      const isRevoked = tk.submission_token_status === 'revoked'
                      const statusVariant: 'success' | 'warning' | 'destructive' = isActive ? 'success' : isUsed ? 'warning' : 'destructive'
                      const statusLabel = isActive ? 'Active' : isUsed ? 'Used' : isRevoked ? 'Revoked' : isExpired ? 'Expired' : tk.submission_token_status
                      const tokenStr = tk.submission_url ? (() => { try { return new URL(tk.submission_url).pathname.split('/').pop() ?? '' } catch { return '' } })() : ''
                      return (
                        <div key={tk.id} className="px-3 py-2.5 space-y-1.5">
                          <div className="flex items-center gap-2">
                            <Badge variant={statusVariant}>{statusLabel}</Badge>
                            <span className="text-xs text-slate-500 tabular-nums">{tk.use_count}/{tk.max_uses} uses</span>
                            {tk.expires_at && (
                              <span className="text-xs text-slate-400">
                                Expires {new Date(tk.expires_at).toLocaleDateString()}
                              </span>
                            )}
                            {isActive && !IS_DEMO && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="ml-auto h-6 text-xs text-red-600 hover:text-red-700 px-2"
                                onClick={() => handleRevokeToken(tk.id)}
                              >
                                <Ban className="h-3 w-3" /> Revoke
                              </Button>
                            )}
                          </div>
                          {tokenStr && (
                            <div className="flex items-center gap-1.5">
                              <code className="text-xs font-mono text-slate-500 truncate max-w-[180px]">{tokenStr}</code>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-xs px-1.5"
                                onClick={() => {
                                  navigator.clipboard.writeText(tokenStr)
                                  toast.success('Token copied')
                                }}
                              >
                                <Copy className="h-3 w-3" /> Token
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-xs px-1.5"
                                onClick={() => {
                                  navigator.clipboard.writeText(tk.submission_url!)
                                  toast.success('URL copied')
                                }}
                              >
                                <Link2 className="h-3 w-3" /> URL
                              </Button>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Upload Invoice Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Utility Invoice</DialogTitle>
            <DialogDescription>Upload a PDF or image of a utility invoice for MRP extraction via OCR.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="mrpBillingMonth">Billing Month</Label>
              <Input id="mrpBillingMonth" type="month" value={uploadMonth} onChange={e => setUploadMonth(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mrpInvoiceFile">Invoice File</Label>
              <Input id="mrpInvoiceFile" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={e => setUploadFile(e.target.files?.[0] ?? null)} />
            </div>
            <Button className="w-full" disabled={uploadLoading || !uploadFile || !uploadMonth} onClick={handleUpload}>
              {uploadLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {uploadLoading ? 'Extracting...' : 'Upload & Extract'}
            </Button>
            {uploadLoading && <p className="text-xs text-slate-400 text-center">OCR extraction may take 20-30 seconds...</p>}
          </div>
        </DialogContent>
      </Dialog>

      {/* Dispute Dialog */}
      <Dialog open={showDisputeDialog} onOpenChange={setShowDisputeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dispute MRP Observation</DialogTitle>
            <DialogDescription>Provide a reason for disputing this observation. The disputed value will be excluded from annual MRP aggregation.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="disputeNotes">Reason for Dispute *</Label>
              <textarea
                id="disputeNotes"
                className="flex min-h-[80px] w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2"
                placeholder="e.g., MRP value extracted incorrectly — 209.5 vs expected ~2.0"
                value={disputeNotes}
                onChange={e => setDisputeNotes(e.target.value)}
              />
            </div>
            <Button
              className="w-full"
              variant="destructive"
              disabled={disputeLoading || !disputeNotes.trim()}
              onClick={handleDisputeSubmit}
            >
              {disputeLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Submit Dispute
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Manual Entry Dialog (for correcting disputed observation) */}
      <Dialog open={showManualEntryDialog} onOpenChange={setShowManualEntryDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enter Corrected MRP</DialogTitle>
            <DialogDescription>Manually enter the corrected MRP rate for this period. This will replace the disputed observation with an estimated value.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="manualEntryPeriod">Billing Month</Label>
              <Input id="manualEntryPeriod" type="month" value={manualEntryPeriod} onChange={e => setManualEntryPeriod(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manualEntryMrp">MRP per kWh</Label>
              <Input id="manualEntryMrp" type="number" step="0.0001" min="0" placeholder="e.g., 2.0350" value={manualEntryMrp} onChange={e => setManualEntryMrp(e.target.value)} />
            </div>
            <Button
              className="w-full"
              disabled={manualEntryLoading || !manualEntryPeriod || !manualEntryMrp}
              onClick={handleManualEntrySubmit}
            >
              {manualEntryLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Corrected Value
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
