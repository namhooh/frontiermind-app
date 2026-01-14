'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { TrendingUp, TrendingDown, DollarSign, Clock } from "lucide-react"

interface PricingSectionProps {
  onSectionChange: (section: string) => void
}

export function PricingSection({ onSectionChange }: PricingSectionProps) {
  const marketPrices = [
    { region: "ERCOT (Texas)", price: "$42.50", change: "+$2.30", trend: "up", time: "2 mins ago" },
    { region: "PJM (Mid-Atlantic)", price: "$38.75", change: "-$1.15", trend: "down", time: "3 mins ago" },
    { region: "CAISO (California)", price: "$55.20", change: "+$4.80", trend: "up", time: "1 min ago" },
    { region: "MISO (Midwest)", price: "$35.90", change: "+$0.45", trend: "up", time: "5 mins ago" },
  ]

  const ppaRates = [
    { contract: "Sunfield Solar Park", rate: "$45.00/MWh", term: "Fixed", escalation: "2.5%/yr" },
    { contract: "Windridge Energy Farm", rate: "$52.00/MWh", term: "Fixed", escalation: "2.0%/yr" },
    { contract: "Coastal Renewable Hub", rate: "$48.50/MWh", term: "Index-linked", escalation: "CPI" },
    { contract: "Metro Grid Storage", rate: "$65.00/MWh", term: "Fixed", escalation: "3.0%/yr" },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Market Electricity Price
        </h1>
        <p className="text-slate-500 text-sm">
          Real-time market prices and PPA rate comparison
        </p>
      </div>

      {/* Market Prices */}
      <Card>
        <CardHeader>
          <CardTitle>Live Market Prices ($/MWh)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {marketPrices.map((item, index) => (
              <div
                key={index}
                className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50 transition-all"
              >
                <div className={`p-3 rounded-lg ${
                  item.trend === "up"
                    ? "bg-green-50"
                    : "bg-red-50"
                }`}>
                  {item.trend === "up" ? (
                    <TrendingUp className="w-5 h-5 text-green-600" />
                  ) : (
                    <TrendingDown className="w-5 h-5 text-red-600" />
                  )}
                </div>
                <div className="flex-1">
                  <div className="text-slate-900 font-medium">{item.region}</div>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <Clock className="w-3 h-3" />
                    {item.time}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xl font-bold text-slate-900">{item.price}</div>
                  <div className={`text-sm ${
                    item.trend === "up" ? "text-green-600" : "text-red-600"
                  }`}>
                    {item.change}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* PPA Contract Rates */}
      <Card>
        <CardHeader>
          <CardTitle>PPA Contract Rates</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {ppaRates.map((item, index) => (
              <div
                key={index}
                className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white"
              >
                <div className="p-3 rounded-lg bg-amber-50">
                  <DollarSign className="w-5 h-5 text-amber-600" />
                </div>
                <div className="flex-1">
                  <div className="text-slate-900 font-medium">{item.contract}</div>
                  <div className="text-sm text-slate-500">
                    {item.term} • Escalation: {item.escalation}
                  </div>
                </div>
                <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                  {item.rate}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
