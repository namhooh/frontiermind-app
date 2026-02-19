'use client'

import { Download, FileText, Shield, RotateCcw } from 'lucide-react'
import { usePIIRedaction } from '@/lib/pii-redaction-temp'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function deduplicateEntities(entityDetails: Array<{ entityType: string; originalValue: string; confidence: number }>) {
  const deduped = new Map<string, Map<string, { occurrences: number; maxConfidence: number }>>()
  for (const entity of entityDetails) {
    if (!deduped.has(entity.entityType)) {
      deduped.set(entity.entityType, new Map())
    }
    const typeMap = deduped.get(entity.entityType)!
    const existing = typeMap.get(entity.originalValue)
    if (existing) {
      existing.occurrences++
      existing.maxConfidence = Math.max(existing.maxConfidence, entity.confidence)
    } else {
      typeMap.set(entity.originalValue, { occurrences: 1, maxConfidence: entity.confidence })
    }
  }
  return deduped
}

export function DownloadStep() {
  const { state, reset } = usePIIRedaction()
  const { result, fileName } = state

  if (!result) return null

  const now = new Date().toISOString()
  const baseFileName = fileName?.replace(/\.[^.]+$/, '') || 'document'

  const handleDownloadTxt = () => {
    const content = [
      'REDACTED DOCUMENT',
      '=================',
      `Original file: ${fileName}`,
      `Processed: ${now}`,
      `PII entities redacted: ${result.piiSummary.totalEntities}`,
      '',
      '---',
      '',
      result.redactedText,
    ].join('\n')

    downloadBlob(content, `${baseFileName}_redacted.txt`, 'text/plain')
  }

  const handleDownloadMd = () => {
    const typeRows = Object.entries(result.piiSummary.entitiesByType)
      .sort(([, a], [, b]) => b - a)
      .map(([type, count]) => `| ${type} | ${count} |`)
      .join('\n')

    const deduped = deduplicateEntities(result.piiSummary.entityDetails)

    const valueSections: string[] = []
    const sortedTypes = [...deduped.entries()].sort(
      ([, a], [, b]) => b.size - a.size
    )
    for (const [type, valuesMap] of sortedTypes) {
      const totalOccurrences = [...valuesMap.values()].reduce((sum, v) => sum + v.occurrences, 0)
      valueSections.push(`### ${type} (${valuesMap.size} unique, ${totalOccurrences} occurrences)`)
      const sortedValues = [...valuesMap.entries()].sort(([, a], [, b]) => b.occurrences - a.occurrences)
      for (const [value, info] of sortedValues) {
        valueSections.push(`- ${value} (${info.occurrences}\u00d7)`)
      }
      valueSections.push('')
    }

    const content = [
      '# Redacted Document',
      '',
      `**Original file:** ${fileName}`,
      `**Processed:** ${now}`,
      `**PII entities redacted:** ${result.piiSummary.totalEntities}`,
      '',
      '---',
      '',
      result.redactedText,
      '',
      '---',
      '',
      '## PII Summary',
      '',
      '| Type | Count |',
      '|------|-------|',
      typeRows,
      '',
      '## Redacted Values',
      '',
      ...valueSections,
    ].join('\n')

    downloadBlob(content, `${baseFileName}_redacted.md`, 'text/markdown')
  }

  const handleDownloadJson = () => {
    const deduped = deduplicateEntities(result.piiSummary.entityDetails)

    const totalUniqueValues = [...deduped.values()].reduce((sum, m) => sum + m.size, 0)

    const entitiesByType: Record<string, { count: number; uniqueValues: number; values: Array<{ value: string; occurrences: number; confidence: number }> }> = {}
    for (const [type, valuesMap] of deduped) {
      const totalOccurrences = [...valuesMap.values()].reduce((sum, v) => sum + v.occurrences, 0)
      const sortedValues = [...valuesMap.entries()]
        .sort(([, a], [, b]) => b.occurrences - a.occurrences)
        .map(([value, info]) => ({
          value,
          occurrences: info.occurrences,
          confidence: info.maxConfidence,
        }))
      entitiesByType[type] = {
        count: totalOccurrences,
        uniqueValues: valuesMap.size,
        values: sortedValues,
      }
    }

    const content = JSON.stringify(
      {
        metadata: {
          originalFile: fileName,
          processedAt: now,
          originalTextLength: result.originalTextLength,
        },
        piiSummary: {
          totalEntities: result.piiSummary.totalEntities,
          uniqueValues: totalUniqueValues,
          entitiesByType,
        },
      },
      null,
      2
    )

    downloadBlob(content, `${baseFileName}_pii_summary.json`, 'application/json')
  }

  const sortedTypes = Object.entries(result.piiSummary.entitiesByType).sort(
    ([, a], [, b]) => b - a
  )

  const previewText = result.redactedText.slice(0, 500)
  const isTruncated = result.redactedText.length > 500

  return (
    <div className="space-y-6">
      {/* PII Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-blue-600" />
            PII Summary
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {result.piiSummary.totalEntities}
              </p>
              <p className="text-sm text-slate-600">Entities Found</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {Object.keys(result.piiSummary.entitiesByType).length}
              </p>
              <p className="text-sm text-slate-600">Entity Types</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg text-center">
              <p className="text-2xl font-bold text-slate-900">
                {result.processingTime.toFixed(1)}s
              </p>
              <p className="text-sm text-slate-600">Processing Time</p>
            </div>
          </div>

          {sortedTypes.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-slate-600">Type</th>
                    <th className="text-right px-4 py-2 font-medium text-slate-600">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedTypes.map(([type, count]) => (
                    <tr key={type} className="border-t">
                      <td className="px-4 py-2 text-slate-700 font-mono text-xs">{type}</td>
                      <td className="px-4 py-2 text-right text-slate-900 font-medium">{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Redacted Text Preview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-slate-600" />
            Redacted Text Preview
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="bg-slate-50 border rounded-lg p-4 max-h-64 overflow-y-auto">
            <pre className="text-xs text-slate-700 whitespace-pre-wrap font-mono">
              {previewText}
              {isTruncated && (
                <span className="text-slate-400">
                  {'\n\n'}... ({result.redactedText.length - 500} more characters)
                </span>
              )}
            </pre>
          </div>
        </CardContent>
      </Card>

      {/* Download Buttons */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="w-5 h-5 text-slate-600" />
            Download Results
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Button variant="outline" onClick={handleDownloadTxt} className="w-full">
              <Download className="w-4 h-4 mr-2" />
              Redacted Text (.txt)
            </Button>
            <Button variant="outline" onClick={handleDownloadMd} className="w-full">
              <Download className="w-4 h-4 mr-2" />
              Redacted Text (.md)
            </Button>
            <Button variant="outline" onClick={handleDownloadJson} className="w-full">
              <Download className="w-4 h-4 mr-2" />
              PII Summary (.json)
            </Button>
          </div>

          <div className="pt-3 border-t">
            <Button variant="outline" onClick={reset}>
              <RotateCcw className="w-4 h-4 mr-2" />
              Start Over
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
