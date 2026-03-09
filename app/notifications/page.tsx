'use client'

/**
 * Notifications Page
 *
 * Standalone page for managing email notification schedules,
 * viewing email history, managing templates, and reviewing inbound messages and submissions.
 */

import { useState, useEffect, useMemo, useCallback, useRef, Fragment, Suspense } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  Bell,
  Mail,
  Clock,
  FileText,
  Inbox,
  ArrowLeft,
  Play,
  Pause,
  Send,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Plus,
  Pencil,
  Check,
  X,
  Download,
  Eye,
  ChevronDown,
  ChevronUp,
  Paperclip,
  Loader2,
  Filter,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/app/components/ui/button'
import { adminClient, type ProjectGroupedItem } from '@/lib/api/adminClient'
import {
  NotificationsClient,
  type EmailTemplate,
  type NotificationSchedule,
  type OutboundMessageEntry,
  type SubmissionResponse,
} from '@/lib/api/notificationsClient'
import {
  InboundClient,
  type InboundMessage,
  type InboundMessageStatus,
  type ApproveResponse,
} from '@/lib/api/inboundClient'
import { createClient } from '@/lib/supabase/client'
import { IS_DEMO } from '@/lib/demoMode'
import { ComposeEmailDialog } from './components/ComposeEmailDialog'
import { ScheduleFormDialog } from './components/ScheduleFormDialog'
import { TemplateEditorDialog } from './components/TemplateEditorDialog'
import { describeDueDateTiming, type DueDateRelativeConfig } from './components/DueDateTimingBuilder'

type TabId = 'inbox' | 'schedules' | 'email-history' | 'templates'
type InboxView = 'emails' | 'submissions'

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  delivered: { bg: 'bg-green-100', text: 'text-green-700' },
  sending: { bg: 'bg-blue-100', text: 'text-blue-700' },
  pending: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  bounced: { bg: 'bg-red-100', text: 'text-red-700' },
  failed: { bg: 'bg-red-100', text: 'text-red-700' },
  suppressed: { bg: 'bg-slate-100', text: 'text-slate-600' },
  // Inbound message statuses
  pending_review: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  approved: { bg: 'bg-green-100', text: 'text-green-700' },
  rejected: { bg: 'bg-red-100', text: 'text-red-700' },
  auto_processed: { bg: 'bg-blue-100', text: 'text-blue-700' },
  noise: { bg: 'bg-slate-100', text: 'text-slate-600' },
  received: { bg: 'bg-slate-100', text: 'text-slate-600' },
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || { bg: 'bg-slate-100', text: 'text-slate-600' }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
      {status}
    </span>
  )
}

export default function NotificationsPage() {
  return (
    <Suspense>
      <NotificationsPageContent />
    </Suspense>
  )
}

function NotificationsPageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const tab = searchParams.get('tab') as TabId | null
    return tab && ['inbox', 'schedules', 'email-history', 'templates'].includes(tab) ? tab : 'inbox'
  })
  const [schedules, setSchedules] = useState<NotificationSchedule[]>([])
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [emailLogs, setEmailLogs] = useState<OutboundMessageEntry[]>([])
  const [emailLogsTotal, setEmailLogsTotal] = useState(0)
  const [submissions, setSubmissions] = useState<SubmissionResponse[]>([])
  const [submissionsTotal, setSubmissionsTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 25

  // Project filter
  const [projects, setProjects] = useState<ProjectGroupedItem[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | undefined>(() => {
    const pid = searchParams.get('project')
    return pid ? Number(pid) : undefined
  })

  // Dialog state
  const [composeOpen, setComposeOpen] = useState(false)
  const [scheduleFormOpen, setScheduleFormOpen] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<NotificationSchedule | undefined>()
  const [templateEditorOpen, setTemplateEditorOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<EmailTemplate | undefined>()

  // Inbox state
  const [inboxView, setInboxView] = useState<InboxView>('emails')
  const [inboundMessages, setInboundMessages] = useState<InboundMessage[]>([])
  const [inboundTotal, setInboundTotal] = useState(0)
  const [inboundStatusFilter, setInboundStatusFilter] = useState<InboundMessageStatus | ''>('pending_review')
  const [expandedMessageId, setExpandedMessageId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [expandedSentId, setExpandedSentId] = useState<number | null>(null)
  const [approveResults, setApproveResults] = useState<Record<number, ApproveResponse>>({})
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectInput, setShowRejectInput] = useState<number | null>(null)
  const [approveProjectId, setApproveProjectId] = useState<number | undefined>()

  const supabase = useRef(createClient())
  const [organizationId, setOrganizationId] = useState<number | undefined>()

  useEffect(() => {
    async function loadOrg() {
      const { data: { user } } = await supabase.current.auth.getUser()
      if (user) {
        const { data } = await supabase.current
          .from('role')
          .select('organization_id')
          .eq('user_id', user.id)
          .eq('is_active', true)
          .limit(1)
          .single()
        if (data) setOrganizationId(data.organization_id)
      }
    }
    loadOrg()
  }, [])

  // Dev/demo fallback: use org 1 when no Supabase session
  useEffect(() => {
    if ((process.env.NODE_ENV === 'development' || IS_DEMO) && !organizationId) {
      setOrganizationId(1)
    }
  }, [organizationId])

  // Load project list for filter dropdown
  useEffect(() => {
    if (!organizationId) return
    adminClient.listProjectsGrouped()
      .then((ps) => setProjects(ps.sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => {})
  }, [organizationId])

  // Sync project filter to URL
  const handleProjectFilterChange = useCallback((pid: number | undefined) => {
    setSelectedProjectId(pid)
    setPage(0)
    const params = new URLSearchParams(searchParams.toString())
    if (pid) {
      params.set('project', pid.toString())
    } else {
      params.delete('project')
    }
    router.replace(`/notifications?${params.toString()}`)
  }, [searchParams, router])

  const isDev = process.env.NODE_ENV === 'development'

  const demoToken = IS_DEMO ? process.env.NEXT_PUBLIC_DEMO_ACCESS_TOKEN : undefined

  const client = useMemo(
    () => new NotificationsClient({
      enableLogging: isDev,
      getAuthToken: async () => {
        if (demoToken) return demoToken
        if (isDev) return null
        const { data: { session } } = await supabase.current.auth.getSession()
        return session?.access_token ?? null
      },
      organizationId,
    }),
    [organizationId, isDev, demoToken]
  )

  const inboundClient = useMemo(
    () => new InboundClient({
      enableLogging: isDev,
      getAuthToken: async () => {
        if (demoToken) return demoToken
        if (isDev) return null
        const { data: { session } } = await supabase.current.auth.getSession()
        return session?.access_token ?? null
      },
      organizationId,
    }),
    [organizationId, isDev, demoToken]
  )

  const loadInbox = useCallback(async () => {
    try {
      const { messages, total } = await inboundClient.listMessages({
        inbound_message_status: inboundStatusFilter || undefined,
        project_id: selectedProjectId,
        limit: pageSize,
        offset: page * pageSize,
      })
      setInboundMessages(messages)
      setInboundTotal(total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load inbox')
    }
  }, [inboundClient, inboundStatusFilter, selectedProjectId, page])

  const loadSchedules = useCallback(async () => {
    try {
      const data = await client.listSchedules(true, { project_id: selectedProjectId })
      setSchedules(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules')
    }
  }, [client, selectedProjectId])

  const loadTemplates = useCallback(async () => {
    try {
      const data = await client.listTemplates(undefined, true)
      setTemplates(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load templates')
    }
  }, [client])

  const loadEmailLogs = useCallback(async () => {
    try {
      const { messages, total } = await client.listOutboundMessages({
        project_id: selectedProjectId,
        limit: pageSize,
        offset: page * pageSize,
      })
      setEmailLogs(messages)
      setEmailLogsTotal(total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load email history')
    }
  }, [client, selectedProjectId, page])

  const loadSubmissions = useCallback(async () => {
    try {
      const { submissions: data, total } = await client.listSubmissions(undefined, pageSize, page * pageSize)
      setSubmissions(data)
      setSubmissionsTotal(total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load submissions')
    }
  }, [client, page])

  useEffect(() => {
    if (!organizationId) return
    setLoading(true)
    setError(null)
    setPage(0)
    const loadData = async () => {
      switch (activeTab) {
        case 'inbox':
          if (inboxView === 'submissions') {
            await loadSubmissions()
          } else {
            await loadInbox()
          }
          break
        case 'schedules':
          await loadSchedules()
          break
        case 'templates':
          await loadTemplates()
          break
        case 'email-history':
          await loadEmailLogs()
          break
      }
      setLoading(false)
    }
    loadData()
  }, [activeTab, inboxView, organizationId, loadInbox, loadSchedules, loadTemplates, loadEmailLogs, loadSubmissions])

  // Reload paginated data when page changes
  useEffect(() => {
    if (!organizationId) return
    if (activeTab === 'inbox' && inboxView === 'emails') loadInbox()
    if (activeTab === 'inbox' && inboxView === 'submissions') loadSubmissions()
    if (activeTab === 'email-history') loadEmailLogs()
  }, [page, activeTab, inboxView, organizationId, loadInbox, loadEmailLogs, loadSubmissions])

  // Reload inbox when status filter changes
  useEffect(() => {
    if (!organizationId || activeTab !== 'inbox' || inboxView !== 'emails') return
    setPage(0)
    setLoading(true)
    loadInbox().finally(() => setLoading(false))
  }, [inboundStatusFilter, organizationId, activeTab, inboxView, loadInbox])

  const handleToggleSchedule = async (schedule: NotificationSchedule) => {
    try {
      await client.updateSchedule(schedule.id, { is_active: !schedule.is_active })
      await loadSchedules()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update schedule')
    }
  }

  const handleTriggerSchedule = async (scheduleId: number) => {
    try {
      const result = await client.triggerSchedule(scheduleId)
      setError(null)
      alert(result.message)
      await loadEmailLogs()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to trigger schedule')
    }
  }

  const handleDeleteSchedule = async (scheduleId: number) => {
    if (!confirm('Delete this schedule? This cannot be undone.')) return
    try {
      await client.deactivateSchedule(scheduleId)
      await loadSchedules()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete schedule')
    }
  }

  const handleApprove = async (messageId: number, projectId?: number) => {
    setActionLoading(messageId)
    setError(null)
    try {
      const result = await inboundClient.approveMessage(messageId, {
        project_id: projectId,
      })
      setApproveResults(prev => ({ ...prev, [messageId]: result }))
      setApproveProjectId(undefined)
      await loadInbox()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to approve message')
    } finally {
      setActionLoading(null)
    }
  }

  const handleReject = async (messageId: number) => {
    setActionLoading(messageId)
    setError(null)
    try {
      await inboundClient.rejectMessage(messageId, { reason: rejectReason || undefined })
      setShowRejectInput(null)
      setRejectReason('')
      await loadInbox()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reject message')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDownloadAttachment = async (attachmentId: number) => {
    try {
      const { url } = await inboundClient.getAttachmentUrl(attachmentId)
      window.open(url, '_blank')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to get download URL')
    }
  }

  const tabs: { id: TabId; label: string; icon: typeof Bell }[] = [
    { id: 'inbox', label: 'Inbox', icon: Inbox },
    { id: 'schedules', label: 'Schedules', icon: Clock },
    { id: 'email-history', label: 'Sent', icon: Mail },
    { id: 'templates', label: 'Templates', icon: FileText },
  ]

  const totalForPagination = activeTab === 'inbox'
    ? (inboxView === 'submissions' ? submissionsTotal : inboundTotal)
    : emailLogsTotal
  const showPagination = (activeTab === 'inbox' || activeTab === 'email-history') && totalForPagination > pageSize

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/" className="text-slate-400 hover:text-slate-600">
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <div>
                <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
                  <Bell className="w-5 h-5" />
                  Notifications
                </h1>
                <p className="text-sm text-slate-500">
                  Inbox, schedules, templates, and delivery history
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
            </div>
          </div>
        </div>
      </div>

      {/* Tabs + Project Selector */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.id
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                </button>
              ))}
              <div className="ml-2 py-1.5">
                <Button size="sm" onClick={() => setComposeOpen(true)}>
                  <Send className="w-4 h-4 mr-1.5" />
                  Compose
                </Button>
              </div>
            </div>
            <div className="flex items-center gap-2 py-1.5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Project</label>
              <select
                value={selectedProjectId ?? ''}
                onChange={(e) => handleProjectFilterChange(e.target.value ? Number(e.target.value) : undefined)}
                className={`px-3 py-1.5 text-sm rounded-lg focus:outline-none min-w-[200px] font-medium ${
                  selectedProjectId
                    ? 'border-2 border-blue-500 bg-blue-50 text-blue-800'
                    : 'border-2 border-amber-400 bg-amber-50 text-amber-800'
                }`}
              >
                <option value="">Select a project...</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.sage_id ? `${p.sage_id} - ${p.name}` : p.name}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-6 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Inbox Tab */}
            {activeTab === 'inbox' && (
              <div>
                {/* Inbox view toggle + filters */}
                <div className="flex items-center gap-4 mb-4">
                  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-0.5">
                    {(['emails', 'submissions'] as const).map((view) => (
                      <button
                        key={view}
                        onClick={() => { setInboxView(view); setPage(0) }}
                        className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                          inboxView === view
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        {view === 'emails' ? 'Emails' : 'Submissions'}
                      </button>
                    ))}
                  </div>
                  {inboxView === 'emails' && (
                    <div className="flex items-center gap-2">
                      <label className="text-sm font-medium text-slate-600">Status:</label>
                      <select
                        value={inboundStatusFilter}
                        onChange={(e) => setInboundStatusFilter(e.target.value as InboundMessageStatus | '')}
                        className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
                      >
                        <option value="">All</option>
                        <option value="pending_review">Pending Review</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                        <option value="auto_processed">Auto Processed</option>
                        <option value="noise">Noise</option>
                        <option value="received">Received</option>
                        <option value="failed">Failed</option>
                      </select>
                    </div>
                  )}
                </div>

                {inboxView === 'emails' && (inboundMessages.length === 0 ? (
                  <EmptyState icon={Inbox} message="No inbound messages" />
                ) : (
                  <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left px-4 py-3 font-medium text-slate-600 w-8"></th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Sender</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Subject</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Status</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Attachments</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Received</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600 w-24">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inboundMessages.map((msg) => {
                          const isExpanded = expandedMessageId === msg.id
                          const isPending = msg.inbound_message_status === 'pending_review'
                          const hasFailedAttachments = msg.inbound_message_status === 'approved'
                            && msg.attachments?.some(a => a.attachment_processing_status === 'failed')
                          const isActioning = actionLoading === msg.id
                          const style = STATUS_STYLES[msg.inbound_message_status] || STATUS_STYLES.received

                          return (
                            <Fragment key={msg.id}>
                              <tr
                                className="border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50"
                                onClick={() => setExpandedMessageId(isExpanded ? null : msg.id)}
                              >
                                <td className="px-4 py-3">
                                  {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="font-medium text-slate-900">{msg.sender_email || 'Unknown'}</div>
                                  {msg.sender_name && <div className="text-xs text-slate-400">{msg.sender_name}</div>}
                                </td>
                                <td className="px-4 py-3 text-slate-700 max-w-xs truncate">{msg.subject || '(no subject)'}</td>
                                <td className="px-4 py-3">
                                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
                                    {msg.inbound_message_status}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-slate-500" onClick={(e) => e.stopPropagation()}>
                                  {msg.attachment_count > 0 && (() => {
                                    const statuses = msg.attachments?.map(a => a.attachment_processing_status) || []
                                    const eyeColor = statuses.includes('failed') ? 'text-red-500'
                                      : statuses.includes('pending') || statuses.includes('processing') ? 'text-amber-500'
                                      : statuses.every(s => s === 'extracted') ? 'text-green-500'
                                      : 'text-slate-400'
                                    return (
                                      <span className="inline-flex items-center gap-1">
                                        <Paperclip className="w-3.5 h-3.5" />
                                        {msg.attachment_count}
                                        {msg.attachments?.map((att) => (
                                          <Button
                                            key={att.id}
                                            variant="ghost"
                                            size="sm"
                                            className="h-6 w-6 p-0"
                                            onClick={() => handleDownloadAttachment(att.id)}
                                            title={`View ${att.filename || 'attachment'}`}
                                          >
                                            <Eye className={`w-3.5 h-3.5 ${eyeColor}`} />
                                          </Button>
                                        ))}
                                      </span>
                                    )
                                  })()}
                                </td>
                                <td className="px-4 py-3 text-slate-500">
                                  {new Date(msg.created_at).toLocaleString()}
                                </td>
                                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                                  {(isPending || hasFailedAttachments) && (
                                    <div className="flex items-center gap-1.5">
                                      <select
                                        value={approveProjectId ?? ''}
                                        onChange={(e) => setApproveProjectId(e.target.value ? Number(e.target.value) : undefined)}
                                        className="w-40 px-2 py-1 text-xs border border-slate-200 rounded focus:outline-none focus:border-slate-400 bg-white"
                                        title="Assign to project"
                                      >
                                        <option value="">Project...</option>
                                        {projects.map((p) => (
                                          <option key={p.id} value={p.id}>{p.sage_id ? `${p.sage_id} - ${p.name}` : p.name}</option>
                                        ))}
                                      </select>
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={isActioning}
                                        onClick={() => handleApprove(msg.id, approveProjectId)}
                                        title={hasFailedAttachments ? "Retry extraction" : "Approve"}
                                        className={hasFailedAttachments
                                          ? "text-amber-600 hover:bg-amber-50 border-amber-200"
                                          : "text-green-600 hover:bg-green-50 border-green-200"}
                                      >
                                        {isActioning ? <Loader2 className="w-3 h-3 animate-spin" />
                                          : hasFailedAttachments ? <RefreshCw className="w-3 h-3" />
                                          : <Check className="w-3 h-3" />}
                                      </Button>
                                      {isPending && (
                                        <Button
                                          variant="outline"
                                          size="sm"
                                          disabled={isActioning}
                                          onClick={() => {
                                            setShowRejectInput(showRejectInput === msg.id ? null : msg.id)
                                          }}
                                          title="Reject"
                                          className="text-red-600 hover:bg-red-50 border-red-200"
                                        >
                                          <X className="w-3 h-3" />
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </td>
                              </tr>

                              {/* Reject reason input */}
                              {showRejectInput === msg.id && (
                                <tr className="bg-red-50 border-b border-slate-100">
                                  <td colSpan={7} className="px-4 py-3">
                                    <div className="flex items-center gap-2 max-w-lg">
                                      <input
                                        type="text"
                                        placeholder="Reason (optional)"
                                        value={rejectReason}
                                        onChange={(e) => setRejectReason(e.target.value)}
                                        className="flex-1 px-3 py-1.5 text-sm border border-red-200 rounded-lg focus:outline-none focus:border-red-400 bg-white"
                                        onClick={(e) => e.stopPropagation()}
                                      />
                                      <Button
                                        size="sm"
                                        disabled={isActioning}
                                        onClick={() => handleReject(msg.id)}
                                        className="bg-red-600 hover:bg-red-700 text-white"
                                      >
                                        {isActioning ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
                                        Reject
                                      </Button>
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => { setShowRejectInput(null); setRejectReason('') }}
                                      >
                                        Cancel
                                      </Button>
                                    </div>
                                  </td>
                                </tr>
                              )}

                              {/* Expanded detail panel */}
                              {isExpanded && (
                                <tr className="bg-slate-50 border-b border-slate-100">
                                  <td colSpan={7} className="px-6 py-4">
                                    <div className="space-y-3">
                                      {msg.classification_reason && (
                                        <div>
                                          <span className="text-xs font-medium text-slate-500 uppercase">Classification</span>
                                          <p className="text-sm text-slate-700 mt-0.5">{msg.classification_reason}</p>
                                        </div>
                                      )}
                                      {msg.failed_reason && (
                                        <div>
                                          <span className="text-xs font-medium text-red-500 uppercase">Error</span>
                                          <p className="text-sm text-red-700 mt-0.5">{msg.failed_reason}</p>
                                        </div>
                                      )}

                                      {/* Attachments */}
                                      {msg.attachments.length > 0 && (
                                        <div>
                                          <span className="text-xs font-medium text-slate-500 uppercase">Attachments</span>
                                          <div className="mt-1 space-y-1.5">
                                            {msg.attachments.map((att) => {
                                              const attStyle = STATUS_STYLES[att.attachment_processing_status] || STATUS_STYLES.pending
                                              return (
                                                <Fragment key={att.id}>
                                                <div className="flex items-center justify-between bg-white rounded border border-slate-200 px-3 py-2">
                                                  <div className="flex items-center gap-2 min-w-0">
                                                    <Paperclip className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                                                    <span className="text-sm text-slate-700 truncate">{att.filename || 'unnamed'}</span>
                                                    <span className="text-xs text-slate-400">{att.content_type}</span>
                                                    {att.size_bytes && (
                                                      <span className="text-xs text-slate-400">
                                                        {att.size_bytes < 1024 ? `${att.size_bytes} B`
                                                          : att.size_bytes < 1048576 ? `${(att.size_bytes / 1024).toFixed(1)} KB`
                                                          : `${(att.size_bytes / 1048576).toFixed(1)} MB`}
                                                      </span>
                                                    )}
                                                    <span
                                                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${attStyle.bg} ${attStyle.text}`}
                                                      title={att.attachment_processing_status === 'failed' && att.failed_reason ? att.failed_reason : undefined}
                                                    >
                                                      {att.attachment_processing_status === 'processing' ? 'extracting...'
                                                        : att.attachment_processing_status === 'failed' ? 'extraction failed'
                                                        : att.attachment_processing_status}
                                                    </span>
                                                    {att.attachment_processing_status === 'failed' && att.failed_reason && (
                                                      <span className="text-xs text-red-500 truncate max-w-xs" title={att.failed_reason}>
                                                        {att.failed_reason}
                                                      </span>
                                                    )}
                                                  </div>
                                                  <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => handleDownloadAttachment(att.id)}
                                                    title="Download"
                                                  >
                                                    <Download className="w-3 h-3" />
                                                  </Button>
                                                </div>
                                                {att.attachment_processing_status === 'extracted' && att.extraction_result && (
                                                  <div className="ml-6 mt-1 bg-green-50 border border-green-200 rounded px-3 py-2 text-sm">
                                                    <div className="flex items-center gap-4 flex-wrap">
                                                      {att.extraction_result.mrp_per_kwh != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">MRP</span>
                                                          <span className="ml-1 text-green-900 font-semibold">{String(att.extraction_result.mrp_per_kwh)} /kWh</span>
                                                        </div>
                                                      )}
                                                      {att.extraction_result.billing_month_stored != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">Month</span>
                                                          <span className="ml-1 text-green-900">{String(att.extraction_result.billing_month_stored)}</span>
                                                        </div>
                                                      )}
                                                      {att.extraction_result.total_variable_charges != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">Total Charges</span>
                                                          <span className="ml-1 text-green-900">{String(att.extraction_result.total_variable_charges)}</span>
                                                        </div>
                                                      )}
                                                      {att.extraction_result.total_kwh_invoiced != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">kWh Invoiced</span>
                                                          <span className="ml-1 text-green-900">{String(att.extraction_result.total_kwh_invoiced)}</span>
                                                        </div>
                                                      )}
                                                      {att.extraction_result.extraction_confidence != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">Confidence</span>
                                                          <span className="ml-1 text-green-900">{String(att.extraction_result.extraction_confidence)}</span>
                                                        </div>
                                                      )}
                                                      {att.extraction_result.observation_id != null && (
                                                        <div>
                                                          <span className="text-xs font-medium text-green-700">Observation</span>
                                                          <span className="ml-1 text-green-900">#{String(att.extraction_result.observation_id)}</span>
                                                        </div>
                                                      )}
                                                    </div>
                                                  </div>
                                                )}
                                                </Fragment>
                                              )
                                            })}
                                          </div>
                                        </div>
                                      )}

                                      {/* Approve extraction results */}
                                      {approveResults[msg.id] && (
                                        <div>
                                          <span className="text-xs font-medium text-slate-500 uppercase">Extraction Results</span>
                                          <div className="mt-1 space-y-1.5">
                                            {approveResults[msg.id].extraction_results.length === 0 ? (
                                              <p className="text-sm text-slate-500">No attachments processed</p>
                                            ) : (
                                              approveResults[msg.id].extraction_results.map((r, i) => (
                                                <div key={i} className={`text-sm rounded border px-3 py-2 ${r.success ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'}`}>
                                                  <div className="font-medium">{r.success ? 'Extracted' : 'Failed'}: {r.message}</div>
                                                  {r.mrp_per_kwh !== undefined && r.mrp_per_kwh !== null && (
                                                    <div className="text-xs mt-0.5">MRP: {r.mrp_per_kwh} per kWh | Month: {r.billing_month} | Confidence: {r.confidence}</div>
                                                  )}
                                                  {r.failed_reason && <div className="text-xs mt-0.5">{r.failed_reason}</div>}
                                                </div>
                                              ))
                                            )}
                                          </div>
                                        </div>
                                      )}

                                      {msg.reviewed_at && (
                                        <div className="text-xs text-slate-400">
                                          Reviewed {new Date(msg.reviewed_at).toLocaleString()}
                                          {msg.reviewed_by && ` by ${msg.reviewed_by}`}
                                        </div>
                                      )}
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
                ))}

                {inboxView === 'submissions' && (submissions.length === 0 ? (
                  <EmptyState icon={Inbox} message="No submissions received yet" />
                ) : (
                  <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left px-4 py-3 font-medium text-slate-600">ID</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Submitted By</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Data</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Date</th>
                        </tr>
                      </thead>
                      <tbody>
                        {submissions.map((s) => (
                          <tr key={s.id} className="border-b border-slate-100 last:border-0">
                            <td className="px-4 py-3 text-slate-500">#{s.id}</td>
                            <td className="px-4 py-3 text-slate-700">{s.submitted_by_email || '-'}</td>
                            <td className="px-4 py-3 text-slate-700 max-w-xs">
                              <pre className="text-xs bg-slate-50 rounded p-1 overflow-auto max-h-16">
                                {JSON.stringify(s.response_data, null, 2)}
                              </pre>
                            </td>
                            <td className="px-4 py-3 text-slate-500">
                              {new Date(s.created_at).toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            )}

            {/* Schedules Tab */}
            {activeTab === 'schedules' && (
              <div className="space-y-3">
                <div className="flex justify-end mb-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => { setEditingSchedule(undefined); setScheduleFormOpen(true) }}
                  >
                    <Plus className="w-4 h-4 mr-1" />
                    Create Schedule
                  </Button>
                </div>
                {schedules.length === 0 ? (
                  <EmptyState icon={Clock} message="No notification schedules configured" />
                ) : (
                  schedules.map((s) => (
                    <div key={s.id} className="bg-white rounded-lg border border-slate-200 p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium text-slate-900">{s.name}</h3>
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              s.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'
                            }`}>
                              {s.is_active ? 'Active' : 'Inactive'}
                            </span>
                            <span className="text-xs text-slate-400 bg-slate-50 px-2 py-0.5 rounded">
                              {s.email_schedule_type.replace(/_/g, ' ')}
                            </span>
                          </div>
                          <div className="mt-1 text-sm text-slate-500 flex flex-wrap gap-x-4 gap-y-1">
                            <span>Frequency: {s.report_frequency}</span>
                            {s.day_of_month && <span>Day: {s.day_of_month}</span>}
                            <span>Time: {s.time_of_day?.slice(0, 5)} {s.timezone === 'Africa/Lagos' ? 'UTC+1' : s.timezone === 'Africa/Johannesburg' ? 'UTC+2' : s.timezone === 'Africa/Nairobi' ? 'UTC+3' : 'UTC'}</span>
                            {s.report_frequency === 'daily' && s.conditions?.due_date_relative ? (
                              <span>Timing: {describeDueDateTiming(s.conditions.due_date_relative as DueDateRelativeConfig)}</span>
                            ) : !['invoice_reminder', 'invoice_initial'].includes(s.email_schedule_type) && s.conditions?.recipient_emails ? (
                              <span>{(s.conditions.recipient_emails as string[]).length} recipient(s)</span>
                            ) : null}
                          </div>
                          {s.next_run_at && (
                            <p className="mt-1 text-xs text-slate-400">
                              Next run: {new Date(s.next_run_at).toLocaleString()}
                            </p>
                          )}
                          {s.last_run_at && (
                            <p className="text-xs text-slate-400">
                              Last run: {new Date(s.last_run_at).toLocaleString()}
                              {s.last_run_status && ` (${s.last_run_status})`}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 ml-4">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => { setEditingSchedule(s); setScheduleFormOpen(true) }}
                            title="Edit"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleTriggerSchedule(s.id)}
                            title="Trigger now"
                          >
                            <Send className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleToggleSchedule(s)}
                            title={s.is_active ? 'Pause' : 'Resume'}
                          >
                            {s.is_active ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDeleteSchedule(s.id)}
                            title="Delete"
                            className="text-red-500 hover:bg-red-50 border-red-200"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Sent Tab */}
            {activeTab === 'email-history' && (
              <div>
                {emailLogs.length === 0 ? (
                  <EmptyState icon={Mail} message="No emails sent yet" />
                ) : (
                  <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left px-4 py-3 font-medium text-slate-600 w-8"></th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Recipient</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Subject</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Status</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Sent</th>
                        </tr>
                      </thead>
                      <tbody>
                        {emailLogs.map((log) => {
                          const isExpanded = expandedSentId === log.id
                          return (
                            <Fragment key={log.id}>
                              <tr
                                className="border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50"
                                onClick={() => setExpandedSentId(isExpanded ? null : log.id)}
                              >
                                <td className="px-4 py-3">
                                  {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="font-medium text-slate-900">{log.recipient_email}</div>
                                  {log.recipient_name && (
                                    <div className="text-xs text-slate-400">{log.recipient_name}</div>
                                  )}
                                </td>
                                <td className="px-4 py-3 text-slate-700 max-w-xs truncate">{log.subject}</td>
                                <td className="px-4 py-3"><StatusBadge status={log.email_status} /></td>
                                <td className="px-4 py-3 text-slate-500">
                                  {log.sent_at ? new Date(log.sent_at).toLocaleString() : '-'}
                                </td>
                              </tr>

                              {isExpanded && (
                                <tr className="bg-slate-50 border-b border-slate-100">
                                  <td colSpan={5} className="px-6 py-4">
                                    <div className="space-y-3">
                                      {/* Delivery details */}
                                      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
                                        {log.delivered_at && (
                                          <span>Delivered: {new Date(log.delivered_at).toLocaleString()}</span>
                                        )}
                                        {log.reminder_count > 0 && (
                                          <span>Reminder #{log.reminder_count}</span>
                                        )}
                                      </div>

                                      {log.error_message && (
                                        <div>
                                          <span className="text-xs font-medium text-red-500 uppercase">Error</span>
                                          <p className="text-sm text-red-700 mt-0.5">{log.error_message}</p>
                                        </div>
                                      )}

                                      {/* Email body */}
                                      {(log.template_body_text || log.template_body_html) && (
                                        <div>
                                          <span className="text-xs font-medium text-slate-500 uppercase">Email Body</span>
                                          {log.template_body_text ? (
                                            <pre className="mt-1 bg-white border border-slate-200 rounded-lg p-4 text-sm text-slate-700 whitespace-pre-wrap overflow-auto max-h-80">
                                              {log.template_body_text}
                                            </pre>
                                          ) : (
                                            <div
                                              className="mt-1 bg-white border border-slate-200 rounded-lg p-4 text-sm text-slate-700 prose prose-sm max-w-none overflow-auto max-h-80"
                                              dangerouslySetInnerHTML={{ __html: log.template_body_html! }}
                                            />
                                          )}
                                        </div>
                                      )}
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
            )}

            {/* Templates Tab */}
            {activeTab === 'templates' && (
              <div className="space-y-3">
                <div className="flex justify-end mb-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => { setEditingTemplate(undefined); setTemplateEditorOpen(true) }}
                  >
                    <Plus className="w-4 h-4 mr-1" />
                    Create Template
                  </Button>
                </div>
                {templates.length === 0 ? (
                  <EmptyState icon={FileText} message="No email templates found" />
                ) : (
                  templates.map((t) => (
                    <div key={t.id} className="bg-white rounded-lg border border-slate-200 p-4">
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium text-slate-900">{t.name}</h3>
                            {t.is_system && (
                              <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded">System</span>
                            )}
                            {!t.is_active && (
                              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">Inactive</span>
                            )}
                          </div>
                          {t.description && <p className="mt-1 text-sm text-slate-500">{t.description}</p>}
                          <p className="mt-1 text-xs text-slate-400">
                            Type: {t.email_schedule_type.replace(/_/g, ' ')} | Subject: {t.subject_template}
                          </p>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => { setEditingTemplate(t); setTemplateEditorOpen(true) }}
                          title="Edit"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Pagination */}
            {showPagination && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-sm text-slate-500">
                  Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, totalForPagination)} of {totalForPagination}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage(p => p - 1)}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * pageSize >= totalForPagination}
                    onClick={() => setPage(p => p + 1)}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Dialogs */}
      <ComposeEmailDialog
        open={composeOpen}
        onOpenChange={setComposeOpen}
        client={client}
        projectId={selectedProjectId}
        onSent={() => { if (activeTab === 'email-history') loadEmailLogs() }}
      />

      <ScheduleFormDialog
        open={scheduleFormOpen}
        onOpenChange={setScheduleFormOpen}
        client={client}
        schedule={editingSchedule}
        onSaved={loadSchedules}
        projects={projects}
      />

      <TemplateEditorDialog
        open={templateEditorOpen}
        onOpenChange={setTemplateEditorOpen}
        client={client}
        template={editingTemplate}
        onSaved={loadTemplates}
      />
    </div>
  )
}

function EmptyState({ icon: Icon, message }: { icon: typeof Bell; message: string }) {
  return (
    <div className="text-center py-16">
      <Icon className="w-10 h-10 text-slate-300 mx-auto mb-3" />
      <p className="text-slate-500 text-sm">{message}</p>
    </div>
  )
}
