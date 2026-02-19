'use client'

import { Shield, RotateCcw } from 'lucide-react'
import { usePIIRedaction } from '@/lib/pii-redaction-temp'
import { Button } from '@/app/components/ui/button'
import { PIIRedactionStepper } from './PIIRedactionStepper'
import { UploadStep } from './steps/UploadStep'
import { ProcessingStep } from './steps/ProcessingStep'
import { DownloadStep } from './steps/DownloadStep'

export function PIIRedactionDashboard() {
  const { state, reset } = usePIIRedaction()

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Shield className="w-8 h-8 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold text-slate-900">PII Redaction Tool</h1>
            <p className="text-sm text-slate-500">
              Upload a document, detect PII, and download redacted content
            </p>
          </div>
        </div>
        {state.currentStep > 1 && (
          <Button variant="outline" size="sm" onClick={reset}>
            <RotateCcw className="w-4 h-4 mr-2" />
            Start Over
          </Button>
        )}
      </div>

      {/* Stepper */}
      <div className="mb-8">
        <PIIRedactionStepper />
      </div>

      {/* Step Content */}
      <div>
        {state.currentStep === 1 && <UploadStep />}
        {state.currentStep === 2 && <ProcessingStep />}
        {state.currentStep === 3 && <DownloadStep />}
      </div>
    </div>
  )
}
