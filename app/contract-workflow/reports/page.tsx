'use client'

/**
 * Reports Page
 *
 * Standalone page for viewing and managing generated reports.
 * Provides report history, filtering, and generation capabilities.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { FileText, Plus, ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { ReportsList } from './components/ReportsList'
import { GenerateReportDialog } from './components/GenerateReportDialog'
import { ReportsClient, ReportsAPIError } from '@/lib/api'
import { createClient } from '@/lib/supabase/client'
import type { GenerateReportRequest } from '@/lib/api'

export default function ReportsPage() {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const supabase = useRef(createClient())
  const [organizationId, setOrganizationId] = useState<number | undefined>()

  useEffect(() => {
    async function loadOrg() {
      const { data: { user } } = await supabase.current.auth.getUser()
      if (user) {
        const { data } = await supabase.current
          .from('role')
          .select('organization_id')
          .eq('user_id', user.id)
          .eq('is_active', true)
          .limit(1)
          .single()
        if (data) setOrganizationId(data.organization_id)
      }
    }
    loadOrg()
  }, [])

  const reportsClient = useMemo(
    () =>
      new ReportsClient({
        enableLogging: process.env.NODE_ENV === 'development',
        getAuthToken: async () => {
          const { data: { session } } = await supabase.current.auth.getSession()
          return session?.access_token ?? null
        },
        organizationId,
      }),
    [organizationId]
  )

  const handleGenerateReport = async (request: GenerateReportRequest) => {
    setIsGenerating(true)
    setError(null)

    try {
      await reportsClient.generateReport(request)
      setIsDialogOpen(false)
      // Trigger refresh of the reports list
      setRefreshTrigger((prev) => prev + 1)
    } catch (err) {
      if (err instanceof ReportsAPIError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to generate report')
      }
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back to Workflow
                </Button>
              </Link>
              <div className="h-6 w-px bg-slate-200" />
              <div>
                <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
                  <FileText className="w-6 h-6" />
                  Reports
                </h1>
                <p className="text-sm text-slate-500 mt-0.5">
                  View and manage generated reports
                </p>
              </div>
            </div>
            <Button onClick={() => setIsDialogOpen(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Generate Report
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* Error Banner */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-700">{error}</p>
            <button
              onClick={() => setError(null)}
              className="mt-2 text-sm text-red-600 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Reports Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              Generated Reports
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ReportsList refreshTrigger={refreshTrigger} reportsClient={reportsClient} />
          </CardContent>
        </Card>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white mt-auto">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between text-sm text-slate-500">
            <p>FrontierMind - Contract Compliance & Invoicing Engine</p>
            <p>
              Backend:{' '}
              <code className="px-2 py-0.5 bg-slate-100 rounded text-xs">
                {process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || 'http://localhost:8000'}
              </code>
            </p>
          </div>
        </div>
      </footer>

      {/* Generate Report Dialog */}
      <GenerateReportDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onSubmit={handleGenerateReport}
        isLoading={isGenerating}
      />
    </div>
  )
}
