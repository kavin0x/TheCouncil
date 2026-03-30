"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function wsUrlForRun(base: string, runId: string, token: string): string {
  const trimmed = base.replace(/\/$/, "");
  const wsBase = trimmed.startsWith("https")
    ? trimmed.replace(/^https/, "wss")
    : trimmed.replace(/^http/, "ws");
  return `${wsBase}/ws/${encodeURIComponent(runId)}?token=${encodeURIComponent(token)}`;
}

type AgentFeed = {
  role: string;
  sections: { phase: string; content: string }[];
  streamBuf: string;
};

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    round1: "Round 1 — Independent take",
    cross_debate_1: "Cross-debate I",
    cross_debate_2: "Cross-debate II",
    tiebreaker: "Tie-breaker",
  };
  return labels[phase] ?? phase;
}

type WsEvent = {
  type: string;
  run_id?: string;
  ts?: number;
  agents?: { name: string; role: string }[];
  agent?: string;
  role?: string;
  round_num?: number;
  content?: string;
  phase?: string;
  delta?: string;
  sender?: string;
  recipient?: string;
  error?: string;
  status?: string;
  result?: unknown;
};

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

  const [feeds, setFeeds] = useState<Record<string, AgentFeed>>({});
  const [dmLog, setDmLog] = useState<string[]>([]);
  const feedsRef = useRef(feeds);
  feedsRef.current = feeds;

  const applyWsEvent = useCallback((msg: WsEvent) => {
    if (msg.type === "agents_announced" && msg.agents?.length) {
      setFeeds(() => {
        const next: Record<string, AgentFeed> = {};
        for (const a of msg.agents!) {
          next[a.name] = { role: a.role, sections: [], streamBuf: "" };
        }
        return next;
      });
      return;
    }
    if (msg.type === "agent_delta" && msg.agent && msg.delta) {
      setFeeds((prev) => {
        const cur = prev[msg.agent!];
        if (!cur) return prev;
        return {
          ...prev,
          [msg.agent!]: { ...cur, streamBuf: cur.streamBuf + msg.delta! },
        };
      });
      return;
    }
    if (msg.type === "agent_response" && msg.agent && msg.content != null && msg.phase) {
      setFeeds((prev) => {
        const cur = prev[msg.agent!];
        if (!cur) return prev;
        return {
          ...prev,
          [msg.agent!]: {
            ...cur,
            streamBuf: "",
            sections: [
              ...cur.sections,
              { phase: msg.phase!, content: msg.content! },
            ],
          },
        };
      });
      return;
    }
    if (msg.type === "agent_dm" && msg.sender && msg.recipient) {
      const line = `${msg.sender} → ${msg.recipient}: ${msg.content ?? ""}`;
      setDmLog((d) => [...d, line]);
    }
  }, []);

  const run = useQuery<Run>({
    queryKey: ["run", id],
    queryFn: () => api.getRun(token!, id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "pending" || s === "running" ? 5000 : false;
    },
  });

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    staleTime: Infinity,
  });

  const canExport = ent.data?.features ? true : false;

  const status = run.data?.status;
  const live = status === "pending" || status === "running";

  useEffect(() => {
    if (!token || !id || !live) return;

    const url = wsUrlForRun(API_BASE, id, token);
    const ws = new WebSocket(url);

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as WsEvent;
        if (msg.type === "run_snapshot" && msg.result && typeof msg.result === "object") {
          const r = msg.result as { agents?: { name: string; role: string }[] };
          if (r.agents?.length && Object.keys(feedsRef.current).length === 0) {
            const next: Record<string, AgentFeed> = {};
            for (const a of r.agents) {
              next[a.name] = { role: a.role, sections: [], streamBuf: "" };
            }
            setFeeds(next);
          }
        }
        applyWsEvent(msg);
      } catch {
        /* ignore */
      }
    };

    return () => {
      ws.close();
    };
  }, [token, id, live, applyWsEvent]);

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

  const agentNames = useMemo(() => Object.keys(feeds).sort(), [feeds]);

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

      {(r.status === "pending" || r.status === "running") && (
        <Card>
          <CardContent className="flex items-center gap-3 pt-5">
            <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-blue-400" />
            <p className="text-sm text-zinc-300">
              {r.status === "pending"
                ? "Run is queued — waiting for a worker…"
                : "Live — agent outputs stream below as they speak."}
            </p>
          </CardContent>
        </Card>
      )}

      {agentNames.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-zinc-400">Agents</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {agentNames.map((name) => {
              const f = feeds[name];
              if (!f) return null;
              return (
                <Card key={name} className="flex min-h-[200px] flex-col">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base text-white">{name}</CardTitle>
                    <p className="text-xs text-zinc-500">{f.role}</p>
                  </CardHeader>
                  <CardContent className="flex-1 space-y-3 text-sm text-zinc-300">
                    {f.sections.map((s, i) => (
                      <div key={`${s.phase}-${i}`}>
                        <p className="mb-1 text-xs font-medium text-violet-400/90">
                          {phaseLabel(s.phase)}
                        </p>
                        <p className="whitespace-pre-wrap break-words">{s.content}</p>
                      </div>
                    ))}
                    {f.streamBuf ? (
                      <div>
                        <p className="mb-1 text-xs font-medium text-blue-400/90">
                          Speaking…
                        </p>
                        <p className="whitespace-pre-wrap break-words text-zinc-200">
                          {f.streamBuf}
                        </p>
                      </div>
                    ) : null}
                    {f.sections.length === 0 && !f.streamBuf && (
                      <p className="text-xs text-zinc-600">Waiting…</p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {dmLog.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Private DMs (observer)</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-xs text-zinc-500">
              {dmLog.map((line, i) => (
                <li key={i} className="font-mono">
                  {line}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

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
