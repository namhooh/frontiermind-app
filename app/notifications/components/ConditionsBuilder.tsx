'use client'

const INVOICE_STATUSES = ['draft', 'sent', 'verified', 'disputed', 'paid']

interface ConditionsBuilderProps {
  value: Record<string, unknown>
  onChange: (conditions: Record<string, unknown>) => void
}

export function ConditionsBuilder({ value, onChange }: ConditionsBuilderProps) {
  const selectedStatuses = (value.invoice_status as string[]) || []
  const daysOverdueMin = (value.days_overdue_min as number) ?? ''
  const daysOverdueMax = (value.days_overdue_max as number) ?? ''
  const minAmount = (value.min_amount as number) ?? ''
  const maxAmount = (value.max_amount as number) ?? ''

  function update(key: string, val: unknown) {
    const next = { ...value }
    if (val === '' || val === null || val === undefined || (Array.isArray(val) && val.length === 0)) {
      delete next[key]
    } else {
      next[key] = val
    }
    onChange(next)
  }

  function toggleStatus(s: string) {
    const current = [...selectedStatuses]
    const idx = current.indexOf(s)
    if (idx >= 0) current.splice(idx, 1)
    else current.push(s)
    update('invoice_status', current)
  }

  return (
    <div className="space-y-4">
      {/* Invoice Status */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1.5">Invoice Status</label>
        <div className="flex flex-wrap gap-2">
          {INVOICE_STATUSES.map((s) => (
            <label key={s} className="inline-flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={selectedStatuses.includes(s)}
                onChange={() => toggleStatus(s)}
                className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="capitalize text-slate-700">{s}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Days Overdue */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Days Overdue (min)</label>
          <input
            type="number"
            min={0}
            value={daysOverdueMin}
            onChange={(e) => update('days_overdue_min', e.target.value ? Number(e.target.value) : '')}
            placeholder="0"
            className="w-full px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Days Overdue (max)</label>
          <input
            type="number"
            min={0}
            value={daysOverdueMax}
            onChange={(e) => update('days_overdue_max', e.target.value ? Number(e.target.value) : '')}
            placeholder="30"
            className="w-full px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
          />
        </div>
      </div>

      {/* Amount Range */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Min Amount</label>
          <input
            type="number"
            min={0}
            step={100}
            value={minAmount}
            onChange={(e) => update('min_amount', e.target.value ? Number(e.target.value) : '')}
            placeholder="0"
            className="w-full px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Max Amount</label>
          <input
            type="number"
            min={0}
            step={100}
            value={maxAmount}
            onChange={(e) => update('max_amount', e.target.value ? Number(e.target.value) : '')}
            placeholder="No limit"
            className="w-full px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
          />
        </div>
      </div>
    </div>
  )
}
