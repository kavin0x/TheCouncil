import Link from "next/link";
import { ArrowRight, Bot, Layers, Shield, Zap } from "lucide-react";
import { Button } from "@/components/ui";

const features = [
  {
    icon: Bot,
    title: "Multi-agent debates",
    body: "Your question enters a structured council of AI agents with distinct reasoning styles — devil's advocate, synthesist, empiricist, and more.",
  },
  {
    icon: Layers,
    title: "Richer answers",
    body: "Multiple rounds of structured exchange surface hidden assumptions, flag weak reasoning, and produce answers that hold up under scrutiny.",
  },
  {
    icon: Zap,
    title: "IDE-native (Pro+)",
    body: "Connect your editor via the TheCouncil MCP server. Ask a council question right from Cursor or Claude Desktop without leaving your flow.",
  },
  {
    icon: Shield,
    title: "Configurable personas",
    body: "Shape the council to your domain. Save custom personas (MBTI-derived or hand-crafted) and reuse them across every run.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600 text-white text-xs font-bold">
              TC
            </div>
            <span className="text-sm font-semibold text-white">TheCouncil</span>
          </div>
          <nav className="flex items-center gap-6">
            <Link href="/pricing" className="text-sm text-zinc-400 hover:text-white transition-colors">
              Pricing
            </Link>
            <Link href="/login">
              <Button variant="outline" size="sm">Sign in</Button>
            </Link>
            <Link href="/pricing">
              <Button size="sm">Start free trial</Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto flex max-w-4xl flex-col items-center px-6 py-28 text-center">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-600/10 px-4 py-1.5 text-xs font-medium text-violet-300">
          14-day free trial · No credit card required
        </div>
        <h1 className="mb-6 text-5xl font-bold tracking-tight text-white sm:text-6xl">
          Every question deserves{" "}
          <span className="text-violet-400">a council</span>
        </h1>
        <p className="mb-10 max-w-2xl text-lg text-zinc-400 leading-relaxed">
          TheCouncil runs your question through a structured multi-agent debate.
          Multiple AI personas argue, push back, and synthesise — so you get
          answers that have actually been stress-tested.
        </p>
        <div className="flex items-center gap-4">
          <Link href="/pricing">
            <Button size="lg" className="gap-2">
              Get started free <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link href="/login">
            <Button size="lg" variant="outline">
              Sign in
            </Button>
          </Link>
        </div>
      </section>

      {/* Feature grid */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-24">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {features.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5"
            >
              <div className="mb-3 inline-flex rounded-lg bg-violet-600/15 p-2 text-violet-400">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="mb-1.5 text-sm font-semibold text-white">{title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA banner */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-24">
        <div className="relative overflow-hidden rounded-2xl border border-violet-500/20 bg-gradient-to-br from-violet-900/30 via-zinc-900 to-zinc-900 p-10 text-center">
          <h2 className="mb-3 text-3xl font-bold text-white">
            Start your free 14-day trial
          </h2>
          <p className="mb-8 text-zinc-400">
            No credit card required. Full Pro features for 14 days.
          </p>
          <Link href="/pricing">
            <Button size="lg">Choose a plan</Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-800 py-8 text-center text-xs text-zinc-500">
        <div className="flex items-center justify-center gap-6">
          <Link href="/pricing" className="hover:text-zinc-300 transition-colors">Pricing</Link>
          <Link href="/legal" className="hover:text-zinc-300 transition-colors">Privacy</Link>
          <Link href="/legal" className="hover:text-zinc-300 transition-colors">Terms</Link>
        </div>
        <p className="mt-4">© {new Date().getFullYear()} TheCouncil. All rights reserved.</p>
      </footer>
    </div>
  );
}
