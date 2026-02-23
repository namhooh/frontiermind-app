/**
 * Conversion utilities between DB rows, SheetJS workbooks, and Univer IWorkbookData.
 */

import type { IWorkbookData, IWorksheetData, ICellData, LocaleType } from '@univerjs/core'
import type { SpreadsheetColumnMeta } from '@/lib/api/adminClient'
import * as XLSX from 'xlsx'

// ============================================================================
// DB Rows → Univer IWorkbookData
// ============================================================================

export function dbRowsToWorkbookData(
  tableName: string,
  columns: SpreadsheetColumnMeta[],
  rows: Record<string, unknown>[],
): IWorkbookData {
  const sheetId = 'sheet_1'
  const columnNames = columns.map((c) => c.name)

  // Build cell data: row 0 = headers, rows 1..N = data
  const cellData: Record<number, Record<number, ICellData>> = {}

  // Header row
  cellData[0] = {}
  columnNames.forEach((name, colIdx) => {
    cellData[0][colIdx] = { v: name, t: 1 } // t=1 is string in Univer
  })

  // Data rows
  rows.forEach((row, rowIdx) => {
    cellData[rowIdx + 1] = {}
    columnNames.forEach((col, colIdx) => {
      const val = row[col]
      cellData[rowIdx + 1][colIdx] = valueToCellData(val)
    })
  })

  const sheetData: Partial<IWorksheetData> = {
    id: sheetId,
    name: tableName,
    tabColor: '',
    rowCount: rows.length + 1 + 20, // data + header + buffer
    columnCount: Math.max(columnNames.length + 5, 26),
    cellData,
  }

  return {
    id: 'workbook_1',
    name: tableName,
    appVersion: '1.0.0',
    locale: 'enUS' as LocaleType,
    styles: {},
    sheetOrder: [sheetId],
    sheets: { [sheetId]: sheetData },
  }
}

function valueToCellData(val: unknown): ICellData {
  if (val === null || val === undefined) {
    return { v: '' }
  }
  if (typeof val === 'number') {
    return { v: val, t: 2 } // t=2 is number
  }
  if (typeof val === 'boolean') {
    return { v: val ? 'TRUE' : 'FALSE', t: 1 }
  }
  if (typeof val === 'object') {
    return { v: JSON.stringify(val), t: 1 }
  }
  // Try to detect numbers in strings
  const str = String(val)
  const num = Number(str)
  if (str !== '' && !isNaN(num) && isFinite(num)) {
    return { v: num, t: 2 }
  }
  return { v: str, t: 1 }
}

// ============================================================================
// SheetJS Workbook → Univer IWorkbookData
// ============================================================================

export function sheetJSToWorkbookData(wb: XLSX.WorkBook): IWorkbookData {
  const sheetOrder: string[] = []
  const sheets: Record<string, Partial<IWorksheetData>> = {}

  wb.SheetNames.forEach((name, idx) => {
    const sheetId = `sheet_${idx + 1}`
    sheetOrder.push(sheetId)
    const ws = wb.Sheets[name]
    const range = XLSX.utils.decode_range(ws['!ref'] || 'A1')
    const rowCount = range.e.r + 1 + 20
    const columnCount = Math.max(range.e.c + 1 + 5, 26)

    const cellData: Record<number, Record<number, ICellData>> = {}

    for (let r = range.s.r; r <= range.e.r; r++) {
      cellData[r] = {}
      for (let c = range.s.c; c <= range.e.c; c++) {
        const addr = XLSX.utils.encode_cell({ r, c })
        const cell = ws[addr] as XLSX.CellObject | undefined
        if (cell) {
          cellData[r][c] = sheetJSCellToUniver(cell)
        }
      }
    }

    sheets[sheetId] = {
      id: sheetId,
      name,
      tabColor: '',
      rowCount,
      columnCount,
      cellData,
    }
  })

  return {
    id: 'workbook_import',
    name: wb.SheetNames[0] || 'Imported',
    appVersion: '1.0.0',
    locale: 'enUS' as LocaleType,
    styles: {},
    sheetOrder,
    sheets,
  }
}

function sheetJSCellToUniver(cell: XLSX.CellObject): ICellData {
  if (cell.t === 'n') {
    return { v: cell.v as number, t: 2 }
  }
  if (cell.t === 'b') {
    return { v: cell.v ? 'TRUE' : 'FALSE', t: 1 }
  }
  if (cell.t === 's') {
    return { v: cell.v as string, t: 1 }
  }
  if (cell.t === 'd') {
    return { v: (cell.v as Date).toISOString(), t: 1 }
  }
  // Fallback
  return { v: cell.w ?? String(cell.v ?? ''), t: 1 }
}

// ============================================================================
// Univer IWorkbookData → SheetJS Workbook (for export)
// ============================================================================

export function workbookDataToSheetJS(data: IWorkbookData): XLSX.WorkBook {
  const wb = XLSX.utils.book_new()

  data.sheetOrder.forEach((sheetId) => {
    const sheetData = data.sheets[sheetId]
    if (!sheetData) return

    const { cellData, name, rowCount = 100, columnCount = 26 } = sheetData
    const aoa: (string | number | boolean | null)[][] = []

    const maxRow = Math.min(rowCount, 50000)
    const maxCol = Math.min(columnCount, 200)

    for (let r = 0; r < maxRow; r++) {
      const row: (string | number | boolean | null)[] = []
      let hasContent = false
      for (let c = 0; c < maxCol; c++) {
        const cell = cellData?.[r]?.[c]
        if (cell && cell.v !== undefined && cell.v !== null && cell.v !== '') {
          row.push(cell.v as string | number)
          hasContent = true
        } else {
          row.push(null)
        }
      }
      if (hasContent || aoa.length > 0) {
        aoa.push(row)
      }
    }

    // Trim trailing empty rows
    while (aoa.length > 0 && aoa[aoa.length - 1].every((v) => v === null)) {
      aoa.pop()
    }

    const ws = XLSX.utils.aoa_to_sheet(aoa)
    XLSX.utils.book_append_sheet(wb, ws, name || `Sheet${data.sheetOrder.indexOf(sheetId) + 1}`)
  })

  return wb
}

// ============================================================================
// Diff Detector: compare original vs current snapshot
// ============================================================================

export interface CellDiff {
  row_id: number
  column: string
  value: unknown
}

export interface DetectChangesResult {
  changes: CellDiff[]
  deletions: number[]
}

// Columns that must never be sent as cell-level updates
const PROTECTED_COLUMNS = new Set([
  'id',
  'created_at',
  'updated_at',
  'ingested_at',
  'project_id',
  'organization_id',
  // Foreign keys — must not be user-editable
  'counterparty_id',
  'contract_id',
  'tariff_type_id',
  'currency_id',
  'meter_id',
  'asset_type_id',
  'vendor_id',
  'meter_type_id',
  'asset_id',
  'clause_tariff_id',
  'billing_period_id',
  'exchange_rate_id',
  'escalation_base_index_id',
])

export function detectChanges(
  original: { columns: string[]; rows: Record<string, unknown>[] },
  currentSnapshot: IWorkbookData,
): DetectChangesResult {
  const changes: CellDiff[] = []
  const deletions: number[] = []

  // Use the first sheet
  const sheetId = currentSnapshot.sheetOrder[0]
  if (!sheetId) return { changes, deletions }
  const sheetData = currentSnapshot.sheets[sheetId]
  if (!sheetData?.cellData) return { changes, deletions }

  const columns = original.columns

  // Row 0 = headers, rows 1..N = data
  original.rows.forEach((origRow, rowIdx) => {
    const id = origRow.id as number
    if (id == null) return

    // Collect per-row diffs and track whether all editable cells are empty
    const rowDiffs: CellDiff[] = []
    let allEditableEmpty = true
    let anyChanged = false

    columns.forEach((col, colIdx) => {
      if (PROTECTED_COLUMNS.has(col)) return

      const currentCell = sheetData.cellData?.[rowIdx + 1]?.[colIdx]
      const currentVal = currentCell?.v ?? null
      const origVal = origRow[col]

      // Normalize for comparison
      const origStr = origVal == null ? '' : String(origVal)
      const curStr = currentVal == null ? '' : String(currentVal)

      if (curStr !== '') {
        allEditableEmpty = false
      }

      if (origStr !== curStr) {
        anyChanged = true
        let finalVal: unknown = currentVal
        if (curStr === '') finalVal = null
        rowDiffs.push({ row_id: id, column: col, value: finalVal })
      }
    })

    if (allEditableEmpty && anyChanged) {
      // All editable columns are now empty and something changed — delete the row
      deletions.push(id)
    } else {
      // Normal cell-level updates
      changes.push(...rowDiffs)
    }
  })

  return { changes, deletions }
}
