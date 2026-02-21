'use client'

/**
 * WorkflowDashboard
 *
 * Main orchestrator component for the 5-step workflow testing dashboard.
 * Manages navigation between steps and provides the workflow context.
 */

import { useWorkflow } from '@/lib/workflow'
import { WorkflowStepper } from './WorkflowStepper'
import { ContractUploadStep } from './steps/ContractUploadStep'
import { ClauseReviewStep } from './steps/ClauseReviewStep'
import { MeterDataStep } from './steps/MeterDataStep'
import { InvoiceGenerationStep } from './steps/InvoiceGenerationStep'
import { ReportGenerationStep } from './steps/ReportGenerationStep'
import { RefreshCw, FileText, ArrowLeft } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import Link from 'next/link'

function WorkflowContent() {
  const { state, resetWorkflow } = useWorkflow()
  const { currentStep } = state

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">
                FrontierMind Workflow Testing
              </h1>
              <p className="text-sm text-slate-500 mt-1">
                Contract Compliance & Invoice Generation Pipeline
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link href="/">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Home
                </Button>
              </Link>
              <Link href="/contract-workflow/reports">
                <Button variant="outline" size="sm">
                  <FileText className="w-4 h-4 mr-2" />
                  View Reports
                </Button>
              </Link>
              <Button variant="outline" size="sm" onClick={resetWorkflow}>
                <RefreshCw className="w-4 h-4 mr-2" />
                Reset Workflow
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Stepper */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-6">
          <WorkflowStepper />
        </div>
      </div>

      {/* Step Content */}
      <main className="max-w-4xl mx-auto px-6 py-8">
        {currentStep === 1 && <ContractUploadStep />}
        {currentStep === 2 && <ClauseReviewStep />}
        {currentStep === 3 && <MeterDataStep />}
        {currentStep === 4 && <InvoiceGenerationStep />}
        {currentStep === 5 && <ReportGenerationStep />}
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
    </div>
  )
}

export function WorkflowDashboard() {
  return <WorkflowContent />
}
