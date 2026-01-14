'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Shield, AlertTriangle, CheckCircle } from "lucide-react"

interface RegulationsSectionProps {
  onSectionChange: (section: string) => void
}

export function RegulationsSection({ onSectionChange }: RegulationsSectionProps) {
  const regulations = [
    {
      name: "Grid Connection Charges",
      authority: "ERCOT",
      status: "compliant",
      lastReview: "Nov 1, 2025",
      nextReview: "Feb 1, 2026"
    },
    {
      name: "Renewable Energy Credits (REC)",
      authority: "EPA",
      status: "compliant",
      lastReview: "Oct 15, 2025",
      nextReview: "Jan 15, 2026"
    },
    {
      name: "Transmission Service Agreement",
      authority: "FERC",
      status: "review",
      lastReview: "Sep 20, 2025",
      nextReview: "Nov 20, 2025"
    },
    {
      name: "Environmental Impact Assessment",
      authority: "State EPA",
      status: "compliant",
      lastReview: "Aug 10, 2025",
      nextReview: "Aug 10, 2026"
    },
  ]

  const gridCharges = [
    { type: "Transmission Use of System", rate: "$2.50/MWh", change: "No change" },
    { type: "Distribution Use of System", rate: "$1.80/MWh", change: "+$0.10/MWh" },
    { type: "System Operator Charges", rate: "$0.35/MWh", change: "No change" },
    { type: "Balancing Service Charges", rate: "$0.75/MWh", change: "-$0.05/MWh" },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Regulation/Grid Charges
        </h1>
        <p className="text-slate-500 text-sm">
          Regulatory compliance and grid charge tracking
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Compliance Status */}
        <Card>
          <CardHeader>
            <CardTitle>Compliance Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {regulations.map((item, index) => (
                <div
                  key={index}
                  className="flex items-start gap-4 p-4 rounded-lg border border-slate-200 bg-white"
                >
                  <div className={`p-2 rounded-lg ${
                    item.status === "compliant"
                      ? "bg-green-50"
                      : "bg-amber-50"
                  }`}>
                    {item.status === "compliant" ? (
                      <CheckCircle className="w-5 h-5 text-green-600" />
                    ) : (
                      <AlertTriangle className="w-5 h-5 text-amber-600" />
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-900 font-medium mb-1">{item.name}</div>
                    <div className="text-sm text-slate-500">{item.authority}</div>
                    <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                      <span>Last: {item.lastReview}</span>
                      <span>Next: {item.nextReview}</span>
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      item.status === "compliant"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                    }
                  >
                    {item.status}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Grid Charges */}
        <Card>
          <CardHeader>
            <CardTitle>Current Grid Charges</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {gridCharges.map((item, index) => (
                <div
                  key={index}
                  className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white"
                >
                  <div className="p-2 rounded-lg bg-purple-50">
                    <Shield className="w-5 h-5 text-purple-600" />
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-900 font-medium">{item.type}</div>
                    <div className="text-sm text-slate-500">{item.change}</div>
                  </div>
                  <span className="text-lg font-bold text-slate-900">{item.rate}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
