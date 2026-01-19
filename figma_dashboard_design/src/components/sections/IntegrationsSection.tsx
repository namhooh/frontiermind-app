import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Database, RefreshCw, CheckCircle2 } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";

export function IntegrationsSection() {
  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-slate-900 mb-2">ERP Integrations</h1>
          <p className="text-slate-600">Connected enterprise resource planning systems</p>
        </div>
        <Button variant="outline">
          <RefreshCw className="w-4 h-4 mr-2" />
          Sync All
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>SAP Integration</CardTitle>
              <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50">
                Connected
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3 p-4 rounded-lg bg-amber-50">
              <Database className="w-8 h-8 text-amber-600" />
              <div className="flex-1">
                <div className="text-slate-900 mb-1">SAP S/4HANA</div>
                <div className="text-sm text-slate-500">Financial & Operations Module</div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Last Sync</span>
                <span className="text-slate-900">1 minute ago</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Records Synced</span>
                <span className="text-slate-900">1,247</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Status</span>
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 className="w-4 h-4" />
                  Operational
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>SAGE Integration</CardTitle>
              <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50">
                Connected
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3 p-4 rounded-lg bg-amber-50">
              <Database className="w-8 h-8 text-amber-600" />
              <div className="flex-1">
                <div className="text-slate-900 mb-1">SAGE Intacct</div>
                <div className="text-sm text-slate-500">Accounting Module</div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Last Sync</span>
                <span className="text-slate-900">3 minutes ago</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Records Synced</span>
                <span className="text-slate-900">892</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600">Status</span>
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 className="w-4 h-4" />
                  Operational
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Data Flow Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-lg border border-slate-200">
              <div className="text-sm text-slate-500 mb-2">Daily Transactions</div>
              <div className="text-slate-900">3,421</div>
              <div className="text-sm text-green-600 mt-1">↑ 12% this week</div>
            </div>
            <div className="p-4 rounded-lg border border-slate-200">
              <div className="text-sm text-slate-500 mb-2">Sync Frequency</div>
              <div className="text-slate-900">Every 5 min</div>
              <div className="text-sm text-slate-500 mt-1">Real-time enabled</div>
            </div>
            <div className="p-4 rounded-lg border border-slate-200">
              <div className="text-sm text-slate-500 mb-2">Data Accuracy</div>
              <div className="text-slate-900">99.8%</div>
              <div className="text-sm text-green-600 mt-1">Excellent</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
