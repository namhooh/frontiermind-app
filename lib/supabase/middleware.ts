import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

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
  const protectedPaths = ['/', '/test-queries', '/dashboard']
  const isProtected = protectedPaths.some(path =>
    pathname === path ||
    pathname.startsWith(path + '/')
  )

  // Only redirect pages to login, not API routes
  if (isProtected && !user && !pathname.startsWith('/api')) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  return response
}
