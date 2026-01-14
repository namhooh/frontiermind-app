'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Zap, TrendingUp, TrendingDown, Sun, Wind } from "lucide-react"

interface GenerationSectionProps {
  onSectionChange: (section: string) => void
}

export function GenerationSection({ onSectionChange }: GenerationSectionProps) {
  const generationData = [
    {
      project: "Sunfield Solar Park",
      type: "Solar",
      icon: Sun,
      current: "45.2 MW",
      capacity: "50 MW",
      utilization: 90,
      trend: "up",
      change: "+5%"
    },
    {
      project: "Windridge Energy Farm",
      type: "Wind",
      icon: Wind,
      current: "72.8 MW",
      capacity: "100 MW",
      utilization: 73,
      trend: "down",
      change: "-3%"
    },
    {
      project: "Coastal Renewable Hub",
      type: "Solar",
      icon: Sun,
      current: "28.5 MW",
      capacity: "35 MW",
      utilization: 81,
      trend: "up",
      change: "+2%"
    },
    {
      project: "Desert Sun Array",
      type: "Solar",
      icon: Sun,
      current: "62.1 MW",
      capacity: "75 MW",
      utilization: 83,
      trend: "up",
      change: "+8%"
    },
  ]

  const totalGeneration = generationData.reduce((acc, item) => {
    return acc + parseFloat(item.current.replace(' MW', ''))
  }, 0)

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Generation Meter Data
        </h1>
        <p className="text-slate-500 text-sm">
          Real-time power generation monitoring
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="hover:border-blue-300 transition-all">
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-lg bg-green-50">
                <Zap className="w-6 h-6 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-slate-500">Total Generation</p>
                <p className="text-2xl font-bold text-slate-900">{totalGeneration.toFixed(1)} MW</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="hover:border-blue-300 transition-all">
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-lg bg-amber-50">
                <Sun className="w-6 h-6 text-amber-600" />
              </div>
              <div>
                <p className="text-sm text-slate-500">Solar Output</p>
                <p className="text-2xl font-bold text-slate-900">135.8 MW</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="hover:border-blue-300 transition-all">
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-lg bg-purple-50">
                <Wind className="w-6 h-6 text-purple-600" />
              </div>
              <div>
                <p className="text-sm text-slate-500">Wind Output</p>
                <p className="text-2xl font-bold text-slate-900">72.8 MW</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Project Details */}
      <Card>
        <CardHeader>
          <CardTitle>Project Generation Details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {generationData.map((item, index) => {
              const Icon = item.icon
              return (
                <div
                  key={index}
                  className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50 transition-all"
                >
                  <div className={`p-3 rounded-lg ${
                    item.type === "Solar"
                      ? "bg-amber-50"
                      : "bg-blue-50"
                  }`}>
                    <Icon className={`w-5 h-5 ${
                      item.type === "Solar" ? "text-amber-600" : "text-blue-600"
                    }`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-900 font-medium">{item.project}</div>
                    <div className="text-sm text-slate-500">
                      {item.type} • Capacity: {item.capacity}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-slate-900">{item.current}</div>
                    <div className="flex items-center justify-end gap-1 text-sm">
                      {item.trend === "up" ? (
                        <TrendingUp className="w-4 h-4 text-green-600" />
                      ) : (
                        <TrendingDown className="w-4 h-4 text-red-600" />
                      )}
                      <span className={item.trend === "up" ? "text-green-600" : "text-red-600"}>
                        {item.change}
                      </span>
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      item.utilization >= 80
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                    }
                  >
                    {item.utilization}% util
                  </Badge>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
