'use client'

import { useEffect, useState } from 'react'
import { adminClient, type ProjectGroupedItem } from '@/lib/api/adminClient'
import { Loader2 } from 'lucide-react'

// TODO: Replace with value from auth context once user authentication is implemented.
// Reset to null on logout.
const CURRENT_ORGANIZATION_ID = 1

interface ProjectSidebarProps {
  selectedProjectId: number | null
  onSelectProject: (id: number) => void
}

export function ProjectSidebar({ selectedProjectId, onSelectProject }: ProjectSidebarProps) {
  const [projects, setProjects] = useState<ProjectGroupedItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const all = await adminClient.listProjectsGrouped()
        setProjects(all.filter((p) => p.organization_id === CURRENT_ORGANIZATION_ID))
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

  if (projects.length === 0) {
    return (
      <div className="px-4 py-8 text-sm text-slate-500 text-center">
        No projects found
      </div>
    )
  }

  return (
    <nav>
      <ul className="space-y-0.5">
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
              {p.external_project_id ? `${p.external_project_id} - ${p.name}` : p.name}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
