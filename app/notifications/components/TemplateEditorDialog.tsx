'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
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
  type EmailTemplate,
  type EmailScheduleType,
} from '@/lib/api/notificationsClient'
import { TemplatePreview } from './TemplatePreview'
import { VariableInsertBar } from './VariableInsertBar'

const SCHEDULE_TYPES: { value: EmailScheduleType; label: string }[] = [
  { value: 'invoice_reminder', label: 'Invoice Reminder' },
  { value: 'invoice_initial', label: 'Invoice Initial' },
  { value: 'invoice_escalation', label: 'Invoice Escalation' },
  { value: 'compliance_alert', label: 'Compliance Alert' },
  { value: 'meter_data_missing', label: 'Meter Data Missing' },
  { value: 'report_ready', label: 'Report Ready' },
  { value: 'custom', label: 'Custom' },
]

const DEFAULT_VARIABLES = [
  'company_name', 'project_name', 'invoice_number', 'invoice_date',
  'due_date', 'total_amount', 'currency', 'billing_period',
  'counterparty_name', 'contract_name', 'submission_url', 'recipient_name',
]

interface TemplateEditorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  client: NotificationsClient
  template?: EmailTemplate
  onSaved?: () => void
}

export function TemplateEditorDialog({ open, onOpenChange, client, template, onSaved }: TemplateEditorDialogProps) {
  const isEdit = !!template
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [scheduleType, setScheduleType] = useState<EmailScheduleType>('custom')
  const [description, setDescription] = useState('')
  const [subjectTemplate, setSubjectTemplate] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [bodyText, setBodyText] = useState('')
  const [showBodyText, setShowBodyText] = useState(false)

  const subjectRef = useRef<HTMLInputElement>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)

  const variables = template?.available_variables?.length
    ? template.available_variables
    : DEFAULT_VARIABLES

  useEffect(() => {
    if (open) {
      setError(null)
      setPreviewHtml('')
      if (template) {
        setName(template.name)
        setScheduleType(template.email_schedule_type)
        setDescription(template.description || '')
        setSubjectTemplate(template.subject_template)
        setBodyHtml(template.body_html)
        setBodyText(template.body_text || '')
        setShowBodyText(!!template.body_text)
      } else {
        setName('')
        setScheduleType('custom')
        setDescription('')
        setSubjectTemplate('')
        setBodyHtml('')
        setBodyText('')
        setShowBodyText(false)
      }
    }
  }, [open, template])

  const loadPreview = useCallback(async (subject: string, html: string) => {
    if (!html) { setPreviewHtml(''); return }
    setPreviewLoading(true)
    try {
      const result = await client.previewTemplate({ subject_template: subject, body_html: html })
      setPreviewHtml(result.html)
    } catch {
      setPreviewHtml('')
    } finally {
      setPreviewLoading(false)
    }
  }, [client])

  // Debounced preview
  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadPreview(subjectTemplate, bodyHtml), 500)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [subjectTemplate, bodyHtml, open, loadPreview])

  async function handleSave() {
    if (!name || !subjectTemplate || !bodyHtml) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        name,
        email_schedule_type: scheduleType,
        subject_template: subjectTemplate,
        body_html: bodyHtml,
        body_text: bodyText || undefined,
        description: description || undefined,
        available_variables: variables as string[],
      }
      if (isEdit) {
        await client.updateTemplate(template!.id, payload)
      } else {
        await client.createTemplate(payload)
      }
      onOpenChange(false)
      onSaved?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save template')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Template' : 'Create Template'}</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="p-2 text-sm text-red-600 bg-red-50 rounded border border-red-200">{error}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Left: Editor */}
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Invoice Reminder"
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
                <label className="block text-sm font-medium text-slate-700 mb-1">Description</label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Optional description"
                  className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Subject</label>
              <input
                ref={subjectRef}
                type="text"
                value={subjectTemplate}
                onChange={(e) => setSubjectTemplate(e.target.value)}
                placeholder="Invoice {{ invoice_number }} — {{ billing_period }}"
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono"
              />
              <VariableInsertBar variables={variables as string[]} targetRef={subjectRef} />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Body HTML</label>
              <textarea
                ref={bodyRef}
                value={bodyHtml}
                onChange={(e) => setBodyHtml(e.target.value)}
                placeholder="<h2>Invoice {{ invoice_number }}</h2>..."
                rows={12}
                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono resize-y"
              />
              <VariableInsertBar variables={variables as string[]} targetRef={bodyRef} />
            </div>

            {!showBodyText ? (
              <button
                type="button"
                onClick={() => setShowBodyText(true)}
                className="text-xs text-blue-600 hover:text-blue-700"
              >
                + Add plain text version
              </button>
            ) : (
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Body Text (optional)</label>
                <textarea
                  value={bodyText}
                  onChange={(e) => setBodyText(e.target.value)}
                  rows={4}
                  className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono resize-y"
                />
              </div>
            )}
          </div>

          {/* Right: Preview */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Live Preview</label>
            <TemplatePreview html={previewHtml} loading={previewLoading} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !name || !subjectTemplate || !bodyHtml}>
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
            {isEdit ? 'Update' : 'Create'} Template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
