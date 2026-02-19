'use client'

import { PIIRedactionProvider } from '@/lib/pii-redaction-temp'
import { PIIRedactionDashboard } from './components/PIIRedactionDashboard'

export default function PIIRedactionTempPage() {
  return (
    <PIIRedactionProvider>
      <div className="min-h-screen bg-slate-50">
        <PIIRedactionDashboard />
      </div>
    </PIIRedactionProvider>
  )
}
