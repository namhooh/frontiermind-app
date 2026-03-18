'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Send, Loader2 } from 'lucide-react'
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
} from '@/lib/api/notificationsClient'
import { RecipientPicker } from './RecipientPicker'
import { TemplatePreview } from './TemplatePreview'

interface ComposeEmailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  client: NotificationsClient
  projectId?: number
  onSent?: () => void
}

export function ComposeEmailDialog({ open, onOpenChange, client, projectId, onSent }: ComposeEmailDialogProps) {
  const [recipients, setRecipients] = useState<string[]>([])
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('')
  const [subject, setSubject] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [editMode, setEditMode] = useState<'html' | 'text'>('html')
  const [bodyText, setBodyText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function htmlToPlainText(html: string): string {
    return html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/p>/gi, '\n\n')
      .replace(/<\/div>/gi, '\n')
      .replace(/<\/li>/gi, '\n')
      .replace(/<li[^>]*>/gi, '- ')
      .replace(/<[^>]+>/g, '')
      .replace(/&nbsp;/gi, ' ')
      .replace(/&amp;/gi, '&')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
      .replace(/&quot;/gi, '"')
      .replace(/&#39;/gi, "'")
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }

  function plainTextToHtml(text: string): string {
    return text
      .split('\n\n')
      .map(paragraph => {
        const lines = paragraph.split('\n').map(line =>
          line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        )
        return `<p>${lines.join('<br/>')}</p>`
      })
      .join('\n')
  }

  useEffect(() => {
    if (open) {
      client.listTemplates().then(setTemplates).catch(() => {})
      setRecipients([])
      setSelectedTemplateId('')
      setSubject('')
      setBodyHtml('')
      setBodyText('')
      setEditMode('html')
      setPreviewHtml('')
      setError(null)
    }
  }, [open, client])

  // When template is selected, populate subject + body from template
  useEffect(() => {
    if (!selectedTemplateId) {
      setSubject('')
      setBodyHtml('')
      setPreviewHtml('')
      return
    }
    const template = templates.find(t => t.id === Number(selectedTemplateId))
    if (template) {
      setSubject(template.subject_template)
      setBodyHtml(template.body_html)
      setBodyText(htmlToPlainText(template.body_html))
      setEditMode('html')
    }
  }, [selectedTemplateId, templates])

  // Preview from the editable body (debounced)
  const loadPreview = useCallback(async (subjectTpl: string, bodyTpl: string) => {
    setPreviewLoading(true)
    try {
      const { html } = await client.previewTemplate({
        subject_template: subjectTpl,
        body_html: bodyTpl,
      })
      setPreviewHtml(html)
    } catch {
      setPreviewHtml('')
    } finally {
      setPreviewLoading(false)
    }
  }, [client])

  useEffect(() => {
    if (!bodyHtml) {
      setPreviewHtml('')
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadPreview(subject, bodyHtml), 500)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [subject, bodyHtml, loadPreview])

  async function handleSend() {
    if (!selectedTemplateId || recipients.length === 0) return
    setSending(true)
    setError(null)
    try {
      const result = await client.sendEmail({
        template_id: Number(selectedTemplateId),
        recipient_emails: recipients,
        include_submission_link: false,
        subject_override: subject || undefined,
        body_html_override: bodyHtml || undefined,
      })
      onOpenChange(false)
      onSent?.()
      alert(result.message)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send')
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl w-[95vw] max-h-[90vh] h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>Compose Email</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="p-2 text-sm text-red-600 bg-red-50 rounded border border-red-200">{error}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          {/* Left: Form */}
          <div className="space-y-4 overflow-y-auto flex flex-col">
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

            {selectedTemplateId && (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Subject</label>
                  <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="Email subject..."
                    className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
                  />
                </div>

                <div className="flex flex-col flex-1 min-h-0">
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm font-medium text-slate-700">Body</label>
                    <div className="flex rounded-md border border-slate-200 text-xs overflow-hidden">
                      <button
                        type="button"
                        onClick={() => {
                          if (editMode === 'text') {
                            setBodyHtml(plainTextToHtml(bodyText))
                          }
                          setEditMode('html')
                        }}
                        className={`px-2.5 py-1 transition-colors ${editMode === 'html' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
                      >
                        HTML
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (editMode === 'html') {
                            setBodyText(htmlToPlainText(bodyHtml))
                          }
                          setEditMode('text')
                        }}
                        className={`px-2.5 py-1 transition-colors ${editMode === 'text' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
                      >
                        Text
                      </button>
                    </div>
                  </div>
                  {editMode === 'html' ? (
                    <textarea
                      value={bodyHtml}
                      onChange={(e) => setBodyHtml(e.target.value)}
                      placeholder="Email body HTML..."
                      className="w-full flex-1 min-h-[300px] px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white font-mono resize-y"
                    />
                  ) : (
                    <textarea
                      value={bodyText}
                      onChange={(e) => {
                        setBodyText(e.target.value)
                        setBodyHtml(plainTextToHtml(e.target.value))
                      }}
                      placeholder="Email body text..."
                      className="w-full flex-1 min-h-[300px] px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white resize-y"
                    />
                  )}
                </div>
              </>
            )}

          </div>

          {/* Right: Preview */}
          <div className="flex flex-col min-h-[400px]">
            <label className="block text-sm font-medium text-slate-700 mb-1">Preview</label>
            <div className="flex-1 min-h-0">
              <TemplatePreview html={previewHtml} loading={previewLoading} />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={handleSend}
            disabled={sending || !selectedTemplateId || recipients.length === 0}
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
            Send Email
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
