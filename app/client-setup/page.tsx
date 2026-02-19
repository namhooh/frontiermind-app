'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/app/components/ui/tabs'
import { OrganizationsTab } from './components/OrganizationsTab'
import { APIKeysTab } from './components/APIKeysTab'

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('organizations')
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null)

  function handleSelectOrganization(orgId: number) {
    setSelectedOrgId(orgId)
    setActiveTab('api-keys')
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Client Onboarding</h1>
            <p className="text-sm text-slate-500 mt-1">
              Manage organizations and API keys for data ingestion
            </p>
          </div>
          <Link
            href="/workflow"
            className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Workflow
          </Link>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="organizations">Organizations</TabsTrigger>
            <TabsTrigger value="api-keys">API Keys</TabsTrigger>
          </TabsList>

          <div className="mt-6">
            <TabsContent value="organizations">
              <OrganizationsTab onSelectOrganization={handleSelectOrganization} />
            </TabsContent>

            <TabsContent value="api-keys">
              <APIKeysTab selectedOrganizationId={selectedOrgId} />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  )
}
