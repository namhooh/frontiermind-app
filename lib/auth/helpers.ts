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
  const result = await pool.query(
    `SELECT r.*, o.name as organization_name
     FROM role r
     LEFT JOIN organization o ON r.organization_id = o.id
     WHERE r.user_id = $1 AND r.is_active = true`,
    [userId]
  )

  return result.rows[0] || null
}

export async function requireAuth(requiredRole?: 'admin' | 'staff') {
  const user = await getCurrentUser()

  if (!user) {
    throw new Error('Unauthorized')
  }

  const role = await getUserRole(user.id)

  if (!role) {
    throw new Error('User role not found')
  }

  if (requiredRole && role.role_type !== requiredRole) {
    throw new Error('Insufficient permissions')
  }

  return { user, role }
}
