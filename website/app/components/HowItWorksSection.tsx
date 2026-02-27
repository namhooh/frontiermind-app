import { Upload, Cable, Lightbulb } from "lucide-react";

const steps = [
  {
    number: "01",
    icon: Upload,
    title: "Upload Your Contracts",
    description:
      "Upload your PPA and O&M contracts. Our AI extracts pricing terms, indexation formulas, and compliance obligations in minutes.",
  },
  {
    number: "02",
    icon: Cable,
    title: "Connect Your Data",
    description:
      "Connect inverter monitoring, meter data, and invoicing systems. We integrate with Enphase, SMA, and manual uploads.",
  },
  {
    number: "03",
    icon: Lightbulb,
    title: "Get Insights",
    description:
      "Receive automated compliance checks, invoice verification, and performance reports. Catch discrepancies before they cost you.",
  },
];

export default function HowItWorksSection() {
  return (
    <section className="bg-[#f3f3f5] py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <div className="text-center max-w-3xl mx-auto">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 tracking-tight">
            How It Works
          </h2>
          <p className="mt-4 text-lg text-gray-500">
            Get up and running in three simple steps
          </p>
        </div>

        <div className="mt-16 grid grid-cols-1 lg:grid-cols-3 gap-8 lg:gap-4">
          {steps.map((step, i) => (
            <div key={step.number} className="relative flex flex-col items-center text-center">
              {/* Connector line (desktop only) */}
              {i < steps.length - 1 && (
                <div className="hidden lg:block absolute top-10 left-[calc(50%+40px)] w-[calc(100%-80px)] h-px bg-gray-300" />
              )}

              <div className="relative flex items-center justify-center w-20 h-20 rounded-2xl bg-white shadow-sm border border-gray-200">
                <step.icon size={32} className="text-blue-600" />
                <span className="absolute -top-2 -right-2 w-7 h-7 rounded-full bg-gradient-to-br from-blue-600 to-indigo-700 text-white text-xs font-bold flex items-center justify-center">
                  {step.number}
                </span>
              </div>

              <h3 className="mt-6 text-xl font-semibold text-gray-900">
                {step.title}
              </h3>
              <p className="mt-3 text-gray-500 leading-relaxed max-w-sm">
                {step.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
