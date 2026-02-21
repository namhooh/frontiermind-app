'use client'

import type { ProjectDashboardResponse } from '@/lib/api/adminClient'
import { CollapsibleSection } from './CollapsibleSection'
import { ProjectTableTab, type Column } from './ProjectTableTab'
import { FieldGrid, type FieldDef } from './shared/FieldGrid'

interface ProjectOverviewTabProps {
  data: ProjectDashboardResponse
  contractColumns: Column[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
}

export function ProjectOverviewTab({ data, contractColumns, projectId, onSaved, editMode }: ProjectOverviewTabProps) {
  const { project, contracts, clauses, lookups } = data
  const pid = project.id as number

  const toOpts = (items: { id: number; code?: string; name: string }[]) =>
    (items ?? []).map((t) => ({ value: t.id, label: t.name }))
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
              ['Contract ID', primaryContract?.external_contract_id, ...(cid != null ? [{ fieldKey: 'external_contract_id', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'text' as const }] : [])],
              ...(cid != null ? [['Contract Name', primaryContract?.name, { fieldKey: 'name', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'text' as const }] as FieldDef] : []),
              ...(cid != null ? [['Contract Type', primaryContract?.contract_type_name, { fieldKey: 'contract_type_id', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'select' as const, options: contractTypeOpts, selectValue: primaryContract?.contract_type_id }] as FieldDef] : []),
              ['Sage ID', project.sage_id, { fieldKey: 'sage_id', entity: 'projects', entityId: pid, type: 'text' }],
              ['Project Name', project.name, { fieldKey: 'name', entity: 'projects', entityId: pid, type: 'text' }],
              ['Country of Operation', project.country, { fieldKey: 'country', entity: 'projects', entityId: pid, type: 'text' }],
              ['Customer Registered Name', primaryContract?.counterparty_registered_name ?? primaryContract?.counterparty_name],
              ['Company Registration Number', primaryContract?.counterparty_registration_number],
              ['Registered Address', primaryContract?.counterparty_registered_address],
              ['Tax PIN/Number', primaryContract?.counterparty_tax_pin],
            ] as FieldDef[]} />
          )
        })()}
      </CollapsibleSection>

      <CollapsibleSection title="Contract Terms">
        {(() => {
          const primaryContract = contracts[0] as Record<string, unknown> | undefined
          const cid = primaryContract?.id as number | undefined
          return (
            <FieldGrid onSaved={onSaved} editMode={editMode} fields={[
              ['COD', project.cod_date, { fieldKey: 'cod_date', entity: 'projects' as const, entityId: pid, type: 'date' as const }],
              ...(cid != null ? [['Contract Term (years)', primaryContract?.contract_term_years, { fieldKey: 'contract_term_years', entity: 'contracts' as const, entityId: cid, projectId: pid, type: 'number' as const }] as FieldDef] : []),
            ] as FieldDef[]} />
          )
        })()}
      </CollapsibleSection>

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

    </div>
  )
}
