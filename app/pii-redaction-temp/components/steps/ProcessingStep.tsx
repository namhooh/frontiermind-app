'use client'

import { Loader2, AlertCircle, Check } from 'lucide-react'
import { usePIIRedaction, type ProcessingStage } from '@/lib/pii-redaction-temp'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { cn } from '@/app/components/ui/cn'

const stages: { key: ProcessingStage; label: string }[] = [
  { key: 'uploading', label: 'Uploading document...' },
  { key: 'parsing', label: 'Parsing document with OCR...' },
  { key: 'detecting', label: 'Detecting PII entities...' },
  { key: 'anonymizing', label: 'Anonymizing sensitive data...' },
  { key: 'complete', label: 'Processing complete' },
]

export function ProcessingStep() {
  const { state, reset } = usePIIRedaction()

  const currentStageIndex = stages.findIndex((s) => s.key === state.processingStage)

  if (state.processingStage === 'error') {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-red-600">
            <AlertCircle className="w-5 h-5" />
            Processing Failed
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">
              {state.processingError || 'An unexpected error occurred during processing.'}
            </p>
          </div>
          <Button variant="outline" onClick={reset}>
            Try Again
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Processing Document</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-slate-500">
          Processing <span className="font-medium text-slate-700">{state.fileName}</span>
        </p>

        <div className="space-y-3">
          {stages.map((stage, index) => {
            const isActive = index === currentStageIndex
            const isComplete = index < currentStageIndex
            const isPending = index > currentStageIndex

            return (
              <div
                key={stage.key}
                className={cn(
                  'flex items-center gap-3 p-3 rounded-lg transition-all',
                  isActive && 'bg-blue-50 border border-blue-200',
                  isComplete && 'bg-emerald-50 border border-emerald-200',
                  isPending && 'bg-slate-50 border border-slate-100'
                )}
              >
                {isComplete && <Check className="w-5 h-5 text-emerald-500 flex-shrink-0" />}
                {isActive && <Loader2 className="w-5 h-5 text-blue-500 animate-spin flex-shrink-0" />}
                {isPending && <div className="w-5 h-5 rounded-full border-2 border-slate-300 flex-shrink-0" />}

                <span
                  className={cn(
                    'text-sm',
                    isActive && 'text-blue-700 font-medium',
                    isComplete && 'text-emerald-700',
                    isPending && 'text-slate-400'
                  )}
                >
                  {stage.label}
                </span>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
