import Link from "next/link";
import { Check, Minus } from "lucide-react";
import { Badge, Button } from "@/components/ui";

interface Tier {
  name: string;
  price: string;
  priceNote?: string;
  description: string;
  cta: string;
  ctaHref: string;
  highlighted?: boolean;
  features: Array<{ label: string; value: string | boolean }>;
}

const tiers: Tier[] = [
  {
    name: "Trial",
    price: "Free",
    priceNote: "14 days",
    description: "Full preview of Pro features. No card required.",
    cta: "Start trial",
    ctaHref: "/login",
    features: [
      { label: "Runs / month", value: "60" },
      { label: "Agents per run", value: "Up to 8" },
      { label: "Rounds per run", value: "Up to 6" },
      { label: "Saved personas", value: "3" },
      { label: "Run history", value: "14 days" },
      { label: "Export", value: true },
      { label: "MCP / IDE plugins", value: true },
      { label: "Custom MCP", value: false },
      { label: "Computer use", value: false },
      { label: "SSO", value: false },
    ],
  },
  {
    name: "Basic",
    price: "$10",
    priceNote: "/ month",
    description: "Light individual usage via web and API.",
    cta: "Get started",
    ctaHref: "/login",
    features: [
      { label: "Runs / month", value: "100" },
      { label: "Agents per run", value: "Up to 6" },
      { label: "Rounds per run", value: "Up to 4" },
      { label: "Saved personas", value: "1" },
      { label: "Run history", value: "7 days" },
      { label: "Export", value: false },
      { label: "MCP / IDE plugins", value: false },
      { label: "Custom MCP", value: false },
      { label: "Computer use", value: false },
      { label: "SSO", value: false },
    ],
  },
  {
    name: "Pro",
    price: "$20",
    priceNote: "/ month",
    description: "Higher limits with IDE integrations and custom MCP.",
    cta: "Get Pro",
    ctaHref: "/login",
    highlighted: true,
    features: [
      { label: "Runs / month", value: "500" },
      { label: "Agents per run", value: "Up to 10" },
      { label: "Rounds per run", value: "Up to 8" },
      { label: "Saved personas", value: "10" },
      { label: "Run history", value: "30 days" },
      { label: "Export", value: true },
      { label: "MCP / IDE plugins", value: true },
      { label: "Custom MCP", value: true },
      { label: "Computer use", value: false },
      { label: "SSO", value: false },
    ],
  },
  {
    name: "Ultra",
    price: "$200",
    priceNote: "/ month",
    description: "Effectively unlimited with sandboxed computer-use.",
    cta: "Get Ultra",
    ctaHref: "/login",
    features: [
      { label: "Runs / month", value: "10 000 (fair use)" },
      { label: "Agents per run", value: "Up to 15" },
      { label: "Rounds per run", value: "Up to 10" },
      { label: "Saved personas", value: "Unlimited" },
      { label: "Run history", value: "180 days" },
      { label: "Export", value: true },
      { label: "MCP / IDE plugins", value: true },
      { label: "Custom MCP", value: true },
      { label: "Computer use", value: true },
      { label: "SSO", value: false },
    ],
  },
  {
    name: "Enterprise",
    price: "$25–$215",
    priceNote: "/ seat / month",
    description: "Contracted seats, SSO, and centralised billing.",
    cta: "Contact us",
    ctaHref: "mailto:hello@thecouncil.ai",
    features: [
      { label: "Runs / month", value: "25 000 (configurable)" },
      { label: "Agents per run", value: "Up to 20" },
      { label: "Rounds per run", value: "Up to 12" },
      { label: "Saved personas", value: "Unlimited" },
      { label: "Run history", value: "365 days" },
      { label: "Export", value: true },
      { label: "MCP / IDE plugins", value: true },
      { label: "Custom MCP", value: true },
      { label: "Computer use", value: true },
      { label: "SSO (SAML/OIDC)", value: true },
    ],
  },
];

function FeatureValue({ value }: { value: string | boolean }) {
  if (typeof value === "boolean") {
    return value ? (
      <Check className="mx-auto h-4 w-4 text-emerald-400" />
    ) : (
      <Minus className="mx-auto h-4 w-4 text-zinc-700" />
    );
  }
  return <span className="text-sm text-zinc-300">{value}</span>;
}

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-[#070b0f] px-4 pb-24">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-zinc-800/60 bg-[#070b0f]/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-600 text-xs font-bold text-white shadow-sm shadow-violet-500/30">
              TC
            </div>
            <span className="text-sm font-semibold text-white">TheCouncil</span>
          </Link>
          <Link href="/login">
            <Button variant="outline" size="sm">Sign in</Button>
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-7xl pt-16">
        <div className="mb-12 text-center">
          <h1 className="mb-3 text-4xl font-bold text-white">Simple, transparent pricing</h1>
          <p className="text-zinc-400">
            Start free for 14 days. Upgrade when you need more.
          </p>
        </div>

        {/* Card grid */}
        <div className="grid gap-4 lg:grid-cols-5">
          {tiers.map((tier) => (
            <div
              key={tier.name}
              className={`flex flex-col rounded-xl border p-5 transition-colors ${
                tier.highlighted
                  ? "border-violet-500/50 bg-violet-950/20 shadow-lg shadow-violet-500/10 ring-1 ring-violet-500/20"
                  : "border-zinc-800 bg-zinc-900/40 hover:border-zinc-700/80"
              }`}
            >
              {tier.highlighted && (
                <div className="mb-3 self-start">
                  <Badge variant="default">Most popular</Badge>
                </div>
              )}
              <h2 className="text-lg font-bold text-white">{tier.name}</h2>
              <div className="mt-2 flex items-baseline gap-1">
                <span className="text-3xl font-extrabold text-white">{tier.price}</span>
                {tier.priceNote && (
                  <span className="text-sm text-zinc-500">{tier.priceNote}</span>
                )}
              </div>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">{tier.description}</p>
              <Link href={tier.ctaHref} className="mt-4">
                <Button
                  className="w-full"
                  variant={tier.highlighted ? "default" : "outline"}
                >
                  {tier.cta}
                </Button>
              </Link>

              <div className="mt-5 space-y-2.5">
                {tier.features.map(({ label, value }) => (
                  <div key={label} className="flex items-start justify-between gap-2">
                    <span className="text-xs text-zinc-500">{label}</span>
                    <span className="text-right">
                      <FeatureValue value={value} />
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Comparison footnote */}
        <p className="mt-10 text-center text-xs text-zinc-600">
          All plans include API access and a 14-day money-back guarantee.
          Enterprise pricing is per seat; contact us for volume discounts.
          &ldquo;Computer use&rdquo; and sandboxed browser features require an Ultra or
          Enterprise plan.
        </p>
      </div>

      {/* Footer */}
      <footer className="mt-20 border-t border-zinc-800/60 py-6">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-zinc-700">
              © {new Date().getFullYear()} TheCouncil
            </span>
            <div className="flex items-center gap-5 text-xs text-zinc-600">
              <Link href="/legal#privacy" className="hover:text-zinc-400 transition-colors">
                Privacy
              </Link>
              <Link href="/legal#tos" className="hover:text-zinc-400 transition-colors">
                Terms
              </Link>
              <Link href="/legal#usage" className="hover:text-zinc-400 transition-colors">
                Usage Limits
              </Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
