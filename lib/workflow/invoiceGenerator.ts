/**
 * Invoice Generator
 *
 * Client-side invoice calculation based on contract clauses and meter data.
 * Generates invoice previews with line items and LD adjustments.
 */

import type { ExtractedClause, RuleEvaluationResult } from '@/lib/api'
import type { MeterDataSummary, InvoicePreview, InvoiceLineItem } from './types'

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Extract pricing information from contract clauses.
 */
function extractPricingFromClauses(clauses: ExtractedClause[]): {
  energyRate: number
  currency: string
  rateUnit: string
} {
  // Default values
  let energyRate = 85 // $/MWh default
  let currency = 'USD'
  let rateUnit = 'MWh'

  // Look for pricing clauses (use new 'category' field with fallback)
  const pricingClauses = clauses.filter((c) => {
    const category = (c.category || c.clause_category || '').toLowerCase()
    return (
      category.includes('pricing') ||
      category.includes('tariff') ||
      category.includes('payment') ||
      category.includes('commercial') ||
      category.includes('payment_terms')
    )
  })

  for (const clause of pricingClauses) {
    const payload = clause.normalized_payload

    // Try to extract rate from payload
    if (payload) {
      if (typeof payload.rate === 'number') {
        energyRate = payload.rate
      } else if (typeof payload.price === 'number') {
        energyRate = payload.price
      } else if (typeof payload.tariff === 'number') {
        energyRate = payload.tariff
      } else if (typeof payload.energy_rate === 'number') {
        energyRate = payload.energy_rate
      }

      if (typeof payload.currency === 'string') {
        currency = payload.currency
      }

      if (typeof payload.unit === 'string') {
        rateUnit = payload.unit
      }
    }

    // Try to parse from raw text as fallback
    const rateMatch = clause.raw_text.match(/\$?([\d,]+\.?\d*)\s*(?:per|\/)\s*(MWh|kWh|MW)/i)
    if (rateMatch) {
      energyRate = parseFloat(rateMatch[1].replace(',', ''))
      rateUnit = rateMatch[2]
    }
  }

  return { energyRate, currency, rateUnit }
}

/**
 * Extract seller and buyer information from clauses.
 */
function extractParties(clauses: ExtractedClause[]): {
  seller: { name: string; address?: string }
  buyer: { name: string; address?: string }
} {
  // Default parties
  let seller = { name: 'Solar Project LLC', address: undefined as string | undefined }
  let buyer = { name: 'Utility Company Inc.', address: undefined as string | undefined }

  // Look for party information in clauses
  for (const clause of clauses) {
    if (clause.responsible_party) {
      // First party mentioned is often the seller
      if (seller.name === 'Solar Project LLC') {
        seller.name = clause.responsible_party
      }
    }
    if (clause.beneficiary_party) {
      buyer.name = clause.beneficiary_party
    }

    // Check payload for party names
    const payload = clause.normalized_payload
    if (payload) {
      if (typeof payload.seller === 'string') {
        seller.name = payload.seller
      }
      if (typeof payload.buyer === 'string') {
        buyer.name = payload.buyer
      }
      if (typeof payload.offtaker === 'string') {
        buyer.name = payload.offtaker
      }
      if (typeof payload.generator === 'string') {
        seller.name = payload.generator
      }
    }
  }

  return { seller, buyer }
}

/**
 * Generate a unique invoice number.
 */
function generateInvoiceNumber(): string {
  const timestamp = Date.now().toString(36).toUpperCase()
  const random = Math.random().toString(36).substring(2, 6).toUpperCase()
  return `INV-${timestamp}-${random}`
}

/**
 * Format currency amount.
 */
function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount)
}

// ============================================================================
// Main Generator Function
// ============================================================================

/**
 * Generate an invoice preview from contract clauses and meter data.
 */
export function generateInvoicePreview(
  clauses: ExtractedClause[],
  meterSummary: MeterDataSummary,
  ruleResult?: RuleEvaluationResult | null
): InvoicePreview {
  // Extract pricing from clauses
  const { energyRate, currency, rateUnit } = extractPricingFromClauses(clauses)

  // Extract parties
  const { seller, buyer } = extractParties(clauses)

  // Calculate line items
  const lineItems: InvoiceLineItem[] = []

  // Main energy charge
  const energyQuantity = meterSummary.totalEnergyMWh
  const energyAmount = energyQuantity * energyRate
  lineItems.push({
    description: 'Energy Delivery',
    quantity: energyQuantity,
    unit: rateUnit,
    rate: energyRate,
    amount: energyAmount,
  })

  // Add capacity charge if significant peak
  if (meterSummary.peakDayMWh > meterSummary.averageDailyMWh * 1.5) {
    const capacityAmount = meterSummary.peakDayMWh * 2 // Example capacity rate
    lineItems.push({
      description: 'Peak Capacity Charge',
      quantity: 1,
      unit: 'month',
      rate: capacityAmount,
      amount: capacityAmount,
    })
  }

  // Calculate subtotal
  const subtotal = lineItems.reduce((sum, item) => sum + item.amount, 0)

  // Process LD adjustments from rule evaluation
  const ldAdjustments: InvoicePreview['ldAdjustments'] = []

  if (ruleResult && ruleResult.default_events) {
    for (const event of ruleResult.default_events) {
      if (event.breach && event.ld_amount) {
        ldAdjustments.push({
          description: `Liquidated Damages - ${event.rule_type.replace(/_/g, ' ')}`,
          amount: -event.ld_amount,
          ruleType: event.rule_type,
        })
      }
    }
  }

  // Check for availability breach based on meter data
  if (meterSummary.availabilityPercentage < 95) {
    const availabilityShortfall = 95 - meterSummary.availabilityPercentage
    const ldAmount = subtotal * (availabilityShortfall / 100) * 0.5 // 50% of shortfall as penalty
    ldAdjustments.push({
      description: `Availability Shortfall (${meterSummary.availabilityPercentage.toFixed(1)}% vs 95% guarantee)`,
      amount: -ldAmount,
      ruleType: 'availability_guarantee',
    })
  }

  const ldTotal = ldAdjustments.reduce((sum, adj) => sum + Math.abs(adj.amount), 0)
  const totalAmount = subtotal - ldTotal

  // Build invoice preview
  const invoice: InvoicePreview = {
    invoiceNumber: generateInvoiceNumber(),
    invoiceDate: new Date().toISOString().split('T')[0],
    billingPeriod: {
      start: meterSummary.dateRange.start,
      end: meterSummary.dateRange.end,
    },
    seller,
    buyer,
    lineItems,
    subtotal,
    ldAdjustments,
    ldTotal,
    totalAmount,
    notes: [
      'This is a preview invoice generated from contract terms and meter data.',
      `Energy rate: ${formatCurrency(energyRate)}/${rateUnit}`,
      `Billing period: ${meterSummary.dateRange.start} to ${meterSummary.dateRange.end}`,
    ],
  }

  return invoice
}

/**
 * Export invoice as downloadable JSON.
 */
export function exportInvoiceJSON(invoice: InvoicePreview): string {
  return JSON.stringify(invoice, null, 2)
}

/**
 * Export invoice as simple text format.
 */
export function exportInvoiceText(invoice: InvoicePreview): string {
  const lines = [
    '═'.repeat(60),
    '                        INVOICE',
    '═'.repeat(60),
    '',
    `Invoice Number: ${invoice.invoiceNumber}`,
    `Invoice Date: ${invoice.invoiceDate}`,
    `Billing Period: ${invoice.billingPeriod.start} to ${invoice.billingPeriod.end}`,
    '',
    '─'.repeat(60),
    'SELLER:',
    `  ${invoice.seller.name}`,
    invoice.seller.address ? `  ${invoice.seller.address}` : '',
    '',
    'BUYER:',
    `  ${invoice.buyer.name}`,
    invoice.buyer.address ? `  ${invoice.buyer.address}` : '',
    '',
    '─'.repeat(60),
    'LINE ITEMS:',
    '─'.repeat(60),
  ]

  // Add line items
  for (const item of invoice.lineItems) {
    lines.push(
      `${item.description}`,
      `  ${item.quantity.toLocaleString()} ${item.unit} @ ${formatCurrency(item.rate)}/${item.unit}`,
      `  Amount: ${formatCurrency(item.amount)}`,
      ''
    )
  }

  lines.push('─'.repeat(60))
  lines.push(`SUBTOTAL: ${formatCurrency(invoice.subtotal)}`)

  // Add LD adjustments
  if (invoice.ldAdjustments.length > 0) {
    lines.push('')
    lines.push('LD ADJUSTMENTS:')
    for (const adj of invoice.ldAdjustments) {
      lines.push(`  ${adj.description}: ${formatCurrency(adj.amount)}`)
    }
    lines.push(`TOTAL LD: ${formatCurrency(-invoice.ldTotal)}`)
  }

  lines.push('')
  lines.push('═'.repeat(60))
  lines.push(`TOTAL AMOUNT DUE: ${formatCurrency(invoice.totalAmount)}`)
  lines.push('═'.repeat(60))

  if (invoice.notes && invoice.notes.length > 0) {
    lines.push('')
    lines.push('NOTES:')
    for (const note of invoice.notes) {
      lines.push(`  • ${note}`)
    }
  }

  return lines.filter((l) => l !== undefined).join('\n')
}
