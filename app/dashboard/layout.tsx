export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 flex bg-background z-50">
      {children}
    </div>
  )
}
