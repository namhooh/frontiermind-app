'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Button } from "@/app/components/ui/button"
import { AlertCircle, CheckCircle, Clock, ChevronDown, ChevronUp } from "lucide-react"
import { useState } from "react"

interface OverviewSectionProps {
  onSectionChange: (section: string) => void
}

export function OverviewSection({ onSectionChange }: OverviewSectionProps) {
  const [expandedCard, setExpandedCard] = useState<number | null>(null)

  const ppaSettlementList = [
    { projectName: "Sunfield Solar Park", finalBill: "$48,500" },
    { projectName: "Windridge Energy Farm", finalBill: "$92,300" },
    { projectName: "Coastal Renewable Hub", finalBill: "$67,800" },
    { projectName: "Metro Grid Storage", finalBill: "$75,400" },
    { projectName: "Desert Sun Array", finalBill: "$54,200" },
  ]

  const actionItems = [
    { text: "5 PPA invoices verification completed successfully", status: "success", icon: CheckCircle },
    { text: "1 O&M payment modification with Liquidated Damage required", status: "urgent", icon: AlertCircle },
    { text: "2 security packages (bank guarantee) renewals due this month", status: "warning", icon: Clock },
  ]

  const contractorPayables = [
    {
      contractorName: "TechInstall Services",
      invoiceMonth: "November 2025",
      dueDate: "Nov 18, 2025",
      amount: "$24,800",
      status: "verified",
      alert: null,
    },
    {
      contractorName: "GridMaintenance Co.",
      invoiceMonth: "November 2025",
      dueDate: "Nov 16, 2025",
      amount: "$15,600",
      status: "pending",
      alert: "Verification Required",
    },
    {
      contractorName: "Solar Panel Experts",
      invoiceMonth: "October 2025",
      dueDate: "Nov 14, 2025",
      amount: "$38,200",
      status: "urgent",
      alert: "Missing Documentation",
    },
    {
      contractorName: "Energy Compliance Ltd",
      invoiceMonth: "November 2025",
      dueDate: "Nov 20, 2025",
      amount: "$12,500",
      status: "pending",
      alert: "Amount Mismatch",
    },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Payment Settlement and Compliance Dashboard */}
      <div className="space-y-6">
        <h1 className="text-slate-900 text-[24px] font-bold" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Payment Settlement and Compliance
        </h1>

        {/* Dashboard Section - Key Updates and Action Points */}
        <div className="space-y-4">
          {/* Action Items */}
          <Card>
            <CardHeader className="pb-0">
              <CardTitle>Dashboard and Action Items</CardTitle>
            </CardHeader>
            <CardContent className="px-6 pb-6 pt-3">
              <div className="space-y-3">
                {actionItems.map((item, index) => {
                  const Icon = item.icon
                  const isExpanded = expandedCard === index
                  return (
                    <div key={index}>
                      <div
                        className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg cursor-pointer hover:bg-slate-100 transition-colors"
                        onClick={() => setExpandedCard(isExpanded ? null : index)}
                      >
                        <Icon
                          className={`w-5 h-5 ${
                            item.status === "urgent"
                              ? "text-red-600"
                              : item.status === "warning"
                              ? "text-amber-600"
                              : "text-green-600"
                          }`}
                        />
                        <span className="flex-1 text-sm text-slate-700 font-bold">{item.text}</span>
                        <Badge
                          variant="outline"
                          className={
                            item.status === "urgent"
                              ? "bg-red-50 text-red-700 border-red-200"
                              : item.status === "warning"
                              ? "bg-amber-50 text-amber-700 border-amber-200"
                              : "bg-green-50 text-green-700 border-green-200"
                          }
                        >
                          {item.status}
                        </Badge>
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4 text-slate-500" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-slate-500" />
                        )}
                      </div>

                      {/* Expanded Content - Only for first card (PPA invoices) */}
                      {isExpanded && index === 0 && (
                        <div className="mt-3 ml-8 space-y-2 bg-white p-4 rounded-lg border border-slate-200">
                          <p className="text-sm text-slate-600 mb-3">PPA Settlement Details</p>
                          {ppaSettlementList.map((project, ppaIndex) => (
                            <div key={ppaIndex} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-b-0">
                              <div className="flex flex-col">
                                <span className="text-sm text-slate-700">{project.projectName}</span>
                                {project.projectName === "Sunfield Solar Park" && (
                                  <span className="text-xs text-red-600 italic">Annual escalation applied</span>
                                )}
                                {project.projectName === "Coastal Renewable Hub" && (
                                  <span className="text-xs text-red-600 italic">Curtailed output deducted</span>
                                )}
                              </div>
                              <div className="flex items-center gap-3">
                                <span className="text-sm text-slate-900">{project.finalBill}</span>
                                <Button size="sm" variant="outline" className="text-xs">
                                  See Settlement Detail
                                </Button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* PPA and Contractors Sections */}
        <div className="grid grid-cols-2 gap-6">
          {/* PPA Section */}
          <Card>
            <CardHeader>
              <CardTitle>PPA</CardTitle>
            </CardHeader>
            <CardContent className="px-6 pb-6 pt-3">
              <div className="space-y-3">
                {ppaSettlementList.map((project, index) => (
                  <Card
                    key={index}
                    className="border border-slate-200 cursor-pointer hover:bg-slate-50 transition-colors"
                    onClick={() => onSectionChange('ppa-summary')}
                  >
                    <CardContent className="p-4">
                      <div className="space-y-2">
                        <div className="flex items-start justify-between">
                          <div>
                            <p className="text-slate-900">{project.projectName}</p>
                            <p className="text-sm text-slate-500">Final Bill</p>
                          </div>
                          <Badge
                            variant="outline"
                            className="bg-green-50 text-green-700 border-green-200"
                          >
                            {project.finalBill}
                          </Badge>
                        </div>
                        <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                          <div>
                            <p className="text-xs text-slate-500">Invoice Amount</p>
                            <p className="text-slate-900">{project.finalBill}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-xs text-slate-500">Deadline</p>
                            <p className="text-sm text-slate-700">Nov 15, 2025</p>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Contractors Section */}
          <Card>
            <CardHeader>
              <CardTitle>Contractors</CardTitle>
            </CardHeader>
            <CardContent className="px-6 pb-6 pt-3">
              <div className="space-y-3">
                {contractorPayables.map((payable, index) => (
                  <Card key={index} className="border border-slate-200">
                    <CardContent className="p-4">
                      <div className="space-y-2">
                        <div className="flex items-start justify-between">
                          <div>
                            <p className="text-slate-900">{payable.contractorName}</p>
                            <p className="text-sm text-slate-500">{payable.invoiceMonth}</p>
                          </div>
                          <Badge
                            variant="outline"
                            className={
                              payable.status === "verified"
                                ? "bg-green-50 text-green-700 border-green-200"
                                : payable.status === "urgent"
                                ? "bg-red-50 text-red-700 border-red-200"
                                : "bg-blue-50 text-blue-700 border-blue-200"
                            }
                          >
                            {payable.status}
                          </Badge>
                        </div>
                        <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                          <div>
                            <p className="text-xs text-slate-500">Invoice Amount</p>
                            <p className="text-slate-900">{payable.amount}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-xs text-slate-500">Deadline</p>
                            <p className="text-sm text-slate-700">{payable.dueDate}</p>
                          </div>
                        </div>
                        {payable.alert && (
                          <div className="mt-2">
                            <Badge
                              variant="outline"
                              className="bg-amber-50 text-amber-700 border-amber-200"
                            >
                              {payable.alert}
                            </Badge>
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
