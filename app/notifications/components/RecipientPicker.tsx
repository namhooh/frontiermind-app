'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import { X, Search } from 'lucide-react'
import { NotificationsClient, type ContactItem } from '@/lib/api/notificationsClient'

interface RecipientPickerProps {
  value: string[]
  onChange: (emails: string[]) => void
  client: NotificationsClient
  projectId?: number
}

export function RecipientPicker({ value, onChange, client, projectId }: RecipientPickerProps) {
  const [contacts, setContacts] = useState<ContactItem[]>([])
  const [search, setSearch] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    client.listContacts({ project_id: projectId, include_all: true })
      .then(({ contacts }) => setContacts(contacts))
      .catch(() => {})
  }, [client, projectId])

  const filtered = useMemo(() => {
    if (!search.trim()) return contacts
    const q = search.toLowerCase()
    return contacts.filter(
      (c) =>
        c.email.toLowerCase().includes(q) ||
        (c.full_name?.toLowerCase().includes(q)) ||
        (c.counterparty_name?.toLowerCase().includes(q))
    )
  }, [contacts, search])

  // Group by counterparty
  const grouped = useMemo(() => {
    const map = new Map<string, ContactItem[]>()
    for (const c of filtered) {
      const key = c.counterparty_name || 'Other'
      const list = map.get(key) ?? []
      list.push(c)
      map.set(key, list)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  const available = useMemo(
    () => filtered.filter((c) => !value.includes(c.email)),
    [filtered, value]
  )

  function addEmail(email: string) {
    const trimmed = email.trim().toLowerCase()
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed])
    }
    setSearch('')
  }

  function removeEmail(email: string) {
    onChange(value.filter((e) => e !== email))
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && search.trim()) {
      e.preventDefault()
      addEmail(search)
    }
  }

  return (
    <div className="space-y-2">
      {/* Selected badges */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((email) => {
            const contact = contacts.find((c) => c.email === email)
            return (
              <span
                key={email}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-blue-50 text-blue-700 border border-blue-200"
              >
                {contact?.full_name || email}
                <button type="button" onClick={() => removeEmail(email)} className="hover:text-blue-900">
                  <X className="w-3 h-3" />
                </button>
              </span>
            )
          })}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          ref={inputRef}
          type="text"
          placeholder="Search contacts or type email..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setShowDropdown(true)
          }}
          onFocus={() => setShowDropdown(true)}
          onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
          onKeyDown={handleKeyDown}
          className="w-full pl-8 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
        />

        {/* Dropdown */}
        {showDropdown && available.length > 0 && (
          <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-auto">
            {grouped.map(([group, items]) => {
              const avail = items.filter((c) => !value.includes(c.email))
              if (!avail.length) return null
              return (
                <div key={group}>
                  <div className="px-3 py-1 text-xs font-medium text-slate-400 bg-slate-50 sticky top-0">
                    {group}
                  </div>
                  {avail.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="w-full text-left px-3 py-1.5 text-sm hover:bg-blue-50 transition-colors"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        addEmail(c.email)
                      }}
                    >
                      <span className="font-medium text-slate-700">{c.full_name || c.email}</span>
                      {c.full_name && (
                        <span className="text-slate-400 ml-2">{c.email}</span>
                      )}
                      {c.role && (
                        <span className="text-slate-400 ml-1">({c.role})</span>
                      )}
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
