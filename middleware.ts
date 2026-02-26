import { updateSession } from '@/lib/supabase/middleware'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === 'true'

export async function middleware(request: NextRequest) {
  if (IS_DEMO) {
    const { pathname } = request.nextUrl
    // Allow /projects*, /api/*, and Next.js internal routes
    if (
      !pathname.startsWith('/projects') &&
      !pathname.startsWith('/api') &&
      !pathname.startsWith('/_next') &&
      !pathname.startsWith('/submit')
    ) {
      return NextResponse.redirect(new URL('/projects', request.url))
    }
    // In demo mode, skip auth — just pass through
    return NextResponse.next()
  }

  return await updateSession(request)
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|login).*)',
  ],
}
