interface StatCardProps {
  label: string
  value: string | number
}

export default function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="border border-slate-200 rounded-lg p-4 bg-white">
      <div className="text-sm text-slate-500">
        {label}
      </div>
      <div className="text-2xl font-semibold text-slate-900 mt-1">{value}</div>
    </div>
  )
}
