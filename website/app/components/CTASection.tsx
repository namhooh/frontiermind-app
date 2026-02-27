import { ArrowRight } from "lucide-react";

export default function CTASection() {
  return (
    <section className="bg-[#030213] py-24 sm:py-32">
      <div className="mx-auto max-w-4xl px-6 text-center">
        <h2 className="text-3xl sm:text-4xl font-bold text-white tracking-tight">
          Ready to automate your energy contract compliance?
        </h2>
        <p className="mt-4 text-lg text-gray-400 max-w-2xl mx-auto">
          Join energy teams that are saving hours on manual contract reviews and
          catching invoice discrepancies automatically.
        </p>
        <div className="mt-10">
          <a
            href="mailto:namho@frontiermind.co"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-700 hover:from-blue-500 hover:to-indigo-600 text-white font-semibold px-8 py-3.5 rounded-lg transition-all shadow-lg shadow-blue-900/30"
          >
            Contact Us
            <ArrowRight size={18} />
          </a>
        </div>
      </div>
    </section>
  );
}
