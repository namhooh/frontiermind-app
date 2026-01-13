import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Frontier Mind - Contract Compliance",
  description: "Energy contract compliance system with automated parsing and rules engine",
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
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Space+Mono:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <nav className="border-b-2 border-stone-900 p-4 bg-white">
          <div className="max-w-6xl mx-auto flex gap-6">
            <Link
              href="/"
              className="text-stone-900 hover:text-emerald-500 transition-colors duration-300"
            >
              Dashboard
            </Link>
            <Link
              href="/contracts/upload"
              className="text-stone-900 hover:text-emerald-500 transition-colors duration-300"
            >
              Upload Contract
            </Link>
            <Link
              href="/test-queries"
              className="text-stone-900 hover:text-emerald-500 transition-colors duration-300"
            >
              Test Queries
            </Link>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
