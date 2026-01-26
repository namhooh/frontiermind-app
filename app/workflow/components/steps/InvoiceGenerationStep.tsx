'use client'

/**
 * InvoiceGenerationStep
 *
 * Step 4: Generate invoice preview from contract clauses and meter data.
 * Calls rules evaluation API and generates client-side invoice.
 */

import { useState, useMemo } from 'react'
import {
  Receipt,
  Loader2,
  AlertCircle,
  Check,
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  FileText,
} from 'lucide-react'
import { useWorkflow } from '@/lib/workflow'
import { generateInvoicePreview } from '@/lib/workflow/invoiceGenerator'
import { APIClient, ContractsAPIError } from '@/lib/api'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'
import { InvoicePreviewComponent } from '../InvoicePreview'

export function InvoiceGenerationStep() {
  const {
    state,
    setInvoicePreview,
    setRuleEvaluationResult,
    setGeneratingInvoice,
    goToPreviousStep,
    goToNextStep,
    resetWorkflow,
  } = useWorkflow()

  const [error, setError] = useState<string | null>(null)
  const [evaluationAttempted, setEvaluationAttempted] = useState(false)

  const apiClient = useMemo(
    () =>
      new APIClient({
        enableLogging: process.env.NODE_ENV === 'development',
      }),
    []
  )

  const { parseResult, meterDataSummary, invoicePreview, isGeneratingInvoice } = state

  const handleGenerateInvoice = async () => {
    if (!parseResult?.clauses || !meterDataSummary) {
      setError('Missing contract clauses or meter data')
      return
    }

    setGeneratingInvoice(true)
    setError(null)
    setEvaluationAttempted(true)

    try {
      // Try to evaluate rules if we have a contract_id
      let ruleResult = null
      if (parseResult.contract_id > 0) {
        try {
          const periodStart = new Date(meterDataSummary.dateRange.start)
          const periodEnd = new Date(meterDataSummary.dateRange.end)

          ruleResult = await apiClient.evaluateRules(
            parseResult.contract_id,
            periodStart,
            periodEnd
          )
          setRuleEvaluationResult(ruleResult)
        } catch (err) {
          // Rule evaluation is optional - continue without it
          console.warn('Rule evaluation failed, continuing without:', err)
        }
      }

      // Generate invoice preview (client-side)
      const invoice = generateInvoicePreview(
        parseResult.clauses,
        meterDataSummary,
        ruleResult
      )

      setInvoicePreview(invoice)
    } catch (err) {
      if (err instanceof ContractsAPIError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to generate invoice')
      }
    } finally {
      setGeneratingInvoice(false)
    }
  }

  const handleRegenerate = () => {
    setInvoicePreview(null)
    setRuleEvaluationResult(null)
    setError(null)
    setEvaluationAttempted(false)
  }

  // Auto-generate on mount if not already generated
  if (!invoicePreview && !isGeneratingInvoice && !error && !evaluationAttempted) {
    handleGenerateInvoice()
  }

  // Missing prerequisites
  if (!parseResult || !meterDataSummary) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <FileText className="w-12 h-12 mx-auto mb-4 text-slate-300" />
          <p className="text-slate-500">Missing required data.</p>
          <p className="text-sm text-slate-400 mt-2">
            Please complete the previous steps first.
          </p>
          <Button variant="outline" onClick={goToPreviousStep} className="mt-4">
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Meter Data
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Receipt className="w-5 h-5" />
            Invoice Generation
          </span>
          {invoicePreview && (
            <div className="flex items-center gap-2">
              <Badge variant="success">Preview Generated</Badge>
              <Button variant="outline" size="sm" onClick={handleRegenerate}>
                <RefreshCw className="w-4 h-4 mr-2" />
                Regenerate
              </Button>
            </div>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Loading State */}
        {isGeneratingInvoice && (
          <div className="py-12 text-center">
            <Loader2 className="w-12 h-12 mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-slate-600 font-medium">Generating invoice preview...</p>
            <p className="text-sm text-slate-400 mt-2">
              Analyzing contract terms and meter data
            </p>
          </div>
        )}

        {/* Error State */}
        {error && !isGeneratingInvoice && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
              <div className="flex-1">
                <h4 className="font-semibold text-red-900 mb-1">
                  Invoice Generation Failed
                </h4>
                <p className="text-red-700 text-sm">{error}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleGenerateInvoice}
                  className="mt-3"
                >
                  Try Again
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Invoice Preview */}
        {invoicePreview && !isGeneratingInvoice && (
          <>
            {/* Summary Banner */}
            <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
              <div className="flex items-center gap-3">
                <Check className="w-6 h-6 text-emerald-500" />
                <div>
                  <p className="font-medium text-emerald-900">
                    Invoice Preview Generated Successfully
                  </p>
                  <p className="text-sm text-emerald-700">
                    Based on {parseResult.clauses_extracted} contract clauses and{' '}
                    {meterDataSummary.totalRecords} meter readings
                  </p>
                </div>
              </div>
            </div>

            {/* Rule Evaluation Results */}
            {state.ruleEvaluationResult && (
              <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <h4 className="font-medium text-blue-900 mb-2">
                  Compliance Check Results
                </h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-blue-600">Default Events:</span>{' '}
                    <span className="font-medium">
                      {state.ruleEvaluationResult.default_events.length}
                    </span>
                  </div>
                  <div>
                    <span className="text-blue-600">Total LD:</span>{' '}
                    <span className="font-medium text-red-600">
                      ${state.ruleEvaluationResult.ld_total.toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Invoice Preview Component */}
            <InvoicePreviewComponent invoice={invoicePreview} />
          </>
        )}

        {/* Navigation */}
        <div className="flex justify-between pt-4 border-t">
          <Button variant="outline" onClick={goToPreviousStep}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Meter Data
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={resetWorkflow}>
              Start New Workflow
            </Button>
            {invoicePreview && (
              <Button variant="emerald" onClick={goToNextStep}>
                Generate Report
                <FileText className="w-4 h-4 ml-2" />
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
