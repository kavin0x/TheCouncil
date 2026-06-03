"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Bot, Download } from "lucide-react";
import { api, type Entitlements, type Run } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { formatRelative } from "@/lib/utils";

function runBadgeVariant(status: string) {
  return (
    {
      pending: "warning",
      running: "default",
      completed: "success",
      failed: "danger",
    } as const
  )[status] ?? "secondary";
}

export default function RunsPage() {
  const { getToken } = useAuth();
  const runs = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(getToken),
    refetchInterval: 5000,
  });
  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
  });

  const exportEnabled = ent.data?.features ? true : false;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Runs</h1>
        <Link href="/personas">
          <Button size="sm" variant="outline" className="gap-1.5">
            Configure council →
          </Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>All runs</CardTitle>
            <div className="flex items-center gap-1.5 text-xs text-zinc-600">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500/60" />
              Auto-refreshes every 5s
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {runs.isLoading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : runs.data?.length === 0 ? (
            <div className="py-10 text-center">
              <Bot className="mx-auto mb-3 h-8 w-8 text-zinc-700 opacity-60" />
              <p className="mb-1 text-sm text-zinc-400">No runs yet.</p>
              <p className="mb-4 text-xs text-zinc-600">
                Select your agents and configure your council on the Personas page, then start a run from there.
              </p>
              <Link href="/personas">
                <Button size="sm" variant="outline">Go to Personas</Button>
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-zinc-800/60">
              {runs.data?.map((run) => (
                <div
                  key={run.run_id}
                  className="group flex items-start gap-3 py-3.5"
                >
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/runs/${run.run_id}`}
                      className="text-sm text-white transition-colors hover:text-violet-300 line-clamp-2"
                    >
                      {run.question}
                    </Link>
                    <p className="mt-0.5 text-xs text-zinc-600">
                      {formatRelative(run.created_at)} · <span className="font-mono">{run.run_id.slice(0, 8)}</span>
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge variant={runBadgeVariant(run.status)}>{run.status}</Badge>
                    {run.status === "completed" && (
                      exportEnabled ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => {
                            const blob = new Blob([JSON.stringify(run, null, 2)], {
                              type: "application/json",
                            });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `run-${run.run_id}.json`;
                            a.click();
                            URL.revokeObjectURL(url);
                          }}
                          title="Export run"
                        >
                          <Download className="h-3.5 w-3.5" />
                        </Button>
                      ) : (
                        <Button size="icon" variant="ghost" disabled title="Export not available">
                          <Download className="h-3.5 w-3.5 opacity-30" />
                        </Button>
                      )
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
