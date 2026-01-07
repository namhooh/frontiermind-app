'use client';

import { useState, useEffect } from 'react';

type Query = {
  id: number;
  title: string;
  description: string;
  sql?: string;
};

type QueryResult = {
  query: Query;
  data: Record<string, any>[];
  rowCount: number;
};

function QueryCard({ query, onExecute, isLoading, result, error }: {
  query: Query;
  onExecute: (id: number) => void;
  isLoading: boolean;
  result: QueryResult | null;
  error: string | null;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <article className="query-card group relative bg-white border-2 border-stone-900 p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
      <div className="absolute top-0 right-0 w-12 h-12 bg-emerald-400 -translate-y-2 translate-x-2 -z-10 transition-transform duration-300 group-hover:translate-x-3 group-hover:-translate-y-3" />

      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-sm font-mono text-stone-400">Query #{query.id}</span>
          </div>
          <h3 className="text-2xl font-serif font-bold text-stone-900 leading-tight mb-2">
            {query.title}
          </h3>
          <p className="text-stone-600 text-sm leading-relaxed">
            {query.description}
          </p>
        </div>
      </div>

      <div className="flex gap-3 pt-4 border-t border-stone-200">
        <button
          onClick={() => onExecute(query.id)}
          disabled={isLoading}
          className="px-4 py-2 bg-emerald-500 text-white font-mono text-sm border-2 border-stone-900 hover:bg-emerald-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? 'Running...' : 'Run Query'}
        </button>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="px-4 py-2 bg-white text-stone-900 font-mono text-sm border-2 border-stone-900 hover:bg-stone-50 transition-colors"
        >
          {isExpanded ? 'Hide SQL' : 'Show SQL'}
        </button>
      </div>

      {isExpanded && result?.query.sql && (
        <div className="mt-4 p-4 bg-stone-900 text-green-400 font-mono text-xs overflow-x-auto">
          <pre>{result.query.sql}</pre>
        </div>
      )}

      {error && (
        <div className="mt-4 p-4 bg-red-50 border-2 border-red-500">
          <p className="font-mono text-sm text-red-800">
            <strong>Error:</strong> {error}
          </p>
        </div>
      )}

      {result && result.data && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <p className="font-mono text-sm text-stone-600">
              {result.rowCount} row{result.rowCount !== 1 ? 's' : ''} returned
            </p>
          </div>
          <div className="overflow-x-auto border-2 border-stone-900">
            <table className="min-w-full">
              <thead className="bg-stone-900 text-white">
                <tr>
                  {result.data.length > 0 && Object.keys(result.data[0]).map((key) => (
                    <th key={key} className="px-4 py-2 text-left font-mono text-xs uppercase tracking-wider">
                      {key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.data.map((row, idx) => (
                  <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-stone-50'}>
                    {Object.values(row).map((value, cidx) => (
                      <td key={cidx} className="px-4 py-2 text-sm font-mono text-stone-700 border-t border-stone-200">
                        {value === null ? (
                          <span className="text-stone-400 italic">null</span>
                        ) : typeof value === 'object' ? (
                          JSON.stringify(value)
                        ) : (
                          String(value)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </article>
  );
}

export default function TestQueriesPage() {
  const [queries, setQueries] = useState<Query[]>([]);
  const [loadingQuery, setLoadingQuery] = useState<number | null>(null);
  const [results, setResults] = useState<Record<number, QueryResult>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});

  useEffect(() => {
    // Fetch list of queries
    fetch('/api/test-queries')
      .then(res => res.json())
      .then(data => setQueries(data.queries))
      .catch(err => console.error('Failed to load queries:', err));
  }, []);

  const executeQuery = async (id: number) => {
    setLoadingQuery(id);
    setErrors(prev => ({ ...prev, [id]: '' }));

    try {
      const res = await fetch(`/api/test-queries?id=${id}`);
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.message || 'Query execution failed');
      }

      setResults(prev => ({ ...prev, [id]: data }));
    } catch (err) {
      setErrors(prev => ({
        ...prev,
        [id]: err instanceof Error ? err.message : 'Unknown error'
      }));
    } finally {
      setLoadingQuery(null);
    }
  };

  return (
    <div className="min-h-screen bg-stone-50">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <header className="mb-16">
          <div className="flex items-end gap-4 mb-4">
            <h1 className="text-7xl font-serif font-black text-stone-900 leading-none">
              Test Queries
            </h1>
            <span className="text-2xl font-mono text-emerald-500 mb-2">
              {queries.length}
            </span>
          </div>
          <div className="h-1 w-32 bg-emerald-400 mb-4" />
          <p className="text-lg text-stone-600 max-w-3xl">
            Contract Compliance & Invoicing Engine test queries. Execute queries to verify the end-to-end functioning of the system.
          </p>
        </header>

        <div className="space-y-8">
          {queries.map((query) => (
            <QueryCard
              key={query.id}
              query={query}
              onExecute={executeQuery}
              isLoading={loadingQuery === query.id}
              result={results[query.id] || null}
              error={errors[query.id] || null}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
