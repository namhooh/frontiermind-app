import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Shield, ArrowLeft } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";

interface RegulationsSectionProps {
  onSectionChange: (section: string) => void;
}

export function RegulationsSection({ onSectionChange }: RegulationsSectionProps) {
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
        <h1 className="text-slate-900 mb-2">Grid Regulations & Charges</h1>
        <p className="text-slate-600">Compliance monitoring and regulatory charge tracking</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Active Regulations</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { name: "ISO Grid Connection Fee", amount: "$1,250/month", status: "compliant" },
              { name: "Transmission Usage Charge", amount: "$0.015/kWh", status: "compliant" },
              { name: "Peak Demand Charge", amount: "$8.50/kW", status: "warning" },
              { name: "Renewable Energy Credit", amount: "$2.30/MWh", status: "compliant" },
            ].map((reg, index) => (
              <div
                key={index}
                className="flex items-center gap-4 p-4 rounded-lg border border-slate-200"
              >
                <div className="p-3 rounded-lg bg-purple-50">
                  <Shield className="w-5 h-5 text-purple-600" />
                </div>
                <div className="flex-1">
                  <div className="text-slate-900 mb-1">{reg.name}</div>
                  <div className="text-sm text-slate-500">{reg.amount}</div>
                </div>
                <Badge
                  variant="outline"
                  className={
                    reg.status === "compliant"
                      ? "text-green-600 border-green-200 bg-green-50"
                      : "text-orange-600 border-orange-200 bg-orange-50"
                  }
                >
                  {reg.status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}