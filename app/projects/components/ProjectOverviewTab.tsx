'use client'

import { useMemo } from 'react'
import type { ProjectDashboardResponse } from '@/lib/api/adminClient'
import { toOpts } from '@/app/projects/utils/constants'
import { CollapsibleSection } from './CollapsibleSection'
import { ProjectTableTab, type Column } from './ProjectTableTab'
import { FieldGrid, type FieldDef } from './shared/FieldGrid'

// Required customer contact titles — always shown even when empty
const REQUIRED_CONTACT_ROLES = [
  'Accounting Department 1',
  'Accounting Department 2',
  'CFO',
  'Financial Manager',
  'General Manager',
  'Operations Manager',
]

interface ProjectOverviewTabProps {
  data: ProjectDashboardResponse
  contractColumns: Column[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
  contacts?: Record<string, unknown>[]
  contactColumns?: Column[]
  onAddContact?: (row: Record<string, unknown>) => Promise<void>
  onRemoveContact?: (id: number) => Promise<void>
}

export function ProjectOverviewTab({ data, contractColumns, projectId, onSaved, editMode, contacts, contactColumns, onAddContact, onRemoveContact }: ProjectOverviewTabProps) {
  const { project, contracts, tariffs, clauses, lookups } = data
  const pid = project.id as number

  // Merge DB contacts with required role slots so every title always appears
  const mergedContacts = useMemo(() => {
    const dbContacts = contacts ?? []
    // Index existing contacts by normalised role
    const byRole = new Map<string, Record<string, unknown>>()
    for (const c of dbContacts) {
      const role = String(c.role ?? '').trim()
      if (role) byRole.set(role.toLowerCase(), c)
    }
    const result: Record<string, unknown>[] = []
    const usedIds = new Set<unknown>()
    // First: required roles in order, filling from DB or creating a placeholder
    for (const role of REQUIRED_CONTACT_ROLES) {
      const existing = byRole.get(role.toLowerCase())
      if (existing) {
        result.push(existing)
        usedIds.add(existing.id)
      } else {
        // Placeholder row — no id means it cannot be edited/removed inline
        result.push({ role, full_name: null, email: null, phone: null, include_in_invoice_email: false, escalation_only: false })
      }
    }
    // Append any additional contacts not matching required roles
    for (const c of dbContacts) {
      if (!usedIds.has(c.id)) {
        result.push(c)
      }
    }
    return result
  }, [contacts])

  const contractTypeOpts = toOpts(lookups?.contract_types)

  return (
    <div className="space-y-4">
      <CollapsibleSection title="Project Information">
        {(() => {
          const primaryContract = contracts[0] as Record<string, unknown> | undefined
          const cid = primaryContract?.id as number | undefined
          return (
            <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
              ['Project ID', project.external_project_id, { fieldKey: 'external_project_id', entity: 'projects', entityId: pid, type: 'text' }],
              ...((project.additional_external_ids as string[] | null)?.length ? [['Additional Project IDs', (project.additional_external_ids as string[]).join(', ')] as FieldDef] : []),
              ['Contract ID', primaryContract?.external_contract_id, ...(cid != null ? [{ fieldKey: 'external_contract_id', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'text' as const }] : [])],
              ['Project Name', project.name, { fieldKey: 'name', entity: 'projects', entityId: pid, type: 'text' }],
              ...(cid != null ? [['Contract Type', primaryContract?.contract_type_name, { fieldKey: 'contract_type_id', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'select' as const, options: contractTypeOpts, selectValue: primaryContract?.contract_type_id }] as FieldDef] : []),
              ['Sage Customer ID', project.sage_id, { fieldKey: 'sage_id', entity: 'projects', entityId: pid, type: 'text' }],
              ['Legal Entity', project.legal_entity_name],
              ['Legal Entity Code', project.legal_entity_code],
              ['Country of Operation', project.country, { fieldKey: 'country', entity: 'projects', entityId: pid, type: 'text' }],
              ['Customer Registered Name', primaryContract?.counterparty_registered_name ?? primaryContract?.counterparty_name],
              ['Industry', primaryContract?.counterparty_industry],
              ['Company Registration Number', primaryContract?.counterparty_registration_number],
              ['Registered Address', primaryContract?.counterparty_registered_address],
            ] as FieldDef[]} />
          )
        })()}
      </CollapsibleSection>

      <CollapsibleSection title="Contract Terms">
        {(() => {
          const primaryContract = contracts[0] as Record<string, unknown> | undefined
          const cid = primaryContract?.id as number | undefined
          const primaryTariff = tariffs[0] as Record<string, unknown> | undefined
          // Collect distinct phase COD dates from contract lines
          const contractLines = (data.contract_lines ?? []) as Record<string, unknown>[]
          const phaseCods = contractLines
            .filter(cl => cl.phase_cod_date != null)
            .map(cl => {
              const desc = String(cl.product_desc ?? '')
              // Extract "Phase N" from product_desc, e.g. "Metered Energy - Phase 1" → "Phase 1 COD"
              const phaseMatch = desc.match(/phase\s*\d+/i)
              const label = phaseMatch ? `${phaseMatch[0]} COD` : (desc || 'Phase COD')
              return { label, date: String(cl.phase_cod_date) }
            })
            .filter((v, i, a) => a.findIndex(x => x.date === v.date) === i)
          return (
            <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
              ...(phaseCods.length > 0
                ? phaseCods.map(p => [p.label, p.date] as FieldDef)
                : [['COD', project.cod_date, { fieldKey: 'cod_date', entity: 'projects' as const, entityId: pid, type: 'date' as const }] as FieldDef]),
              ...(cid != null ? [['Contract Term (years)', primaryContract?.contract_term_years, { fieldKey: 'contract_term_years', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'number' as const }] as FieldDef] : []),
              ['Installed Capacity (kWp)', project.installed_dc_capacity_kwp, { fieldKey: 'installed_dc_capacity_kwp', entity: 'projects' as const, entityId: pid, type: 'number' as const }],
              ['Energy Sales Type', primaryTariff?.energy_sale_type_name],
              ['Billing Currency', primaryTariff?.currency_code],
            ] as FieldDef[]} />
          )
        })()}
      </CollapsibleSection>

      {/* Amendment History */}
      {(() => {
        const amendments = (data.amendments ?? []) as Record<string, unknown>[]
        if (amendments.length === 0) return null

        const humanizeField: Record<string, string> = {
          contract_term_years: 'Contract Term (years)',
          solar_discount_pct: 'Solar Discount',
          min_solar_price_escalation: 'Min Solar Price Escalation',
          early_termination_charges: 'Early Termination Charges',
        }

        const formatValue = (field: string, value: unknown): string => {
          if (value == null) return '\u2014'
          if (field === 'solar_discount_pct' && typeof value === 'number')
            return `${(value * 100).toFixed(1)}%`
          return String(value)
        }

        return (
          <CollapsibleSection title="Amendment History">
            <div className="space-y-4">
              {amendments.map((a) => {
                const changes = ((a.source_metadata as Record<string, unknown>)?.changes ?? []) as Record<string, unknown>[]
                return (
                  <div key={a.id as number} className="space-y-2">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-slate-800">
                        Amendment {a.amendment_number as number}
                      </span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                        {a.amendment_date
                          ? new Date(String(a.amendment_date)).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
                          : ''}
                      </span>
                    </div>
                    {a.description != null && (
                      <p className="text-sm text-slate-600">{String(a.description)}</p>
                    )}
                    {changes.length > 0 && (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-slate-200">
                              <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Field</th>
                              <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">Before</th>
                              <th className="text-left px-3 py-1.5 text-xs font-medium text-slate-500">After</th>
                            </tr>
                          </thead>
                          <tbody>
                            {changes.map((ch, j) => {
                              const field = String(ch.field ?? '')
                              const label = humanizeField[field] ?? field
                              const hasBefore = ch.from != null
                              const hasAfter = ch.to != null
                              const isRevised = ch.action === 'revised'
                              return (
                                <tr key={j} className="border-b border-slate-50 hover:bg-slate-50">
                                  <td className="px-3 py-1.5 text-slate-700 font-medium">{label}</td>
                                  <td className="px-3 py-1.5 text-slate-500">
                                    {hasBefore ? (
                                      <span className="line-through">{formatValue(field, ch.from)}</span>
                                    ) : (
                                      <span className="text-slate-400">{'\u2014'}</span>
                                    )}
                                  </td>
                                  <td className="px-3 py-1.5 text-slate-900 font-semibold">
                                    {isRevised ? 'revised' : hasAfter ? formatValue(field, ch.to) : '\u2014'}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </CollapsibleSection>
        )
      })()}

      {(() => {
        const primaryContract = contracts[0] as Record<string, unknown> | undefined
        const paymentClause = (clauses ?? []).find(
          (cl: Record<string, unknown>) =>
            cl.clause_category_code === 'PAYMENT_TERMS' &&
            cl.contract_id === primaryContract?.id,
        ) as Record<string, unknown> | undefined
        if (!paymentClause) return null
        const np = (paymentClause.normalized_payload ?? {}) as Record<string, unknown>
        if (np.default_rate_benchmark == null && np.default_rate_spread_pct == null && np.payment_due_days == null) return null

        const accrualMap: Record<string, string> = {
          PRO_RATA_DAILY: 'Pro-rata Daily',
          SIMPLE_ANNUAL: 'Simple Annual',
        }

        const benchmarkLabel =
          np.default_rate_benchmark != null && np.default_rate_spread_pct != null
            ? `${np.default_rate_benchmark} + ${Number(np.default_rate_spread_pct).toFixed(2)}%`
            : np.default_rate_benchmark != null
              ? String(np.default_rate_benchmark)
              : np.default_rate_spread_pct != null
                ? `${Number(np.default_rate_spread_pct).toFixed(2)}%`
                : null

        return (
          <CollapsibleSection title="Payment Terms & Default Rate">
            <FieldGrid fields={[
              ...(np.payment_due_days != null ? [['Payment Due (days)', np.payment_due_days] as FieldDef] : []),
              ...(benchmarkLabel != null ? [['Default Rate', benchmarkLabel] as FieldDef] : []),
              ...(np.default_rate_accrual_method != null ? [['Accrual Method', accrualMap[String(np.default_rate_accrual_method)] ?? String(np.default_rate_accrual_method)] as FieldDef] : []),
              ...(np.late_payment_fx_indemnity != null ? [['Late Payment FX Indemnity', np.late_payment_fx_indemnity === true ? 'Yes' : 'No'] as FieldDef] : []),
              ...(np.dispute_resolution_days != null ? [['Dispute Resolution Period', `${np.dispute_resolution_days} days`] as FieldDef] : []),
              ...(np.dispute_resolution_clause_ref != null ? [['Dispute Resolution Clause', np.dispute_resolution_clause_ref] as FieldDef] : []),
            ] as FieldDef[]} />
          </CollapsibleSection>
        )
      })()}

      <CollapsibleSection title="Contracts">
        <ProjectTableTab
          data={data.contracts}
          columns={contractColumns}
          emptyMessage="No contracts found"
          entity="contracts"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </CollapsibleSection>

      {contactColumns && (
        <CollapsibleSection title="Contacts">
          <ProjectTableTab
            data={mergedContacts}
            columns={contactColumns}
            emptyMessage="No contacts found"
            entity="contacts"
            onSaved={onSaved}
            editMode={editMode}
            onAdd={onAddContact}
            onRemove={onRemoveContact}
            addLabel="Add Contact"
          />
        </CollapsibleSection>
      )}

    </div>
  )
}
