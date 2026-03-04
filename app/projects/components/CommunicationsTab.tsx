'use client'

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { Mail, Clock, Send, Play, Pause, Loader2, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import {
  NotificationsClient,
  type OutboundMessageEntry,
  type NotificationSchedule,
  type EmailTemplate,
} from '@/lib/api/notificationsClient'
import { createClient } from '@/lib/supabase/client'
import { RecipientPicker } from '@/app/notifications/components/RecipientPicker'

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  delivered: { bg: 'bg-green-100', text: 'text-green-700' },
  sending: { bg: 'bg-blue-100', text: 'text-blue-700' },
  pending: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  bounced: { bg: 'bg-red-100', text: 'text-red-700' },
  failed: { bg: 'bg-red-100', text: 'text-red-700' },
  suppressed: { bg: 'bg-slate-100', text: 'text-slate-600' },
}

type SubView = 'history' | 'quick-send' | 'schedules'

interface CommunicationsTabProps {
  projectId?: number
  organizationId?: number
  editMode?: boolean
}

export function CommunicationsTab({ projectId, organizationId }: CommunicationsTabProps) {
  const [subView, setSubView] = useState<SubView>('history')
  const [emailLogs, setEmailLogs] = useState<OutboundMessageEntry[]>([])
  const [emailLogsTotal, setEmailLogsTotal] = useState(0)
  const [schedules, setSchedules] = useState<NotificationSchedule[]>([])
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 25

  // Quick Send state
  const [recipients, setRecipients] = useState<string[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('')
  const [sending, setSending] = useState(false)

  const supabase = useRef(createClient())

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

  const loadHistory = useCallback(async () => {
    if (!projectId) return
    try {
      const { messages, total } = await client.listOutboundMessages({
        project_id: projectId,
        limit: pageSize,
        offset: page * pageSize,
      })
      setEmailLogs(messages)
      setEmailLogsTotal(total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load email history')
    }
  }, [client, projectId, page])

  const loadSchedules = useCallback(async () => {
    if (!projectId) return
    try {
      const data = await client.listSchedules(true, { project_id: projectId })
      setSchedules(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules')
    }
  }, [client, projectId])

  const loadTemplates = useCallback(async () => {
    try {
      const data = await client.listTemplates()
      setTemplates(data)
    } catch { /* ignore */ }
  }, [client])

  useEffect(() => {
    setLoading(true)
    setError(null)
    setPage(0)
    const load = async () => {
      switch (subView) {
        case 'history': await loadHistory(); break
        case 'schedules': await loadSchedules(); break
        case 'quick-send': await loadTemplates(); break
      }
      setLoading(false)
    }
    load()
  }, [subView, loadHistory, loadSchedules, loadTemplates])

  useEffect(() => {
    if (subView === 'history') loadHistory()
  }, [page, subView, loadHistory])

  const handleToggleSchedule = async (s: NotificationSchedule) => {
    try {
      await client.updateSchedule(s.id, { is_active: !s.is_active })
      await loadSchedules()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update schedule')
    }
  }

  const handleTrigger = async (id: number) => {
    try {
      const result = await client.triggerSchedule(id)
      alert(result.message)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to trigger')
    }
  }

  const handleQuickSend = async () => {
    if (!selectedTemplateId || recipients.length === 0) return
    setSending(true)
    setError(null)
    try {
      const result = await client.sendEmail({
        template_id: Number(selectedTemplateId),
        recipient_emails: recipients,
      })
      alert(result.message)
      setRecipients([])
      setSelectedTemplateId('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send')
    } finally {
      setSending(false)
    }
  }

  const subViews: { id: SubView; label: string; icon: typeof Mail }[] = [
    { id: 'history', label: 'Email History', icon: Mail },
    { id: 'quick-send', label: 'Quick Send', icon: Send },
    { id: 'schedules', label: 'Active Schedules', icon: Clock },
  ]

  const showPagination = subView === 'history' && emailLogsTotal > pageSize

  return (
    <div className="space-y-4">
      {/* Sub-view buttons */}
      <div className="flex gap-2">
        {subViews.map((sv) => (
          <button
            key={sv.id}
            onClick={() => setSubView(sv.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              subView === sv.id
                ? 'bg-blue-600 text-white'
                : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
            }`}
          >
            <sv.icon className="w-3.5 h-3.5" />
            {sv.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="p-2 text-sm text-red-600 bg-red-50 rounded border border-red-200 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
        </div>
      ) : (
        <>
          {/* Email History */}
          {subView === 'history' && (
            <>
              {emailLogs.length === 0 ? (
                <div className="text-center py-12 text-sm text-slate-400">
                  <Mail className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                  No emails sent for this project
                </div>
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
                            {log.recipient_name && <div className="text-xs text-slate-400">{log.recipient_name}</div>}
                          </td>
                          <td className="px-4 py-3 text-slate-700 max-w-xs truncate">{log.subject}</td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              (STATUS_STYLES[log.email_status] || STATUS_STYLES.pending).bg
                            } ${
                              (STATUS_STYLES[log.email_status] || STATUS_STYLES.pending).text
                            }`}>{log.email_status}</span>
                          </td>
                          <td className="px-4 py-3 text-slate-500">
                            {log.sent_at ? new Date(log.sent_at).toLocaleString() : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {showPagination && (
                <div className="flex items-center justify-between mt-3">
                  <p className="text-sm text-slate-500">
                    Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, emailLogsTotal)} of {emailLogsTotal}
                  </p>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button variant="outline" size="sm" disabled={(page + 1) * pageSize >= emailLogsTotal} onClick={() => setPage(p => p + 1)}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Quick Send */}
          {subView === 'quick-send' && (
            <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-4 max-w-lg">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Recipients</label>
                <RecipientPicker
                  value={recipients}
                  onChange={setRecipients}
                  client={client}
                  projectId={projectId}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Template</label>
                <select
                  value={selectedTemplateId}
                  onChange={(e) => setSelectedTemplateId(e.target.value ? Number(e.target.value) : '')}
                  className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
                >
                  <option value="">Select a template...</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>
              <Button
                onClick={handleQuickSend}
                disabled={sending || !selectedTemplateId || recipients.length === 0}
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
                Send
              </Button>
            </div>
          )}

          {/* Active Schedules */}
          {subView === 'schedules' && (
            <div className="space-y-3">
              {schedules.length === 0 ? (
                <div className="text-center py-12 text-sm text-slate-400">
                  <Clock className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                  No schedules for this project
                </div>
              ) : (
                schedules.map((s) => (
                  <div key={s.id} className="bg-white rounded-lg border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm text-slate-900">{s.name}</span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            s.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'
                          }`}>
                            {s.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {s.report_frequency} | {s.time_of_day} {s.timezone}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Button variant="outline" size="sm" onClick={() => handleTrigger(s.id)} title="Trigger">
                          <Send className="w-3 h-3" />
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleToggleSchedule(s)} title={s.is_active ? 'Pause' : 'Resume'}>
                          {s.is_active ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                        </Button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
