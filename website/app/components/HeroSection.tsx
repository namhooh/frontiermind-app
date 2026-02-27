import { ArrowRight, ChevronDown } from "lucide-react";

export default function HeroSection() {
  return (
    <section className="relative min-h-screen overflow-hidden">
      {/* Background image */}
      <img
        src="/solar.jpg"
        alt=""
        className="absolute inset-0 w-full h-full object-cover brightness-100 saturate-[0.7] scale-110"
      />
      {/* Dark overlay for text readability */}
      <div className="absolute inset-0 bg-black/30" />
      {/* Bottom fade gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/40" />

      <div className="relative z-10 mx-auto max-w-6xl px-6 flex flex-col items-center justify-center min-h-screen text-center">
        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white tracking-tight leading-tight" style={{ fontFamily: "'Urbanist', sans-serif" }}>
          AI Copilot for Corporate Energy Projects
        </h1>

        <p className="mt-6 text-lg sm:text-2xl text-white max-w-2xl mx-auto leading-relaxed">
          Automate compliance, settlement, and asset management for your energy portfolios
        </p>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a
            href="mailto:namho@frontiermind.co"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-700 hover:from-blue-500 hover:to-indigo-600 text-white font-semibold px-8 py-3.5 rounded-lg transition-all shadow-lg shadow-blue-900/30"
          >
            Contact Us
            <ArrowRight size={18} />
          </a>

          <a
            href="#value-props"
            className="inline-flex items-center gap-2 text-gray-400 hover:text-white font-medium px-6 py-3.5 transition-colors"
          >
            Learn More
            <ChevronDown size={18} />
          </a>
        </div>
      </div>
    </section>
  );
}
