'use client'

/**
 * WorkflowStepper
 *
 * Visual 5-step progress indicator showing the current workflow state.
 * Steps: Upload Contract → Review Clauses → Meter Data → Invoice → Reports
 */

import { Check, Upload, FileSearch, Database, Receipt, FileText } from 'lucide-react'
import { useWorkflow, type WorkflowStep } from '@/lib/workflow'
import { cn } from '@/app/components/ui/cn'

interface StepConfig {
  number: WorkflowStep
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const steps: StepConfig[] = [
  { number: 1, label: 'Upload Contract', icon: Upload },
  { number: 2, label: 'Review Clauses', icon: FileSearch },
  { number: 3, label: 'Meter Data', icon: Database },
  { number: 4, label: 'Invoice', icon: Receipt },
  { number: 5, label: 'Reports', icon: FileText },
]

export function WorkflowStepper() {
  const { state, setStep, canProceedToStep } = useWorkflow()
  const { currentStep } = state

  const handleStepClick = (step: WorkflowStep) => {
    // Can always go back to previous steps
    if (step < currentStep) {
      setStep(step)
      return
    }
    // Can only go forward if allowed
    if (canProceedToStep(step)) {
      setStep(step)
    }
  }

  return (
    <div className="w-full">
      <div className="flex items-center justify-between">
        {steps.map((step, index) => {
          const isCompleted = currentStep > step.number
          const isCurrent = currentStep === step.number
          const isPending = currentStep < step.number
          const canNavigate = step.number < currentStep || canProceedToStep(step.number)

          const Icon = step.icon

          return (
            <div key={step.number} className="flex items-center flex-1 last:flex-initial">
              {/* Step Circle */}
              <button
                onClick={() => handleStepClick(step.number)}
                disabled={!canNavigate}
                className={cn(
                  'flex flex-col items-center gap-2 transition-all',
                  canNavigate ? 'cursor-pointer' : 'cursor-not-allowed'
                )}
              >
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
              </button>

              {/* Connector Line */}
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
