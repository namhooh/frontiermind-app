'use client'

export interface DueDateRelativeConfig {
  days_before?: number
  on_due_date?: boolean
  days_after_start?: number
  days_after_interval?: number
}

interface DueDateTimingBuilderProps {
  value: DueDateRelativeConfig
  onChange: (value: DueDateRelativeConfig) => void
}

export function DueDateTimingBuilder({ value, onChange }: DueDateTimingBuilderProps) {
  const hasBefore = value.days_before != null && value.days_before > 0
  const hasOnDue = value.on_due_date === true
  const hasAfter = value.days_after_start != null && value.days_after_start > 0

  return (
    <div className="space-y-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
      {/* Before due date */}
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={hasBefore}
          onChange={(e) => {
            if (e.target.checked) {
              onChange({ ...value, days_before: 7 })
            } else {
              const { days_before: _, ...rest } = value
              onChange(rest)
            }
          }}
          className="rounded border-slate-300"
        />
        <span className="text-sm text-slate-700">Send</span>
        {hasBefore && (
          <input
            type="number"
            min={1}
            max={90}
            value={value.days_before ?? 7}
            onChange={(e) => onChange({ ...value, days_before: Number(e.target.value) || 1 })}
            className="w-16 px-2 py-1 text-sm border border-slate-200 rounded focus:outline-none focus:border-blue-400 text-center"
          />
        )}
        <span className="text-sm text-slate-700">days BEFORE due date</span>
      </label>

      {/* On due date */}
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={hasOnDue}
          onChange={(e) => onChange({ ...value, on_due_date: e.target.checked || undefined })}
          className="rounded border-slate-300"
        />
        <span className="text-sm text-slate-700">Send ON the due date</span>
      </label>

      {/* After due date */}
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={hasAfter}
          onChange={(e) => {
            if (e.target.checked) {
              onChange({ ...value, days_after_start: 1, days_after_interval: 7 })
            } else {
              const { days_after_start: _, days_after_interval: __, ...rest } = value
              onChange(rest)
            }
          }}
          className="rounded border-slate-300"
        />
        <span className="text-sm text-slate-700">Send AFTER due date</span>
      </label>
      {hasAfter && (
        <div className="ml-8 flex items-center gap-2 text-sm text-slate-600">
          <span>starting</span>
          <input
            type="number"
            min={1}
            max={90}
            value={value.days_after_start ?? 1}
            onChange={(e) => onChange({ ...value, days_after_start: Number(e.target.value) || 1 })}
            className="w-16 px-2 py-1 border border-slate-200 rounded focus:outline-none focus:border-blue-400 text-center"
          />
          <span>days after, every</span>
          <input
            type="number"
            min={1}
            max={90}
            value={value.days_after_interval ?? 7}
            onChange={(e) => onChange({ ...value, days_after_interval: Number(e.target.value) || 1 })}
            className="w-16 px-2 py-1 border border-slate-200 rounded focus:outline-none focus:border-blue-400 text-center"
          />
          <span>days</span>
        </div>
      )}
    </div>
  )
}

/** Produce a human-readable summary of a due_date_relative config. */
export function describeDueDateTiming(config: DueDateRelativeConfig): string {
  const parts: string[] = []
  if (config.days_before) parts.push(`${config.days_before}d before`)
  if (config.on_due_date) parts.push('on due date')
  if (config.days_after_start && config.days_after_interval) {
    parts.push(`every ${config.days_after_interval}d after`)
  }
  return parts.length > 0 ? parts.join(', ') : 'no timing configured'
}
