import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Settings, Bell, Lock, Users } from "lucide-react";
import { Button } from "../ui/button";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";

export function SettingsSection() {
  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-slate-900 mb-2 font-[Libre_Baskerville] text-2xl font-bold">Settings</h1>
        <p className="text-slate-600">Manage your account and system preferences</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bell className="w-5 h-5" />
              <CardTitle>Notifications</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="email-alerts" className="cursor-pointer">
                Email Alerts
              </Label>
              <Switch id="email-alerts" defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="price-alerts" className="cursor-pointer">
                Price Change Alerts
              </Label>
              <Switch id="price-alerts" defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="maintenance-alerts" className="cursor-pointer">
                Maintenance Alerts
              </Label>
              <Switch id="maintenance-alerts" defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="weekly-reports" className="cursor-pointer">
                Weekly Reports
              </Label>
              <Switch id="weekly-reports" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Lock className="w-5 h-5" />
              <CardTitle>Security</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="two-factor" className="cursor-pointer">
                Two-Factor Authentication
              </Label>
              <Switch id="two-factor" defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="session-timeout" className="cursor-pointer">
                Auto Session Timeout
              </Label>
              <Switch id="session-timeout" defaultChecked />
            </div>
            <div className="pt-4">
              <Button variant="outline" className="w-full">
                Change Password
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Settings className="w-5 h-5" />
              <CardTitle>System Preferences</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-sync" className="cursor-pointer">
                Automatic Synchronization
              </Label>
              <Switch id="auto-sync" defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="dark-mode" className="cursor-pointer">
                Dark Mode
              </Label>
              <Switch id="dark-mode" />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="advanced-analytics" className="cursor-pointer">
                Advanced Analytics
              </Label>
              <Switch id="advanced-analytics" defaultChecked />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Users className="w-5 h-5" />
              <CardTitle>Team Management</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm text-slate-600">
              <div className="flex items-center justify-between mb-2">
                <span>Team Members</span>
                <span className="text-slate-900">5</span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span>Active Users</span>
                <span className="text-slate-900">3</span>
              </div>
            </div>
            <Button variant="outline" className="w-full">
              Manage Team
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}