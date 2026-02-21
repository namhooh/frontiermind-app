import Link from 'next/link'

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full">
        <div className="mb-10 text-center">
          <h1
            className="text-3xl font-bold text-slate-900"
            style={{ fontFamily: "'Libre Baskerville', serif" }}
          >
            FrontierMind
          </h1>
          <p className="text-slate-500 text-sm mt-2">
            AI co-pilot for corporate energy projects
          </p>
        </div>

        <div className="grid gap-4">
          <Link
            href="/contract-workflow"
            className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <h2 className="text-lg font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              Contract Digitization
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              Upload, parse, and extract clauses from energy contracts
            </p>
          </Link>

          <Link
            href="/pii-redaction"
            className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <h2 className="text-lg font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              PII Redaction
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              Detect and redact personally identifiable information from documents
            </p>
          </Link>

          <Link
            href="/client-setup"
            className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <h2 className="text-lg font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              Client Onboarding
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              Manage organizations and API keys for data ingestion
            </p>
          </Link>

          <Link
            href="/projects"
            className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <h2 className="text-lg font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              Project Dashboard
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              View onboarded project data, contracts, and technical details
            </p>
          </Link>
        </div>
      </div>
    </div>
  )
}
