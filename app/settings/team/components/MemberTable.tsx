'use client'

import { useState } from 'react'
import { MoreHorizontal, Shield, ShieldCheck, Pencil, Eye, UserX, UserCheck } from 'lucide-react'
import { Badge } from '@/app/components/ui/badge'
import { Button } from '@/app/components/ui/button'
import type { TeamMember, UpdateMemberRequest } from '@/lib/api/adminClient'

interface MemberTableProps {
  members: TeamMember[]
  currentUserId: string
  onUpdate: (memberId: number, body: UpdateMemberRequest) => Promise<void>
  onDeactivate: (memberId: number) => Promise<void>
  onReactivate: (memberId: number) => Promise<void>
}

const ROLE_LABELS: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  admin: { label: 'Admin', icon: <Shield className="h-3.5 w-3.5" />, color: 'bg-purple-100 text-purple-700' },
  approver: { label: 'Approver', icon: <ShieldCheck className="h-3.5 w-3.5" />, color: 'bg-blue-100 text-blue-700' },
  editor: { label: 'Editor', icon: <Pencil className="h-3.5 w-3.5" />, color: 'bg-green-100 text-green-700' },
  viewer: { label: 'Viewer', icon: <Eye className="h-3.5 w-3.5" />, color: 'bg-slate-100 text-slate-700' },
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  invited: 'bg-amber-100 text-amber-700',
  suspended: 'bg-orange-100 text-orange-700',
  deactivated: 'bg-red-100 text-red-700',
}

export function MemberTable({ members, currentUserId, onUpdate, onDeactivate, onReactivate }: MemberTableProps) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editRole, setEditRole] = useState('')
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [menuOpen, setMenuOpen] = useState<number | null>(null)

  const startEdit = (member: TeamMember) => {
    setEditingId(member.id)
    setEditRole(member.role_type)
    setMenuOpen(null)
  }

  const saveEdit = async (memberId: number) => {
    if (!editRole) return
    setActionLoading(memberId)
    try {
      await onUpdate(memberId, { role_type: editRole as UpdateMemberRequest['role_type'] })
      setEditingId(null)
    } catch {
      // error handled by parent
    } finally {
      setActionLoading(null)
    }
  }

  const handleDeactivate = async (memberId: number) => {
    setActionLoading(memberId)
    setMenuOpen(null)
    try {
      await onDeactivate(memberId)
    } finally {
      setActionLoading(null)
    }
  }

  const handleReactivate = async (memberId: number) => {
    setActionLoading(memberId)
    setMenuOpen(null)
    try {
      await onReactivate(memberId)
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="overflow-visible">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
            <th className="py-3 px-4">Name</th>
            <th className="py-3 px-4">Email</th>
            <th className="py-3 px-4">Role</th>
            <th className="py-3 px-4">Department</th>
            <th className="py-3 px-4">Job Title</th>
            <th className="py-3 px-4">Status</th>
            <th className="py-3 px-4 w-12"></th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => {
            const isCurrentUser = member.user_id === currentUserId
            const roleInfo = ROLE_LABELS[member.role_type] || ROLE_LABELS.viewer
            const isEditing = editingId === member.id

            return (
              <tr key={member.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-3 px-4 font-medium text-slate-900">
                  {member.name || '—'}
                  {isCurrentUser && (
                    <span className="ml-2 text-xs text-slate-400">(you)</span>
                  )}
                </td>
                <td className="py-3 px-4 text-slate-600">{member.email || '—'}</td>
                <td className="py-3 px-4">
                  {isEditing ? (
                    <div className="flex items-center gap-2">
                      <select
                        value={editRole}
                        onChange={(e) => setEditRole(e.target.value)}
                        className="rounded border border-slate-300 px-2 py-1 text-sm"
                      >
                        <option value="admin">Admin</option>
                        <option value="approver">Approver</option>
                        <option value="editor">Editor</option>
                        <option value="viewer">Viewer</option>
                      </select>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => saveEdit(member.id)}
                        disabled={actionLoading === member.id}
                      >
                        Save
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${roleInfo.color}`}>
                      {roleInfo.icon}
                      {roleInfo.label}
                    </span>
                  )}
                </td>
                <td className="py-3 px-4 text-slate-600">{member.department || '—'}</td>
                <td className="py-3 px-4 text-slate-600">{member.job_title || '—'}</td>
                <td className="py-3 px-4">
                  <Badge className={STATUS_COLORS[member.status] || ''}>
                    {member.status}
                  </Badge>
                </td>
                <td className="py-3 px-4">
                  {!isCurrentUser && (
                    <div className="relative">
                      <button
                        onClick={() => setMenuOpen(menuOpen === member.id ? null : member.id)}
                        className="p-1 rounded hover:bg-slate-100"
                      >
                        <MoreHorizontal className="h-4 w-4 text-slate-500" />
                      </button>
                      {menuOpen === member.id && (
                        <div className="absolute right-0 top-8 z-50 w-44 rounded-md border border-slate-200 bg-white py-1 shadow-lg">
                          {member.status !== 'deactivated' && (
                            <>
                              <button
                                onClick={() => startEdit(member)}
                                className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                Change Role
                              </button>
                              <button
                                onClick={() => handleDeactivate(member.id)}
                                disabled={actionLoading === member.id}
                                className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
                              >
                                <UserX className="h-3.5 w-3.5" />
                                Deactivate
                              </button>
                            </>
                          )}
                          {member.status === 'deactivated' && (
                            <button
                              onClick={() => handleReactivate(member.id)}
                              disabled={actionLoading === member.id}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-green-600 hover:bg-green-50"
                            >
                              <UserCheck className="h-3.5 w-3.5" />
                              Reactivate
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
