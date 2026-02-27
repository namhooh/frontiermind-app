const footerLinks = [
  { label: "About", href: "#" },
  { label: "Product", href: "#" },
  { label: "Contact", href: "mailto:namho@frontiermind.co" },
];

export default function MarketingFooter() {
  return (
    <footer className="bg-[#030213] border-t border-white/10">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex flex-col items-center sm:items-start gap-2">
            <span
              className="text-lg text-white font-bold"
              style={{ fontFamily: "'Libre Baskerville', serif" }}
            >
              FrontierMind
            </span>
            <a
              href="mailto:namho@frontiermind.co"
              className="text-sm text-gray-400 hover:text-white transition-colors"
            >
              namho@frontiermind.co
            </a>
          </div>

          <nav className="flex flex-wrap items-center gap-4 sm:gap-6">
            {footerLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                {link.label}
              </a>
            ))}
          </nav>
        </div>

        <div className="mt-8 pt-6 border-t border-white/10 text-center">
          <p className="text-xs text-gray-500">
            &copy; {new Date().getFullYear()} FrontierMind. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
