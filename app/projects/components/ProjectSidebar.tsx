'use client'

import { useEffect, useState } from 'react'
import { adminClient, type ProjectGroupedItem } from '@/lib/api/adminClient'
import { Loader2 } from 'lucide-react'

interface ProjectSidebarProps {
  selectedProjectId: number | null
  onSelectProject: (id: number) => void
}

interface OrgGroup {
  organization_id: number
  organization_name: string
  projects: ProjectGroupedItem[]
}

export function ProjectSidebar({ selectedProjectId, onSelectProject }: ProjectSidebarProps) {
  const [groups, setGroups] = useState<OrgGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const projects = await adminClient.listProjectsGrouped()

        // Group by organization (already sorted by org name, project name from API)
        const orgMap = new Map<number, OrgGroup>()
        for (const p of projects) {
          let group = orgMap.get(p.organization_id)
          if (!group) {
            group = { organization_id: p.organization_id, organization_name: p.organization_name, projects: [] }
            orgMap.set(p.organization_id, group)
          }
          group.projects.push(p)
        }

        setGroups(Array.from(orgMap.values()))
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load projects')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error) {
    return <div className="px-4 py-3 text-sm text-red-600">{error}</div>
  }

  if (groups.length === 0) {
    return (
      <div className="px-4 py-8 text-sm text-slate-500 text-center">
        No projects found
      </div>
    )
  }

  return (
    <nav className="space-y-4">
      {groups.map(({ organization_id, organization_name, projects }) => (
        <div key={organization_id}>
          <div className="px-3 py-1 text-xs font-medium text-slate-400 uppercase tracking-wider">
            {organization_name}
          </div>
          <ul className="mt-1 space-y-0.5">
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => onSelectProject(p.id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                    selectedProjectId === p.id
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-slate-700 hover:bg-slate-100'
                  }`}
                >
                  {p.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}
