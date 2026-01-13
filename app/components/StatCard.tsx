interface StatCardProps {
  label: string
  value: string | number
}

export default function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="border-2 border-stone-900 rounded-lg p-4 bg-white">
      <div className="text-sm text-stone-600" style={{ fontFamily: 'Space Mono, monospace' }}>
        {label}
      </div>
      <div className="text-2xl font-bold text-stone-900 mt-1">{value}</div>
    </div>
  )
}
