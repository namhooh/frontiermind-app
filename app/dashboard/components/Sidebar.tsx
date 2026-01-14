'use client'

import {
  LayoutDashboard,
  Link2,
  FileText,
  Calendar,
  Settings,
  Sparkles
} from "lucide-react"
import { Button } from "@/app/components/ui/button"

interface SidebarProps {
  activeSection: string
  onSectionChange: (section: string) => void
}

export function Sidebar({ activeSection, onSectionChange }: SidebarProps) {
  const menuItems = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "integration-status", label: "Integration Status", icon: Link2 },
    { id: "contracts", label: "Contracts Hub", icon: FileText },
    { id: "calendar", label: "Calendar Sync", icon: Calendar },
    { id: "settings", label: "Settings", icon: Settings },
  ]

  return (
    <div className="w-64 bg-white border-r border-slate-200 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-slate-900 font-bold" style={{ fontFamily: "'Libre Baskerville', serif" }}>
              FrontierMind
            </h1>
            <p className="text-slate-500 text-xs font-normal text-[10px]">
              AI co-pilot for corporate energy projects
            </p>
          </div>
        </div>
      </div>

      {/* Assistant Button */}
      <div className="p-4">
        <Button className="w-full bg-gradient-to-r from-blue-600 to-indigo-700 text-white hover:from-blue-700 hover:to-indigo-800">
          <Sparkles className="w-4 h-4 mr-2" />
          Assistant
        </Button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 pt-0 space-y-1">
        <div className="text-xs text-slate-500 px-3 py-2">MAIN MENU</div>
        {menuItems.map((item) => {
          const Icon = item.icon
          const isActive = activeSection === item.id
          return (
            <button
              key={item.id}
              onClick={() => onSectionChange(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <Icon className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      {/* User Profile */}
      <div className="p-4 border-t border-slate-200">
        <div className="flex items-center gap-3 px-3">
          <div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center">
            <span className="text-slate-600 text-sm">NO</span>
          </div>
          <div className="flex-1">
            <p className="text-sm text-slate-900">Namho Oh</p>
            <p className="text-xs text-slate-500">Admin</p>
          </div>
        </div>
      </div>
    </div>
  )
}
