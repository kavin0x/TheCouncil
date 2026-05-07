"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, Play, Zap } from "lucide-react";
import { api, type Entitlements, type Run, type Usage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Progress,
  QueryError,
  Skeleton,
} from "@/components/ui";
import { formatRelative, statusColor } from "@/lib/utils";

function useDashboard(getToken: () => Promise<string | null>) {
  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
  });
  const usage = useQuery<Usage>({
    queryKey: ["usage"],
    queryFn: () => api.getUsage(getToken),
  });
  const runs = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(getToken),
    select: (data) => data.slice(0, 5),
  });
  return { ent, usage, runs };
}

function tierBadgeVariant(tier: string) {
  return (
    {
      "open-source": "secondary",
      trial: "warning",
      basic: "secondary",
      pro: "default",
      ultra: "success",
      enterprise: "success",
    } as const
  )[tier] ?? "secondary";
}

export default function DashboardPage() {
  const { getToken } = useAuth();
  const { ent, usage, runs } = useDashboard(getToken);

  const runsUsed = usage.data?.runs.used ?? 0;
  const runsLimit = usage.data?.runs.limit ?? 1;
  const pct = Math.min(100, Math.round((runsUsed / runsLimit) * 100));

  const loadError = ent.error || usage.error || runs.error;
  const refetchAll = () => {
    void ent.refetch();
    void usage.refetch();
    void runs.refetch();
  };
  const isRefetching =
    (ent.isFetching && !ent.isLoading) ||
    (usage.isFetching && !usage.isLoading) ||
    (runs.isFetching && !runs.isLoading);

  return (
    <div className="space-y-6">
      {loadError && (
        <QueryError
          message="We couldn&apos;t load your dashboard. Check your connection and try again."
          onRetry={refetchAll}
          isRetrying={isRefetching}
        />
      )}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <Link href="/runs">
          <Button size="sm" className="gap-2">
            <Play className="h-3.5 w-3.5" /> New run
          </Button>
        </Link>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {/* Tier card */}
        <Card>
          <CardHeader>
            <CardTitle>Current access</CardTitle>
          </CardHeader>
          <CardContent>
            {ent.isLoading ? (
              <Skeleton className="h-7 w-24" />
            ) : (
              <div className="flex items-center gap-2">
                <Badge variant={tierBadgeVariant(ent.data?.tier ?? "")}>
                  {ent.data?.display_name}
                </Badge>
                <Link href="/usage" className="text-xs text-violet-400 hover:underline">
                  View details
                </Link>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Usage card */}
        <Card className="sm:col-span-2">
          <CardHeader>
            <CardTitle>Monthly runs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {usage.isLoading ? (
              <Skeleton className="h-8 w-full" />
            ) : (
              <>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-zinc-400">
                    {runsUsed} of {runsLimit} used
                  </span>
                  <span className={pct >= 90 ? "text-red-400" : "text-zinc-500"}>
                    {pct}%
                  </span>
                </div>
                <Progress value={pct} />
                {pct >= 90 && (
                  <p className="text-xs text-amber-400">
                    Approaching your current limit. {" "}
                    <Link href="/usage" className="underline">
                      Review access details
                    </Link>
                    .
                  </p>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Feature flags */}
      {ent.data && (
        <Card>
          <CardHeader>
            <CardTitle>Features</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {[
                { key: "api_access", label: "API" },
                { key: "mcp_enabled", label: "MCP" },
                { key: "ide_plugins_enabled", label: "IDE plugins" },
                { key: "custom_mcp_enabled", label: "Custom MCP" },
                { key: "computer_use_enabled", label: "Computer use" },
                { key: "sso_enabled", label: "SSO" },
              ].map(({ key, label }) => {
                const enabled = ent.data!.features[key as keyof typeof ent.data.features];
                return (
                  <div
                    key={key}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium ring-1 ${
                      enabled
                        ? "bg-emerald-600/10 text-emerald-300 ring-emerald-500/20"
                        : "bg-zinc-800/80 text-zinc-600 ring-zinc-700/50"
                    }`}
                  >
                    {enabled ? (
                      <Zap className="h-3 w-3 shrink-0" />
                    ) : (
                      <span className="inline-block h-2.5 w-2.5 rounded-full border border-zinc-700" />
                    )}
                    {label}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent runs */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Recent runs</CardTitle>
            <Link
              href="/runs"
              className="flex items-center gap-1 text-xs text-violet-400 hover:underline"
            >
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {runs.isLoading ? (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : runs.data?.length === 0 ? (
            <div className="py-8 text-center">
              <Bot className="mx-auto mb-3 h-8 w-8 text-zinc-700 opacity-60" />
              <p className="text-sm text-zinc-500">No runs yet.</p>
              <Link href="/runs" className="mt-3 inline-block">
                <Button size="sm" variant="secondary" className="gap-2">
                  <Play className="h-3.5 w-3.5" /> Start your first run
                </Button>
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-zinc-800/60">
              {runs.data?.map((run) => (
                <Link
                  key={run.run_id}
                  href={`/runs/${run.run_id}`}
                  className="group -mx-5 flex items-start gap-3 rounded-lg px-5 py-3 transition-colors hover:bg-zinc-800/30"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-white group-hover:text-violet-200 transition-colors">{run.question}</p>
                    <p className="text-xs text-zinc-600">{formatRelative(run.created_at)}</p>
                  </div>
                  <span className={`shrink-0 text-xs font-medium ${statusColor(run.status)}`}>
                    {run.status}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
