'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { adminClient, type PatchEntity } from '@/lib/api/adminClient'

export interface EditableCellProps {
  value: unknown
  fieldKey: string
  entity: PatchEntity
  entityId: number
  projectId?: number
  type?: 'text' | 'number' | 'date' | 'boolean' | 'select'
  options?: { value: number | string; label: string }[]
  editMode: boolean
  onSaved?: () => void
  formatDisplay?: (value: unknown) => string
  scaleOnSave?: number
}

export function EditableCell({
  value,
  fieldKey,
  entity,
  entityId,
  projectId,
  type = 'text',
  options,
  editMode,
  onSaved,
  formatDisplay,
  scaleOnSave,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const selectRef = useRef<HTMLSelectElement>(null)

  const displayValue = formatDisplay ? formatDisplay(value) : type === 'select' ? formatSelect(value, options) : formatDefault(value, type)

  useEffect(() => {
    if (editing) {
      if (type === 'select' && selectRef.current) {
        selectRef.current.focus()
      } else if (type === 'text' && textareaRef.current) {
        const ta = textareaRef.current
        ta.focus()
        ta.select()
        ta.style.height = 'auto'
        ta.style.height = `${ta.scrollHeight}px`
      } else if (inputRef.current) {
        inputRef.current.focus()
        inputRef.current.select()
      }
    }
  }, [editing, type])

  const startEdit = useCallback(() => {
    if (!editMode || saving) return
    if (type === 'boolean') {
      handleSave(!value)
      return
    }
    setDraft(value == null ? '' : String(value))
    setEditing(true)
    setError(false)
  }, [value, saving, type, editMode]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave(newValue?: unknown) {
    let saveValue = newValue !== undefined ? newValue : coerce(draft, type)
    if (scaleOnSave != null && typeof saveValue === 'number') {
      saveValue = saveValue * scaleOnSave
    }
    // Skip save if unchanged
    if (saveValue === value || (saveValue === '' && value == null)) {
      setEditing(false)
      return
    }

    const oldValue = value
    setSaving(true)
    setEditing(false)
    setError(false)
    try {
      await adminClient.patchEntity({
        entity,
        entityId,
        projectId,
        fields: { [fieldKey]: saveValue === '' ? null : saveValue },
      })
      onSaved?.()
      // Show undo toast
      toast('Field updated', {
        action: {
          label: 'Undo',
          onClick: async () => {
            try {
              await adminClient.patchEntity({
                entity,
                entityId,
                projectId,
                fields: { [fieldKey]: oldValue === '' ? null : oldValue ?? null },
              })
              onSaved?.()
            } catch {
              toast.error('Failed to undo')
            }
          },
        },
        duration: 5000,
      })
    } catch {
      setError(true)
      setTimeout(() => setError(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSave()
    } else if (e.key === 'Escape') {
      setEditing(false)
    }
  }

  // When editMode is off, render plain text
  if (!editMode) {
    return <span className="whitespace-pre-line">{displayValue}</span>
  }

  if (saving) {
    return (
      <span className="inline-flex items-center gap-1 text-slate-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span className="text-xs">Saving</span>
      </span>
    )
  }

  if (editing && type === 'select' && options) {
    return (
      <select
        ref={selectRef}
        value={draft}
        onChange={(e) => {
          const selected = e.target.value
          // Coerce to number for _id columns
          const coerced = fieldKey.endsWith('_id') ? Number(selected) : selected
          handleSave(coerced)
        }}
        onBlur={() => setEditing(false)}
        className="w-full min-w-[60px] rounded border border-blue-300 bg-white px-1.5 py-0.5 text-sm text-slate-900 outline-none ring-1 ring-blue-200 focus:ring-blue-400"
      >
        <option value="">— select —</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    )
  }

  if (editing && type === 'text') {
    return (
      <textarea
        ref={textareaRef}
        rows={1}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          e.target.style.height = 'auto'
          e.target.style.height = `${e.target.scrollHeight}px`
        }}
        onBlur={() => handleSave()}
        onKeyDown={handleKeyDown}
        className="w-full min-w-[60px] rounded border border-blue-300 bg-white px-1.5 py-0.5 text-sm text-slate-900 outline-none ring-1 ring-blue-200 focus:ring-blue-400 resize-none overflow-hidden"
      />
    )
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type={type === 'number' ? 'number' : 'date'}
        step={type === 'number' ? 'any' : undefined}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => handleSave()}
        onKeyDown={handleKeyDown}
        className="w-full min-w-[60px] rounded border border-blue-300 bg-white px-1.5 py-0.5 text-sm text-slate-900 outline-none ring-1 ring-blue-200 focus:ring-blue-400"
      />
    )
  }

  return (
    <span
      onClick={startEdit}
      className={`cursor-pointer rounded px-1 -mx-1 transition-colors bg-amber-50 hover:bg-amber-100 ${
        error ? 'ring-2 ring-red-300 bg-red-50' : ''
      }`}
      title="Click to edit"
    >
      {displayValue}
    </span>
  )
}

function formatDefault(value: unknown, type: string): string {
  if (value == null) return '—'
  if (type === 'boolean') return value ? 'Yes' : 'No'
  if (type === 'number' && typeof value === 'number') return value.toLocaleString('en-US', { maximumFractionDigits: 10 })
  if (type === 'number' && typeof value === 'string' && value !== '' && !isNaN(Number(value))) {
    return Number(value).toLocaleString('en-US', { maximumFractionDigits: 10 })
  }
  return String(value)
}

function formatSelect(value: unknown, options?: { value: number | string; label: string }[]): string {
  if (value == null) return '—'
  if (options) {
    const match = options.find((o) => String(o.value) === String(value))
    if (match) return match.label
  }
  return String(value)
}

function coerce(draft: string, type: string): unknown {
  if (type === 'number') {
    const n = Number(draft)
    return isNaN(n) ? draft : n
  }
  return draft
}
