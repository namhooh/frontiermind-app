import { DashboardShell } from './dashboard/components/DashboardShell'

export default function Home() {
  return (
    <div className="fixed inset-0 flex bg-background z-50">
      <DashboardShell />
    </div>
  )
}
