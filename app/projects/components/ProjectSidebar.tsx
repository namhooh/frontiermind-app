'use client'

import { useEffect, useMemo, useState } from 'react'
import { adminClient, type ProjectGroupedItem } from '@/lib/api/adminClient'
import { BarChart3, Bell, ChevronDown, ChevronRight, Loader2, Search, X } from 'lucide-react'
import Link from 'next/link'
import { CURRENT_ORGANIZATION_ID } from '@/app/projects/utils/constants'

type SortBy = 'name' | 'sage_id' | 'country'

interface ProjectSidebarProps {
  selectedProjectId: number | null
  onSelectProject: (id: number) => void
  onSelectHome?: () => void
}

export function ProjectSidebar({ selectedProjectId, onSelectProject, onSelectHome }: ProjectSidebarProps) {
  const [projects, setProjects] = useState<ProjectGroupedItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortBy>('name')
  const [searchQuery, setSearchQuery] = useState('')
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

  const filteredProjects = useMemo(() => {
    if (!searchQuery.trim()) return projects
    const q = searchQuery.toLowerCase()
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.sage_id ?? '').toLowerCase().includes(q)
    )
  }, [projects, searchQuery])

  const sortedProjects = useMemo(() => {
    const sorted = [...filteredProjects]
    if (sortBy === 'name') {
      sorted.sort((a, b) => a.name.localeCompare(b.name))
    } else if (sortBy === 'sage_id') {
      sorted.sort((a, b) => (a.sage_id ?? '').localeCompare(b.sage_id ?? ''))
    }
    return sorted
  }, [filteredProjects, sortBy])

  const countryGroups = useMemo(() => {
    if (sortBy !== 'country') return null
    const groups = new Map<string, ProjectGroupedItem[]>()
    for (const p of filteredProjects) {
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
  }, [filteredProjects, sortBy])

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
      <a
        href={`/projects?id=${p.id}`}
        onClick={(e) => {
          e.preventDefault()
          onSelectProject(p.id)
        }}
        className={`block w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
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
      </a>
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
      {/* Portfolio Dashboard link */}
      {onSelectHome && (
        <>
          <button
            type="button"
            onClick={onSelectHome}
            className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              selectedProjectId === null
                ? 'bg-blue-700/70 text-white'
                : 'bg-blue-100 text-slate-700 hover:bg-blue-200'
            }`}
          >
            <BarChart3 className="h-4 w-4 shrink-0" />
            Portfolio Dashboard
          </button>
          <Link
            href="/notifications"
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors bg-slate-50 text-slate-600 hover:bg-slate-100"
          >
            <Bell className="h-4 w-4 shrink-0" />
            Notifications
          </Link>

          <div className="border-b border-slate-200 my-2" />
        </>
      )}

      <div className="px-3 pb-2 mb-1 flex items-center gap-2">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
          <input
            type="text"
            placeholder="Search…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full text-xs rounded-md border border-slate-200 bg-white pl-7 pr-7 py-1.5 text-slate-700 placeholder:text-slate-400 focus:outline-none focus:border-blue-400"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <select
          id="sort-select"
          aria-label="Sort by"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortBy)}
          className="text-xs rounded-md border border-slate-200 bg-white px-2 py-1.5 text-slate-700 focus:outline-none focus:border-blue-400 shrink-0"
        >
          <option value="name">Name</option>
          <option value="sage_id">Sage ID</option>
          <option value="country">Country</option>
        </select>
      </div>

      {filteredProjects.length === 0 && searchQuery ? (
        <div className="px-4 py-6 text-xs text-slate-400 text-center">
          No projects matching &ldquo;{searchQuery}&rdquo;
        </div>
      ) : sortBy === 'country' && countryGroups ? (
        <div className="space-y-0.5">
          {countryGroups.map(([group, items]) => {
            const isCollapsed = collapsedGroups.has(group)
            return (
              <div key={group}>
                <button
                  type="button"
                  onClick={() => toggleGroup(group)}
                  className="w-full flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-slate-600 hover:text-slate-700 transition-colors"
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
