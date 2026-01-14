'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Input } from "@/app/components/ui/input"
import { Badge } from "@/app/components/ui/badge"
import { FileText } from "lucide-react"
import ContractUpload from "@/app/components/ContractUpload"

interface ContractsSectionProps {
  onSectionChange: (section: string) => void
}

export function ContractsSection({ onSectionChange }: ContractsSectionProps) {
  const contracts = [
    { name: "PPA - Sunfield Solar Park", term: "20 years", expiry: "Dec 2043", status: "active" },
    { name: "PPA - Windridge Energy Farm", term: "15 years", expiry: "Jun 2038", status: "active" },
    { name: "PPA - Coastal Renewable Hub", term: "10 years", expiry: "Mar 2028", status: "renewal" },
    { name: "PPA - Metro Grid Storage", term: "10 years", expiry: "Sep 2033", status: "active" },
    { name: "PPA - Desert Sun Array", term: "5 years", expiry: "Nov 2030", status: "active" },
  ]

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Digitize your documents
        </h1>
        <p className="text-slate-500 text-sm">
          Upload and process contracts with AI-powered extraction
        </p>
      </div>

      {/* Contract Upload Component */}
      <ContractUpload />

      {/* Contracts Hub */}
      <div className="space-y-4">
        <h2 className="text-slate-900 text-xl font-semibold">
          Contracts Hub
        </h2>

        <Card>
          <CardHeader>
            <Input placeholder="Search contracts..." className="max-w-md" />
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {contracts.map((contract, index) => (
                <div
                  key={index}
                  className={`flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white transition-all ${
                    contract.name === "PPA - Sunfield Solar Park"
                      ? "cursor-pointer hover:border-blue-300 hover:bg-blue-50"
                      : ""
                  }`}
                  onClick={() => {
                    if (contract.name === "PPA - Sunfield Solar Park") {
                      onSectionChange("ppa-summary")
                    }
                  }}
                >
                  <div className={`p-3 rounded-lg ${
                    contract.status === "renewal"
                      ? "bg-amber-50"
                      : "bg-green-50"
                  }`}>
                    <FileText className={`w-5 h-5 ${
                      contract.status === "renewal"
                        ? "text-amber-600"
                        : "text-green-600"
                    }`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-900 font-medium mb-1">{contract.name}</div>
                    <div className="text-sm text-slate-500">
                      {contract.term} • Expires {contract.expiry}
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      contract.status === "active"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                    }
                  >
                    {contract.status}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
