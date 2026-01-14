import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Calendar, Clock, AlertTriangle } from "lucide-react";
import { Badge } from "../ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { Label } from "../ui/label";
import { ImageWithFallback } from "../figma/ImageWithFallback";

export function CalendarSection() {
  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-slate-900 mb-2 font-[Libre_Baskerville] text-2xl font-bold">Calendar Synchronization</h1>
        
        {/* Project Selection */}
        <div className="flex gap-4 items-center mt-4">
          <Label className="text-slate-700">Select Project:</Label>
          <Select>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Choose project" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sunfield">Sunfield Solar Park</SelectItem>
              <SelectItem value="windridge">Windridge Energy Farm</SelectItem>
              <SelectItem value="coastal">Coastal Renewable Hub</SelectItem>
              <SelectItem value="metro">Metro Grid Storage</SelectItem>
              <SelectItem value="desert">Desert Sun Array</SelectItem>
            </SelectContent>
          </Select>
        </div>
        
        {/* Staff Sync */}
        <div className="flex gap-4 items-center mt-4">
          <Label className="text-slate-700">Staff Name:</Label>
          <Input placeholder="Enter staff name" className="w-[200px]" />
          <Button size="sm" variant="outline" className="text-xs">
            Google Calendar Sync
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>November 2025</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {/* Calendar Header - Days of Week */}
            <div className="grid grid-cols-7 gap-2">
              {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
                <div key={day} className="text-center text-sm text-slate-500 p-2">
                  {day}
                </div>
              ))}
            </div>
            
            {/* Calendar Grid */}
            <div className="grid grid-cols-7 gap-2">
              {/* Empty cells for days before month starts (Nov 1 is Saturday) */}
              {[...Array(6)].map((_, i) => (
                <div key={`empty-${i}`} className="aspect-square p-2 rounded-lg bg-slate-50"></div>
              ))}
              
              {/* Day 1 - Saturday */}
              <div className="aspect-square p-2 rounded-lg border border-slate-200 bg-white">
                <div className="text-sm text-slate-900 mb-1">1</div>
              </div>
              
              {/* Days 2-11 */}
              {[2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((day) => (
                <div key={day} className="aspect-square p-2 rounded-lg border border-slate-200 bg-white">
                  <div className="text-sm text-slate-900 mb-1">{day}</div>
                  {day === 2 && (
                    <div className="space-y-1">
                      <div className="text-xs p-1 rounded bg-blue-50 text-blue-700 truncate" title="Meter Maintenance - Solar A">
                        9:00 AM
                      </div>
                      <div className="text-xs p-1 rounded bg-[rgb(240,114,35)] text-white flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        <span>D-7 alert scheduled</span>
                      </div>
                      <div className="text-xs text-slate-600"><b> Sunfield Solar Park</b> Letter of Credit expiration</div>
                    </div>
                  )}
                  {day === 5 && (
                    <div className="space-y-1">
                      <div className="text-xs p-1 rounded bg-[rgb(219,245,226)] text-[rgb(69,196,139)] truncate" title="Market Price Analysis Report">
                        2:00 PM
                      </div>
                      <div className="text-xs text-slate-600"><b>Invoice issuance</b></div>
                    </div>
                  )}
                </div>
              ))}
              
              {/* Day 12 - Today (Wednesday) */}
              <div className="aspect-square p-2 rounded-lg border-2 border-blue-500 bg-blue-50">
                <div className="text-sm text-blue-700 mb-1">12</div>
                <div className="space-y-1">
                  <div className="text-xs p-1 rounded bg-red-100 text-red-700 truncate" title="Peak Demand Period">
                    2:00 PM
                  </div>
                  <div className="text-xs p-1 rounded bg-red-600 text-white flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" />
                    <span>Service down</span>
                  </div>
                  <div className="text-xs text-slate-700 font-bold">O&M Response Time deadline</div>
                </div>
              </div>
              
              {/* Day 13 - Tomorrow */}
              <div className="aspect-square p-2 rounded-lg border border-slate-200 bg-white">
                <div className="text-sm text-slate-900 mb-1">13</div>
                <div className="space-y-1">
                  <div className="text-xs p-1 rounded bg-orange-50 text-orange-700 truncate" title="Contract Renewal Review">
                    10:00 AM
                  </div>
                  <div className="text-xs text-slate-600"><b>Desert Sun Array</b> Insurance review </div>
                </div>
              </div>
              
              {/* Days 14-30 */}
              {[14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30].map((day) => (
                <div key={day} className="aspect-square p-2 rounded-lg border border-slate-200 bg-white">
                  <div className="text-sm text-slate-900 mb-1">{day}</div>
                </div>
              ))}
            </div>
            
            {/* Legend */}
            <div className="flex items-center gap-4 pt-4 border-t border-slate-200">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded bg-red-100"></div>
                <span className="text-sm text-slate-600">Critical</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded bg-orange-50"></div>
                <span className="text-sm text-slate-600">Important</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded bg-blue-50"></div>
                <span className="text-sm text-slate-600">Scheduled</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded border-2 border-blue-500"></div>
                <span className="text-sm text-slate-600">Today</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}