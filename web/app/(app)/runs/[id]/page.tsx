"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download } from "lucide-react";
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
import { formatDate } from "@/lib/utils";

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

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { token } = useAuth();

  const run = useQuery<Run>({
    queryKey: ["run", id],
    queryFn: () => api.getRun(token!, id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "pending" || s === "running" ? 2000 : false;
    },
  });

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    staleTime: Infinity,
  });

  const canExport = ent.data?.features ? true : false;

  function exportRun() {
    if (!run.data) return;
    const blob = new Blob([JSON.stringify(run.data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `run-${id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (run.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (run.error || !run.data) {
    return (
      <div className="text-center py-16">
        <p className="mb-4 text-zinc-400">Run not found or you don&apos;t have access.</p>
        <Link href="/runs">
          <Button variant="outline">Back to runs</Button>
        </Link>
      </div>
    );
  }

  const r = run.data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Link href="/runs">
          <Button size="icon" variant="ghost">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-white break-words">{r.question}</h1>
          <p className="mt-1 text-xs text-zinc-500">ID: {r.run_id}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Badge variant={runBadgeVariant(r.status)}>{r.status}</Badge>
          {r.status === "completed" && canExport && (
            <Button size="sm" variant="outline" onClick={exportRun} className="gap-2">
              <Download className="h-3.5 w-3.5" /> Export
            </Button>
          )}
          {r.status === "completed" && !canExport && (
            <Link href="/usage">
              <Button size="sm" variant="outline" disabled>
                Upgrade to export
              </Button>
            </Link>
          )}
        </div>
      </div>

      {/* Timing */}
      <Card>
        <CardContent className="pt-5">
          <dl className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <dt className="text-xs text-zinc-500 mb-0.5">Created</dt>
              <dd className="text-white">{formatDate(r.created_at)}</dd>
            </div>
            {r.started_at && (
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Started</dt>
                <dd className="text-white">{formatDate(r.started_at)}</dd>
              </div>
            )}
            {r.finished_at && (
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Finished</dt>
                <dd className="text-white">{formatDate(r.finished_at)}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>

      {/* Live status indicator */}
      {(r.status === "pending" || r.status === "running") && (
        <Card>
          <CardContent className="flex items-center gap-3 pt-5">
            <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-blue-400" />
            <p className="text-sm text-zinc-300">
              {r.status === "pending"
                ? "Run is queued — waiting for a worker…"
                : "Council is in session — agents are debating…"}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Result */}
      {r.result && (
        <Card>
          <CardHeader>
            <CardTitle>Result</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap break-words rounded-lg bg-zinc-800/50 p-4 text-sm text-zinc-200 font-mono overflow-x-auto">
              {JSON.stringify(r.result, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {r.error && (
        <Card>
          <CardHeader>
            <CardTitle className="text-red-400">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-red-300">{r.error}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
