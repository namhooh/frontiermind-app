/**
 * API Configuration
 *
 * Resolves the backend API base URL, handling mixed-content issues
 * when the frontend is served over HTTPS (Vercel) but the backend
 * is HTTP-only (AWS ALB). In production, returns an empty string so
 * requests use relative URLs proxied by Next.js rewrites.
 */

export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL

  // Server-side rendering: use the full backend URL
  if (typeof window === 'undefined') {
    return envUrl || 'http://localhost:8000'
  }

  // Browser on production/preview (non-localhost): use relative URLs
  // Next.js rewrites proxy /api/* to the backend
  if (window.location.hostname !== 'localhost') {
    return ''
  }

  // Browser on localhost: call backend directly
  return envUrl || 'http://localhost:8000'
}
