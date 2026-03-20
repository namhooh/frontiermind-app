'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'

/**
 * Accept Invite Page
 *
 * Supabase invite links redirect here with a hash fragment containing
 * the access_token and refresh_token. This page:
 * 1. Extracts tokens from the URL hash
 * 2. Sets the Supabase session using those tokens
 * 3. Prompts the new user to set a password
 * 4. Updates member_status from 'invited' to 'active' via backend
 */
export default function AcceptInvitePage() {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [userEmail, setUserEmail] = useState<string | null>(null)

  const supabase = createClient()

  useEffect(() => {
    async function processInvite() {
      // Parse hash fragment: #access_token=...&refresh_token=...&type=invite
      const hash = window.location.hash.substring(1)
      const params = new URLSearchParams(hash)

      const accessToken = params.get('access_token')
      const refreshToken = params.get('refresh_token')
      const errorParam = params.get('error')
      const errorDesc = params.get('error_description')

      // Check for error in hash (e.g. expired link on second click)
      if (errorParam) {
        setError(errorDesc?.replace(/\+/g, ' ') || 'Invite link is invalid or expired.')
        setLoading(false)
        return
      }

      // If we have tokens in the hash, set the session
      if (accessToken && refreshToken) {
        const { data, error: sessionError } = await supabase.auth.setSession({
          access_token: accessToken,
          refresh_token: refreshToken,
        })

        if (sessionError) {
          setError(sessionError.message)
          setLoading(false)
          return
        }

        if (data.user) {
          setUserEmail(data.user.email ?? null)
          // Clear the hash from the URL so tokens aren't exposed
          window.history.replaceState(null, '', '/auth/accept-invite')
          setLoading(false)
          return
        }
      }

      // No tokens in hash — check if there's an existing session
      // (e.g. redirected from /auth/callback)
      const { data: { session } } = await supabase.auth.getSession()
      if (session?.user) {
        setUserEmail(session.user.email ?? null)
        setLoading(false)
        return
      }

      setError('No invite token found. Please click the invite link from your email.')
      setLoading(false)
    }

    processInvite()
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
          <p className="text-slate-600 text-sm">Setting up your account...</p>
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
