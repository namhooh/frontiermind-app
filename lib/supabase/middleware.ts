import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Session timeout configuration (in seconds)
const SESSION_CONFIG = {
  // Idle timeout: 30 minutes (session expires if inactive)
  IDLE_TIMEOUT: parseInt(process.env.SESSION_IDLE_TIMEOUT || '1800', 10),
  // Absolute timeout: 24 hours (session expires regardless of activity)
  ABSOLUTE_TIMEOUT: parseInt(process.env.SESSION_ABSOLUTE_TIMEOUT || '86400', 10),
}

// Cookie names for session tracking
const SESSION_COOKIES = {
  LAST_ACTIVITY: 'session_last_activity',
  SESSION_START: 'session_start_time',
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value
        },
        set(name: string, value: string, options: any) {
          response.cookies.set({ name, value, ...options })
        },
        remove(name: string, options: any) {
          response.cookies.set({ name, value: '', ...options })
        },
      },
    }
  )

  // Refresh session
  const { data: { user } } = await supabase.auth.getUser()

  const pathname = request.nextUrl.pathname

  // Redirect authenticated users away from login page
  if (pathname === '/login' && user) {
    return NextResponse.redirect(new URL('/', request.url))
  }

  // Protect PAGE routes only (not API routes - they handle their own auth)
  // NOTE: '/' temporarily removed for workflow testing
  const protectedPaths = ['/test-queries', '/dashboard']
  const isProtected = protectedPaths.some(path =>
    pathname === path ||
    pathname.startsWith(path + '/')
  )

  // Only redirect pages to login, not API routes
  if (isProtected && !user && !pathname.startsWith('/api')) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  // Session timeout tracking for authenticated users
  if (user) {
    const now = Math.floor(Date.now() / 1000) // Current time in seconds
    const lastActivity = request.cookies.get(SESSION_COOKIES.LAST_ACTIVITY)?.value
    const sessionStart = request.cookies.get(SESSION_COOKIES.SESSION_START)?.value

    // Check if session has exceeded absolute timeout
    if (sessionStart) {
      const startTime = parseInt(sessionStart, 10)
      if (now - startTime > SESSION_CONFIG.ABSOLUTE_TIMEOUT) {
        console.log('Session expired: absolute timeout exceeded')
        // Sign out and redirect to login with timeout message
        await supabase.auth.signOut()
        // Clear session tracking cookies
        response.cookies.set({ name: SESSION_COOKIES.LAST_ACTIVITY, value: '', maxAge: 0 })
        response.cookies.set({ name: SESSION_COOKIES.SESSION_START, value: '', maxAge: 0 })
        return NextResponse.redirect(new URL('/login?reason=session_expired', request.url))
      }
    } else {
      // Initialize session start time
      response.cookies.set({
        name: SESSION_COOKIES.SESSION_START,
        value: now.toString(),
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
        maxAge: SESSION_CONFIG.ABSOLUTE_TIMEOUT,
      })
    }

    // Check if session has exceeded idle timeout
    if (lastActivity) {
      const lastTime = parseInt(lastActivity, 10)
      if (now - lastTime > SESSION_CONFIG.IDLE_TIMEOUT) {
        console.log('Session expired: idle timeout exceeded')
        // Sign out and redirect to login with timeout message
        await supabase.auth.signOut()
        // Clear session tracking cookies
        response.cookies.set({ name: SESSION_COOKIES.LAST_ACTIVITY, value: '', maxAge: 0 })
        response.cookies.set({ name: SESSION_COOKIES.SESSION_START, value: '', maxAge: 0 })
        return NextResponse.redirect(new URL('/login?reason=idle_timeout', request.url))
      }
    }

    // Update last activity time
    response.cookies.set({
      name: SESSION_COOKIES.LAST_ACTIVITY,
      value: now.toString(),
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: SESSION_CONFIG.IDLE_TIMEOUT,
    })
  }

  return response
}
