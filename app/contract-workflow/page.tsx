'use client'

/**
 * Home Page
 *
 * Renders the 4-step workflow testing dashboard for the FrontierMind pipeline:
 * 1. Contract Upload → 2. Clause Review → 3. Meter Data Ingestion → 4. Invoice Generation
 */

import { WorkflowProvider } from '@/lib/workflow'
import { WorkflowDashboard } from './components'

export default function Home() {
  return (
    <WorkflowProvider>
      <WorkflowDashboard />
    </WorkflowProvider>
  )
}
