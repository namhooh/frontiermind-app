'use client'

/**
 * InvoicePreview
 *
 * Displays a preview of the generated invoice with line items,
 * LD adjustments, and totals. Includes a "Preview Only" watermark.
 */

import {
  Building2,
  Calendar,
  Hash,
  AlertTriangle,
  Download,
  FileText,
} from 'lucide-react'
import type { InvoicePreview as InvoicePreviewType } from '@/lib/workflow'
import { exportInvoiceText, exportInvoiceJSON } from '@/lib/workflow/invoiceGenerator'
import { Button } from '@/app/components/ui/button'
import { Badge } from '@/app/components/ui/badge'
import { cn } from '@/app/components/ui/cn'

interface InvoicePreviewProps {
  invoice: InvoicePreviewType
  className?: string
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(amount)
}

function formatNumber(num: number): string {
  return num.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export function InvoicePreviewComponent({ invoice, className }: InvoicePreviewProps) {
  const handleDownloadText = () => {
    const text = exportInvoiceText(invoice)
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${invoice.invoiceNumber}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDownloadJSON = () => {
    const json = exportInvoiceJSON(invoice)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${invoice.invoiceNumber}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={cn('relative', className)}>
      {/* Preview Watermark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10 overflow-hidden">
        <div className="text-8xl font-bold text-slate-200/50 -rotate-45 whitespace-nowrap">
          PREVIEW ONLY
        </div>
      </div>

      {/* Invoice Content */}
      <div className="relative bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-slate-800 to-slate-700 text-white p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold">INVOICE</h2>
              <Badge variant="outline" className="mt-2 text-white border-white/30">
                Preview
              </Badge>
            </div>
            <div className="text-right">
              <div className="flex items-center gap-2 text-slate-300">
                <Hash className="w-4 h-4" />
                <span className="font-mono">{invoice.invoiceNumber}</span>
              </div>
              <div className="flex items-center gap-2 text-slate-300 mt-1">
                <Calendar className="w-4 h-4" />
                <span>{invoice.invoiceDate}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Parties */}
        <div className="grid grid-cols-2 gap-6 p-6 border-b">
          <div>
            <div className="flex items-center gap-2 text-slate-500 text-sm mb-2">
              <Building2 className="w-4 h-4" />
              <span>From (Seller)</span>
            </div>
            <p className="font-semibold text-slate-900">{invoice.seller.name}</p>
            {invoice.seller.address && (
              <p className="text-sm text-slate-600">{invoice.seller.address}</p>
            )}
          </div>
          <div>
            <div className="flex items-center gap-2 text-slate-500 text-sm mb-2">
              <Building2 className="w-4 h-4" />
              <span>To (Buyer)</span>
            </div>
            <p className="font-semibold text-slate-900">{invoice.buyer.name}</p>
            {invoice.buyer.address && (
              <p className="text-sm text-slate-600">{invoice.buyer.address}</p>
            )}
          </div>
        </div>

        {/* Billing Period */}
        <div className="px-6 py-4 bg-slate-50 border-b">
          <div className="flex items-center gap-2 text-slate-600">
            <Calendar className="w-4 h-4" />
            <span className="text-sm">
              Billing Period: <strong>{invoice.billingPeriod.start}</strong> to{' '}
              <strong>{invoice.billingPeriod.end}</strong>
            </span>
          </div>
        </div>

        {/* Line Items */}
        <div className="p-6">
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">
            Line Items
          </h3>
          <table className="w-full">
            <thead>
              <tr className="text-left text-sm text-slate-500 border-b">
                <th className="pb-3">Description</th>
                <th className="pb-3 text-right">Quantity</th>
                <th className="pb-3 text-right">Rate</th>
                <th className="pb-3 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {invoice.lineItems.map((item, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="py-3 text-slate-900">{item.description}</td>
                  <td className="py-3 text-right text-slate-600">
                    {formatNumber(item.quantity)} {item.unit}
                  </td>
                  <td className="py-3 text-right text-slate-600">
                    {formatCurrency(item.rate)}/{item.unit}
                  </td>
                  <td className="py-3 text-right font-medium text-slate-900">
                    {formatCurrency(item.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Subtotal */}
          <div className="flex justify-end mt-4 pt-4 border-t">
            <div className="text-right">
              <span className="text-slate-600 mr-8">Subtotal</span>
              <span className="font-semibold text-slate-900">
                {formatCurrency(invoice.subtotal)}
              </span>
            </div>
          </div>
        </div>

        {/* LD Adjustments */}
        {invoice.ldAdjustments.length > 0 && (
          <div className="px-6 pb-6">
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
                <h3 className="font-semibold text-amber-900">
                  Liquidated Damages Adjustments
                </h3>
              </div>
              <div className="space-y-2">
                {invoice.ldAdjustments.map((adj, idx) => (
                  <div key={idx} className="flex justify-between text-sm">
                    <span className="text-amber-800">{adj.description}</span>
                    <span className="font-medium text-red-600">
                      {formatCurrency(adj.amount)}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex justify-between mt-3 pt-3 border-t border-amber-200">
                <span className="font-semibold text-amber-900">Total LD Deduction</span>
                <span className="font-semibold text-red-600">
                  -{formatCurrency(invoice.ldTotal)}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Total */}
        <div className="px-6 pb-6">
          <div className="flex justify-end p-4 bg-slate-800 rounded-lg">
            <div className="text-right">
              <span className="text-slate-300 mr-8">Total Amount Due</span>
              <span className="text-2xl font-bold text-white">
                {formatCurrency(invoice.totalAmount)}
              </span>
            </div>
          </div>
        </div>

        {/* Notes */}
        {invoice.notes && invoice.notes.length > 0 && (
          <div className="px-6 pb-6">
            <div className="p-4 bg-slate-50 rounded-lg">
              <h4 className="text-sm font-semibold text-slate-500 mb-2">Notes</h4>
              <ul className="space-y-1">
                {invoice.notes.map((note, idx) => (
                  <li key={idx} className="text-sm text-slate-600 flex items-start gap-2">
                    <span className="text-slate-400">•</span>
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* Download Actions */}
        <div className="px-6 pb-6">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleDownloadText}>
              <FileText className="w-4 h-4 mr-2" />
              Download TXT
            </Button>
            <Button variant="outline" size="sm" onClick={handleDownloadJSON}>
              <Download className="w-4 h-4 mr-2" />
              Download JSON
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
