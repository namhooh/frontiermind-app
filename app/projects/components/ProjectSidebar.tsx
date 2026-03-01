'use client'

import { useEffect, useMemo, useState } from 'react'
import { adminClient, type ProjectGroupedItem } from '@/lib/api/adminClient'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'

// TODO: Replace with value from auth context once user authentication is implemented.
// Reset to null on logout.
const CURRENT_ORGANIZATION_ID = 1

type SortBy = 'name' | 'sage_id' | 'country'

interface ProjectSidebarProps {
  selectedProjectId: number | null
  onSelectProject: (id: number) => void
}

export function ProjectSidebar({ selectedProjectId, onSelectProject }: ProjectSidebarProps) {
  const [projects, setProjects] = useState<ProjectGroupedItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortBy>('name')
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())

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

  const badgeWidth = useMemo(() => {
    const maxLen = projects.reduce((max, p) => Math.max(max, p.sage_id?.length ?? 0), 0)
    return maxLen > 0 ? `${maxLen}ch` : undefined
  }, [projects])

  const sortedProjects = useMemo(() => {
    const sorted = [...projects]
    if (sortBy === 'name') {
      sorted.sort((a, b) => a.name.localeCompare(b.name))
    } else if (sortBy === 'sage_id') {
      sorted.sort((a, b) => (a.sage_id ?? '').localeCompare(b.sage_id ?? ''))
    }
    return sorted
  }, [projects, sortBy])

  const countryGroups = useMemo(() => {
    if (sortBy !== 'country') return null
    const groups = new Map<string, ProjectGroupedItem[]>()
    for (const p of projects) {
      const key = p.country || 'No Country'
      const list = groups.get(key) ?? []
      list.push(p)
      groups.set(key, list)
    }
    // Sort group keys alphabetically, but "No Country" goes last
    const sortedEntries = [...groups.entries()].sort(([a], [b]) => {
      if (a === 'No Country') return 1
      if (b === 'No Country') return -1
      return a.localeCompare(b)
    })
    // Sort projects within each group by name
    for (const [, list] of sortedEntries) {
      list.sort((a, b) => a.name.localeCompare(b.name))
    }
    return sortedEntries
  }, [projects, sortBy])

  function toggleGroup(group: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(group)) {
        next.delete(group)
      } else {
        next.add(group)
      }
      return next
    })
  }

  function renderProjectButton(p: ProjectGroupedItem) {
    return (
      <button
        type="button"
        onClick={() => onSelectProject(p.id)}
        className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
          selectedProjectId === p.id
            ? 'bg-blue-50 text-blue-700 font-medium'
            : 'text-slate-700 hover:bg-slate-100'
        }`}
      >
        {p.sage_id ? (
          <span className="flex items-center gap-1.5">
            <span
              className="inline-flex items-center justify-center px-1 py-0 rounded text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200 shrink-0"
              style={{ minWidth: badgeWidth }}
            >
              {p.sage_id}
            </span>
            <span className="truncate">{p.name}</span>
          </span>
        ) : p.name}
      </button>
    )
  }

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
      <div className="px-3 pb-2 mb-1">
        <div className="flex items-center gap-2">
          <label htmlFor="sort-select" className="text-xs text-slate-500 shrink-0">Sort by</label>
          <select
            id="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            className="w-full text-xs rounded-md border border-slate-200 bg-white px-2 py-1 text-slate-700 focus:outline-none focus:border-blue-400"
          >
            <option value="name">Name</option>
            <option value="sage_id">Sage ID</option>
            <option value="country">Country</option>
          </select>
        </div>
      </div>

      {sortBy === 'country' && countryGroups ? (
        <div className="space-y-0.5">
          {countryGroups.map(([group, items]) => {
            const isCollapsed = collapsedGroups.has(group)
            return (
              <div key={group}>
                <button
                  type="button"
                  onClick={() => toggleGroup(group)}
                  className="w-full flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-slate-700 hover:text-slate-700 transition-colors"
                >
                  {isCollapsed ? (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                  )}
                  {group}
                  <span className="text-slate-400 font-normal ml-auto">{items.length}</span>
                </button>
                {!isCollapsed && (
                  <ul className="space-y-0.5">
                    {items.map((p) => (
                      <li key={p.id}>{renderProjectButton(p)}</li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <ul className="space-y-0.5">
          {sortedProjects.map((p) => (
            <li key={p.id}>{renderProjectButton(p)}</li>
          ))}
        </ul>
      )}
    </nav>
  )
}
