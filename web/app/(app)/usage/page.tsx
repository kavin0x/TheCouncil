"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type Entitlements, type Usage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Progress,
  QueryError,
  Skeleton,
} from "@/components/ui";

function formatLimit(value: number | null | undefined): string {
  return value === null || value === undefined ? "Unlimited" : value.toLocaleString();
}

export default function UsagePage() {
  const { getToken } = useAuth();

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
  });
  const usage = useQuery<Usage>({
    queryKey: ["usage"],
    queryFn: () => api.getUsage(getToken),
    refetchInterval: 30_000,
  });

  const sandboxRun = useMutation({
    mutationFn: () =>
      api.createRun(getToken, {
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

  const loadError = ent.error || usage.error;
  const refetchAll = () => {
    void ent.refetch();
    void usage.refetch();
  };
  const isRefetching =
    (ent.isFetching && !ent.isLoading) ||
    (usage.isFetching && !usage.isLoading);

  return (
    <div className="space-y-8">
      {loadError && (
        <QueryError
          message="We couldn&apos;t load usage or feature access. Check your connection and try again."
          onRetry={refetchAll}
          isRetrying={isRefetching}
        />
      )}
      <h1 className="text-2xl font-bold text-white">Usage & Access</h1>

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
              <CardTitle>Feature limits</CardTitle>
            </CardHeader>
            <CardContent>
              {ent.isLoading ? (
                <Skeleton className="h-20 w-full" />
              ) : (
                <dl className="space-y-1.5 text-sm">
                  {[
                    ["Agents / run", formatLimit(ent.data?.limits.max_agents)],
                    ["Rounds / run", formatLimit(ent.data?.limits.max_rounds)],
                    ["Max tokens", formatLimit(ent.data?.limits.max_input_tokens)],
                    ["Saved personas", formatLimit(ent.data?.limits.max_saved_personas)],
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
            <CardTitle>Self-hosted sandbox demo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-zinc-400">
              Launch an isolated sandbox run in this deployment. This is the foundation for CUA-style
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
                Computer-use sandboxing is not enabled for this deployment.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="space-y-4">
        <Card>
          <CardContent className="pt-5">
            <div className="space-y-2">
              <p className="text-sm font-semibold text-white">Open-source deployment</p>
              <p className="text-sm text-zinc-400">
                This instance exposes capability flags instead of paid-plan metadata. Use settings and
                integrations to review the features available in this deployment.
              </p>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
