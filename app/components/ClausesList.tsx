import { type ExtractedClause } from '@/lib/api'

interface ClausesListProps {
  clauses: ExtractedClause[]
}

export default function ClausesList({ clauses }: ClausesListProps) {
  if (clauses.length === 0) {
    return (
      <div className="border border-slate-200 rounded-lg p-6 bg-slate-50">
        <p className="text-slate-500 text-center">
          No clauses extracted from this contract.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-slate-900">
        Extracted Clauses ({clauses.length})
      </h3>

      {clauses.map((clause, idx) => {
        // Use new fields with fallbacks to deprecated ones
        const confidence = clause.extraction_confidence ?? clause.confidence_score ?? 0
        const category = clause.category || clause.clause_category || 'Unknown'

        return (
        <details
          key={idx}
          className="border border-slate-200 rounded-lg p-4 bg-white group"
        >
          <summary className="cursor-pointer font-medium text-slate-900 list-none flex items-center justify-between">
            <span>
              {clause.section_reference && `${clause.section_reference} - `}
              {clause.clause_name}
              <span className="ml-2 text-sm text-slate-500">
                ({Math.round(confidence * 100)}% confidence)
              </span>
            </span>
            <span className="text-slate-400 group-open:rotate-180 transition-transform duration-200">
              ▼
            </span>
          </summary>

          <div className="mt-4 space-y-4 pt-4 border-t border-slate-200">
            <div>
              <h4 className="text-sm font-medium text-slate-700 mb-1">
                Summary
              </h4>
              <p className="text-slate-600">{clause.summary}</p>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-slate-500">Category:</span>
                <span className="ml-2 text-slate-900">{category}</span>
              </div>
              <div>
                <span className="text-slate-500">Responsible Party:</span>
                <span className="ml-2 text-slate-900">{clause.responsible_party}</span>
              </div>
              {clause.beneficiary_party && (
                <div>
                  <span className="text-slate-500">Beneficiary:</span>
                  <span className="ml-2 text-slate-900">{clause.beneficiary_party}</span>
                </div>
              )}
            </div>

            {clause.raw_text && (
              <div>
                <h4 className="text-sm font-medium text-slate-700 mb-1">
                  Raw Text
                </h4>
                <p className="text-sm text-slate-500 italic">{clause.raw_text}</p>
              </div>
            )}

            {Object.keys(clause.normalized_payload).length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-slate-700 mb-1">
                  Structured Data
                </h4>
                <pre className="mt-1 p-3 bg-slate-50 rounded-lg text-xs overflow-x-auto border border-slate-200 font-mono">
                  {JSON.stringify(clause.normalized_payload, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </details>
        )
      })}
    </div>
  )
}
