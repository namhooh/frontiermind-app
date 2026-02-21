'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'

import { getApiBaseUrl } from '@/lib/api/config'

const API_BASE_URL = getApiBaseUrl()

interface SubmissionField {
  name?: string
  label?: string
  type?: string
  required?: boolean
}

interface InvoiceSummary {
  invoice_number: string
  total_amount?: string
  due_date?: string
}

interface FormConfig {
  fields: (string | SubmissionField)[]
  invoice_summary?: InvoiceSummary
  counterparty_name?: string
  organization_name?: string
  project_name?: string
  submission_type?: string
  expires_at: string
}

interface ExtractionResult {
  grp_per_kwh: number
  total_variable_charges: number
  total_kwh_invoiced: number
  line_items_count: number
  extraction_confidence: string
}

type PageState = 'loading' | 'form' | 'success' | 'error'

export default function SubmissionPage() {
  const params = useParams()
  const token = params.token as string

  const [state, setState] = useState<PageState>('loading')
  const [config, setConfig] = useState<FormConfig | null>(null)
  const [formData, setFormData] = useState<Record<string, string>>({})
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [extractionResult, setExtractionResult] = useState<ExtractionResult | null>(null)

  const isGRPUpload = config?.submission_type === 'grp_upload'

  useEffect(() => {
    async function loadForm() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/submit/${token}`)
        if (!res.ok) {
          const data = await res.json().catch(() => null)
          setErrorMessage(data?.detail?.message || 'This link is invalid or has expired.')
          setState('error')
          return
        }
        const data: FormConfig = await res.json()
        setConfig(data)

        // Initialize form data with empty strings for each field
        const initial: Record<string, string> = {}
        for (const field of data.fields) {
          const name = typeof field === 'string' ? field : field.name || ''
          if (name && (typeof field === 'string' || field.type !== 'file')) {
            initial[name] = ''
          }
        }
        setFormData(initial)
        setState('form')
      } catch {
        setErrorMessage('Unable to load form. Please try again later.')
        setState('error')
      }
    }
    loadForm()
  }, [token])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null
    setSelectedFile(file)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setErrorMessage('')

    try {
      if (isGRPUpload) {
        // File upload: POST to /api/submit/{token}/upload as multipart
        if (!selectedFile) {
          setErrorMessage('Please select a file to upload.')
          setSubmitting(false)
          return
        }
        if (!formData.billing_month) {
          setErrorMessage('Please select a billing month.')
          setSubmitting(false)
          return
        }

        const fd = new FormData()
        fd.append('file', selectedFile)
        fd.append('billing_month', formData.billing_month)
        if (email) fd.append('submitted_by_email', email)

        const res = await fetch(`${API_BASE_URL}/api/submit/${token}/upload`, {
          method: 'POST',
          body: fd,
        })

        if (!res.ok) {
          const data = await res.json().catch(() => null)
          setErrorMessage(data?.detail?.message || 'Upload failed. Please try again.')
          setSubmitting(false)
          return
        }

        const result = await res.json()
        setExtractionResult({
          grp_per_kwh: result.grp_per_kwh,
          total_variable_charges: result.total_variable_charges,
          total_kwh_invoiced: result.total_kwh_invoiced,
          line_items_count: result.line_items_count,
          extraction_confidence: result.extraction_confidence,
        })
        setState('success')
      } else {
        // Standard form submission: POST as JSON
        const res = await fetch(`${API_BASE_URL}/api/submit/${token}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            response_data: formData,
            submitted_by_email: email || undefined,
          }),
        })

        if (!res.ok) {
          const data = await res.json().catch(() => null)
          setErrorMessage(data?.detail?.message || 'Submission failed. Please try again.')
          setSubmitting(false)
          return
        }

        setState('success')
      }
    } catch {
      setErrorMessage('Network error. Please try again.')
      setSubmitting(false)
    }
  }

  const getFieldLabel = (field: string | SubmissionField): string => {
    if (typeof field === 'string') {
      return field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    }
    return field.label || field.name?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Field'
  }

  const getFieldName = (field: string | SubmissionField): string => {
    return typeof field === 'string' ? field : field.name || ''
  }

  const getFieldType = (field: string | SubmissionField): string => {
    if (typeof field === 'string') {
      if (field.includes('date')) return 'date'
      if (field.includes('email')) return 'email'
      return 'text'
    }
    return field.type || 'text'
  }

  // Loading state
  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="mt-4 text-slate-500 text-sm">Loading form...</p>
        </div>
      </div>
    )
  }

  // Error state
  if (state === 'error') {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 className="text-lg font-semibold text-slate-900 mb-2">Link Unavailable</h1>
          <p className="text-slate-500 text-sm">{errorMessage}</p>
        </div>
      </div>
    )
  }

  // Success state
  if (state === 'success') {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center">
          <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>

          {extractionResult ? (
            <>
              <h1 className="text-lg font-semibold text-slate-900 mb-2">Invoice Processed</h1>
              <div className="mt-4 text-left bg-slate-50 rounded-lg p-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">GRP</span>
                  <span className="font-medium text-slate-900">
                    {extractionResult.grp_per_kwh.toFixed(4)} /kWh
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Variable Charges</span>
                  <span className="font-medium text-slate-900">
                    {extractionResult.total_variable_charges.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">kWh Invoiced</span>
                  <span className="font-medium text-slate-900">
                    {extractionResult.total_kwh_invoiced.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Line Items</span>
                  <span className="font-medium text-slate-900">{extractionResult.line_items_count}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Confidence</span>
                  <span className={`font-medium ${
                    extractionResult.extraction_confidence === 'high' ? 'text-green-600' :
                    extractionResult.extraction_confidence === 'medium' ? 'text-amber-600' :
                    'text-red-600'
                  }`}>
                    {extractionResult.extraction_confidence}
                  </span>
                </div>
              </div>
              <p className="text-slate-400 text-xs mt-4">
                You can upload another invoice using the same link.
              </p>
              <button
                onClick={() => {
                  setState('form')
                  setSelectedFile(null)
                  setFormData(prev => ({ ...prev, billing_month: '' }))
                  setExtractionResult(null)
                }}
                className="mt-4 text-blue-600 text-sm font-medium hover:underline"
              >
                Upload Another Invoice
              </button>
            </>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-slate-900 mb-2">Submission Received</h1>
              <p className="text-slate-500 text-sm">Thank you. Your response has been recorded successfully.</p>
            </>
          )}
        </div>
      </div>
    )
  }

  // Form state
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="max-w-lg w-full">
        {/* Header */}
        <div className="bg-slate-900 text-white rounded-t-xl px-6 py-5">
          <h1 className="text-lg font-semibold">
            {config?.organization_name || 'FrontierMind'}
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            {isGRPUpload
              ? `Utility Invoice Upload${config?.project_name ? ` — ${config.project_name}` : ''}`
              : 'Submission Form'
            }
          </p>
        </div>

        <div className="bg-white rounded-b-xl shadow-sm border border-slate-200 border-t-0">
          {/* Invoice summary */}
          {config?.invoice_summary && (
            <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">Invoice Details</p>
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Invoice</span>
                  <span className="font-medium text-slate-900">{config.invoice_summary.invoice_number}</span>
                </div>
                {config.invoice_summary.total_amount && (
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Amount</span>
                    <span className="font-medium text-slate-900">
                      ${Number(config.invoice_summary.total_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                )}
                {config.invoice_summary.due_date && (
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Due Date</span>
                    <span className="font-medium text-slate-900">
                      {new Date(config.invoice_summary.due_date).toLocaleDateString()}
                    </span>
                  </div>
                )}
              </div>
              {config.counterparty_name && (
                <p className="text-xs text-slate-400 mt-2">For: {config.counterparty_name}</p>
              )}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
            {config?.fields.map((field, i) => {
              const name = getFieldName(field)
              const label = getFieldLabel(field)
              const type = getFieldType(field)

              if (!name) return null

              if (type === 'file') {
                return (
                  <div key={i}>
                    <label htmlFor={name} className="block text-sm font-medium text-slate-700 mb-1">
                      {label}
                    </label>
                    <input
                      id={name}
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg"
                      onChange={handleFileChange}
                      className="w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                    />
                    {selectedFile && (
                      <p className="mt-1 text-xs text-slate-400">
                        {selectedFile.name} ({(selectedFile.size / 1024).toFixed(0)} KB)
                      </p>
                    )}
                  </div>
                )
              }

              if (type === 'month') {
                return (
                  <div key={i}>
                    <label htmlFor={name} className="block text-sm font-medium text-slate-700 mb-1">
                      {label}
                    </label>
                    <input
                      id={name}
                      type="month"
                      value={formData[name] || ''}
                      onChange={e => setFormData(prev => ({ ...prev, [name]: e.target.value }))}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </div>
                )
              }

              return (
                <div key={i}>
                  <label htmlFor={name} className="block text-sm font-medium text-slate-700 mb-1">
                    {label}
                  </label>
                  {type === 'textarea' ? (
                    <textarea
                      id={name}
                      value={formData[name] || ''}
                      onChange={e => setFormData(prev => ({ ...prev, [name]: e.target.value }))}
                      rows={3}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  ) : (
                    <input
                      id={name}
                      type={type}
                      value={formData[name] || ''}
                      onChange={e => setFormData(prev => ({ ...prev, [name]: e.target.value }))}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  )}
                </div>
              )
            })}

            {/* Email field */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
                Your Email <span className="text-slate-400 font-normal">(optional)</span>
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {errorMessage && (
              <p className="text-red-600 text-sm">{errorMessage}</p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-blue-600 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting
                ? (isGRPUpload ? 'Processing Invoice...' : 'Submitting...')
                : (isGRPUpload ? 'Upload & Process' : 'Submit')
              }
            </button>

            {isGRPUpload && submitting && (
              <p className="text-xs text-slate-400 text-center">
                This may take 10-30 seconds while the invoice is being processed.
              </p>
            )}
          </form>
        </div>

        <p className="text-center text-xs text-slate-400 mt-4">
          Powered by FrontierMind
        </p>
      </div>
    </div>
  )
}
