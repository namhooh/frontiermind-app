import { createClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')
  const next = searchParams.get('next') ?? '/'

  if (code) {
    const supabase = await createClient()
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      // Detect invite flow: if the user has no password set (invited via link),
      // redirect to the accept-invite page to set one.
      // Supabase invited users have identities but haven't set a password yet.
      const user = data?.user
      if (user && !user.last_sign_in_at) {
        // First-time user (accepted invite) — redirect to set password
        return NextResponse.redirect(`${origin}/auth/accept-invite`)
      }

      // Check if next points to accept-invite (from redirect_to param)
      if (next.includes('/auth/accept-invite')) {
        return NextResponse.redirect(`${origin}/auth/accept-invite`)
      }

      return NextResponse.redirect(`${origin}${next}`)
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_failed`)
}
