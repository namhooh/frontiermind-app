'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const supabase = createClient()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (error) {
      setError(error.message)
      setLoading(false)
    } else {
      router.push('/')
      router.refresh()
    }
  }

  return (
    <div className="min-h-screen bg-stone-50 flex items-center justify-center">
      <div className="border-4 border-stone-900 bg-white p-12 max-w-md w-full">
        <h1 className="text-4xl font-serif font-black text-stone-900 mb-8">
          Frontier Mind Login
        </h1>

        <form onSubmit={handleLogin} className="space-y-6">
          <div>
            <label className="block text-sm font-mono text-stone-700 mb-2">
              EMAIL
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border-2 border-stone-900 p-3 font-mono text-sm"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-mono text-stone-700 mb-2">
              PASSWORD
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border-2 border-stone-900 p-3 font-mono text-sm"
              required
            />
          </div>

          {error && (
            <div className="border-2 border-red-500 bg-red-50 p-3">
              <p className="font-mono text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full px-8 py-4 bg-emerald-500 text-white font-mono text-lg font-bold border-4 border-stone-900 hover:bg-emerald-600 transition-colors disabled:opacity-50"
          >
            {loading ? 'LOGGING IN...' : 'LOG IN'}
          </button>
        </form>
      </div>
    </div>
  )
}
