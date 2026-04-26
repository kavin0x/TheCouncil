import Link from "next/link";
import { ArrowRight, Terminal, Cpu, Shield, Network } from "lucide-react";
import { Button } from "@/components/ui";

const capabilities = [
  {
    icon: Cpu,
    label: "Multi-agent deliberation",
    desc: "N agents with distinct reasoning styles debate in structured rounds — devil's advocate, synthesist, empiricist, and more.",
  },
  {
    icon: Network,
    label: "IDE-native via MCP",
    desc: "Expose a council debate as a tool in Cursor, Claude Desktop, or any MCP-compatible client. Query it without leaving your flow.",
  },
  {
    icon: Shield,
    label: "Configurable personas",
    desc: "Compose councils from MBTI-derived or hand-crafted personas. Save them, version them, reuse across every run.",
  },
  {
    icon: Terminal,
    label: "API-first",
    desc: "Full REST API with bearer-token auth. Pipe questions in, stream results out. Integrates with any toolchain.",
  },
];

const DEMO_LINES = [
  { role: "sys",     text: "council.run  q='Should we adopt a monorepo?'  agents=5  rounds=3" },
  { role: "agent",   text: "[INTJ] Risk: coupling between teams increases blast radius of CI failures." },
  { role: "agent",   text: "[ENTP] Counter: shared tooling amortises cross-repo refactors. Data from Google/Meta support this." },
  { role: "agent",   text: "[INFJ] Second-order: culture drift accelerates when ownership boundaries blur." },
  { role: "agent",   text: "[ENTJ] Synthesis: adopt monorepo with explicit ownership CODEOWNERS + per-pkg CI isolation." },
  { role: "result",  text: "✓  Consensus reached in round 2 of 3  ·  4.2 s" },
];

function TerminalDemo() {
  return (
    <div className="w-full overflow-hidden rounded-xl border border-zinc-800 bg-[#0a0d12] shadow-2xl shadow-black/50">
      {/* window chrome */}
      <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
        <span className="ml-3 text-xs text-zinc-600 font-mono">council — bash</span>
      </div>
      <div className="space-y-1.5 p-5">
        {DEMO_LINES.map((line, i) => (
          <div key={i} className="flex gap-3 font-mono text-xs leading-relaxed">
            <span className={
              line.role === "sys"    ? "shrink-0 text-cyan-400 select-none" :
              line.role === "result" ? "shrink-0 text-emerald-400 select-none" :
                                      "shrink-0 text-zinc-600 select-none"
            }>
              {line.role === "sys"    ? "❯" :
               line.role === "result" ? "  " :
                                        "  "}
            </span>
            <span className={
              line.role === "sys"    ? "text-zinc-200" :
              line.role === "result" ? "text-emerald-300" :
                                      "text-zinc-400"
            }>
              {line.text}
            </span>
          </div>
        ))}
        <div className="flex gap-3 font-mono text-xs">
          <span className="text-cyan-400">❯</span>
          <span className="text-zinc-200">
            <span className="inline-block h-3.5 w-0.5 animate-pulse bg-cyan-400 align-middle" />
          </span>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  return (
    <div className="relative flex min-h-screen flex-col bg-[#070b0f]">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-zinc-800/50 bg-[#070b0f]/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-violet-600 font-mono text-[10px] font-bold text-white shadow-sm shadow-violet-500/30">
              TC
            </div>
            <span className="text-sm font-semibold tracking-tight text-white">
              TheCouncil
            </span>
            <span className="hidden rounded-md border border-violet-500/30 bg-violet-600/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-400 sm:block">
              BETA
            </span>
          </div>
          <nav className="flex items-center gap-5">
            <Link
              href="/pricing"
              className="text-xs text-zinc-500 hover:text-zinc-200 transition-colors"
            >
              Pricing
            </Link>
            <Link
              href="https://github.com"
              className="text-xs text-zinc-500 hover:text-zinc-200 transition-colors"
              target="_blank"
              rel="noopener"
            >
              Docs
            </Link>
            <Link href="/login">
              <Button variant="outline" size="sm">
                Sign in
              </Button>
            </Link>
            <Link href="/pricing">
              <Button size="sm">
                Get access
              </Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="relative mx-auto w-full max-w-6xl px-6 py-20">
        {/* Subtle radial glow behind headline */}
        <div
          className="pointer-events-none absolute left-0 top-0 h-[500px] w-[500px] opacity-20"
          style={{
            background: "radial-gradient(ellipse at 20% 40%, rgba(139,92,246,0.3) 0%, transparent 60%)",
          }}
        />
        <div className="relative grid gap-12 lg:grid-cols-2 lg:items-center">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-md border border-zinc-700/60 bg-zinc-900/50 px-3 py-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              <span className="font-mono text-[11px] text-zinc-400">
                Multi-agent deliberation engine
              </span>
            </div>

            <h1 className="mb-5 text-4xl font-bold leading-[1.12] tracking-tight text-white sm:text-5xl">
              Your question,
              <br />
              <span className="text-violet-400">Multiple (configurable) experts</span>,
              <br />
              one rigorous answer.
            </h1>

            <p className="mb-8 max-w-lg text-base leading-relaxed text-zinc-400">
              TheCouncil routes your question through a structured debate between
              AI agents with distinct reasoning profiles, configurable personas, and customizable tool calling capabilities.
              They argue, push back, and synthesise — so you get answers that have been stress-tested,
              not just generated.
            </p>

            <div className="flex items-center gap-3">
              <Link href="/pricing">
                <Button size="lg" className="gap-2">
                  Start free trial <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
              <Link href="/login">
                <Button size="lg" variant="outline">
                  Sign in
                </Button>
              </Link>
            </div>

            <div className="mt-8 flex items-center gap-6 text-xs text-zinc-600">
              <span>14-day trial · No card required</span>
              <span>·</span>
              <span>REST API + MCP server</span>
              <span>·</span>
              <span>Configurable personas</span>
            </div>
          </div>

          <div className="lg:pl-4">
            <TerminalDemo />
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-20">
        <div className="mb-8 flex items-center gap-3">
          <div className="h-px flex-1 bg-zinc-800" />
          <span className="font-mono text-xs uppercase tracking-widest text-zinc-600">
            Capabilities
          </span>
          <div className="h-px flex-1 bg-zinc-800" />
        </div>

        <div className="grid gap-px overflow-hidden rounded-xl border border-zinc-800 sm:grid-cols-2">
          {capabilities.map(({ icon: Icon, label, desc }) => (
            <div
              key={label}
              className="group bg-zinc-900/40 p-6 transition-colors hover:bg-zinc-900/70"
            >
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-800 transition-colors group-hover:bg-violet-600/15">
                  <Icon className="h-4 w-4 text-zinc-400 transition-colors group-hover:text-violet-400" />
                </div>
                <span className="text-sm font-semibold text-white">{label}</span>
              </div>
              <p className="text-sm leading-relaxed text-zinc-500">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-24">
        <div className="rounded-xl border border-zinc-800 bg-gradient-to-b from-violet-950/10 to-zinc-900/20 p-10 text-center">
          <p className="mb-2 font-mono text-xs uppercase tracking-widest text-zinc-600">
            Get started
          </p>
          <h2 className="mb-3 text-2xl font-bold text-white">
            14-day free trial. Full Pro features.
          </h2>
          <p className="mb-8 text-sm text-zinc-500">
            No credit card required. Cancel any time.
          </p>
          <Link href="/pricing">
            <Button size="lg">
              Choose a plan
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="mt-auto border-t border-zinc-800/60 py-6">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-zinc-700">
              © {new Date().getFullYear()} TheCouncil LLC
            </span>
            <div className="flex items-center gap-5 text-xs text-zinc-600">
              <Link href="/pricing" className="hover:text-zinc-400 transition-colors">
                Pricing
              </Link>
              <Link href="/legal#privacy" className="hover:text-zinc-400 transition-colors">
                Privacy
              </Link>
              <Link href="/legal#tos" className="hover:text-zinc-400 transition-colors">
                Terms
              </Link>
            </div>
          </div>
          <p className="mt-3 font-mono text-[10px] text-zinc-700">
            AI-generated outputs are for informational purposes only and do not constitute legal, medical, financial, or other professional advice.
            TheCouncil LLC makes no warranties as to accuracy. By using the service you agree to our{" "}
            <Link href="/legal#tos" className="underline underline-offset-2 hover:text-zinc-500 transition-colors">Terms of Service</Link>.
          </p>
        </div>
      </footer>
    </div>
  );
}
