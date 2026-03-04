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

const SCHEDULE_TYPES: { value: EmailScheduleType; label: string }[] = [
  { value: 'invoice_reminder', label: 'Invoice Reminder' },
  { value: 'invoice_initial', label: 'Invoice Initial' },
  { value: 'invoice_escalation', label: 'Invoice Escalation' },
  { value: 'compliance_alert', label: 'Compliance Alert' },
  { value: 'meter_data_missing', label: 'Meter Data Missing' },
  { value: 'report_ready', label: 'Report Ready' },
  { value: 'custom', label: 'Custom' },
]

const FREQUENCIES = ['monthly', 'quarterly', 'annual', 'on_demand']

const TIMEZONES = [
  'UTC', 'US/Eastern', 'US/Central', 'US/Mountain', 'US/Pacific',
  'Europe/London', 'Europe/Paris', 'Africa/Johannesburg', 'Asia/Tokyo',
]

interface ScheduleFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  client: NotificationsClient
  schedule?: NotificationSchedule
  onSaved?: () => void
}

export function ScheduleFormDialog({ open, onOpenChange, client, schedule, onSaved }: ScheduleFormDialogProps) {
  const isEdit = !!schedule
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [scheduleType, setScheduleType] = useState<EmailScheduleType>('invoice_reminder')
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [frequency, setFrequency] = useState<ReportFrequency>('monthly')
  const [dayOfMonth, setDayOfMonth] = useState<number | ''>(15)
  const [timeOfDay, setTimeOfDay] = useState('09:00')
  const [timezone, setTimezone] = useState('UTC')
  const [conditions, setConditions] = useState<Record<string, unknown>>({})
  const [maxReminders, setMaxReminders] = useState<number | ''>(3)
  const [escalationAfter, setEscalationAfter] = useState<number | ''>(1)
  const [includeSubmissionLink, setIncludeSubmissionLink] = useState(false)

  useEffect(() => {
    if (open) {
      client.listTemplates().then(setTemplates).catch(() => {})
      setError(null)
      if (schedule) {
        setName(schedule.name)
        setScheduleType(schedule.email_schedule_type)
        setTemplateId(schedule.email_template_id)
        setFrequency(schedule.report_frequency as ReportFrequency)
        setDayOfMonth(schedule.day_of_month ?? 15)
        setTimeOfDay(schedule.time_of_day?.slice(0, 5) || '09:00')
        setTimezone(schedule.timezone)
        setConditions(schedule.conditions || {})
        setMaxReminders(schedule.max_reminders ?? 3)
        setEscalationAfter(schedule.escalation_after ?? 1)
        setIncludeSubmissionLink(schedule.include_submission_link)
      } else {
        setName('')
        setScheduleType('invoice_reminder')
        setTemplateId('')
        setFrequency('monthly')
        setDayOfMonth(15)
        setTimeOfDay('09:00')
        setTimezone('UTC')
        setConditions({})
        setMaxReminders(3)
        setEscalationAfter(1)
        setIncludeSubmissionLink(false)
      }
    }
  }, [open, client, schedule])

  async function handleSave() {
    if (!name || !templateId) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        name,
        email_template_id: Number(templateId),
        email_schedule_type: scheduleType,
        report_frequency: frequency,
        day_of_month: frequency !== 'on_demand' && dayOfMonth ? Number(dayOfMonth) : undefined,
        time_of_day: `${timeOfDay}:00`,
        timezone,
        conditions,
        max_reminders: maxReminders ? Number(maxReminders) : undefined,
        escalation_after: escalationAfter ? Number(escalationAfter) : undefined,
        include_submission_link: includeSubmissionLink,
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

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Type</label>
              <select
                value={scheduleType}
                onChange={(e) => setScheduleType(e.target.value as EmailScheduleType)}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
              >
                {SCHEDULE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
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
            {frequency !== 'on_demand' && (
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
              <input
                type="time"
                value={timeOfDay}
                onChange={(e) => setTimeOfDay(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Timezone</label>
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Conditions</label>
            <ConditionsBuilder value={conditions} onChange={setConditions} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Max Reminders</label>
              <input
                type="number"
                min={1}
                value={maxReminders}
                onChange={(e) => setMaxReminders(e.target.value ? Number(e.target.value) : '')}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Escalation After</label>
              <input
                type="number"
                min={1}
                value={escalationAfter}
                onChange={(e) => setEscalationAfter(e.target.value ? Number(e.target.value) : '')}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={includeSubmissionLink}
              onChange={(e) => setIncludeSubmissionLink(e.target.checked)}
              className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            Include submission link
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !name || !templateId}>
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
            {isEdit ? 'Update' : 'Create'} Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
