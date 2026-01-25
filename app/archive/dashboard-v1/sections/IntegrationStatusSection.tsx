'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Progress } from "@/app/components/ui/progress"
import Image from "next/image"
import {
  Zap,
  TrendingUp,
  Shield,
  FileText,
  ArrowRight,
  Database,
  Calendar
} from "lucide-react"
import snowflakeLogo from '@/app/assets/integrations/snowflake.png'
import sapLogo from '@/app/assets/integrations/sap.png'
import sageLogo from '@/app/assets/integrations/sage.png'
import { useRouter } from "next/navigation"

interface IntegrationStatusSectionProps {
  onSectionChange?: (section: string) => void
}

export function IntegrationStatusSection({ onSectionChange }: IntegrationStatusSectionProps) {
  const router = useRouter()

  const handleNavigate = (section: string) => {
    if (onSectionChange) {
      onSectionChange(section)
    } else {
      const routes: Record<string, string> = {
        'generation': '/dashboard/integrations',
        'pricing': '/dashboard/integrations',
        'regulations': '/dashboard/integrations',
        'contracts': '/dashboard/contracts',
        'calendar': '/dashboard/calendar',
      }
      router.push(routes[section] || '/dashboard')
    }
  }
  const dataInputs = [
    {
      name: "Generation Meter Data",
      icon: Zap,
      status: "active",
      lastUpdate: "2 mins ago",
      color: "text-blue-600 bg-blue-50",
      sectionId: "generation"
    },
    {
      name: "Market Electricity Price",
      icon: TrendingUp,
      status: "active",
      lastUpdate: "5 mins ago",
      color: "text-green-600 bg-green-50",
      sectionId: "pricing"
    },
    {
      name: "Regulation/Grid Charges",
      icon: Shield,
      status: "active",
      lastUpdate: "10 mins ago",
      color: "text-purple-600 bg-purple-50",
      sectionId: "regulations"
    },
    {
      name: "Contractual Terms",
      icon: FileText,
      status: "active",
      lastUpdate: "1 hour ago",
      color: "text-orange-600 bg-orange-50",
      sectionId: "contracts"
    },
  ]

  const outputs = [
    { name: "ERP (SAP, SAGE)", icon: Database, status: "synced", color: "text-amber-600 bg-amber-50" },
    { name: "Calendar", icon: Calendar, status: "synced", color: "text-amber-600 bg-amber-50" },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 mb-2 text-2xl font-bold" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Integration Status
        </h1>
      </div>

      {/* Data Flow Visualization */}
      <Card>
        <CardContent>
          <div className="flex items-center justify-between gap-6 py-8">
            {/* Input Sources */}
            <div className="flex-1 space-y-3">
              <div className="text-sm text-slate-500 mb-4">INPUT SOURCES</div>
              {dataInputs.map((input, index) => {
                const Icon = input.icon
                return (
                  <button
                    key={index}
                    onClick={() => handleNavigate(input.sectionId)}
                    className="w-full flex items-center gap-3 p-3 rounded-lg border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50 transition-all cursor-pointer"
                  >
                    <div className={`p-2 rounded-lg ${input.color}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1 text-left">
                      <div className="text-sm text-slate-900">{input.name}</div>
                      <div className="text-xs text-slate-500">{input.lastUpdate}</div>
                    </div>
                    <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50">
                      {input.status}
                    </Badge>
                  </button>
                )
              })}
            </div>

            {/* AI Ontology Center */}
            <div className="flex flex-col items-center gap-4">
              <ArrowRight className="w-6 h-6 text-slate-400" />
              <div className="relative">
                <div className="w-42 h-28 bg-gradient-to-br from-slate-900 to-slate-700 rounded-2xl flex items-center justify-center shadow-xl">
                  <div className="text-center">
                    <div className="text-white mb-1">Power Purchase</div>
                    <div className="text-white">Ontology</div>
                  </div>
                </div>
                <div className="absolute -top-2 -right-2 w-4 h-4 bg-green-500 rounded-full animate-pulse" />
              </div>
              {/* Snowflake Logo */}
              <div className="flex flex-col items-center gap-2 text-xs text-slate-500">
                <span>Run on your data warehouse</span>
                <Image
                  src={snowflakeLogo}
                  alt="Snowflake Logo"
                  width={112}
                  height={64}
                  className="object-contain"
                />
              </div>
              <ArrowRight className="w-6 h-6 text-slate-400" />
            </div>

            {/* Output Integrations */}
            <div className="flex-1 space-y-3">
              <div className="text-sm text-slate-500 mb-4">OUTPUT INTEGRATIONS</div>
              {outputs.map((output, index) => {
                const Icon = output.icon
                return (
                  <div
                    key={index}
                    onClick={() => output.name === "Calendar" && handleNavigate('calendar')}
                    className={`flex items-center gap-3 p-3 rounded-lg border border-amber-200 bg-amber-50 ${
                      output.name === "Calendar" ? "hover:border-amber-300 hover:bg-amber-100 cursor-pointer transition-all" : ""
                    }`}
                  >
                    <div className={`p-2 rounded-lg ${output.color}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1">
                      <div className="text-sm text-slate-900">{output.name}</div>
                      <div className="text-xs text-slate-500">Last sync: 1 min ago</div>
                    </div>
                    <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50">
                      {output.status}
                    </Badge>
                  </div>
                )
              })}
              {/* SAP and SAGE Logos */}
              <div className="flex flex-col items-center gap-2 mt-4 text-xs text-slate-500">
                <span>Integrated with</span>
                <div className="flex items-center gap-3">
                  <Image
                    src={sapLogo}
                    alt="SAP Logo"
                    width={72}
                    height={40}
                    className="object-contain"
                  />
                  <Image
                    src={sageLogo}
                    alt="SAGE Logo"
                    width={72}
                    height={40}
                    className="object-contain"
                  />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Recent Processing Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[
                { action: "Market price analysis completed", time: "2 mins ago", type: "success" },
                { action: "Generation data synchronized", time: "5 mins ago", type: "success" },
                { action: "ERP integration updated", time: "15 mins ago", type: "info" },
                { action: "Contract terms validated", time: "1 hour ago", type: "success" },
              ].map((activity, index) => (
                <div key={index} className="flex items-start gap-3 pb-3 border-b border-slate-100 last:border-0">
                  <div className={`w-2 h-2 rounded-full mt-2 ${
                    activity.type === "success" ? "bg-green-500" : "bg-blue-500"
                  }`} />
                  <div className="flex-1">
                    <p className="text-sm text-slate-900">{activity.action}</p>
                    <p className="text-xs text-slate-500">{activity.time}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-600">Data Processing</span>
                  <span className="text-sm text-slate-900">95%</span>
                </div>
                <Progress value={95} className="h-2" />
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-600">API Response Time</span>
                  <span className="text-sm text-slate-900">82%</span>
                </div>
                <Progress value={82} className="h-2" />
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-600">Integration Sync</span>
                  <span className="text-sm text-slate-900">100%</span>
                </div>
                <Progress value={100} className="h-2" />
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-600">Data Quality Score</span>
                  <span className="text-sm text-slate-900">98%</span>
                </div>
                <Progress value={98} className="h-2" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
