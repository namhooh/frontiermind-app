import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FrontierMind - AI Copilot for Corporate Energy Projects",
  description:
    "Automate PPA compliance, settlement, and asset management for renewable energy portfolios.",
  openGraph: {
    title: "FrontierMind - AI Copilot for Corporate Energy Projects",
    description:
      "Automate PPA compliance, settlement, and asset management for renewable energy portfolios.",
    type: "website",
    url: "https://frontiermind.co",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Urbanist:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className={`${geistSans.variable} font-sans antialiased bg-white min-h-screen`}
      >
        {children}
      </body>
    </html>
  );
}
