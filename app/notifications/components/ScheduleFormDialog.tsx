'use client'

import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/app/components/ui/dialog'
import {
  NotificationsClient,
  type NotificationSchedule,
  type EmailTemplate,
  type EmailScheduleType,
  type ReportFrequency,
} from '@/lib/api/notificationsClient'
import { ConditionsBuilder } from './ConditionsBuilder'
import { RecipientPicker } from './RecipientPicker'
import { DueDateTimingBuilder, type DueDateRelativeConfig } from './DueDateTimingBuilder'
import type { ProjectGroupedItem } from '@/lib/api/adminClient'

const INVOICE_TYPES: EmailScheduleType[] = ['invoice_reminder', 'invoice_initial']

const FREQUENCIES = ['daily', 'monthly', 'quarterly', 'annual', 'on_demand']

const TIMEZONES = [
  { value: 'UTC', label: 'UTC / GMT', line1: 'UTC', line2: 'GMT' },
  { value: 'Africa/Lagos', label: 'UTC+1 / Nigeria', line1: 'UTC+1', line2: 'Nigeria' },
  { value: 'Africa/Johannesburg', label: 'UTC+2 / South Africa', line1: 'UTC+2', line2: 'S. Africa' },
  { value: 'Africa/Nairobi', label: 'UTC+3 / East Africa', line1: 'UTC+3', line2: 'E. Africa' },
]

interface ScheduleFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  client: NotificationsClient
  schedule?: NotificationSchedule
  onSaved?: () => void
  projects?: ProjectGroupedItem[]
}

export function ScheduleFormDialog({ open, onOpenChange, client, schedule, onSaved, projects = [] }: ScheduleFormDialogProps) {
  const isEdit = !!schedule
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [frequency, setFrequency] = useState<ReportFrequency>('daily')
  const [dayOfMonth, setDayOfMonth] = useState<number | ''>(15)
  const [timeOfDay, setTimeOfDay] = useState('09:00')
  const [timezone, setTimezone] = useState('UTC')
  const [conditions, setConditions] = useState<Record<string, unknown>>({})
  const [recipients, setRecipients] = useState<string[]>([])
  const [maxReminders, setMaxReminders] = useState<number | ''>(3)
  const [escalationAfter, setEscalationAfter] = useState<number | ''>(1)
  const [dueDateRelative, setDueDateRelative] = useState<DueDateRelativeConfig>({})
  const [projectId, setProjectId] = useState<number | ''>('')

  // Derive schedule type from selected template
  const selectedTemplate = templates.find((t) => t.id === templateId)
  const scheduleType: EmailScheduleType = selectedTemplate?.email_schedule_type ?? 'invoice_reminder'
  const isDirectSend = !INVOICE_TYPES.includes(scheduleType)

  useEffect(() => {
    if (open) {
      client.listTemplates().then(setTemplates).catch(() => {})
      setError(null)
      if (schedule) {
        setName(schedule.name)
        setTemplateId(schedule.email_template_id)
        setFrequency(schedule.report_frequency as ReportFrequency)
        setDayOfMonth(schedule.day_of_month ?? 15)
        setTimeOfDay(schedule.time_of_day?.slice(0, 5) || '09:00')
        // Map stored timezone to a known value, default to UTC if not in our list
        const knownTz = TIMEZONES.find((tz) => tz.value === schedule.timezone)
        setTimezone(knownTz ? schedule.timezone : 'UTC')
        setConditions(schedule.conditions || {})
        setRecipients((schedule.conditions?.recipient_emails as string[]) || [])
        setMaxReminders(schedule.max_reminders ?? 3)
        setEscalationAfter(schedule.escalation_after ?? 1)
        setDueDateRelative((schedule.conditions?.due_date_relative as DueDateRelativeConfig) || {})
        setProjectId(schedule.project_id ?? '')
      } else {
        setName('')
        setTemplateId('')
        setFrequency('daily')
        setDayOfMonth(15)
        setTimeOfDay('09:00')
        setTimezone('UTC')
        setConditions({})
        setRecipients([])
        setMaxReminders(3)
        setEscalationAfter(1)
        setDueDateRelative({})
        setProjectId('')
      }
    }
  }, [open, client, schedule])

  async function handleSave() {
    if (!name || !templateId) return
    setSaving(true)
    setError(null)
    try {
      const isDailyInvoice = frequency === 'daily' && !isDirectSend
      const effectiveConditions = isDirectSend
        ? { ...conditions, recipient_emails: recipients }
        : isDailyInvoice
          ? { ...conditions, due_date_relative: dueDateRelative }
          : conditions
      const payload = {
        name,
        email_template_id: Number(templateId),
        email_schedule_type: scheduleType,
        report_frequency: frequency,
        day_of_month: !['on_demand', 'daily'].includes(frequency) && dayOfMonth ? Number(dayOfMonth) : undefined,
        time_of_day: `${timeOfDay}:00`,
        timezone,
        conditions: effectiveConditions,
        max_reminders: isDirectSend ? undefined : (maxReminders ? Number(maxReminders) : undefined),
        escalation_after: isDirectSend ? undefined : (escalationAfter ? Number(escalationAfter) : undefined),
        include_submission_link: false,
        project_id: projectId ? Number(projectId) : undefined,
      }
      if (isEdit) {
        await client.updateSchedule(schedule!.id, payload)
      } else {
        await client.createSchedule(payload as Parameters<typeof client.createSchedule>[0])
      }
      onOpenChange(false)
      onSaved?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save schedule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Schedule' : 'Create Schedule'}</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="p-2 text-sm text-red-600 bg-red-50 rounded border border-red-200">{error}</div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Monthly Invoice Reminder"
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Project</label>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : '')}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
            >
              <option value="">All Projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.sage_id ? `${p.sage_id} - ${p.name}` : p.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Template</label>
            <select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : '')}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
            >
              <option value="">Select...</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Frequency</label>
              <select
                value={frequency}
                onChange={(e) => setFrequency(e.target.value as ReportFrequency)}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
              >
                {FREQUENCIES.map((f) => (
                  <option key={f} value={f}>{f.replace('_', ' ')}</option>
                ))}
              </select>
            </div>
            {!['on_demand', 'daily'].includes(frequency) && (
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Day of Month</label>
                <input
                  type="number"
                  min={1}
                  max={28}
                  value={dayOfMonth}
                  onChange={(e) => setDayOfMonth(e.target.value ? Number(e.target.value) : '')}
                  className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
                />
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Time</label>
              <div className="flex items-center border border-slate-200 rounded-lg focus-within:border-blue-400 overflow-hidden bg-white">
                <input
                  type="time"
                  value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)}
                  className="w-[70px] px-2 py-2 text-sm border-0 focus:outline-none bg-transparent [&::-webkit-calendar-picker-indicator]:hidden"
                />
                <div className="relative border-l border-slate-200">
                  <select
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz.value} value={tz.value}>{tz.label}</option>
                    ))}
                  </select>
                  <div className="px-1 py-0.5 text-center pointer-events-none leading-tight">
                    <div className="text-[10px] font-medium text-slate-600">{TIMEZONES.find((tz) => tz.value === timezone)?.line1}</div>
                    <div className="text-[9px] text-slate-400">{TIMEZONES.find((tz) => tz.value === timezone)?.line2}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {isDirectSend ? (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Recipients</label>
              <RecipientPicker value={recipients} onChange={setRecipients} client={client} />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Conditions</label>
                <ConditionsBuilder value={conditions} onChange={setConditions} />
              </div>

              {frequency === 'daily' && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Due Date Timing</label>
                  <DueDateTimingBuilder value={dueDateRelative} onChange={setDueDateRelative} />
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !name || !templateId || (isDirectSend && recipients.length === 0)}>
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
            {isEdit ? 'Update' : 'Create'} Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
