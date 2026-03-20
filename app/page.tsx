import Link from 'next/link'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { SignOutButton } from './components/SignOutButton'

export default async function LandingPage() {
  // Non-admin users go straight to the project dashboard
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (user) {
    const { data } = await supabase
      .from('role')
      .select('role_type')
      .eq('user_id', user.id)
      .eq('is_active', true)
      .limit(1)
      .single()
    if (data && data.role_type !== 'admin') {
      redirect('/projects')
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full">
        <div className="mb-10 text-center relative">
          <div className="absolute right-0 top-0">
            <SignOutButton />
          </div>
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

          <Link
            href="/settings/team"
            className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <h2 className="text-lg font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              Settings
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              Manage team members, roles, and organization settings
            </p>
          </Link>
        </div>
      </div>
    </div>
  )
}
