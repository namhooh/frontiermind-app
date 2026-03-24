'use client'

import { useState, useEffect, useCallback } from 'react'
import { X, Check, XCircle, Clock, AlertTriangle, Loader2 } from 'lucide-react'
import { Badge } from '@/app/components/ui/badge'
import { Button } from '@/app/components/ui/button'
import { adminClient, type ChangeRequest } from '@/lib/api/adminClient'
import { toast } from 'sonner'

interface PendingChangesPanelProps {
  projectId?: number
  open: boolean
  onClose: () => void
  userRole: string
  userId: string
  onChanged?: () => void
}

const STATUS_BADGE: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  pending: { variant: 'default', label: 'Pending' },
  conflicted: { variant: 'destructive', label: 'Conflicted' },
  approved: { variant: 'secondary', label: 'Approved' },
  rejected: { variant: 'outline', label: 'Rejected' },
  cancelled: { variant: 'outline', label: 'Cancelled' },
  superseded: { variant: 'outline', label: 'Superseded' },
}

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'number') return val.toLocaleString('en-US', { maximumFractionDigits: 6 })
  if (typeof val === 'boolean') return val ? 'Yes' : 'No'
  return String(val)
}

/** Pretty-print a JSONB payload for full-row proposals (field_name = '*'). */
function formatPayload(val: unknown): { key: string; value: string }[] {
  if (val === null || val === undefined) return []
  if (typeof val === 'object' && !Array.isArray(val)) {
    return Object.entries(val as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => ({
        key: k.replace(/_/g, ' '),
        value: typeof v === 'object' ? JSON.stringify(v) : String(v),
      }))
  }
  return [{ key: 'value', value: formatValue(val) }]
}

export function PendingChangesPanel({ projectId, open, onClose, userRole, userId, onChanged }: PendingChangesPanelProps) {
  const [requests, setRequests] = useState<ChangeRequest[]>([])
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [filter, setFilter] = useState<'pending' | 'all'>('pending')

  const canApprove = userRole === 'admin' || userRole === 'approver'

  const loadRequests = useCallback(async () => {
    setLoading(true)
    try {
      const data = await adminClient.listChangeRequests(projectId, filter === 'pending' ? 'pending' : undefined)
      setRequests(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [projectId, filter])

  useEffect(() => {
    if (open) loadRequests()
  }, [open, loadRequests])

  const handleApprove = async (id: number) => {
    setActionLoading(id)
    try {
      const result = await adminClient.approveChangeRequest(id) as Record<string, unknown>
      if (result.success) {
        if (result.status === 'step_approved') {
          toast.success(`Step ${(result.current_step as number) - 1} approved. Awaiting step ${result.current_step}: ${result.step_name || 'next review'}`)
        } else {
          toast.success('Change approved and applied')
        }
        await loadRequests()
        onChanged?.()
      } else {
        toast.error(result.status === 'conflicted' ? 'Data changed since submission — please re-submit' : 'Failed to approve')
        await loadRequests()
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to approve')
    } finally {
      setActionLoading(null)
    }
  }

  const handleReject = async (id: number) => {
    setActionLoading(id)
    try {
      await adminClient.rejectChangeRequest(id)
      toast('Change rejected')
      await loadRequests()
      onChanged?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to reject')
    } finally {
      setActionLoading(null)
    }
  }

  const handleCancel = async (id: number) => {
    setActionLoading(id)
    try {
      await adminClient.cancelChangeRequest(id)
      toast('Change request cancelled')
      await loadRequests()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to cancel')
    } finally {
      setActionLoading(null)
    }
  }

  const pendingRequests = requests.filter(r => r.change_request_status === 'pending')

  const handleApproveAll = async () => {
    if (!pendingRequests.length) return
    // Filter out own requests (four-eyes)
    const approvable = pendingRequests.filter(r => r.requested_by !== userId)
    if (!approvable.length) {
      toast.error('Cannot approve your own requests (four-eyes principle)')
      return
    }
    setBulkLoading(true)
    let approved = 0
    let failed = 0
    for (const cr of approvable) {
      try {
        const result = await adminClient.approveChangeRequest(cr.id)
        if (result.success) approved++
        else failed++
      } catch {
        failed++
      }
    }
    setBulkLoading(false)
    toast.success(`Approved ${approved} change${approved !== 1 ? 's' : ''}${failed ? `, ${failed} failed` : ''}`)
    await loadRequests()
    onChanged?.()
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-white shadow-xl border-l border-slate-200 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold text-slate-900">Pending Changes</h2>
          <div className="flex items-center gap-2">
            {canApprove && pendingRequests.length > 0 && (
              <button
                onClick={handleApproveAll}
                disabled={bulkLoading}
                className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1 hover:bg-green-100 disabled:opacity-50"
              >
                {bulkLoading ? 'Approving...' : `Approve All (${pendingRequests.length})`}
              </button>
            )}
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as 'pending' | 'all')}
              className="text-xs border border-slate-200 rounded px-2 py-1"
            >
              <option value="pending">Pending</option>
              <option value="all">All</option>
            </select>
            <button onClick={onClose} className="p-1 rounded hover:bg-slate-100">
              <X className="h-4 w-4 text-slate-500" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          )}

          {!loading && requests.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-8">No change requests found</p>
          )}

          {!loading && requests.map((cr) => {
            const statusInfo = STATUS_BADGE[cr.change_request_status] || STATUS_BADGE.pending
            const isOwn = cr.requested_by === userId
            const isPending = cr.change_request_status === 'pending'

            return (
              <div key={cr.id} className="rounded-lg border border-slate-200 p-3 space-y-2">
                {/* Header row */}
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">
                      {cr.display_label || cr.field_name}
                    </p>
                    <p className="text-xs text-slate-500">
                      {cr.field_name === '*'
                        ? `${cr.target_table} — new entry`
                        : `${cr.target_table}.${cr.field_name} (ID: ${cr.target_id})`}
                    </p>
                  </div>
                  <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                </div>

                {/* Multi-step progress */}
                {cr.total_steps > 1 && cr.approval_steps && (
                  <div className="flex items-center gap-1 text-xs overflow-x-auto pb-1">
                    {cr.approval_steps.map((step, i) => (
                      <div key={step.step_order} className="flex items-center gap-1 shrink-0">
                        {i > 0 && <span className="text-slate-300">&rarr;</span>}
                        <span className={
                          step.step_status === 'approved' ? 'text-green-600 font-medium' :
                          step.step_status === 'pending' ? 'text-amber-600 font-medium' :
                          step.step_status === 'rejected' ? 'text-red-600 font-medium' :
                          'text-slate-400'
                        }>
                          {step.step_status === 'approved' ? '\u2713' :
                           step.step_status === 'pending' ? '\u25CF' :
                           step.step_status === 'rejected' ? '\u2717' : '\u25CB'}
                          {' '}{step.step_name || `Step ${step.step_order}`}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Diff */}
                {cr.field_name === '*' ? (
                  /* Full-row proposal: show payload as key-value list */
                  <div className="text-xs space-y-1">
                    <span className="text-slate-400">Proposed entry</span>
                    <div className="bg-amber-50/50 rounded p-2 space-y-0.5">
                      {formatPayload(cr.new_value).map(({ key, value }) => (
                        <div key={key} className="flex justify-between gap-2">
                          <span className="text-slate-500 capitalize">{key}</span>
                          <span className="font-mono text-amber-700 font-medium text-right truncate max-w-[200px]">{value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-slate-400">Current</span>
                      <p className="font-mono text-slate-600">{formatValue(cr.old_value)}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">Proposed</span>
                      <p className="font-mono text-amber-700 font-medium">{formatValue(cr.new_value)}</p>
                    </div>
                  </div>
                )}

                {/* Meta */}
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(cr.requested_at).toLocaleDateString()}
                  </span>
                  <span>by {cr.requester_name || 'Unknown'}</span>
                </div>

                {/* Conflict warning */}
                {cr.change_request_status === 'conflicted' && (
                  <div className="flex items-center gap-1.5 text-xs text-red-600 bg-red-50 rounded p-2">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Data changed since submission. Please re-submit.
                  </div>
                )}

                {/* Review note */}
                {cr.review_note && (
                  <p className="text-xs text-slate-500 italic">Note: {cr.review_note}</p>
                )}

                {/* Actions */}
                {isPending && (
                  <div className="flex items-center gap-2 pt-1">
                    {canApprove && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleApprove(cr.id)}
                          disabled={actionLoading === cr.id}
                          className="text-xs h-7 text-green-700 border-green-200 hover:bg-green-50"
                        >
                          <Check className="h-3 w-3 mr-1" />
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleReject(cr.id)}
                          disabled={actionLoading === cr.id}
                          className="text-xs h-7 text-red-600 border-red-200 hover:bg-red-50"
                        >
                          <XCircle className="h-3 w-3 mr-1" />
                          Reject
                        </Button>
                      </>
                    )}
                    {isOwn && (
                      <button
                        onClick={() => handleCancel(cr.id)}
                        disabled={actionLoading === cr.id}
                        className="text-xs text-slate-500 hover:text-slate-700"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
