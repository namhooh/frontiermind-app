'use client'

import { Check, Upload, Shield, Download } from 'lucide-react'
import { usePIIRedaction, type PIIRedactionStep } from '@/lib/pii-redaction-temp'
import { cn } from '@/app/components/ui/cn'

interface StepConfig {
  number: PIIRedactionStep
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const steps: StepConfig[] = [
  { number: 1, label: 'Upload', icon: Upload },
  { number: 2, label: 'Process', icon: Shield },
  { number: 3, label: 'Download', icon: Download },
]

export function PIIRedactionStepper() {
  const { state } = usePIIRedaction()
  const { currentStep } = state

  return (
    <div className="w-full">
      <div className="flex items-center justify-between">
        {steps.map((step, index) => {
          const isCompleted = currentStep > step.number
          const isCurrent = currentStep === step.number
          const isPending = currentStep < step.number

          const Icon = step.icon

          return (
            <div key={step.number} className="flex items-center flex-1 last:flex-initial">
              <div className="flex flex-col items-center gap-2">
                <div
                  className={cn(
                    'flex items-center justify-center w-12 h-12 rounded-full border-2 transition-all',
                    isCompleted && 'bg-emerald-500 border-emerald-500 text-white',
                    isCurrent && 'bg-blue-600 border-blue-600 text-white',
                    isPending && 'bg-slate-100 border-slate-300 text-slate-400'
                  )}
                >
                  {isCompleted ? (
                    <Check className="w-6 h-6" />
                  ) : (
                    <Icon className="w-5 h-5" />
                  )}
                </div>
                <span
                  className={cn(
                    'text-sm font-medium whitespace-nowrap',
                    isCompleted && 'text-emerald-600',
                    isCurrent && 'text-blue-600',
                    isPending && 'text-slate-400'
                  )}
                >
                  {step.label}
                </span>
              </div>

              {index < steps.length - 1 && (
                <div className="flex-1 mx-4 h-0.5 relative top-[-12px]">
                  <div
                    className={cn(
                      'h-full transition-all',
                      currentStep > step.number ? 'bg-emerald-500' : 'bg-slate-200'
                    )}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
