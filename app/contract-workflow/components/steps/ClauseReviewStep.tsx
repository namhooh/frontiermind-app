'use client'

/**
 * ClauseReviewStep
 *
 * Step 2: Review extracted clauses and validate required items.
 * Shows clause details grouped by category with validation status.
 */

import { useEffect, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Tag,
  User,
  Percent,
  ArrowLeft,
  ArrowRight,
} from 'lucide-react'
import { useWorkflow, type ValidationItem } from '@/lib/workflow'
import type { ExtractedClause } from '@/lib/api'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'
import { ValidationBanner } from '../ValidationBanner'
import { cn } from '@/app/components/ui/cn'

interface ClauseGroup {
  category: string
  clauses: ExtractedClause[]
}

function groupClausesByCategory(clauses: ExtractedClause[]): ClauseGroup[] {
  const grouped = clauses.reduce(
    (acc, clause) => {
      // Use new 'category' field with fallback to deprecated 'clause_category'
      const category = clause.category || clause.clause_category || 'Other'
      if (!acc[category]) {
        acc[category] = []
      }
      acc[category].push(clause)
      return acc
    },
    {} as Record<string, ExtractedClause[]>
  )

  return Object.entries(grouped)
    .map(([category, clauses]) => ({ category, clauses }))
    .sort((a, b) => a.category.localeCompare(b.category))
}

function ClauseItem({ clause }: { clause: ExtractedClause }) {
  const [isExpanded, setIsExpanded] = useState(false)

  // Use new extraction_confidence field with fallback to deprecated confidence_score
  const confidence = clause.extraction_confidence ?? clause.confidence_score ?? 0

  const confidenceColor =
    confidence >= 0.8
      ? 'text-emerald-600 bg-emerald-50'
      : confidence >= 0.6
        ? 'text-amber-600 bg-amber-50'
        : 'text-red-600 bg-red-50'

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
          <div className="text-left">
            <p className="font-medium text-slate-900">{clause.clause_name}</p>
            <p className="text-sm text-slate-500">{clause.section_reference}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{clause.category || clause.clause_category}</Badge>
          <span
            className={cn(
              'text-xs px-2 py-1 rounded-full font-medium',
              confidenceColor
            )}
          >
            {Math.round(confidence * 100)}%
          </span>
        </div>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-slate-100 bg-slate-50">
          <div className="pt-4">
            <h4 className="text-sm font-medium text-slate-500 mb-2">Summary</h4>
            <p className="text-sm text-slate-700">{clause.summary}</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex items-center gap-2">
              <Tag className="w-4 h-4 text-slate-400" />
              <span className="text-sm text-slate-600">
                <span className="text-slate-500">Category:</span> {clause.category || clause.clause_category}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-slate-400" />
              <span className="text-sm text-slate-600">
                <span className="text-slate-500">Responsible:</span>{' '}
                {clause.responsible_party || 'N/A'}
              </span>
            </div>
            {clause.beneficiary_party && (
              <div className="flex items-center gap-2">
                <User className="w-4 h-4 text-slate-400" />
                <span className="text-sm text-slate-600">
                  <span className="text-slate-500">Beneficiary:</span>{' '}
                  {clause.beneficiary_party}
                </span>
              </div>
            )}
            <div className="flex items-center gap-2">
              <Percent className="w-4 h-4 text-slate-400" />
              <span className="text-sm text-slate-600">
                <span className="text-slate-500">Confidence:</span>{' '}
                {Math.round(confidence * 100)}%
              </span>
            </div>
          </div>

          {clause.raw_text && (
            <div>
              <h4 className="text-sm font-medium text-slate-500 mb-2">Raw Text</h4>
              <div className="bg-white border border-slate-200 rounded p-3 max-h-40 overflow-y-auto">
                <p className="text-sm text-slate-700 whitespace-pre-wrap font-mono">
                  {clause.raw_text}
                </p>
              </div>
            </div>
          )}

          {clause.normalized_payload &&
            Object.keys(clause.normalized_payload).length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-slate-500 mb-2">
                  Extracted Values
                </h4>
                <div className="bg-white border border-slate-200 rounded p-3">
                  <pre className="text-xs text-slate-700 overflow-x-auto">
                    {JSON.stringify(clause.normalized_payload, null, 2)}
                  </pre>
                </div>
              </div>
            )}
        </div>
      )}
    </div>
  )
}

export function ClauseReviewStep() {
  const {
    state,
    setClauseValidation,
    goToNextStep,
    goToPreviousStep,
    canProceedToStep,
  } = useWorkflow()

  const { parseResult, clauseValidation } = state

  // Analyze clauses on mount and when parseResult changes
  useEffect(() => {
    if (!parseResult?.clauses) return

    const clauses = parseResult.clauses

    // Use new 'category' field with fallback to deprecated fields
    const categories = clauses.map((c) =>
      (c.category || c.clause_category || '').toLowerCase()
    )

    const hasPricingClause = categories.some(
      (cat) =>
        cat.includes('pricing') ||
        cat.includes('payment') ||
        cat.includes('payment_terms') ||
        cat.includes('tariff') ||
        cat.includes('rate') ||
        cat.includes('commercial')
    )

    const hasAvailabilityClause = categories.some(
      (cat) => cat.includes('availability') || cat.includes('performance')
    )

    const hasTerminationClause = categories.some(
      (cat) => cat.includes('termination') || cat.includes('expiry')
    )

    const hasForceClause = categories.some(
      (cat) => cat.includes('force_majeure') || cat.includes('force majeure')
    )

    setClauseValidation({
      hasPricingClause,
      hasAvailabilityClause,
      hasTerminationClause,
      hasForceClause,
    })
  }, [parseResult, setClauseValidation])

  if (!parseResult) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <FileText className="w-12 h-12 mx-auto mb-4 text-slate-300" />
          <p className="text-slate-500">No contract data available.</p>
          <p className="text-sm text-slate-400 mt-2">
            Please upload a contract first.
          </p>
          <Button variant="outline" onClick={goToPreviousStep} className="mt-4">
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Upload
          </Button>
        </CardContent>
      </Card>
    )
  }

  const clauseGroups = groupClausesByCategory(parseResult.clauses)

  const validationItems: ValidationItem[] = [
    {
      label: 'Pricing/Tariff Clause',
      found: clauseValidation.hasPricingClause,
      required: true,
    },
    {
      label: 'Availability Guarantee',
      found: clauseValidation.hasAvailabilityClause,
      required: false,
    },
    {
      label: 'Termination Clause',
      found: clauseValidation.hasTerminationClause,
      required: false,
    },
    {
      label: 'Force Majeure',
      found: clauseValidation.hasForceClause,
      required: false,
    },
  ]

  const canProceed = canProceedToStep(3)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Review Extracted Clauses</span>
          <Badge variant="info">{parseResult.clauses.length} clauses</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Validation Banner */}
        <ValidationBanner items={validationItems} />

        {/* Clause Groups */}
        <div className="space-y-6">
          {clauseGroups.map((group) => (
            <div key={group.category}>
              <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
                {group.category} ({group.clauses.length})
              </h3>
              <div className="space-y-2">
                {group.clauses.map((clause, idx) => (
                  <ClauseItem key={`${clause.clause_name}-${idx}`} clause={clause} />
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Navigation */}
        <div className="flex justify-between pt-4 border-t">
          <Button variant="outline" onClick={goToPreviousStep}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Upload
          </Button>
          <Button onClick={goToNextStep} disabled={!canProceed}>
            Continue to Meter Data
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>

        {!canProceed && (
          <p className="text-sm text-red-600 text-center">
            A pricing/tariff clause is required to continue.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
