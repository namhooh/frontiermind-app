'use client'

import { useEffect, useState, useCallback } from 'react'
import { Key, Trash2 } from 'lucide-react'
import { Button } from '@/app/components/ui/button'
import { Switch } from '@/app/components/ui/switch'
import { Badge } from '@/app/components/ui/badge'
import {
  AdminClient,
  type CredentialResponse,
  type DataSourceResponse,
  type OrganizationResponse,
} from '@/lib/api/adminClient'
import { GenerateAPIKeyDialog } from './GenerateAPIKeyDialog'

const client = new AdminClient()

interface APIKeysTabProps {
  selectedOrganizationId: number | null
}

export function APIKeysTab({ selectedOrganizationId }: APIKeysTabProps) {
  const [organizations, setOrganizations] = useState<OrganizationResponse[]>([])
  const [dataSources, setDataSources] = useState<DataSourceResponse[]>([])
  const [credentials, setCredentials] = useState<CredentialResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [orgId, setOrgId] = useState<number | null>(selectedOrganizationId)
  const [dialogOpen, setDialogOpen] = useState(false)

  // Sync external selection
  useEffect(() => {
    if (selectedOrganizationId !== null) {
      setOrgId(selectedOrganizationId)
    }
  }, [selectedOrganizationId])

  // Load orgs + data sources on mount
  useEffect(() => {
    Promise.all([client.listOrganizations(), client.listDataSources()])
      .then(([orgs, ds]) => {
        setOrganizations(orgs)
        setDataSources(ds)
      })
      .catch(() => {})
  }, [])

  const loadCredentials = useCallback(async () => {
    if (!orgId) return
    setLoading(true)
    setError(null)
    try {
      const creds = await client.listCredentials(orgId)
      setCredentials(creds)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load credentials')
    } finally {
      setLoading(false)
    }
  }, [orgId])

  useEffect(() => {
    loadCredentials()
  }, [loadCredentials])

  function dataSourceName(dsId: number): string {
    return dataSources.find((ds) => ds.id === dsId)?.name ?? `ID ${dsId}`
  }

  async function handleToggleActive(cred: CredentialResponse) {
    if (!orgId) return
    try {
      await client.updateCredential(cred.id, orgId, { is_active: !cred.is_active })
      loadCredentials()
    } catch {
      // Silently fail and reload
      loadCredentials()
    }
  }

  async function handleDelete(cred: CredentialResponse) {
    if (!orgId) return
    if (!confirm(`Delete credential "${cred.label || cred.id}"? This cannot be undone.`)) return
    try {
      await client.deleteCredential(cred.id, orgId)
      loadCredentials()
    } catch {
      loadCredentials()
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">API Keys</h2>
        <Button
          size="sm"
          disabled={!orgId}
          onClick={() => setDialogOpen(true)}
        >
          <Key className="h-4 w-4 mr-1" />
          Generate API Key
        </Button>
      </div>

      {/* Organization selector */}
      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-600">Organization</label>
        <select
          value={orgId ?? ''}
          onChange={(e) => setOrgId(e.target.value ? Number(e.target.value) : null)}
          className="flex h-9 w-full max-w-xs rounded-md border border-slate-200 bg-white px-3 py-1 text-sm outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400"
        >
          <option value="">Select an organization</option>
          {organizations.map((org) => (
            <option key={org.id} value={org.id}>
              {org.name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {!orgId ? (
        <div className="text-sm text-slate-500 py-8 text-center">
          Select an organization to view its API keys.
        </div>
      ) : loading ? (
        <div className="text-sm text-slate-500 py-8 text-center">Loading credentials...</div>
      ) : credentials.length === 0 ? (
        <div className="text-sm text-slate-500 py-8 text-center">
          No API keys yet. Generate one to get started.
        </div>
      ) : (
        <div className="rounded-md border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="text-left px-4 py-2 font-medium text-slate-600">ID</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Label</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Data Source</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Status</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Last Used</th>
                <th className="text-left px-4 py-2 font-medium text-slate-600">Errors</th>
                <th className="text-right px-4 py-2 font-medium text-slate-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {credentials.map((cred) => (
                <tr key={cred.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-slate-500">{cred.id}</td>
                  <td className="px-4 py-2.5 text-slate-900">
                    {cred.label || <span className="text-slate-400 italic">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {dataSourceName(cred.data_source_id)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge variant={cred.is_active ? 'default' : 'destructive'}>
                      {cred.is_active ? 'Active' : 'Revoked'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {cred.last_used_at
                      ? new Date(cred.last_used_at).toLocaleDateString()
                      : 'Never'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{cred.error_count}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <Switch
                        checked={cred.is_active}
                        onCheckedChange={() => handleToggleActive(cred)}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(cred)}
                        className="text-slate-400 hover:text-red-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {orgId && (
        <GenerateAPIKeyDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          organizationId={orgId}
          dataSources={dataSources}
          onCreated={loadCredentials}
        />
      )}
    </div>
  )
}
