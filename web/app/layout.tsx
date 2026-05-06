import type { Metadata } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const fontSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "TheCouncil — Multi-agent deliberation engine",
  description:
    "Run structured multi-agent AI debates. Get rigorously stress-tested answers through expert council deliberation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${fontSans.variable} ${fontMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen antialiased" suppressHydrationWarning>
        <Providers>{children}</Providers>
        <div className="border-t border-zinc-900 py-2 text-center">
          <p className="px-4 font-mono text-[10px] text-zinc-700">
            AI-generated outputs are for informational purposes only and do not constitute legal, medical, financial, or other professional advice.
          </p>
        </div>
      </body>
    </html>
  );
}
