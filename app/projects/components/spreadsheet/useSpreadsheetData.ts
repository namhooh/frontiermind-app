'use client'

import { useState, useCallback, useRef } from 'react'
import type { IWorkbookData } from '@univerjs/core'
import * as XLSX from 'xlsx'
import { adminClient, type SpreadsheetTable, type SpreadsheetColumnMeta } from '@/lib/api/adminClient'
import {
  dbRowsToWorkbookData,
  sheetJSToWorkbookData,
  workbookDataToSheetJS,
  detectChanges,
} from './univerDataConverter'
import type { UniverSheetAPI } from './UniverSheet'

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'dirty' | 'error'

export function useSpreadsheetData(projectId: number | undefined) {
  const [tables, setTables] = useState<SpreadsheetTable[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [workbookData, setWorkbookData] = useState<IWorkbookData | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  // Track original data for diff detection
  const originalRef = useRef<{
    columns: string[]
    rows: Record<string, unknown>[]
    columnsMeta: SpreadsheetColumnMeta[]
  } | null>(null)

  // Track the Univer API instance
  const univerAPIRef = useRef<UniverSheetAPI | null>(null)

  const setUniverAPI = useCallback((api: UniverSheetAPI | null) => {
    univerAPIRef.current = api
  }, [])

  const fetchTables = useCallback(async () => {
    if (!projectId) return
    try {
      const data = await adminClient.getSpreadsheetTables(projectId)
      setTables(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch tables')
    }
  }, [projectId])

  const loadTableData = useCallback(async (tableName: string) => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    setSaveStatus('idle')

    try {
      const result = await adminClient.querySpreadsheetData({
        table: tableName,
        project_id: projectId,
        limit: 50000,
      })

      const colNames = result.columns.map((c) => c.name)
      originalRef.current = {
        columns: colNames,
        rows: result.rows,
        columnsMeta: result.columns,
      }

      const wb = dbRowsToWorkbookData(tableName, result.columns, result.rows)
      setWorkbookData(wb)
      setSelectedTable(tableName)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load table data')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const saveChanges = useCallback(async () => {
    if (!projectId || !selectedTable || !originalRef.current) return
    const api = univerAPIRef.current
    if (!api) return

    const snapshot = api.getSnapshot()
    if (!snapshot) {
      setError('Could not read spreadsheet data')
      return
    }

    const { changes, deletions } = detectChanges(originalRef.current, snapshot)
    if (changes.length === 0 && deletions.length === 0) {
      setSaveStatus('saved')
      return
    }

    setSaveStatus('saving')
    try {
      const result = await adminClient.saveSpreadsheetChanges({
        table: selectedTable,
        project_id: projectId,
        changes,
        ...(deletions.length > 0 ? { deletions } : {}),
      })

      if (result.success) {
        setSaveStatus('saved')
        // Reload to get fresh data
        await loadTableData(selectedTable)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save changes')
      setSaveStatus('error')
    }
  }, [projectId, selectedTable, loadTableData])

  const importExcel = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target?.result as ArrayBuffer)
        const wb = XLSX.read(data)
        const univerData = sheetJSToWorkbookData(wb)
        setWorkbookData(univerData)
        setSelectedTable('')
        originalRef.current = null
        setSaveStatus('idle')
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to parse file')
      }
    }
    reader.readAsArrayBuffer(file)
  }, [])

  const exportExcel = useCallback((filename?: string) => {
    const api = univerAPIRef.current
    if (!api) return

    const snapshot = api.getSnapshot()
    if (!snapshot) {
      setError('Could not read spreadsheet data')
      return
    }

    const wb = workbookDataToSheetJS(snapshot)
    const name = filename || `${selectedTable || 'export'}.xlsx`
    XLSX.writeFile(wb, name)
  }, [selectedTable])

  const markDirty = useCallback(() => {
    if (saveStatus !== 'saving') {
      setSaveStatus('dirty')
    }
  }, [saveStatus])

  return {
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
    markDirty,
    setError,
  }
}
