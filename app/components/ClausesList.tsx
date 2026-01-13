import { type ExtractedClause } from '@/lib/api'

interface ClausesListProps {
  clauses: ExtractedClause[]
}

export default function ClausesList({ clauses }: ClausesListProps) {
  if (clauses.length === 0) {
    return (
      <div className="border-2 border-stone-900 rounded-lg p-6 bg-stone-50">
        <p className="text-stone-600 text-center">
          No clauses extracted from this contract.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h3 className="text-xl font-bold text-stone-900">
        Extracted Clauses ({clauses.length})
      </h3>

      {clauses.map((clause, idx) => (
        <details
          key={idx}
          className="border-2 border-stone-900 rounded-lg p-4 bg-stone-50 group"
        >
          <summary className="cursor-pointer font-bold text-stone-900 list-none flex items-center justify-between">
            <span>
              {clause.section_reference && `${clause.section_reference} - `}
              {clause.clause_name}
              <span className="ml-2 text-sm text-stone-600" style={{ fontFamily: 'Space Mono, monospace' }}>
                ({Math.round(clause.confidence_score * 100)}% confidence)
              </span>
            </span>
            <span className="text-stone-600 group-open:rotate-180 transition-transform duration-300">
              ▼
            </span>
          </summary>

          <div className="mt-4 space-y-4 pt-4 border-t-2 border-stone-300">
            <div>
              <h4 className="text-sm font-bold text-stone-900 mb-1" style={{ fontFamily: 'Space Mono, monospace' }}>
                Summary:
              </h4>
              <p className="text-stone-700">{clause.summary}</p>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="font-mono text-stone-600">Type:</span>
                <span className="ml-2 text-stone-900">{clause.clause_type}</span>
              </div>
              <div>
                <span className="font-mono text-stone-600">Category:</span>
                <span className="ml-2 text-stone-900">{clause.clause_category}</span>
              </div>
              <div>
                <span className="font-mono text-stone-600">Responsible Party:</span>
                <span className="ml-2 text-stone-900">{clause.responsible_party}</span>
              </div>
              {clause.beneficiary_party && (
                <div>
                  <span className="font-mono text-stone-600">Beneficiary:</span>
                  <span className="ml-2 text-stone-900">{clause.beneficiary_party}</span>
                </div>
              )}
            </div>

            {clause.raw_text && (
              <div>
                <h4 className="text-sm font-bold text-stone-900 mb-1" style={{ fontFamily: 'Space Mono, monospace' }}>
                  Raw Text:
                </h4>
                <p className="text-sm text-stone-600 italic">{clause.raw_text}</p>
              </div>
            )}

            {Object.keys(clause.normalized_payload).length > 0 && (
              <div>
                <h4 className="text-sm font-bold text-stone-900 mb-1" style={{ fontFamily: 'Space Mono, monospace' }}>
                  Structured Data:
                </h4>
                <pre
                  className="mt-1 p-3 bg-stone-100 rounded text-xs overflow-x-auto border border-stone-300"
                  style={{ fontFamily: 'Space Mono, monospace' }}
                >
                  {JSON.stringify(clause.normalized_payload, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </details>
      ))}
    </div>
  )
}
