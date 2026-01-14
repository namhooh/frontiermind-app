import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { TrendingUp, ArrowLeft } from "lucide-react";
import { Button } from "../ui/button";

interface PricingSectionProps {
  onSectionChange: (section: string) => void;
}

export function PricingSection({ onSectionChange }: PricingSectionProps) {
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
      
      <div>
        <h1 className="text-slate-900 mb-2">Market Electricity Pricing</h1>
        <p className="text-slate-600">Real-time market price analysis and forecasting</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Nigeria - Current Market Prices</CardTitle>
            <p className="text-sm text-slate-500">Last updated: Nov 12, 2025 14:30 UTC</p>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { market: "Day-Ahead", price: "$45.20/MWh", change: "+2.3%" },
              { market: "Real-Time", price: "$48.75/MWh", change: "+5.1%" },
              { market: "Capacity", price: "$12.40/MW", change: "-1.2%" },
              { market: "Ancillary", price: "$8.90/MW", change: "+0.8%" },
            ].map((item, index) => (
              <div key={index} className="p-4 rounded-lg border border-slate-200">
                <div className="text-sm text-slate-500 mb-2">{item.market}</div>
                <div className="text-slate-900 mb-1">{item.price}</div>
                <div
                  className={`text-sm ${
                    item.change.startsWith("+") ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {item.change}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Kenya - Current Market Prices</CardTitle>
            <p className="text-sm text-slate-500">Last updated: Nov 12, 2025 14:28 UTC</p>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { market: "Day-Ahead", price: "$52.80/MWh", change: "+3.7%" },
              { market: "Real-Time", price: "$55.30/MWh", change: "+4.2%" },
              { market: "Capacity", price: "$14.20/MW", change: "+1.5%" },
              { market: "Ancillary", price: "$9.60/MW", change: "-0.5%" },
            ].map((item, index) => (
              <div key={index} className="p-4 rounded-lg border border-slate-200">
                <div className="text-sm text-slate-500 mb-2">{item.market}</div>
                <div className="text-slate-900 mb-1">{item.price}</div>
                <div
                  className={`text-sm ${
                    item.change.startsWith("+") ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {item.change}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}