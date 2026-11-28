import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { USE_MOCK_API } from "@/lib/api";
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
  title: "TravAI",
  description: "AI travel planner: three budget-checked itineraries from real, sourced prices.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {USE_MOCK_API && (
          <p
            role="note"
            className="bg-amber-200 px-4 py-2 text-center text-sm font-medium text-amber-950 dark:bg-amber-900 dark:text-amber-50"
          >
            Demo data: the backend is mocked, and every price and link on this page is made up.
          </p>
        )}
        <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mx-auto flex max-w-6xl items-center px-4 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              TravAI
            </Link>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-10">{children}</main>
      </body>
    </html>
  );
}
