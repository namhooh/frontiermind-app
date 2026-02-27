import { FileCheck, CircleDollarSign, BarChart3 } from "lucide-react";

const cards = [
  {
    icon: FileCheck,
    title: "Contract Compliance",
    description:
      "AI-powered contract parsing extracts key terms, pricing structures, and compliance obligations automatically. Never miss a contractual requirement again.",
  },
  {
    icon: CircleDollarSign,
    title: "Payment Verification",
    description:
      "Automated invoice validation cross-references meter data, contract rates, and indexation formulas to verify every line item on every invoice.",
  },
  {
    icon: BarChart3,
    title: "Asset Management",
    description:
      "Real-time plant performance monitoring tracks generation, availability, and curtailment against contractual guarantees and market benchmarks.",
  },
];

export default function ValuePropSection() {
  return (
    <section id="value-props" className="relative py-16 sm:py-24 lg:py-32 overflow-hidden">
      {/* Background image */}
      <img
        src="/work.jpeg"
        alt=""
        className="absolute inset-0 w-full h-full object-cover brightness-85 saturate-[0.5] scale-110"
      />
      {/* Light overlay for text readability */}
      <div className="absolute inset-0 bg-white/80" />

      <div className="relative z-10 mx-auto max-w-6xl px-4 sm:px-6">
        <div className="text-center max-w-3xl mx-auto">
          <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-gray-900 tracking-tight leading-normal" style={{ fontFamily: "'Urbanist', sans-serif" }}>
            Save time, bring transparency,
            <br />
            and protect your cashflow
          </h2>
          <p className="mt-4 text-lg text-gray-500">
            Purpose-built for corporate energy teams managing PPAs and
            O&M contracts
          </p>
        </div>

        <div className="mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-8">
          {cards.map((card) => (
            <div
              key={card.title}
              className="group rounded-2xl border border-gray-200 bg-white p-6 sm:p-8 hover:shadow-lg hover:border-gray-300 transition-all"
            >
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 text-white">
                <card.icon size={24} />
              </div>
              <h3 className="mt-5 text-lg sm:text-xl font-semibold text-gray-900">
                {card.title}
              </h3>
              <p className="mt-3 text-gray-500 leading-relaxed">
                {card.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
