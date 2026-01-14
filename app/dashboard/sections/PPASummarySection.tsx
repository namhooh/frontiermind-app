'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Button } from "@/app/components/ui/button"
import { ArrowLeft, Download, FileText } from "lucide-react"

interface PPASummarySectionProps {
  onSectionChange: (section: string) => void
  projectName?: string
}

export function PPASummarySection({ onSectionChange, projectName = "Sunfield Solar Park" }: PPASummarySectionProps) {
  return (
    <div className="p-8 space-y-6">
      {/* Header with Back Button */}
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onSectionChange("contracts")}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Contracts Hub
        </Button>
      </div>

      <h1 className="text-slate-900 text-2xl font-bold" style={{ fontFamily: "'Libre Baskerville', serif" }}>
        PPA Summary: {projectName}
      </h1>

      {/* Source Document */}
      <Card>
        <CardHeader>
          <CardTitle>Source Document</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between p-4 rounded-lg border border-slate-200 bg-slate-50">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-slate-100">
                <FileText className="w-6 h-6 text-slate-600" />
              </div>
              <div>
                <p className="text-slate-900 font-medium">Sunfield_Solar_Park_PPA_Agreement.pdf</p>
                <p className="text-sm text-slate-500">Uploaded on Nov 1, 2025 • 2.4 MB</p>
              </div>
            </div>
            <Button variant="outline" size="sm" className="gap-2">
              <Download className="w-4 h-4" />
              Download
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Terms */}
      <Card>
        <CardHeader>
          <CardTitle>Terms</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Commercial Operations Date (COD)</p>
              <p className="text-slate-900 font-medium">January 15, 2026</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Duration</p>
              <p className="text-slate-900 font-medium">20 years</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Conditions Precedent */}
      <Card>
        <CardHeader>
          <CardTitle>Conditions Precedent</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {[
              "Completion of all construction permits and regulatory approvals",
              "Successful interconnection agreement with local utility",
              "Financial close and security arrangements in place",
              "Insurance policies effective and compliant with agreement terms"
            ].map((item, index) => (
              <li key={index} className="flex items-start gap-2 p-2 border-l-2 border-green-500 bg-green-50 rounded-r-lg">
                <span className="text-slate-700">{item}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Price */}
      <Card>
        <CardHeader>
          <CardTitle>Price</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Price per kWh</p>
              <p className="text-slate-900 font-medium">$0.085/kWh</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Price Escalation</p>
              <p className="text-slate-900 font-medium">2.5% annually</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Taxes</p>
              <p className="text-slate-900 font-medium">Buyer responsibility</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Invoicing and Payment */}
      <Card>
        <CardHeader>
          <CardTitle>Invoicing and Payment</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Payment Deadline</p>
              <p className="text-slate-900 font-medium">30 days from invoice</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Late Payment Interest</p>
              <p className="text-slate-900 font-medium">1.5% per month</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Dispute Timeline</p>
              <p className="text-slate-900 font-medium">90 days</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Generation */}
      <Card>
        <CardHeader>
          <CardTitle>Generation</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Expected Annual Generation</p>
              <p className="text-slate-900 font-medium">12,500,000 kWh</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Take or Pay Conditions</p>
              <p className="text-slate-900 font-medium">Minimum 80% of expected</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Availability Percentage</p>
              <p className="text-slate-900 font-medium">95% minimum</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Availability Damages</p>
              <p className="text-slate-900 font-medium">$5,000 per % below 95%</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Failure to Deliver</p>
              <p className="text-slate-900 font-medium">Market differential rate</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Curtailment Cap</p>
              <p className="text-slate-900 font-medium">5% annual</p>
            </div>
          </div>
          <div className="p-3 rounded-lg border border-amber-200 bg-amber-50">
            <p className="text-sm text-slate-500 uppercase">Meter Accuracy Test</p>
            <p className="text-slate-700">Annual testing required; reimbursement if accuracy exceeds ±2% threshold</p>
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle>Security</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Seller Performance Guarantee</p>
              <p className="text-slate-900 font-medium">$500,000</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Buyer Payment Guarantee</p>
              <p className="text-slate-900 font-medium">$300,000</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Cash Collateral</p>
              <p className="text-slate-900 font-medium">$200,000, -20%/yr</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Letter of Credit</p>
              <p className="text-slate-900 font-medium">$750,000 for 24 months</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Security Interest</p>
              <p className="text-slate-900 font-medium">First lien on equipment</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Delayed COD Damages</p>
              <p className="text-slate-900 font-medium">$10,000/day after 30 days</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Maintenance */}
      <Card>
        <CardHeader>
          <CardTitle>Maintenance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Repair and Maintenance</p>
              <p className="text-slate-900 font-medium">Seller responsibility</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Scheduled Outage</p>
              <p className="text-slate-900 font-medium">Max 7 days/yr, 60 days notice</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Event of Default */}
      <Card>
        <CardHeader>
          <CardTitle>Event of Default</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <p className="text-sm text-slate-500 uppercase mb-2">List of Events</p>
            <ul className="space-y-2">
              {[
                "Failure to make payment within 10 business days of notice",
                "Breach of material obligation not cured within 30 days",
                "False or misleading representations",
                "Insolvency or bankruptcy proceedings",
                "Failure to maintain required insurance"
              ].map((item, index) => (
                <li key={index} className="flex items-start gap-2 p-2 border-l-2 border-red-500 bg-red-50 rounded-r-lg">
                  <span className="text-slate-700">{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Remedy Timeline</p>
              <p className="text-slate-900 font-medium">30 days after notice</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Fee Reimbursement</p>
              <p className="text-slate-900 font-medium">All legal costs</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Termination & Purchase */}
      <Card>
        <CardHeader>
          <CardTitle>Termination & Purchase</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Termination Payment</p>
              <p className="text-slate-900 font-medium">NPV of remaining value</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Option to Purchase</p>
              <p className="text-slate-900 font-medium">Buyer right after year 10</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Fair Market Value</p>
              <p className="text-slate-900 font-medium">Independent appraisal</p>
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-sm text-slate-500 uppercase">Early Termination</p>
              <p className="text-slate-900 font-medium">120 days notice</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Force Majeure */}
      <Card>
        <CardHeader>
          <CardTitle>Force Majeure</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="p-3 rounded-lg border border-slate-200 bg-slate-50 mb-4">
            <p className="text-slate-700">
              Either party may suspend performance during force majeure events (acts of God, war, natural disasters, governmental actions)
            </p>
          </div>
          <div className="p-3 rounded-lg border border-amber-200 bg-amber-50">
            <p className="text-sm text-slate-500 uppercase">Termination Right</p>
            <p className="text-slate-900 font-medium">Either party may terminate if FM persists for more than 12 consecutive months</p>
          </div>
        </CardContent>
      </Card>

      {/* Confidentiality */}
      <Card>
        <CardHeader>
          <CardTitle>Confidentiality</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
            <p className="text-slate-700">
              All terms and financial information confidential for 5 years post-termination, except as required by law or regulatory authorities
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
