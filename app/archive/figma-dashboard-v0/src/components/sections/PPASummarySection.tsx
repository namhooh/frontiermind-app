import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { ArrowLeft, Download, FileText } from "lucide-react";

interface PPASummarySectionProps {
  onSectionChange: (section: string) => void;
  projectName?: string;
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

      <h1 className="text-slate-900 font-[Libre_Baskerville] text-[24px] font-bold">
        PPA Summary: {projectName}
      </h1>

      {/* PDF Upload Section */}
      <Card>
        <CardHeader>
          <CardTitle>Source Document</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-200">
            <div className="flex items-center gap-3">
              <FileText className="w-8 h-8 text-slate-600" />
              <div>
                <p className="text-slate-900">Sunfield_Solar_Park_PPA_Agreement.pdf</p>
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

      {/* Duration */}
      <Card>
        <CardHeader>
          <CardTitle>Terms</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Commercial Operations Date (COD) Expected</p>
              <p className="text-slate-900">January 15, 2026</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Duration</p>
              <p className="text-slate-900">20 years</p>
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
          <ul className="list-disc list-inside space-y-2 text-slate-700">
            <li>Completion of all construction permits and regulatory approvals</li>
            <li>Successful interconnection agreement with local utility</li>
            <li>Financial close and security arrangements in place</li>
            <li>Insurance policies effective and compliant with agreement terms</li>
          </ul>
        </CardContent>
      </Card>

      {/* Price */}
      <Card>
        <CardHeader>
          <CardTitle>Price</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-slate-500">Price per kWh</p>
              <p className="text-slate-900">$0.085/kWh</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Price Escalation</p>
              <p className="text-slate-900">2.5% annually</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Taxes</p>
              <p className="text-slate-900">Buyer responsibility</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Invoicing and Payment */}
      <Card>
        <CardHeader>
          <CardTitle>Invoicing and Payment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-slate-500">Deadline for Invoice Payment</p>
              <p className="text-slate-900">30 days from invoice date</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Interest on Delayed Payment</p>
              <p className="text-slate-900">1.5% per month</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Dispute Settlement Timeline</p>
              <p className="text-slate-900">90 days</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Generation */}
      <Card>
        <CardHeader>
          <CardTitle>Generation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Expected Generation (Annual)</p>
              <p className="text-slate-900">12,500,000 kWh</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Take or Pay Conditions</p>
              <p className="text-slate-900">Minimum 80% of expected generation</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Availability Percentage</p>
              <p className="text-slate-900">95% minimum</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Availability Damages</p>
              <p className="text-slate-900">$5,000 per percentage point below 95%</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Failure to Deliver Compensation</p>
              <p className="text-slate-900">Market differential rate</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Curtailment by Seller Cap</p>
              <p className="text-slate-900">5% annual</p>
            </div>
          </div>
          <div className="pt-2">
            <p className="text-sm text-slate-500">Meter Accuracy Test & Reimbursement</p>
            <p className="text-slate-700">Annual meter testing required; reimbursement if accuracy exceeds ±2% threshold</p>
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle>Security</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Performance Guarantee by Seller</p>
              <p className="text-slate-900">$500,000</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Payment Guarantee by Buyer</p>
              <p className="text-slate-900">$300,000</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Cash Collateral & Adjustment</p>
              <p className="text-slate-900">$200,000, reducible by 20% annually</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Letter of Credit</p>
              <p className="text-slate-900">$750,000 for 24 months</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Security Interest/Collateral</p>
              <p className="text-slate-900">First lien on all equipment</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Delayed COD Liquidated Damages</p>
              <p className="text-slate-900">$10,000 per day after 30-day grace period</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Maintenance */}
      <Card>
        <CardHeader>
          <CardTitle>Maintenance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Repair and Maintenance Cost</p>
              <p className="text-slate-900">Seller responsibility</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Scheduled Outage</p>
              <p className="text-slate-900">Maximum 7 days annually with 60 days notice</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Event of Default */}
      <Card>
        <CardHeader>
          <CardTitle>Event of Default</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm text-slate-500 mb-2">List of Events</p>
            <ul className="list-disc list-inside space-y-1 text-slate-700">
              <li>Failure to make payment within 10 business days of notice</li>
              <li>Breach of material obligation not cured within 30 days</li>
              <li>False or misleading representations</li>
              <li>Insolvency or bankruptcy proceedings</li>
              <li>Failure to maintain required insurance</li>
            </ul>
          </div>
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div>
              <p className="text-sm text-slate-500">Remedy Timeline</p>
              <p className="text-slate-900">30 days after written notice</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Fee Reimbursement</p>
              <p className="text-slate-900">All reasonable legal and enforcement costs</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Termination & Purchase */}
      <Card>
        <CardHeader>
          <CardTitle>Termination & Purchase</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Termination Payment</p>
              <p className="text-slate-900">NPV of remaining contract value</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Option to Purchase</p>
              <p className="text-slate-900">Buyer has right after year 10</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Fair Market Value Calculation</p>
              <p className="text-slate-900">Independent appraisal by mutually agreed third party</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Early Termination</p>
              <p className="text-slate-900">120 days written notice required</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Damage */}
      <Card>
        <CardHeader>
          <CardTitle>Damage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm text-slate-500 mb-2">Conditions</p>
            <p className="text-slate-700">Seller must repair or replace damaged facility within 180 days</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-500">Payment Obligations</p>
              <p className="text-slate-900">Suspended during repair period exceeding 30 days</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Insurance Requirements</p>
              <p className="text-slate-900">All-risk property insurance, minimum $50M</p>
            </div>
          </div>
          <div className="pt-2">
            <p className="text-sm text-slate-500">Insurance Policy Provisions</p>
            <p className="text-slate-700">Comprehensive general liability, workers compensation, environmental liability</p>
          </div>
        </CardContent>
      </Card>

      {/* Indemnification & Liability */}
      <Card>
        <CardHeader>
          <CardTitle>Indemnification & Liability</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <p className="text-slate-700">
              Each party indemnifies the other for third-party claims arising from its negligence or breach of agreement
            </p>
            <p className="text-slate-700">
              Liability cap: $10,000,000 per incident (excluding gross negligence or willful misconduct)
            </p>
            <p className="text-slate-700">
              No liability for indirect, consequential, or punitive damages except in cases of gross negligence
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Force Majeure */}
      <Card>
        <CardHeader>
          <CardTitle>Force Majeure</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div>
            <p className="text-slate-700">
              Either party may suspend performance during force majeure events (acts of God, war, natural disasters, governmental actions)
            </p>
          </div>
          <div>
            <p className="text-sm text-slate-500">Right to Terminate Under Prolonged FM</p>
            <p className="text-slate-900">Either party may terminate if FM persists for more than 12 consecutive months</p>
          </div>
        </CardContent>
      </Card>

      {/* Assignment */}
      <Card>
        <CardHeader>
          <CardTitle>Assignment</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-slate-700">
            No assignment without prior written consent of the other party, except to affiliates or in connection with financing arrangements
          </p>
        </CardContent>
      </Card>

      {/* Confidentiality */}
      <Card>
        <CardHeader>
          <CardTitle>Confidentiality</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-slate-700">
            All terms and financial information confidential for 5 years post-termination, except as required by law or regulatory authorities
          </p>
        </CardContent>
      </Card>

      {/* Change in Law */}
      <Card>
        <CardHeader>
          <CardTitle>Change in Law</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm text-slate-500 mb-2">Material Adverse Effect</p>
            <p className="text-slate-700">Parties to negotiate in good faith for equitable adjustment</p>
          </div>
          <div>
            <p className="text-sm text-slate-500 mb-2">Utility Rate Schedule or Market Tariff Change</p>
            <p className="text-slate-700">Price adjustment mechanism triggered if change exceeds 10% impact</p>
          </div>
          <div>
            <p className="text-sm text-slate-500 mb-2">Change in Tax Law</p>
            <p className="text-slate-700">Pass-through of increased tax burden to buyer if tax credits eliminated or reduced</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}