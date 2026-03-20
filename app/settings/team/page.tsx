'use client'

import { useState, useEffect, useCallback } from 'react'
import { ArrowLeft, Loader2, Plus, Users } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/app/components/ui/button'
import { adminClient, type TeamMember, type UpdateMemberRequest } from '@/lib/api/adminClient'
import { IS_DEMO } from '@/lib/demoMode'
import { toast } from 'sonner'
import { MemberTable } from './components/MemberTable'
import { InviteMemberDialog } from './components/InviteMemberDialog'

export default function TeamPage() {
  const [members, setMembers] = useState<TeamMember[]>([])
  const [currentUser, setCurrentUser] = useState<TeamMember | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  const isAdmin = currentUser?.role_type === 'admin'

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const me = await adminClient.getMe()
      setCurrentUser(me)
      adminClient.setOrganizationId(me.organization_id)

      if (me.role_type === 'admin') {
        const list = await adminClient.listTeamMembers()
        setMembers(list)
      } else {
        setMembers([me])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load team data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (IS_DEMO) {
      adminClient.setOrganizationId(1)
    }
    loadData()
  }, [loadData])

  const handleInvite = async (data: {
    email: string
    full_name: string
    role_type: 'admin' | 'approver' | 'editor' | 'viewer'
    department?: string
    job_title?: string
  }) => {
    await adminClient.inviteTeamMember(data)
    toast.success(`Invite sent to ${data.email}`)
    await loadData()
  }

  const handleUpdate = async (memberId: number, body: UpdateMemberRequest) => {
    try {
      await adminClient.updateTeamMember(memberId, body)
      toast.success('Member updated')
      await loadData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update member')
      throw err
    }
  }

  const handleDeactivate = async (memberId: number) => {
    try {
      await adminClient.deactivateTeamMember(memberId)
      toast.success('Member deactivated')
      await loadData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to deactivate member')
    }
  }

  const handleReactivate = async (memberId: number) => {
    try {
      await adminClient.reactivateTeamMember(memberId)
      toast.success('Member reactivated')
      await loadData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to reactivate member')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Team Management</h1>
            <p className="text-sm text-slate-500 mt-1">
              Manage your organization&apos;s team members and roles
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isAdmin && (
              <Button onClick={() => setInviteOpen(true)}>
                <Plus className="h-4 w-4 mr-1.5" />
                Invite Member
              </Button>
            )}
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Home
            </Link>
          </div>
        </div>

        {/* Current user info */}
        {currentUser && !loading && (
          <div className="bg-white rounded-lg border border-slate-200 p-4 mb-6">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center">
                <Users className="h-5 w-5 text-slate-500" />
              </div>
              <div>
                <p className="font-medium text-slate-900">{currentUser.name || currentUser.email}</p>
                <p className="text-sm text-slate-500">
                  {currentUser.role_type.charAt(0).toUpperCase() + currentUser.role_type.slice(1)}
                  {currentUser.department && ` \u00b7 ${currentUser.department}`}
                  {currentUser.job_title && ` \u00b7 ${currentUser.job_title}`}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Members table */}
        <div className="bg-white rounded-lg border border-slate-200 overflow-visible">
          <div className="px-4 py-3 border-b border-slate-200">
            <h2 className="text-sm font-medium text-slate-900">
              {isAdmin ? 'All Members' : 'Your Membership'}
            </h2>
          </div>

          {loading && (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          )}

          {error && (
            <div className="p-6 text-sm text-red-600">{error}</div>
          )}

          {!loading && !error && members.length > 0 && currentUser && (
            <MemberTable
              members={members}
              currentUserId={currentUser.user_id}
              onUpdate={handleUpdate}
              onDeactivate={handleDeactivate}
              onReactivate={handleReactivate}
            />
          )}

          {!loading && !error && members.length === 0 && (
            <div className="p-6 text-sm text-slate-500 text-center">No members found</div>
          )}
        </div>

        {/* Role permission reference */}
        {isAdmin && (
          <div className="mt-6 bg-white rounded-lg border border-slate-200 p-4">
            <h3 className="text-sm font-medium text-slate-900 mb-3">Role Permissions</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="py-2 px-3 font-medium">Role</th>
                    <th className="py-2 px-3 font-medium">View</th>
                    <th className="py-2 px-3 font-medium">Edit</th>
                    <th className="py-2 px-3 font-medium">Approve</th>
                    <th className="py-2 px-3 font-medium">Manage Users</th>
                  </tr>
                </thead>
                <tbody className="text-slate-700">
                  {[
                    { role: 'Admin', view: true, edit: true, approve: true, manage: true },
                    { role: 'Approver', view: true, edit: true, approve: true, manage: false },
                    { role: 'Editor', view: true, edit: true, approve: false, manage: false },
                    { role: 'Viewer', view: true, edit: false, approve: false, manage: false },
                  ].map((row) => (
                    <tr key={row.role} className="border-b border-slate-50">
                      <td className="py-2 px-3 font-medium">{row.role}</td>
                      {[row.view, row.edit, row.approve, row.manage].map((v, i) => (
                        <td key={i} className="py-2 px-3">{v ? '\u2713' : '\u2014'}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <InviteMemberDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        onInvite={handleInvite}
      />
    </div>
  )
}
