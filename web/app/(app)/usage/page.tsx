"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, ExternalLink } from "lucide-react";
import { api, type Billing, type Entitlements, type Usage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Progress,
  Skeleton,
} from "@/components/ui";

const UPGRADE_TIERS = [
  {
    name: "Basic",
    value: "basic",
    price: "$10",
    perks: ["100 runs/mo", "1 persona", "Web & API"],
  },
  {
    name: "Pro",
    value: "pro",
    price: "$20",
    perks: ["500 runs/mo", "10 personas", "MCP + IDE plugins"],
    popular: true,
  },
  {
    name: "Ultra",
    value: "ultra",
    price: "$200",
    perks: ["10k runs/mo", "Unlimited personas", "Computer use"],
  },
];

function statusBadge(status: string) {
  const v = status === "active" ? "success" : status === "trialing" ? "warning" : "danger";
  return <Badge variant={v}>{status}</Badge>;
}

function validateStripeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return ["stripe.com", "checkout.stripe.com", "billing.stripe.com"].some(
      (domain) =>
        parsed.hostname === domain || parsed.hostname.endsWith("." + domain)
    );
  } catch {
    return false;
  }
}

export default function UsagePage() {
  const { token } = useAuth();

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
  });
  const usage = useQuery<Usage>({
    queryKey: ["usage"],
    queryFn: () => api.getUsage(token!),
    refetchInterval: 30_000,
  });
  const billing = useQuery<Billing>({
    queryKey: ["billing"],
    queryFn: () => api.getBilling(token!),
  });

  const portal = useMutation({
    mutationFn: () => api.createPortal(token!, window.location.href),
    onSuccess: ({ url }) => {
      if (validateStripeUrl(url)) {
        window.location.assign(url);
      } else {
        console.error("Invalid redirect URL from portal API");
      }
    },
  });

  const checkout = useMutation({
    mutationFn: (tier: string) =>
      api.createCheckout(token!, {
        tier,
        success_url: `${window.location.origin}/dashboard`,
        cancel_url: window.location.href,
      }),
    onSuccess: ({ url }) => {
      if (validateStripeUrl(url)) {
        window.location.assign(url);
      } else {
        console.error("Invalid redirect URL from checkout API");
      }
    },
  });

  const sandboxRun = useMutation({
    mutationFn: () =>
      api.createRun(token!, {
        question: "Sandbox demo: verify environment and return a readiness message.",
        config: {
          run_kind: "sandbox",
          sandbox_cmd: "python -c \"print('TheCouncil sandbox ready')\"",
          sandbox_timeout_s: 60,
        },
      }),
  });

  const runsUsed = usage.data?.runs.used ?? 0;
  const runsLimit = usage.data?.runs.limit ?? 1;
  const pct = Math.min(100, Math.round((runsUsed / runsLimit) * 100));

  const computerUseEnabled = !!ent.data?.features.computer_use_enabled;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-white">Usage & Billing</h1>

      {/* Usage section */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-600">Current usage</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Runs this month</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {usage.isLoading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <>
                  <div className="flex justify-between text-sm">
                    <span className="text-zinc-400">{runsUsed} used</span>
                    <span className="text-zinc-500">{runsLimit} limit</span>
                  </div>
                  <Progress value={pct} />
                  {pct >= 90 && (
                    <p className="text-xs text-amber-400">
                      You&apos;re at {pct}% of your monthly limit.
                    </p>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Plan limits</CardTitle>
            </CardHeader>
            <CardContent>
              {ent.isLoading ? (
                <Skeleton className="h-20 w-full" />
              ) : (
                <dl className="space-y-1.5 text-sm">
                  {[
                    ["Agents / run", ent.data?.limits.max_agents],
                    ["Rounds / run", ent.data?.limits.max_rounds],
                    ["Max tokens", ent.data?.limits.max_input_tokens?.toLocaleString()],
                    [
                      "Saved personas",
                      ent.data?.limits.max_saved_personas ?? "Unlimited",
                    ],
                  ].map(([label, val]) => (
                    <div key={String(label)} className="flex justify-between">
                      <dt className="text-zinc-500">{label}</dt>
                      <dd className="text-zinc-200">{String(val)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Ultra sandbox demo */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-600">Computer-use sandbox</h2>
        <Card>
          <CardHeader>
            <CardTitle>Ultra sandbox demo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-zinc-400">
              Launch an isolated sandbox run (Ultra/Enterprise only). This is the foundation for CUA-style
              computer-use workflows.
            </p>
            {computerUseEnabled ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  onClick={() => sandboxRun.mutate()}
                  disabled={sandboxRun.isPending}
                >
                  {sandboxRun.isPending ? "Starting…" : "Run sandbox demo"}
                </Button>
                {sandboxRun.data?.run_id && (
                  <Link
                    href={`/runs/${sandboxRun.data.run_id}`}
                    className="text-sm text-violet-400 hover:underline"
                  >
                    View run
                  </Link>
                )}
              </div>
            ) : (
              <p className="text-sm text-zinc-600">
                Upgrade to Ultra to enable sandboxed computer-use features.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Billing section */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-600">Billing</h2>
        <Card>
          <CardContent className="pt-5">
            {billing.isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">
                      {billing.data?.display_name} plan
                    </span>
                    {billing.data?.status && statusBadge(billing.data.status)}
                  </div>
                  <p className="text-sm text-zinc-400">
                    ${billing.data?.price_usd_monthly}/month
                  </p>
                  {billing.data?.trial_end && (
                    <p className="text-xs text-amber-400">
                      Trial ends{" "}
                      {new Date(billing.data.trial_end * 1000).toLocaleDateString()}
                    </p>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => portal.mutate()}
                  disabled={portal.isPending || !billing.data?.stripe_customer_id}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {portal.isPending ? "Opening…" : "Manage subscription"}
                </Button>
              </div>
            )}
            {!billing.data?.stripe_customer_id && !billing.isLoading && (
              <p className="mt-3 text-xs text-zinc-600">
                No active subscription — choose a plan below.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Upgrade CTAs */}
        <div className="grid gap-4 sm:grid-cols-3">
          {UPGRADE_TIERS.map((tier) => {
            const isCurrent = ent.data?.tier === tier.value;
            return (
              <Card
                key={tier.value}
                className={
                  tier.popular
                    ? "border-violet-500/50 shadow-md shadow-violet-500/10 ring-1 ring-violet-500/20"
                    : ""
                }
              >
                <CardContent className="flex flex-col gap-3 pt-5">
                  {tier.popular && (
                    <Badge variant="default" className="self-start">Most popular</Badge>
                  )}
                  <div>
                    <p className="text-base font-bold text-white">{tier.name}</p>
                    <p className="text-lg font-extrabold text-white">
                      {tier.price}
                      <span className="text-xs font-normal text-zinc-500">/mo</span>
                    </p>
                  </div>
                  <ul className="space-y-1.5 text-xs text-zinc-400">
                    {tier.perks.map((p) => (
                      <li key={p} className="flex items-center gap-1.5">
                        <Check className="h-3 w-3 shrink-0 text-emerald-400" />
                        {p}
                      </li>
                    ))}
                  </ul>
                  <Button
                    variant={isCurrent ? "secondary" : tier.popular ? "default" : "outline"}
                    size="sm"
                    disabled={isCurrent || checkout.isPending}
                    onClick={() => !isCurrent && checkout.mutate(tier.value)}
                    className="mt-auto"
                  >
                    {isCurrent ? "Current plan" : `Upgrade to ${tier.name}`}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>

        <p className="text-center text-xs text-zinc-600">
          Enterprise pricing is per seat. Contact{" "}
          <a href="mailto:sales@thecouncil.ai" className="text-violet-400 hover:underline">
            sales@thecouncil.ai
          </a>{" "}
          for a quote.
        </p>
      </section>
    </div>
  );
}
