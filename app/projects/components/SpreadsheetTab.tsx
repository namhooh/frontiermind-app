'use client'

import { useEffect, useCallback, useState } from 'react'
import dynamic from 'next/dynamic'
import { Maximize2, Minimize2 } from 'lucide-react'
import { useSpreadsheetData } from './spreadsheet/useSpreadsheetData'
import { SpreadsheetToolbar } from './spreadsheet/SpreadsheetToolbar'
import type { UniverSheetAPI } from './spreadsheet/UniverSheet'

// Dynamic import with SSR disabled — Univer uses canvas rendering
const UniverSheet = dynamic(
  () => import('./spreadsheet/UniverSheet'),
  { ssr: false }
)

interface SpreadsheetTabProps {
  projectId: number | undefined
  editMode: boolean
}

export function SpreadsheetTab({ projectId, editMode }: SpreadsheetTabProps) {
  const {
    tables,
    selectedTable,
    loading,
    workbookData,
    saveStatus,
    error,
    fetchTables,
    loadTableData,
    saveChanges,
    importExcel,
    exportExcel,
    setSelectedTable,
    setUniverAPI,
    setError,
  } = useSpreadsheetData(projectId)

  const [fullscreen, setFullscreen] = useState(false)

  // Fetch table list on mount
  useEffect(() => {
    fetchTables()
  }, [fetchTables])

  // Escape key exits fullscreen
  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  const handleReady = useCallback((api: UniverSheetAPI) => {
    setUniverAPI(api)
  }, [setUniverAPI])

  const content = (
    <div className={fullscreen ? 'flex flex-col h-full bg-white' : 'space-y-4'}>
      <div className={`flex items-center justify-between ${fullscreen ? 'px-4 pt-3 pb-2' : ''}`}>
        <h3 className="text-lg font-semibold text-slate-900">Spreadsheet</h3>
        <button
          onClick={() => setFullscreen(!fullscreen)}
          className="inline-flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
          title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
        >
          {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          {fullscreen ? 'Exit' : 'Fullscreen'}
        </button>
      </div>

      <div className={fullscreen ? 'px-4' : ''}>
        <SpreadsheetToolbar
          tables={tables}
          selectedTable={selectedTable}
          loading={loading}
          saveStatus={saveStatus}
          editMode={editMode}
          onSelectTable={setSelectedTable}
          onLoad={loadTableData}
          onImport={importExcel}
          onExport={exportExcel}
          onSave={saveChanges}
        />
      </div>

      {error && (
        <div className={`flex items-center justify-between rounded-md bg-red-50 border border-red-200 px-4 py-2 ${fullscreen ? 'mx-4' : ''}`}>
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={() => setError(null)}
            className="text-sm text-red-500 hover:text-red-700"
          >
            Dismiss
          </button>
        </div>
      )}

      <div
        className={`rounded-lg border border-slate-200 overflow-hidden ${fullscreen ? 'flex-1 mx-4 mb-4' : ''}`}
        style={fullscreen ? undefined : { height: 600 }}
      >
        {workbookData ? (
          <UniverSheet data={workbookData} onReady={handleReady} />
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-slate-400">
            {loading ? 'Loading...' : 'Select a table and click Load, or import an Excel file'}
          </div>
        )}
      </div>
    </div>
  )

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 bg-white">
        {content}
      </div>
    )
  }

  return content
}
