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
  Skeleton,
} from "@/components/ui";
import { formatRelative, statusColor } from "@/lib/utils";

function useDashboard(token: string) {
  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token),
  });
  const usage = useQuery<Usage>({
    queryKey: ["usage"],
    queryFn: () => api.getUsage(token),
  });
  const runs = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(token),
    select: (data) => data.slice(0, 5),
  });
  return { ent, usage, runs };
}

function tierBadgeVariant(tier: string) {
  return (
    {
      trial: "warning",
      basic: "secondary",
      pro: "default",
      ultra: "success",
      enterprise: "success",
    } as const
  )[tier] ?? "secondary";
}

export default function DashboardPage() {
  const { token } = useAuth();
  const { ent, usage, runs } = useDashboard(token!);

  const runsUsed = usage.data?.runs.used ?? 0;
  const runsLimit = usage.data?.runs.limit ?? 1;
  const pct = Math.min(100, Math.round((runsUsed / runsLimit) * 100));

  return (
    <div className="space-y-6">
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
            <CardTitle>Current plan</CardTitle>
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
                  Manage
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
                  <span className={pct >= 90 ? "text-red-400" : "text-zinc-400"}>
                    {pct}%
                  </span>
                </div>
                <Progress value={pct} />
                {pct >= 90 && (
                  <p className="text-xs text-amber-400">
                    Approaching limit.{" "}
                    <Link href="/usage" className="underline">
                      Upgrade your plan
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
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                      enabled
                        ? "bg-emerald-600/15 text-emerald-300"
                        : "bg-zinc-800 text-zinc-500"
                    }`}
                  >
                    {enabled ? (
                      <Zap className="h-3 w-3" />
                    ) : (
                      <span className="h-3 w-3 rounded-full border border-zinc-600 inline-block" />
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
              <Bot className="mx-auto mb-3 h-8 w-8 text-zinc-600" />
              <p className="text-sm text-zinc-500">No runs yet.</p>
              <Link href="/runs" className="mt-3 inline-block">
                <Button size="sm" variant="secondary" className="gap-2">
                  <Play className="h-3.5 w-3.5" /> Start your first run
                </Button>
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {runs.data?.map((run) => (
                <Link
                  key={run.run_id}
                  href={`/runs/${run.run_id}`}
                  className="flex items-start gap-3 py-3 hover:bg-zinc-800/30 -mx-5 px-5 transition-colors rounded-lg"
                >
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm text-white">{run.question}</p>
                    <p className="text-xs text-zinc-500">{formatRelative(run.created_at)}</p>
                  </div>
                  <span className={`text-xs font-medium ${statusColor(run.status)}`}>
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
