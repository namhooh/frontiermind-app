/**
 * Dummy Meter Data Generator
 *
 * Generates realistic sample meter data for testing the workflow.
 * Creates 30 days of hourly readings for a solar/wind project.
 */

import type { MeterDataSummary } from './types'

// ============================================================================
// Types
// ============================================================================

export interface MeterReading {
  timestamp: string
  energy_mwh: number
  power_mw: number
  availability: number
  status: 'normal' | 'curtailed' | 'offline'
}

export interface DummyMeterDataOptions {
  projectType?: 'solar' | 'wind'
  capacityMW?: number
  daysCount?: number
  startDate?: Date
  targetAvailability?: number
  includeOutages?: boolean
}

// ============================================================================
// Generator Functions
// ============================================================================

/**
 * Generate a solar generation profile for an hour.
 * Returns capacity factor (0-1) based on hour of day.
 */
function getSolarCapacityFactor(hour: number): number {
  // Solar generation curve: peaks at noon
  if (hour < 6 || hour > 20) return 0

  // Bell curve approximation centered at 13:00
  const peakHour = 13
  const spread = 4
  const factor = Math.exp(-Math.pow(hour - peakHour, 2) / (2 * Math.pow(spread, 2)))

  // Add some randomness (weather variation)
  const weatherFactor = 0.7 + Math.random() * 0.3

  return Math.min(1, factor * weatherFactor)
}

/**
 * Generate a wind generation profile for an hour.
 * Returns capacity factor (0-1) with more variation than solar.
 */
function getWindCapacityFactor(): number {
  // Wind is more variable, tends to be higher at night
  const baseFactor = 0.25 + Math.random() * 0.5

  // Occasional high wind periods
  if (Math.random() > 0.85) {
    return Math.min(1, baseFactor + 0.3)
  }

  // Occasional low wind periods
  if (Math.random() > 0.9) {
    return Math.max(0, baseFactor - 0.2)
  }

  return baseFactor
}

/**
 * Generate hourly meter readings for a specified period.
 */
export function generateMeterReadings(options: DummyMeterDataOptions = {}): MeterReading[] {
  const {
    projectType = 'solar',
    capacityMW = 50,
    daysCount = 30,
    startDate = new Date(Date.now() - daysCount * 24 * 60 * 60 * 1000),
    targetAvailability = 0.95,
    includeOutages = true,
  } = options

  const readings: MeterReading[] = []
  const totalHours = daysCount * 24

  // Determine outage periods (if enabled)
  const outageHours = new Set<number>()
  if (includeOutages) {
    // Add 1-2 outage periods
    const outageCount = Math.floor(Math.random() * 2) + 1
    for (let i = 0; i < outageCount; i++) {
      const outageStart = Math.floor(Math.random() * totalHours)
      const outageDuration = Math.floor(Math.random() * 12) + 4 // 4-16 hours
      for (let h = outageStart; h < Math.min(outageStart + outageDuration, totalHours); h++) {
        outageHours.add(h)
      }
    }
  }

  // Generate readings
  for (let hourIndex = 0; hourIndex < totalHours; hourIndex++) {
    const timestamp = new Date(startDate.getTime() + hourIndex * 60 * 60 * 1000)
    const hour = timestamp.getHours()

    // Check for outage
    const isOutage = outageHours.has(hourIndex)

    if (isOutage) {
      readings.push({
        timestamp: timestamp.toISOString(),
        energy_mwh: 0,
        power_mw: 0,
        availability: 0,
        status: 'offline',
      })
      continue
    }

    // Get capacity factor based on project type
    const capacityFactor =
      projectType === 'solar' ? getSolarCapacityFactor(hour) : getWindCapacityFactor()

    // Calculate power and energy
    const power_mw = capacityMW * capacityFactor
    const energy_mwh = power_mw // MWh for 1 hour = MW

    // Check for curtailment (grid constraints)
    const isCurtailed = capacityFactor > 0.7 && Math.random() > 0.95
    const curtailmentFactor = isCurtailed ? 0.7 : 1

    readings.push({
      timestamp: timestamp.toISOString(),
      energy_mwh: energy_mwh * curtailmentFactor,
      power_mw: power_mw * curtailmentFactor,
      availability: capacityFactor > 0 ? targetAvailability : 1,
      status: isCurtailed ? 'curtailed' : 'normal',
    })
  }

  return readings
}

/**
 * Convert meter readings to CSV format.
 */
export function meterReadingsToCSV(readings: MeterReading[]): string {
  const header = 'timestamp,energy_mwh,power_mw,availability,status'
  const rows = readings.map(
    (r) =>
      `${r.timestamp},${r.energy_mwh.toFixed(3)},${r.power_mw.toFixed(3)},${r.availability.toFixed(3)},${r.status}`
  )
  return [header, ...rows].join('\n')
}

/**
 * Calculate summary statistics from meter readings.
 */
export function calculateMeterSummary(
  readings: MeterReading[],
  fileName: string
): MeterDataSummary {
  if (readings.length === 0) {
    return {
      fileName,
      totalRecords: 0,
      dateRange: { start: '', end: '' },
      totalEnergyMWh: 0,
      averageDailyMWh: 0,
      peakDayMWh: 0,
      availabilityPercentage: 0,
    }
  }

  const totalEnergyMWh = readings.reduce((sum, r) => sum + r.energy_mwh, 0)
  const availableHours = readings.filter((r) => r.status !== 'offline').length
  const totalAvailability = readings.reduce((sum, r) => sum + r.availability, 0)
  const avgAvailability = availableHours > 0 ? totalAvailability / readings.length : 0

  // Group by date and calculate daily totals
  const dailyTotals: Record<string, number> = {}
  readings.forEach((r) => {
    const date = r.timestamp.split('T')[0]
    dailyTotals[date] = (dailyTotals[date] || 0) + r.energy_mwh
  })

  const dailyValues = Object.values(dailyTotals)
  const daysCount = dailyValues.length || 1
  const averageDailyMWh = totalEnergyMWh / daysCount
  const peakDayMWh = Math.max(...dailyValues, 0)

  // Get date range
  const dates = readings.map((r) => new Date(r.timestamp))
  const startDate = new Date(Math.min(...dates.map((d) => d.getTime())))
  const endDate = new Date(Math.max(...dates.map((d) => d.getTime())))

  return {
    fileName,
    totalRecords: readings.length,
    dateRange: {
      start: startDate.toISOString().split('T')[0],
      end: endDate.toISOString().split('T')[0],
    },
    totalEnergyMWh: Math.round(totalEnergyMWh * 100) / 100,
    averageDailyMWh: Math.round(averageDailyMWh * 100) / 100,
    peakDayMWh: Math.round(peakDayMWh * 100) / 100,
    availabilityPercentage: Math.round(avgAvailability * 10000) / 100,
  }
}

/**
 * Generate dummy meter data and return as a Blob for upload.
 */
export function generateDummyMeterDataBlob(
  options: DummyMeterDataOptions = {}
): { blob: Blob; summary: MeterDataSummary; readings: MeterReading[] } {
  const readings = generateMeterReadings(options)
  const csv = meterReadingsToCSV(readings)
  const blob = new Blob([csv], { type: 'text/csv' })
  const fileName = `meter_data_${new Date().toISOString().split('T')[0]}.csv`
  const summary = calculateMeterSummary(readings, fileName)

  return { blob, summary, readings }
}
