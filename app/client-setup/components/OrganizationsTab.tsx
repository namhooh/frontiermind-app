'use client'

import { useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import { AdminClient, type OrganizationResponse } from '@/lib/api/adminClient'
import { CreateOrganizationDialog } from './CreateOrganizationDialog'

const client = new AdminClient()

interface OrganizationsTabProps {
  onSelectOrganization: (orgId: number) => void
}

export function OrganizationsTab({ onSelectOrganization }: OrganizationsTabProps) {
  const [organizations, setOrganizations] = useState<OrganizationResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  async function loadOrganizations() {
    setLoading(true)
    setError(null)
    try {
      const orgs = await client.listOrganizations()
      setOrganizations(orgs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load organizations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOrganizations()
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Organizations</h2>
        <Button size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-1" />
          Create Organization
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-slate-500 py-8 text-center">Loading organizations...</div>
      ) : organizations.length === 0 ? (
        <div className="text-sm text-slate-500 py-8 text-center">
          No organizations yet. Create one to get started.
        </div>
      ) : (
        <div className="rounded-md border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="text-left px-4 py-2 font-medium text-slate-600">ID</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Name</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Country</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Created</th>
                <th className="text-right px-4 py-2 font-medium text-slate-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {organizations.map((org) => (
                <tr key={org.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-slate-500">{org.id}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-900">{org.name}</td>
                  <td className="px-4 py-2.5 text-slate-600">{org.country || '—'}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {org.created_at
                      ? new Date(org.created_at).toLocaleDateString()
                      : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onSelectOrganization(org.id)}
                    >
                      Select &rarr;
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateOrganizationDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCreated={loadOrganizations}
      />
    </div>
  )
}
