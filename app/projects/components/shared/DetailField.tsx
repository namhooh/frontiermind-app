export function DetailField({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null
  const text = String(value)
  return (
    <div className="mt-2 py-1">
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="text-sm text-slate-900 mt-0.5 whitespace-pre-line">{text}</dd>
    </div>
  )
}
