// app/page.tsx

import Link from 'next/link';

type EntityGroup = {
  id: number;
  name: string;
  tableCount: number;
  tables: string[];
  description: string;
  accentColor: string;
};

const entityGroups: EntityGroup[] = [
  {
    id: 1,
    name: "Organization & Access",
    tableCount: 2,
    tables: ["organization", "role"],
    description: "Multi-tenant foundation with user roles scoped to organizations",
    accentColor: "bg-purple-400"
  },
  {
    id: 2,
    name: "Project Management",
    tableCount: 3,
    tables: ["project", "counterparty", "counterparty_type"],
    description: "Renewable energy projects linked to external parties and partners",
    accentColor: "bg-amber-400"
  },
  {
    id: 3,
    name: "Contract Management",
    tableCount: 9,
    tables: ["contract", "clause", "clause_type", "clause_category", "clause_tariff"],
    description: "PPAs, O&M contracts, individual terms, obligations, and pricing",
    accentColor: "bg-emerald-400"
  },
  {
    id: 4,
    name: "Assets & Monitoring",
    tableCount: 8,
    tables: ["asset", "vendor", "meter", "meter_reading", "meter_aggregate"],
    description: "Physical equipment, measurement devices, and time-series monitoring",
    accentColor: "bg-blue-400"
  },
  {
    id: 5,
    name: "Event & Fault Management",
    tableCount: 7,
    tables: ["event", "fault", "default_event", "severity", "data_source"],
    description: "Operational incidents, equipment failures, and contract breaches",
    accentColor: "bg-red-400"
  },
  {
    id: 6,
    name: "Financial & Billing",
    tableCount: 12,
    tables: ["invoice_header", "invoice_line_item", "rule_output", "billing_period"],
    description: "Generated, expected, and received invoices with reconciliation",
    accentColor: "bg-green-400"
  },
  {
    id: 7,
    name: "Notifications & Alerts",
    tableCount: 2,
    tables: ["notification", "notification_type"],
    description: "System alerts for breaches, invoice readiness, and payment reminders",
    accentColor: "bg-yellow-400"
  },
  {
    id: 8,
    name: "External Data Sources",
    tableCount: 10,
    tables: ["grid_event", "weather_data", "market_price", "regulatory_fee"],
    description: "Grid intelligence, weather metrics, market pricing, and compliance data",
    accentColor: "bg-cyan-400"
  },
  {
    id: 9,
    name: "System Configuration",
    tableCount: 5,
    tables: ["update_frequency", "currency", "grid_operator", "contractor_report"],
    description: "System settings, reference data, and reporting metadata",
    accentColor: "bg-stone-400"
  }
];

function EntityGroupCard({ group, index }: { group: EntityGroup; index: number }) {
  return (
    <article
      className="entity-card group relative bg-white border-2 border-stone-900 p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]"
      style={{
        animationDelay: `${index * 50}ms`,
      }}
    >
      {/* Corner accent */}
      <div className={`absolute top-0 right-0 w-12 h-12 ${group.accentColor} -translate-y-2 translate-x-2 -z-10 transition-transform duration-300 group-hover:translate-x-3 group-hover:-translate-y-3`} />

      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <span className={`px-2 py-1 text-xs font-mono font-bold border-2 border-stone-900 ${group.accentColor} text-stone-900`}>
              {group.tableCount} TABLES
            </span>
          </div>
          <h3 className="text-2xl font-serif font-bold text-stone-900 leading-tight mb-2">
            {group.name}
          </h3>
        </div>
      </div>

      <p className="text-stone-600 text-sm leading-relaxed mb-3">
        {group.description}
      </p>

      <div className="pt-3 border-t border-stone-200">
        <p className="text-xs font-mono text-stone-500 leading-relaxed">
          {group.tables.slice(0, 4).join(", ")}
          {group.tables.length > 4 && `, +${group.tables.length - 4} more`}
        </p>
      </div>
    </article>
  );
}

export default function Home() {
  const totalTables = entityGroups.reduce((sum, group) => sum + group.tableCount, 0);

  return (
    <div className="min-h-screen bg-stone-50">
      <div className="mx-auto max-w-7xl px-6 py-16">
        {/* Hero Section */}
        <header className="mb-20">
          <div className="flex items-end gap-6 mb-6">
            <h1 className="text-8xl font-serif font-black text-stone-900 leading-none">
              Frontier Mind
            </h1>
          </div>
          <div className="h-2 w-48 bg-emerald-400 mb-8" />

          <div className="max-w-3xl space-y-4">
            <p className="text-2xl text-stone-700 leading-relaxed">
              Contract Compliance & Invoicing Engine for renewable energy projects.
            </p>
            <p className="text-lg text-stone-600 leading-relaxed">
              Automated monitoring of Power Purchase Agreements (PPAs) and O&M contracts
              with performance tracking, breach detection, financial calculations, and billing reconciliation.
            </p>
          </div>

          <div className="flex gap-6 mt-8">
            <div className="border-2 border-stone-900 bg-white p-4">
              <div className="text-4xl font-serif font-black text-emerald-500">{totalTables}</div>
              <div className="text-sm font-mono text-stone-600 uppercase tracking-wider">Tables</div>
            </div>
            <div className="border-2 border-stone-900 bg-white p-4">
              <div className="text-4xl font-serif font-black text-emerald-500">{entityGroups.length}</div>
              <div className="text-sm font-mono text-stone-600 uppercase tracking-wider">Entity Groups</div>
            </div>
          </div>
        </header>

        {/* Database Architecture Section */}
        <section className="mb-20">
          <header className="mb-12">
            <h2 className="text-5xl font-serif font-black text-stone-900 mb-4">
              Database Architecture
            </h2>
            <div className="h-1 w-32 bg-amber-400 mb-4" />
            <p className="text-lg text-stone-600 max-w-3xl">
              The system is organized into {entityGroups.length} functional entity groups covering
              the full lifecycle from project setup to financial reconciliation.
            </p>
          </header>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {entityGroups.map((group, index) => (
              <EntityGroupCard key={group.id} group={group} index={index} />
            ))}
          </div>
        </section>

        {/* Call to Action Section */}
        <section className="text-center py-16">
          <div className="inline-block border-4 border-stone-900 bg-white p-12 relative">
            {/* Decorative corner blocks */}
            <div className="absolute -top-3 -left-3 w-8 h-8 bg-emerald-400" />
            <div className="absolute -top-3 -right-3 w-8 h-8 bg-amber-400" />
            <div className="absolute -bottom-3 -left-3 w-8 h-8 bg-blue-400" />
            <div className="absolute -bottom-3 -right-3 w-8 h-8 bg-red-400" />

            <h3 className="text-4xl font-serif font-black text-stone-900 mb-4">
              Ready to Test?
            </h3>
            <p className="text-lg text-stone-600 mb-8 max-w-2xl mx-auto">
              Execute 12 end-to-end test queries to verify the complete system from
              physical events to financial impact.
            </p>

            <Link
              href="/test-queries"
              className="inline-block px-8 py-4 bg-emerald-500 text-white font-mono text-lg font-bold border-4 border-stone-900 hover:bg-emerald-600 transition-all duration-200 hover:-translate-y-1 hover:shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]"
            >
              RUN TEST QUERIES →
            </Link>
          </div>
        </section>

        {/* Data Flow Summary */}
        <section className="mt-20 border-t-2 border-stone-300 pt-16">
          <h3 className="text-3xl font-serif font-black text-stone-900 mb-6">
            Core Business Processes
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              "Contract Monitoring: Track compliance with PPA and O&M requirements",
              "Performance Tracking: Monitor asset performance against contractual guarantees",
              "Breach Detection: Identify when performance falls below thresholds",
              "Financial Calculation: Auto-calculate liquidated damages or bonuses",
              "Billing Management: Generate, receive, and reconcile invoices",
              "Notification: Alert stakeholders to breaches and payment due dates"
            ].map((process, idx) => (
              <div key={idx} className="flex items-start gap-3 p-4 border-2 border-stone-900 bg-white">
                <div className="mt-1 w-2 h-2 bg-emerald-500 flex-shrink-0" />
                <p className="text-sm text-stone-700 leading-relaxed">{process}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
