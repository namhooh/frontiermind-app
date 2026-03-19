'use client'

import { useState, useEffect, useRef } from 'react'
import { createClient } from '@/lib/supabase/client'

/**
 * Accept Invite Page
 *
 * Handles the Supabase invite link flow:
 * 1. Supabase client auto-processes the invite token from the URL hash
 *    and establishes a session for the invited user (replacing any existing session)
 * 2. Prompts the new user to set a password
 * 3. Updates member_status from 'invited' to 'active' via backend
 */
export default function AcceptInvitePage() {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [userEmail, setUserEmail] = useState<string | null>(null)
  const readyRef = useRef(false)

  const supabase = createClient()

  useEffect(() => {
    // Listen for auth state changes — Supabase client will auto-process
    // the invite token from the URL hash (#access_token=...&type=invite)
    // and fire a SIGNED_IN or TOKEN_REFRESHED event with the new session.
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (readyRef.current) return
        if (session?.user) {
          readyRef.current = true
          setUserEmail(session.user.email ?? null)
          setLoading(false)
        }
      }
    )

    // Also check if the token was already exchanged by the time this runs
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (readyRef.current) return
      // Only accept if this looks like the invited user's session
      // (i.e. there's a hash fragment in the URL indicating a fresh token exchange)
      const hash = window.location.hash
      if (session?.user && (hash.includes('access_token') || hash.includes('type=invite'))) {
        readyRef.current = true
        setUserEmail(session.user.email ?? null)
        setLoading(false)
      }
    })

    // Timeout: if no session after 8 seconds, the link is bad
    const timer = setTimeout(() => {
      if (!readyRef.current) {
        setError('Invite link is invalid or expired. Please ask your admin to send a new invite.')
        setLoading(false)
      }
    }, 8000)

    return () => {
      subscription.unsubscribe()
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setSaving(true)
    try {
      // Set the password for the new user
      const { error: updateError } = await supabase.auth.updateUser({
        password,
      })
      if (updateError) {
        setError(updateError.message)
        setSaving(false)
        return
      }

      // Update member_status from 'invited' to 'active' via backend
      try {
        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) {
          const { getApiBaseUrl } = await import('@/lib/api/config')
          await fetch(`${getApiBaseUrl()}/api/team/accept-invite`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${session.access_token}`,
            },
          })
        }
      } catch {
        // Non-critical — admin can manually update status
      }

      setSuccess(true)
    } catch {
      setError('Failed to set password')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-lg border border-slate-200 p-8 max-w-md w-full text-center">
          <div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-blue-600 rounded-full mx-auto mb-4" />
          <p className="text-slate-600 text-sm">Processing your invitation...</p>
        </div>
      </div>
    )
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-lg border border-slate-200 p-8 max-w-md w-full text-center">
          <h2 className="text-xl font-semibold text-slate-900 mb-2">You&apos;re all set!</h2>
          <p className="text-slate-600 text-sm mb-6">Your password has been set. You can now sign in.</p>
          <a
            href="/login"
            className="inline-block bg-gradient-to-r from-blue-600 to-indigo-700 text-white font-medium py-3 px-6 rounded-lg hover:from-blue-700 hover:to-indigo-800 transition-all"
          >
            Sign in
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg border border-slate-200 p-8 max-w-md w-full">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-900" style={{ fontFamily: "'Libre Baskerville', serif" }}>
            FrontierMind
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            AI co-pilot for corporate energy projects
          </p>
        </div>

        <h2 className="text-xl font-semibold text-slate-900 mb-2">
          Welcome! Set your password
        </h2>
        {userEmail && (
          <p className="text-sm text-slate-500 mb-6">
            Setting up account for <span className="font-medium text-slate-700">{userEmail}</span>
          </p>
        )}

        <form onSubmit={handleSetPassword} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="At least 8 characters"
              required
              minLength={8}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Confirm Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Re-enter your password"
              required
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-gradient-to-r from-blue-600 to-indigo-700 text-white font-medium py-3 px-4 rounded-lg hover:from-blue-700 hover:to-indigo-800 transition-all disabled:opacity-50"
          >
            {saving ? 'Setting password...' : 'Set Password & Continue'}
          </button>
        </form>
      </div>
    </div>
  )
}
