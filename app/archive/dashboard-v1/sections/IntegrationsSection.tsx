'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Button } from "@/app/components/ui/button"
import Image from "next/image"
import { Database, Calendar, RefreshCw, CheckCircle, XCircle, Clock } from "lucide-react"
import snowflakeLogo from '@/app/assets/integrations/snowflake.png'
import sapLogo from '@/app/assets/integrations/sap.png'
import sageLogo from '@/app/assets/integrations/sage.png'

export function IntegrationsSection() {
  const integrations = [
    {
      name: "Snowflake",
      description: "Data warehouse for analytics",
      status: "connected",
      lastSync: "2 mins ago",
      logo: snowflakeLogo
    },
    {
      name: "SAP",
      description: "Enterprise resource planning",
      status: "connected",
      lastSync: "5 mins ago",
      logo: sapLogo
    },
    {
      name: "SAGE",
      description: "Accounting and finance",
      status: "connected",
      lastSync: "10 mins ago",
      logo: sageLogo
    },
  ]

  const availableIntegrations = [
    { name: "Salesforce", description: "Customer relationship management", icon: Database },
    { name: "Google Calendar", description: "Calendar synchronization", icon: Calendar },
    { name: "Microsoft Teams", description: "Team collaboration", icon: Database },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1
          className="text-stone-900 text-2xl font-bold mb-2"
          style={{ fontFamily: "'Playfair Display', serif" }}
        >
          Integrations
        </h1>
        <p className="text-stone-600 font-mono text-sm">
          Manage connected services and data integrations
        </p>
      </div>

      {/* Connected Integrations */}
      <Card>
        <CardHeader>
          <CardTitle>Connected Services</CardTitle>
          <CardDescription>Currently active integrations</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {integrations.map((item, index) => (
              <div
                key={index}
                className="flex items-center gap-4 p-4 border-2 border-stone-900 bg-white hover:-translate-y-0.5 hover:shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] transition-all"
              >
                <div className="w-16 h-12 border-2 border-stone-200 flex items-center justify-center bg-white p-2">
                  <Image
                    src={item.logo}
                    alt={item.name}
                    width={48}
                    height={32}
                    className="object-contain"
                  />
                </div>
                <div className="flex-1">
                  <div className="text-stone-900 font-medium">{item.name}</div>
                  <div className="text-sm text-stone-500 font-mono">{item.description}</div>
                </div>
                <div className="flex items-center gap-2 text-xs text-stone-500 font-mono">
                  <Clock className="w-3 h-3" />
                  {item.lastSync}
                </div>
                <Badge variant="success">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  {item.status}
                </Badge>
                <Button variant="outline" size="sm">
                  <RefreshCw className="w-4 h-4 mr-1" />
                  Sync
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Available Integrations */}
      <Card>
        <CardHeader>
          <CardTitle>Available Integrations</CardTitle>
          <CardDescription>Connect additional services</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {availableIntegrations.map((item, index) => {
              const Icon = item.icon
              return (
                <div
                  key={index}
                  className="flex flex-col items-center p-6 border-2 border-stone-300 bg-stone-50 hover:border-stone-900 hover:bg-white transition-all cursor-pointer"
                >
                  <div className="p-3 border-2 border-stone-400 bg-white mb-3">
                    <Icon className="w-6 h-6 text-stone-600" />
                  </div>
                  <div className="text-stone-900 font-medium text-center">{item.name}</div>
                  <div className="text-xs text-stone-500 font-mono text-center mt-1">
                    {item.description}
                  </div>
                  <Button variant="outline" size="sm" className="mt-4">
                    Connect
                  </Button>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
