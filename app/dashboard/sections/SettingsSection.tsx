'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/app/components/ui/card"
import { Button } from "@/app/components/ui/button"
import { Input } from "@/app/components/ui/input"
import { Label } from "@/app/components/ui/label"
import { Switch } from "@/app/components/ui/switch"
import { Bell, Shield, Database, Mail } from "lucide-react"

export function SettingsSection() {
  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Settings
        </h1>
        <p className="text-slate-500 text-sm">
          Configure your dashboard preferences and integrations
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Notifications */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-50">
                <Bell className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <CardTitle>Notifications</CardTitle>
                <CardDescription>Manage alert preferences</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div>
                <Label className="text-slate-900">Email Notifications</Label>
                <p className="text-xs text-slate-500">Receive alerts via email</p>
              </div>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div>
                <Label className="text-slate-900">Payment Reminders</Label>
                <p className="text-xs text-slate-500">7 days before due date</p>
              </div>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div>
                <Label className="text-slate-900">Compliance Alerts</Label>
                <p className="text-xs text-slate-500">Urgent compliance issues</p>
              </div>
              <Switch defaultChecked />
            </div>
          </CardContent>
        </Card>

        {/* Security */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-green-50">
                <Shield className="w-5 h-5 text-green-600" />
              </div>
              <div>
                <CardTitle>Security</CardTitle>
                <CardDescription>Account security settings</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div>
                <Label className="text-slate-900">Two-Factor Authentication</Label>
                <p className="text-xs text-slate-500">Extra layer of security</p>
              </div>
              <Switch />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div>
                <Label className="text-slate-900">Session Timeout</Label>
                <p className="text-xs text-slate-500">Auto logout after inactivity</p>
              </div>
              <Switch defaultChecked />
            </div>
            <Button variant="outline" className="w-full">
              Change Password
            </Button>
          </CardContent>
        </Card>

        {/* Integrations */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-50">
                <Database className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <CardTitle>Integrations</CardTitle>
                <CardDescription>Connected services</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div className="flex items-center justify-between mb-2">
                <Label className="text-slate-900">Snowflake Data Warehouse</Label>
                <span className="text-xs text-green-600">Connected</span>
              </div>
              <Input placeholder="Connection string..." defaultValue="snowflake://..." />
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div className="flex items-center justify-between mb-2">
                <Label className="text-slate-900">SAP Integration</Label>
                <span className="text-xs text-green-600">Connected</span>
              </div>
              <Input placeholder="API Endpoint..." defaultValue="https://sap.example.com/api" />
            </div>
            <Button variant="outline" className="w-full">
              Add Integration
            </Button>
          </CardContent>
        </Card>

        {/* Email Settings */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-purple-50">
                <Mail className="w-5 h-5 text-purple-600" />
              </div>
              <div>
                <CardTitle>Email Settings</CardTitle>
                <CardDescription>Configure email preferences</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <Label className="mb-2 block text-slate-900">Primary Email</Label>
              <Input placeholder="email@example.com" defaultValue="namho@frontiermind.ai" />
            </div>
            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <Label className="mb-2 block text-slate-900">CC Recipients</Label>
              <Input placeholder="Add CC recipients..." />
            </div>
            <Button className="w-full bg-gradient-to-r from-blue-600 to-indigo-700 text-white hover:from-blue-700 hover:to-indigo-800">
              Save Changes
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
