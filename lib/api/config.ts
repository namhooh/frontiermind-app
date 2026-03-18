/**
 * API Configuration
 *
 * Resolves the backend API base URL. In production, returns an empty
 * string so requests use relative URLs proxied by Next.js rewrites
 * (backend is at https://api.frontiermind.co via Railway).
 */

export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL

  // Server-side rendering: use the full backend URL
  if (typeof window === 'undefined') {
    return envUrl || 'http://localhost:8000'
  }

  // Browser: always use relative URLs so Next.js rewrites proxy to backend
  return ''
}
