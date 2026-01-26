'use client'

/**
 * MeterDataStep
 *
 * Step 3: Upload or generate meter data for invoice calculation.
 * Two tabs: "Upload Data" and "Generate Test Data"
 */

import { useState, useCallback, useRef, useMemo } from 'react'
import {
  Upload,
  Zap,
  FileSpreadsheet,
  Loader2,
  AlertCircle,
  Check,
  Calendar,
  BarChart3,
  Activity,
  ArrowLeft,
  ArrowRight,
} from 'lucide-react'
import { useWorkflow, generateDummyMeterDataBlob, calculateMeterSummary } from '@/lib/workflow'
import type { MeterReading } from '@/lib/workflow'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/tabs'
import { Badge } from '@/app/components/ui/badge'
import { cn } from '@/app/components/ui/cn'

function formatNumber(num: number): string {
  return num.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function MeterDataSummaryDisplay() {
  const { state } = useWorkflow()
  const { meterDataSummary } = state

  if (!meterDataSummary) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-emerald-600">
        <Check className="w-5 h-5" />
        <span className="font-medium">Meter Data Loaded</span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2 text-slate-500 mb-1">
            <Calendar className="w-4 h-4" />
            <span className="text-sm">Date Range</span>
          </div>
          <p className="font-semibold text-slate-900 text-sm">
            {meterDataSummary.dateRange.start} to {meterDataSummary.dateRange.end}
          </p>
        </div>

        <div className="p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2 text-slate-500 mb-1">
            <BarChart3 className="w-4 h-4" />
            <span className="text-sm">Total Energy</span>
          </div>
          <p className="font-semibold text-slate-900">
            {formatNumber(meterDataSummary.totalEnergyMWh)} MWh
          </p>
        </div>

        <div className="p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2 text-slate-500 mb-1">
            <Zap className="w-4 h-4" />
            <span className="text-sm">Avg Daily</span>
          </div>
          <p className="font-semibold text-slate-900">
            {formatNumber(meterDataSummary.averageDailyMWh)} MWh
          </p>
        </div>

        <div className="p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2 text-slate-500 mb-1">
            <Activity className="w-4 h-4" />
            <span className="text-sm">Availability</span>
          </div>
          <p className="font-semibold text-slate-900">
            {meterDataSummary.availabilityPercentage}%
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <FileSpreadsheet className="w-8 h-8 text-blue-500" />
        <div>
          <p className="font-medium text-slate-900">{meterDataSummary.fileName}</p>
          <p className="text-sm text-slate-600">
            {formatNumber(meterDataSummary.totalRecords)} records
          </p>
        </div>
      </div>
    </div>
  )
}

function UploadTab() {
  const {
    state,
    setMeterDataStatus,
    setMeterDataSummary,
    setMeterDataError,
    setUseDummyData,
  } = useWorkflow()

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragActive, setIsDragActive] = useState(false)
  const [localFile, setLocalFile] = useState<File | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)

  const handleFileSelect = useCallback((file: File) => {
    // Validate file type
    const validExtensions = ['.csv', '.xlsx', '.xls']
    const fileName = file.name.toLowerCase()
    const isValid = validExtensions.some((ext) => fileName.endsWith(ext))

    if (!isValid) {
      setMeterDataError('Please upload a CSV or Excel file')
      return
    }

    setLocalFile(file)
    setMeterDataError(null)
  }, [setMeterDataError])

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(false)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragActive(false)

      const droppedFiles = e.dataTransfer.files
      if (droppedFiles && droppedFiles.length > 0) {
        handleFileSelect(droppedFiles[0])
      }
    },
    [handleFileSelect]
  )

  const processFile = async () => {
    if (!localFile) return

    setIsProcessing(true)
    setMeterDataStatus('uploading')

    try {
      // For demo purposes, we'll parse CSV locally
      // In production, this would upload to S3 via presigned URL
      const text = await localFile.text()
      const lines = text.split('\n').filter((line) => line.trim())

      if (lines.length < 2) {
        throw new Error('CSV file must have at least a header and one data row')
      }

      // Parse CSV
      const readings: MeterReading[] = []
      for (let i = 1; i < lines.length; i++) {
        const cols = lines[i].split(',')
        if (cols.length >= 4) {
          readings.push({
            timestamp: cols[0],
            energy_mwh: parseFloat(cols[1]) || 0,
            power_mw: parseFloat(cols[2]) || 0,
            availability: parseFloat(cols[3]) || 1,
            status: (cols[4]?.trim() as 'normal' | 'curtailed' | 'offline') || 'normal',
          })
        }
      }

      const summary = calculateMeterSummary(readings, localFile.name)
      setMeterDataSummary(summary)
      setMeterDataStatus('success')
      setUseDummyData(false)
    } catch (error) {
      setMeterDataError(
        error instanceof Error ? error.message : 'Failed to process file'
      )
      setMeterDataStatus('error')
    } finally {
      setIsProcessing(false)
    }
  }

  if (state.meterDataStatus === 'success' && !state.useDummyData) {
    return <MeterDataSummaryDisplay />
  }

  return (
    <div className="space-y-4">
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all',
          isDragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-slate-300 hover:border-blue-400'
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFileSelect(file)
          }}
          className="hidden"
        />

        <Upload className="w-10 h-10 mx-auto mb-3 text-slate-400" />
        <p className="font-medium text-slate-900 mb-1">
          {isDragActive ? 'Drop file here' : 'Upload Meter Data'}
        </p>
        <p className="text-sm text-slate-500">
          Drag and drop or click to browse (CSV, Excel)
        </p>
      </div>

      {localFile && (
        <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border">
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="w-8 h-8 text-blue-500" />
            <div>
              <p className="font-medium text-slate-900">{localFile.name}</p>
              <p className="text-sm text-slate-500">
                {(localFile.size / 1024).toFixed(1)} KB
              </p>
            </div>
          </div>
          <Button onClick={processFile} disabled={isProcessing}>
            {isProcessing ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Processing...
              </>
            ) : (
              'Process File'
            )}
          </Button>
        </div>
      )}

      {state.meterDataError && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
          <div>
            <p className="font-medium text-red-900">Error</p>
            <p className="text-sm text-red-700">{state.meterDataError}</p>
          </div>
        </div>
      )}
    </div>
  )
}

function GenerateTab() {
  const {
    state,
    setMeterDataStatus,
    setMeterDataSummary,
    setMeterDataError,
    setUseDummyData,
  } = useWorkflow()

  const [projectType, setProjectType] = useState<'solar' | 'wind'>('solar')
  const [capacityMW, setCapacityMW] = useState(50)
  const [daysCount, setDaysCount] = useState(30)
  const [isGenerating, setIsGenerating] = useState(false)

  const handleGenerate = async () => {
    setIsGenerating(true)
    setMeterDataStatus('uploading')
    setMeterDataError(null)

    try {
      // Simulate a brief delay for better UX
      await new Promise((resolve) => setTimeout(resolve, 500))

      const { summary } = generateDummyMeterDataBlob({
        projectType,
        capacityMW,
        daysCount,
        includeOutages: true,
      })

      setMeterDataSummary(summary)
      setMeterDataStatus('success')
      setUseDummyData(true)
    } catch (error) {
      setMeterDataError(
        error instanceof Error ? error.message : 'Failed to generate data'
      )
      setMeterDataStatus('error')
    } finally {
      setIsGenerating(false)
    }
  }

  if (state.meterDataStatus === 'success' && state.useDummyData) {
    return (
      <div className="space-y-4">
        <MeterDataSummaryDisplay />
        <Badge variant="info" className="text-sm">
          Test Data Generated
        </Badge>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <p className="text-slate-600">
        Generate realistic test data to simulate meter readings for your project.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Project Type
          </label>
          <div className="flex gap-2">
            <Button
              variant={projectType === 'solar' ? 'default' : 'outline'}
              onClick={() => setProjectType('solar')}
              className="flex-1"
            >
              Solar
            </Button>
            <Button
              variant={projectType === 'wind' ? 'default' : 'outline'}
              onClick={() => setProjectType('wind')}
              className="flex-1"
            >
              Wind
            </Button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Capacity (MW)
          </label>
          <input
            type="number"
            value={capacityMW}
            onChange={(e) => setCapacityMW(Number(e.target.value) || 50)}
            min={1}
            max={500}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Days of Data
          </label>
          <input
            type="number"
            value={daysCount}
            onChange={(e) => setDaysCount(Number(e.target.value) || 30)}
            min={7}
            max={90}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
        <p className="text-sm text-amber-800">
          <strong>Note:</strong> This will generate {daysCount * 24} hourly readings
          with realistic generation patterns, including occasional outages and
          curtailment events.
        </p>
      </div>

      <Button
        onClick={handleGenerate}
        disabled={isGenerating}
        className="w-full"
        size="lg"
      >
        {isGenerating ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Generating Data...
          </>
        ) : (
          <>
            <Zap className="w-4 h-4 mr-2" />
            Generate Test Data
          </>
        )}
      </Button>
    </div>
  )
}

export function MeterDataStep() {
  const { state, goToNextStep, goToPreviousStep, canProceedToStep, setMeterDataStatus, setMeterDataSummary, setMeterDataError, setUseDummyData } = useWorkflow()

  const canProceed = canProceedToStep(4)

  const handleReset = () => {
    setMeterDataStatus('pending')
    setMeterDataSummary(null)
    setMeterDataError(null)
    setUseDummyData(false)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Meter Data Ingestion</span>
          {state.meterDataStatus === 'success' && (
            <Button variant="outline" size="sm" onClick={handleReset}>
              Load Different Data
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <Tabs defaultValue="generate">
          <TabsList className="mb-4">
            <TabsTrigger value="upload">Upload Data</TabsTrigger>
            <TabsTrigger value="generate">Generate Test Data</TabsTrigger>
          </TabsList>

          <TabsContent value="upload">
            <UploadTab />
          </TabsContent>

          <TabsContent value="generate">
            <GenerateTab />
          </TabsContent>
        </Tabs>

        {/* Navigation */}
        <div className="flex justify-between pt-4 border-t">
          <Button variant="outline" onClick={goToPreviousStep}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Clauses
          </Button>
          <Button onClick={goToNextStep} disabled={!canProceed}>
            Continue to Invoice
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
