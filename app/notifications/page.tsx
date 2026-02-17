'use client'

/**
 * Notifications Page
 *
 * Standalone page for managing email notification schedules,
 * viewing email history, managing templates, and reviewing submissions.
 */

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
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
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/app/components/ui/button'
import {
  NotificationsClient,
  type EmailTemplate,
  type NotificationSchedule,
  type EmailLogEntry,
  type SubmissionResponse,
  type EmailStatus,
} from '@/lib/api/notificationsClient'
import { createClient } from '@/lib/supabase/client'

type TabId = 'schedules' | 'email-history' | 'templates' | 'submissions'

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  delivered: { bg: 'bg-green-100', text: 'text-green-700' },
  sending: { bg: 'bg-blue-100', text: 'text-blue-700' },
  pending: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  bounced: { bg: 'bg-red-100', text: 'text-red-700' },
  failed: { bg: 'bg-red-100', text: 'text-red-700' },
  suppressed: { bg: 'bg-slate-100', text: 'text-slate-600' },
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
  const [activeTab, setActiveTab] = useState<TabId>('schedules')
  const [schedules, setSchedules] = useState<NotificationSchedule[]>([])
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [emailLogs, setEmailLogs] = useState<EmailLogEntry[]>([])
  const [emailLogsTotal, setEmailLogsTotal] = useState(0)
  const [submissions, setSubmissions] = useState<SubmissionResponse[]>([])
  const [submissionsTotal, setSubmissionsTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 25

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

  const client = useMemo(
    () => new NotificationsClient({
      enableLogging: process.env.NODE_ENV === 'development',
      getAuthToken: async () => {
        const { data: { session } } = await supabase.current.auth.getSession()
        return session?.access_token ?? null
      },
      organizationId,
    }),
    [organizationId]
  )

  const loadSchedules = useCallback(async () => {
    try {
      const data = await client.listSchedules(true)
      setSchedules(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules')
    }
  }, [client])

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
      const { logs, total } = await client.listEmailLogs({ limit: pageSize, offset: page * pageSize })
      setEmailLogs(logs)
      setEmailLogsTotal(total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load email history')
    }
  }, [client, page])

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
    setLoading(true)
    setError(null)
    setPage(0)
    const loadData = async () => {
      switch (activeTab) {
        case 'schedules':
          await loadSchedules()
          break
        case 'templates':
          await loadTemplates()
          break
        case 'email-history':
          await loadEmailLogs()
          break
        case 'submissions':
          await loadSubmissions()
          break
      }
      setLoading(false)
    }
    loadData()
  }, [activeTab, loadSchedules, loadTemplates, loadEmailLogs, loadSubmissions])

  // Reload paginated data when page changes
  useEffect(() => {
    if (activeTab === 'email-history') loadEmailLogs()
    if (activeTab === 'submissions') loadSubmissions()
  }, [page, activeTab, loadEmailLogs, loadSubmissions])

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

  const tabs: { id: TabId; label: string; icon: typeof Bell }[] = [
    { id: 'schedules', label: 'Schedules', icon: Clock },
    { id: 'email-history', label: 'Email History', icon: Mail },
    { id: 'templates', label: 'Templates', icon: FileText },
    { id: 'submissions', label: 'Submissions', icon: Inbox },
  ]

  const totalForPagination = activeTab === 'email-history' ? emailLogsTotal : submissionsTotal
  const showPagination = (activeTab === 'email-history' || activeTab === 'submissions') && totalForPagination > pageSize

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-4">
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
                Email schedules, templates, and delivery history
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex gap-1">
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
            {/* Schedules Tab */}
            {activeTab === 'schedules' && (
              <div className="space-y-3">
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
                            <span>Time: {s.time_of_day} {s.timezone}</span>
                            {s.max_reminders && <span>Max reminders: {s.max_reminders}</span>}
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
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Email History Tab */}
            {activeTab === 'email-history' && (
              <div>
                {emailLogs.length === 0 ? (
                  <EmptyState icon={Mail} message="No emails sent yet" />
                ) : (
                  <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Recipient</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Subject</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Status</th>
                          <th className="text-left px-4 py-3 font-medium text-slate-600">Sent</th>
                        </tr>
                      </thead>
                      <tbody>
                        {emailLogs.map((log) => (
                          <tr key={log.id} className="border-b border-slate-100 last:border-0">
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
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Templates Tab */}
            {activeTab === 'templates' && (
              <div className="space-y-3">
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
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Submissions Tab */}
            {activeTab === 'submissions' && (
              <div>
                {submissions.length === 0 ? (
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
