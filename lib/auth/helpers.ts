import { createClient } from '@/lib/supabase/server'
import { Pool } from 'pg'

const pool = new Pool({
  connectionString: process.env.SUPABASE_DB_URL,
})

export async function getCurrentUser() {
  const supabase = await createClient()
  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    return null
  }

  return user
}

export async function getUserRole(userId: string) {
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

export async function requireAuth(requiredRole?: 'admin' | 'staff') {
  try {
    const user = await getCurrentUser()

    if (!user) {
      throw new Error('Unauthorized')
    }

    console.log('Auth: User authenticated, ID:', user.id)

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
