'use client'

import { useRef } from 'react'
import { Upload, Download, Save, Loader2 } from 'lucide-react'
import type { SpreadsheetTable } from '@/lib/api/adminClient'
import type { SaveStatus } from './useSpreadsheetData'

interface SpreadsheetToolbarProps {
  tables: SpreadsheetTable[]
  selectedTable: string
  loading: boolean
  saveStatus: SaveStatus
  editMode: boolean
  onSelectTable: (table: string) => void
  onLoad: (table: string) => void
  onImport: (file: File) => void
  onExport: () => void
  onSave: () => void
}

const STATUS_BADGE: Record<SaveStatus, { label: string; className: string }> = {
  idle: { label: '', className: '' },
  saving: { label: 'Saving...', className: 'bg-blue-100 text-blue-700' },
  saved: { label: 'Saved', className: 'bg-green-100 text-green-700' },
  dirty: { label: 'Unsaved changes', className: 'bg-amber-100 text-amber-700' },
  error: { label: 'Save error', className: 'bg-red-100 text-red-700' },
}

export function SpreadsheetToolbar({
  tables,
  selectedTable,
  loading,
  saveStatus,
  editMode,
  onSelectTable,
  onLoad,
  onImport,
  onExport,
  onSave,
}: SpreadsheetToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const badge = STATUS_BADGE[saveStatus]

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Table selector */}
      <select
        value={selectedTable}
        onChange={(e) => onSelectTable(e.target.value)}
        className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <option value="">Select a table...</option>
        {tables.map((t) => (
          <option key={t.table_name} value={t.table_name}>
            {t.table_name}
          </option>
        ))}
      </select>

      {/* Load button */}
      <button
        onClick={() => selectedTable && onLoad(selectedTable)}
        disabled={!selectedTable || loading}
        className="inline-flex items-center gap-1.5 h-8 px-3 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Load
      </button>

      <div className="w-px h-6 bg-slate-200" />

      {/* Import Excel */}
      <button
        onClick={() => fileInputRef.current?.click()}
        className="inline-flex items-center gap-1.5 h-8 px-3 text-sm rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
      >
        <Upload className="h-3.5 w-3.5" />
        Import
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xlsb,.xls,.csv,.tsv,.ods"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onImport(file)
          // Reset so the same file can be re-imported
          e.target.value = ''
        }}
      />

      {/* Export Excel */}
      <button
        onClick={() => onExport()}
        className="inline-flex items-center gap-1.5 h-8 px-3 text-sm rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
      >
        <Download className="h-3.5 w-3.5" />
        Export
      </button>

      <div className="w-px h-6 bg-slate-200" />

      {/* Save to DB */}
      <button
        onClick={onSave}
        disabled={!selectedTable || saveStatus === 'saving'}
        className="inline-flex items-center gap-1.5 h-8 px-3 text-sm rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {saveStatus === 'saving' ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Save className="h-3.5 w-3.5" />
        )}
        Save to DB
      </button>

      {/* Status badge */}
      {badge.label && (
        <span className={`inline-flex items-center h-6 px-2 text-xs font-medium rounded-full ${badge.className}`}>
          {badge.label}
        </span>
      )}
    </div>
  )
}
