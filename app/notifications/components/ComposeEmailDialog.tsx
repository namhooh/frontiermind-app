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
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (open) {
      client.listTemplates().then(setTemplates).catch(() => {})
      setRecipients([])
      setSelectedTemplateId('')
      setPreviewHtml('')
      setError(null)
    }
  }, [open, client])

  const loadPreview = useCallback(async (templateId: number) => {
    setPreviewLoading(true)
    try {
      const { html } = await client.previewTemplate({ template_id: templateId })
      setPreviewHtml(html)
    } catch {
      setPreviewHtml('')
    } finally {
      setPreviewLoading(false)
    }
  }, [client])

  useEffect(() => {
    if (!selectedTemplateId) {
      setPreviewHtml('')
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadPreview(Number(selectedTemplateId)), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [selectedTemplateId, loadPreview])

  async function handleSend() {
    if (!selectedTemplateId || recipients.length === 0) return
    setSending(true)
    setError(null)
    try {
      const result = await client.sendEmail({
        template_id: Number(selectedTemplateId),
        recipient_emails: recipients,
        include_submission_link: false,
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
      <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>Compose Email</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="p-2 text-sm text-red-600 bg-red-50 rounded border border-red-200">{error}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          {/* Left: Form */}
          <div className="space-y-4">
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
