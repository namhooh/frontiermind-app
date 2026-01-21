import { createClient } from '@/lib/supabase/server'
import { Pool } from 'pg'

const pool = new Pool({
  connectionString: process.env.SUPABASE_DB_URL,
})

// Security configuration
const SECURITY_CONFIG = {
  // MFA enforcement - set to true to require MFA for all users
  REQUIRE_MFA: process.env.REQUIRE_MFA === 'true',
  // Session idle timeout in seconds (30 minutes)
  SESSION_IDLE_TIMEOUT: parseInt(process.env.SESSION_IDLE_TIMEOUT || '1800', 10),
  // Session absolute timeout in seconds (24 hours)
  SESSION_ABSOLUTE_TIMEOUT: parseInt(process.env.SESSION_ABSOLUTE_TIMEOUT || '86400', 10),
}

export interface AuthenticatedUser {
  id: string
  email?: string
  phone?: string
  created_at: string
  updated_at?: string
  app_metadata: {
    provider?: string
    providers?: string[]
  }
  user_metadata: Record<string, unknown>
  aal: 'aal1' | 'aal2' // Authentication Assurance Level
  amr?: Array<{ method: string; timestamp: number }>
  factors?: Array<{ id: string; type: string; status: string }>
}

export async function getCurrentUser(): Promise<AuthenticatedUser | null> {
  const supabase = await createClient()
  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    return null
  }

  // Get the current session to check MFA status
  const { data: { session } } = await supabase.auth.getSession()

  // Check if user has MFA factors enrolled
  const { data: factors } = await supabase.auth.mfa.listFactors()

  return {
    ...user,
    aal: (session?.aal as 'aal1' | 'aal2') || 'aal1',
    amr: session?.amr,
    factors: factors?.totp || [],
  } as AuthenticatedUser
}

/**
 * Check if user has completed MFA verification (AAL2)
 * AAL1 = password only, AAL2 = password + second factor
 */
export async function checkMFAStatus(): Promise<{
  hasEnrolledFactors: boolean
  isVerified: boolean
  currentLevel: 'aal1' | 'aal2'
}> {
  const supabase = await createClient()

  const { data: { session } } = await supabase.auth.getSession()
  const { data: factors } = await supabase.auth.mfa.listFactors()

  const hasEnrolledFactors = (factors?.totp?.length || 0) > 0
  const currentLevel = (session?.aal as 'aal1' | 'aal2') || 'aal1'
  const isVerified = currentLevel === 'aal2'

  return {
    hasEnrolledFactors,
    isVerified,
    currentLevel,
  }
}

export interface UserRole {
  id: number
  user_id: string
  organization_id: number
  role_type: 'admin' | 'staff'
  is_active: boolean
  organization_name?: string
}

export async function getUserRole(userId: string): Promise<UserRole | null> {
  try {
    const result = await pool.query(
      `SELECT r.*, o.name as organization_name
       FROM role r
       LEFT JOIN organization o ON r.organization_id = o.id
       WHERE r.user_id = $1 AND r.is_active = true`,
      [userId]
    )

    return result.rows[0] || null
  } catch (error) {
    console.error('Database error in getUserRole:', error)
    throw new Error(`Database error: ${error instanceof Error ? error.message : 'Unknown error'}`)
  }
}

export interface RequireAuthOptions {
  requiredRole?: 'admin' | 'staff'
  requireMFA?: boolean  // Override global MFA requirement for specific routes
}

/**
 * Require authentication with optional role and MFA verification.
 *
 * @param options - Authentication options
 * @param options.requiredRole - Required role ('admin' | 'staff')
 * @param options.requireMFA - Override global MFA requirement (default: uses SECURITY_CONFIG.REQUIRE_MFA)
 *
 * @throws Error('Unauthorized') - User not authenticated
 * @throws Error('MFA_REQUIRED') - MFA required but not verified
 * @throws Error('MFA_NOT_ENROLLED') - MFA required but user has no enrolled factors
 * @throws Error('User role not found') - User has no assigned role
 * @throws Error('Insufficient permissions') - User lacks required role
 */
export async function requireAuth(
  options?: RequireAuthOptions | 'admin' | 'staff'
): Promise<{ user: AuthenticatedUser; role: UserRole }> {
  // Handle legacy single-argument format
  const opts: RequireAuthOptions = typeof options === 'string'
    ? { requiredRole: options }
    : options || {}

  const { requiredRole, requireMFA = SECURITY_CONFIG.REQUIRE_MFA } = opts

  try {
    const user = await getCurrentUser()

    if (!user) {
      throw new Error('Unauthorized')
    }

    console.log('Auth: User authenticated, ID:', user.id)

    // Check MFA if required
    if (requireMFA) {
      const mfaStatus = await checkMFAStatus()

      if (!mfaStatus.hasEnrolledFactors) {
        console.log('Auth: MFA required but not enrolled for user:', user.id)
        throw new Error('MFA_NOT_ENROLLED')
      }

      if (!mfaStatus.isVerified) {
        console.log('Auth: MFA required but not verified for user:', user.id)
        throw new Error('MFA_REQUIRED')
      }

      console.log('Auth: MFA verified (AAL2) for user:', user.id)
    }

    const role = await getUserRole(user.id)

    if (!role) {
      console.log('Auth: No role found for user:', user.id)
      throw new Error('User role not found')
    }

    console.log('Auth: User role:', role.role_type, 'Org:', role.organization_name)

    if (requiredRole && role.role_type !== requiredRole) {
      throw new Error('Insufficient permissions')
    }

    return { user, role }
  } catch (error) {
    console.error('Auth error in requireAuth:', error)
    throw error
  }
}

/**
 * Get security configuration for client-side use
 */
export function getSecurityConfig() {
  return {
    requireMFA: SECURITY_CONFIG.REQUIRE_MFA,
    sessionIdleTimeout: SECURITY_CONFIG.SESSION_IDLE_TIMEOUT,
    sessionAbsoluteTimeout: SECURITY_CONFIG.SESSION_ABSOLUTE_TIMEOUT,
  }
}
