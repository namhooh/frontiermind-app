import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Zap, TrendingUp, TrendingDown, ArrowLeft } from "lucide-react";
import { Button } from "../ui/button";

interface GenerationSectionProps {
  onSectionChange: (section: string) => void;
}

export function GenerationSection({ onSectionChange }: GenerationSectionProps) {
  const meters = [
    { id: "MTR-001", location: "Solar Farm A", current: "2.4 MW", status: "active", trend: "up" },
    { id: "MTR-002", location: "Wind Farm B", current: "5.1 MW", status: "active", trend: "up" },
    { id: "MTR-003", location: "Solar Farm C", current: "1.8 MW", status: "active", trend: "down" },
    { id: "MTR-004", location: "Hydro Plant D", current: "3.2 MW", status: "maintenance", trend: "neutral" },
  ];

  return (
    <div className="p-8 space-y-6">
      <Button
        variant="ghost"
        onClick={() => onSectionChange("integration-status")}
        className="mb-2"
      >
        <ArrowLeft className="w-4 h-4 mr-2" />
        Back to Integration Status
      </Button>
      
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-slate-900 mb-2">Generation Meter Data</h1>
          <p className="text-slate-600">Real-time monitoring of energy generation sources</p>
        </div>
        <Button>
          <Zap className="w-4 h-4 mr-2" />
          Add Meter
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-600">Total Generation</span>
              <Zap className="w-5 h-5 text-blue-600" />
            </div>
            <div className="text-slate-900">12.5 MW</div>
            <p className="text-sm text-green-600 mt-1">↑ 8% from yesterday</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-600">Active Meters</span>
              <div className="w-2 h-2 bg-green-500 rounded-full" />
            </div>
            <div className="text-slate-900">3/4</div>
            <p className="text-sm text-slate-500 mt-1">1 under maintenance</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-600">Efficiency Rate</span>
              <TrendingUp className="w-5 h-5 text-green-600" />
            </div>
            <div className="text-slate-900">94.2%</div>
            <p className="text-sm text-slate-500 mt-1">Above target</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connected Meters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {meters.map((meter) => (
              <div
                key={meter.id}
                className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 bg-white"
              >
                <div className="p-3 rounded-lg bg-blue-50">
                  <Zap className="w-5 h-5 text-blue-600" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-slate-900">{meter.location}</span>
                    <Badge variant="outline" className="text-xs">
                      {meter.id}
                    </Badge>
                  </div>
                  <div className="text-sm text-slate-500">Current output: {meter.current}</div>
                </div>
                <div className="flex items-center gap-3">
                  {meter.trend === "up" && <TrendingUp className="w-4 h-4 text-green-600" />}
                  {meter.trend === "down" && <TrendingDown className="w-4 h-4 text-red-600" />}
                  <Badge
                    variant="outline"
                    className={
                      meter.status === "active"
                        ? "text-green-600 border-green-200 bg-green-50"
                        : "text-orange-600 border-orange-200 bg-orange-50"
                    }
                  >
                    {meter.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}