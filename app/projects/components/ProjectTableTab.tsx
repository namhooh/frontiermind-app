'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Plus, Trash2, Loader2, Check, X } from 'lucide-react'
import type { PatchEntity } from '@/lib/api/adminClient'
import { EditableCell } from './EditableCell'

export interface Column {
  key: string
  label: string
  editable?: boolean
  editKey?: string    // DB column name if different from key
  type?: 'text' | 'number' | 'date' | 'boolean' | 'select'
  options?: { value: number | string; label: string }[]
  format?: (v: unknown) => string   // Custom display formatter
}

interface ProjectTableTabProps {
  data: Record<string, unknown>[]
  columns: Column[]
  emptyMessage?: string
  entity?: PatchEntity
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
  onAdd?: (fields: Record<string, unknown>) => Promise<void>
  onRemove?: (id: number) => Promise<void>
  addLabel?: string
  footerRow?: Record<string, React.ReactNode>
}

export function ProjectTableTab({
  data,
  columns,
  emptyMessage = 'No data available',
  entity,
  projectId,
  onSaved,
  editMode,
  onAdd,
  onRemove,
  addLabel = 'Add Row',
  footerRow,
}: ProjectTableTabProps) {
  const [showAddRow, setShowAddRow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [removingId, setRemovingId] = useState<number | null>(null)
  const firstInputRef = useRef<HTMLInputElement>(null)

  // Focus the first input when the add row appears
  useEffect(() => {
    if (showAddRow && firstInputRef.current) {
      firstInputRef.current.focus()
    }
  }, [showAddRow])

  // Close add row when edit mode is turned off
  useEffect(() => {
    if (!editMode) {
      setShowAddRow(false)
      setDraft({})
    }
  }, [editMode])

  function handleOpenAddRow() {
    const initial: Record<string, unknown> = {}
    for (const col of columns) {
      if (col.type === 'boolean') initial[col.editKey || col.key] = false
      else initial[col.editKey || col.key] = ''
    }
    setDraft(initial)
    setShowAddRow(true)
  }

  function handleCancelAdd() {
    setShowAddRow(false)
    setDraft({})
  }

  async function handleSaveAdd() {
    if (!onAdd) return
    setSaving(true)
    try {
      // Build clean fields — strip empty strings
      const fields: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(draft)) {
        if (v !== '' && v != null) fields[k] = v
      }
      await onAdd(fields)
      setShowAddRow(false)
      setDraft({})
    } finally {
      setSaving(false)
    }
  }

  function handleAddKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSaveAdd()
    } else if (e.key === 'Escape') {
      handleCancelAdd()
    }
  }

  const updateDraft = useCallback((key: string, value: unknown) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }, [])

  async function handleRemove(id: number) {
    if (!onRemove) return
    setRemovingId(id)
    try {
      await onRemove(id)
    } finally {
      setRemovingId(null)
    }
  }

  const showActions = editMode && onRemove
  const hasData = data.length > 0 || showAddRow

  return (
    <div>
      {!hasData && !editMode ? (
        <div className="text-center py-12 text-sm text-slate-500">
          {emptyMessage}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className="text-left px-3 py-2 text-xs font-medium text-slate-500 uppercase tracking-wider"
                  >
                    {col.label}
                  </th>
                ))}
                {showActions && (
                  <th className="w-10 px-3 py-2" />
                )}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-2 text-slate-700">
                      {col.editable && entity && row.id != null && editMode ? (
                        <EditableCell
                          value={col.type === 'select' ? row[(col.editKey || col.key)] : row[col.key]}
                          fieldKey={col.editKey || col.key}
                          entity={entity}
                          entityId={row.id as number}
                          projectId={projectId}
                          type={col.type}
                          options={col.options}
                          editMode={true}
                          onSaved={onSaved}
                          formatDisplay={col.format}
                        />
                      ) : (
                        col.format ? col.format(row[col.key]) : formatValue(row[col.key])
                      )}
                    </td>
                  ))}
                  {showActions && (
                    <td className="px-3 py-2">
                      {removingId === row.id ? (
                        <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                      ) : (
                        <button
                          onClick={() => handleRemove(row.id as number)}
                          className="text-slate-400 hover:text-red-500 transition-colors"
                          title="Remove"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}

              {/* Inline add row */}
              {showAddRow && (
                <tr className="border-b border-blue-200 bg-blue-50/50">
                  {columns.map((col, colIdx) => {
                    const fieldKey = col.editKey || col.key
                    return (
                      <td key={col.key} className="px-3 py-2">
                        {col.type === 'boolean' ? (
                          <input
                            type="checkbox"
                            checked={!!draft[fieldKey]}
                            onChange={(e) => updateDraft(fieldKey, e.target.checked)}
                            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                          />
                        ) : col.type === 'select' && col.options ? (
                          <select
                            value={String(draft[fieldKey] ?? '')}
                            onChange={(e) => {
                              const v = fieldKey.endsWith('_id') ? Number(e.target.value) : e.target.value
                              updateDraft(fieldKey, v)
                            }}
                            onKeyDown={handleAddKeyDown}
                            className="w-full min-w-[80px] rounded border border-blue-300 bg-white px-1.5 py-1 text-sm text-slate-900 outline-none focus:ring-1 focus:ring-blue-400"
                          >
                            <option value="">— select —</option>
                            {col.options.map((opt) => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            ref={colIdx === 0 ? firstInputRef : undefined}
                            type={col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : 'text'}
                            step={col.type === 'number' ? 'any' : undefined}
                            value={String(draft[fieldKey] ?? '')}
                            onChange={(e) => {
                              const v = col.type === 'number' && e.target.value !== ''
                                ? Number(e.target.value)
                                : e.target.value
                              updateDraft(fieldKey, v)
                            }}
                            onKeyDown={handleAddKeyDown}
                            placeholder={col.label}
                            className="w-full min-w-[80px] rounded border border-blue-300 bg-white px-1.5 py-1 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:ring-1 focus:ring-blue-400"
                          />
                        )}
                      </td>
                    )
                  })}
                  {showActions && (
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        {saving ? (
                          <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                        ) : (
                          <>
                            <button
                              onClick={handleSaveAdd}
                              className="text-green-600 hover:text-green-700 transition-colors"
                              title="Save"
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              onClick={handleCancelAdd}
                              className="text-slate-400 hover:text-red-500 transition-colors"
                              title="Cancel"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              )}
              {/* Footer summary row */}
              {footerRow && data.length > 0 && (
                <tr className="border-t border-slate-300 bg-slate-50 font-medium">
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-2 text-slate-800 text-xs">
                      {footerRow[col.key] ?? ''}
                    </td>
                  ))}
                  {showActions && <td className="px-3 py-2" />}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {editMode && onAdd && !showAddRow && (
        <button
          onClick={handleOpenAddRow}
          className="mt-3 flex items-center gap-1.5 rounded-md border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50 transition-colors"
        >
          <Plus className="h-4 w-4" />
          {addLabel}
        </button>
      )}
    </div>
  )
}

function formatValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'number') return value.toLocaleString('en-US', { maximumFractionDigits: 10 })
  // If it looks like a plain number string, format it too
  if (typeof value === 'string' && value !== '' && !isNaN(Number(value)) && !/^\d{4}-\d{2}/.test(value)) {
    return Number(value).toLocaleString('en-US', { maximumFractionDigits: 10 })
  }
  return String(value)
}
