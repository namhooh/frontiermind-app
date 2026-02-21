export function str(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return v.toLocaleString('en-US', { maximumFractionDigits: 10 })
  // Format numeric strings, but not dates (e.g. 2025-01-01)
  if (typeof v === 'string' && v !== '' && !isNaN(Number(v)) && !/^\d{4}-\d{2}/.test(v)) {
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: 10 })
  }
  return String(v)
}

export function formatNum(v: unknown): string {
  if (v == null) return '—'
  const n = Number(v)
  if (isNaN(n)) return str(v)
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function hasAnyValue(obj: Record<string, unknown>, keys: string[]): boolean {
  return keys.some((k) => obj[k] != null)
}

export function formatEscalationRules(rules: unknown): string {
  if (!Array.isArray(rules)) return str(rules)
  return rules.map((r: Record<string, unknown>) => {
    const parts: string[] = []
    if (r.component) parts.push(String(r.component))
    if (r.type) parts.push(`type: ${r.type}`)
    if (r.value != null) parts.push(`value: ${r.value}`)
    if (r.start_year != null) parts.push(`from year ${r.start_year}`)
    return parts.join(', ')
  }).join('\n')
}

export function formatExcusedEvents(events: unknown): string {
  if (typeof events === 'string') return events
  if (Array.isArray(events)) return events.map(String).join('\n')
  return str(events)
}

export function formatConfidenceScores(scores: unknown): string {
  if (scores == null || typeof scores !== 'object') return str(scores)
  const entries = Object.entries(scores as Record<string, unknown>)
  if (entries.length === 0) return '—'
  return entries
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
    .join(', ')
}

// ---------------------------------------------------------------------------
// Tariff ↔ Product mapping
// ---------------------------------------------------------------------------

type R = Record<string, unknown>

export interface ProductWithTariffs {
  product: R
  tariffs: R[]
}

const PRODUCT_TARIFF_MAP: [RegExp, string][] = [
  [/energy|metered|available/i, 'ENERGY_SALES'],
  [/bess|battery/i, 'BESS_LEASE'],
  [/equipment|rental|lease/i, 'EQUIPMENT_RENTAL_LEASE'],
  [/loan/i, 'LOAN'],
]

export function mapProductToTariffType(product: R): string | null {
  const name = String(product.product_name ?? product.product_code ?? '')
  for (const [re, type] of PRODUCT_TARIFF_MAP) {
    if (re.test(name)) return type
  }
  return null
}

export function groupProductsWithTariffs(
  billingProducts: R[],
  tariffs: R[],
  contractId: unknown,
): { matched: ProductWithTariffs[]; unmatched: R[] } {
  const contractBps = billingProducts.filter((bp) => bp.contract_id === contractId)
  const contractTariffs = tariffs.filter((t) => t.contract_id === contractId)
  const claimedTariffIds = new Set<unknown>()

  const matched: ProductWithTariffs[] = contractBps.map((bp) => {
    const tariffType = mapProductToTariffType(bp)
    let productTariffs: R[]
    if (tariffType) {
      productTariffs = contractTariffs.filter(
        (t) => String(t.tariff_type_code).toUpperCase() === tariffType,
      )
    } else {
      // No match → show all tariffs as fallback for this product
      productTariffs = contractTariffs
    }
    for (const t of productTariffs) claimedTariffIds.add(t.id)
    return { product: bp, tariffs: productTariffs }
  })

  const unmatched = contractTariffs.filter((t) => !claimedTariffIds.has(t.id))
  return { matched, unmatched }
}
