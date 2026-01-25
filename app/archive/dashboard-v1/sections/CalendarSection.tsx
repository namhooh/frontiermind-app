'use client'

import { Card, CardContent, CardHeader, CardTitle } from "@/app/components/ui/card"
import { Badge } from "@/app/components/ui/badge"
import { Calendar, Clock, AlertTriangle, CheckCircle } from "lucide-react"

export function CalendarSection() {
  const upcomingEvents = [
    {
      title: "PPA Invoice Due - Sunfield Solar",
      date: "Nov 15, 2025",
      time: "5:00 PM",
      type: "payment",
      status: "upcoming"
    },
    {
      title: "Bank Guarantee Renewal",
      date: "Nov 18, 2025",
      time: "12:00 PM",
      type: "compliance",
      status: "urgent"
    },
    {
      title: "Quarterly Review - Windridge Farm",
      date: "Nov 22, 2025",
      time: "10:00 AM",
      type: "meeting",
      status: "scheduled"
    },
    {
      title: "Contract Amendment Deadline",
      date: "Nov 30, 2025",
      time: "11:59 PM",
      type: "deadline",
      status: "upcoming"
    },
  ]

  const completedTasks = [
    { title: "PPA Settlement - Metro Grid Storage", date: "Nov 10, 2025" },
    { title: "O&M Invoice Verification", date: "Nov 8, 2025" },
    { title: "Annual Escalation Applied", date: "Nov 5, 2025" },
  ]

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-slate-900 text-2xl font-bold mb-2" style={{ fontFamily: "'Libre Baskerville', serif" }}>
          Calendar Sync
        </h1>
        <p className="text-slate-500 text-sm">
          Upcoming deadlines and scheduled events
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Calendar Widget */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Upcoming Events</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {upcomingEvents.map((event, index) => (
                <div
                  key={index}
                  className="flex items-start gap-4 p-4 rounded-lg border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50 transition-all"
                >
                  <div className={`p-3 rounded-lg ${
                    event.status === "urgent"
                      ? "bg-red-50"
                      : event.type === "payment"
                      ? "bg-green-50"
                      : event.type === "compliance"
                      ? "bg-amber-50"
                      : "bg-blue-50"
                  }`}>
                    {event.status === "urgent" ? (
                      <AlertTriangle className="w-5 h-5 text-red-600" />
                    ) : (
                      <Calendar className={`w-5 h-5 ${
                        event.type === "payment"
                          ? "text-green-600"
                          : event.type === "compliance"
                          ? "text-amber-600"
                          : "text-blue-600"
                      }`} />
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-900 font-medium mb-1">{event.title}</div>
                    <div className="flex items-center gap-4 text-sm text-slate-500">
                      <span>{event.date}</span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {event.time}
                      </span>
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      event.status === "urgent"
                        ? "bg-red-50 text-red-700 border-red-200"
                        : event.status === "upcoming"
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-blue-50 text-blue-700 border-blue-200"
                    }
                  >
                    {event.status}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Completed Tasks */}
        <Card>
          <CardHeader>
            <CardTitle>Recently Completed</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {completedTasks.map((task, index) => (
                <div
                  key={index}
                  className="flex items-start gap-3 p-3 rounded-lg border border-slate-200 bg-white"
                >
                  <CheckCircle className="w-5 h-5 text-green-600 mt-0.5" />
                  <div className="flex-1">
                    <div className="text-sm text-slate-700">{task.title}</div>
                    <div className="text-xs text-slate-500">{task.date}</div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
