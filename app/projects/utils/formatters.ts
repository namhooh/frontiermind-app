/**
 * Shared formatting utilities for project dashboard tabs.
 */

/** Format YYYY-MM-DD to "MMM YYYY" (e.g. "Dec 2025") */
export function formatMonth(v: string | null | undefined): string {
  if (!v) return '—'
  const d = new Date(v)
  if (isNaN(d.getTime())) return String(v)
  return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** Format number with locale grouping (e.g. 1,234) */
export function fmtNum(v: number | null | undefined, decimals = 0): string {
  if (v == null) return '—'
  return v.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/** Format currency amount to 2 decimal places */
export function fmtCurrency(v: number | null | undefined, _currency?: string | null): string {
  if (v == null) return '—'
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Format a ratio (0..1) as percentage (e.g. 0.85 → "85.0%") */
export function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(decimals)}%`
}

/** Format a ratio as percentage string */
export function fmtRatio(v: number | null | undefined): string {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

/** Return Tailwind color class for comparison ratios (≥1 = good) */
export function compClass(v: number | null | undefined): string {
  if (v == null) return ''
  if (v >= 1) return 'text-emerald-600'
  return 'text-amber-600'
}

/** Return Tailwind color class for variance percentages */
export function varianceClass(pct: number | null | undefined): string {
  if (pct == null) return ''
  if (pct > 0) return 'text-emerald-600'
  if (pct < 0) return 'text-red-600'
  return ''
}
