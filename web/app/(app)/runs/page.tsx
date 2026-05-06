"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Download, Monitor, Play, Plus, Search } from "lucide-react";
import { api, type Entitlements, type Run } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Textarea,
  Tooltip,
  TooltipProvider,
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

/** Simple toggle switch built with Tailwind — no extra Radix dependency needed. */
function ToggleSwitch({
  id,
  checked,
  onChange,
  disabled,
}: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={[
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent",
        "transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-violet-500 focus-visible:ring-offset-1 focus-visible:ring-offset-zinc-950",
        disabled ? "cursor-not-allowed opacity-40" : "",
        checked ? "bg-violet-600" : "bg-zinc-700",
      ].join(" ")}
    >
      <span
        className={[
          "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm",
          "transform transition-transform duration-200",
          checked ? "translate-x-4" : "translate-x-0",
        ].join(" ")}
      />
    </button>
  );
}

function CreateRunDialog({ entitlements }: { entitlements?: Entitlements }) {
  const { getToken } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [agents, setAgents] = useState("3");
  const [rounds, setRounds] = useState("3");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [computerUseEnabled, setComputerUseEnabled] = useState(false);
  const [sandboxStreamUrl, setSandboxStreamUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  const maxAgents = entitlements?.limits.max_agents ?? 6;
  const maxRounds = entitlements?.limits.max_rounds ?? 4;
  const canWebSearch = entitlements?.features.web_search_enabled ?? false;
  const canComputerUse = entitlements?.features.computer_use_enabled ?? false;

  const create = useMutation({
    mutationFn: () =>
      api.createRun(getToken, {
        question,
        config: { num_agents: parseInt(agents), num_rounds: parseInt(rounds) },
        web_search_enabled: webSearchEnabled,
        computer_use_enabled: computerUseEnabled,
      }),
    onSuccess: async (run) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["usage"] });

  // If computer use was enabled, fetch the VNC stream URL to display it.
  if (computerUseEnabled) {
        try {
          const { stream_url } = await api.getSandboxStream(getToken, run.run_id);
          setSandboxStreamUrl(stream_url);
        } catch (err) {
          console.warn("Sandbox stream URL unavailable");
          if (process.env.NODE_ENV === "development") console.error(err);
          setError("Run started, but the sandbox stream could not be fetched yet. Check the run status page.");
          qc.invalidateQueries({ queryKey: ["runs"] });
        }
      } else {
        setOpen(false);
        setQuestion("");
      }
    },
    onError: (err: Error & { status?: number }) => {
      if (err.status === 429) {
        setError("Monthly run limit reached. Upgrade your plan to continue.");
      } else if (err.status === 403) {
        setError("You don't have permission to perform this action.");
      } else if (err.status === 404) {
        setError("Resource not found.");
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
    },
  });

  function handleOpenChange(v: boolean) {
    setOpen(v);
    if (!v) {
      setQuestion("");
      setWebSearchEnabled(false);
      setComputerUseEnabled(false);
      setSandboxStreamUrl(null);
      setError("");
    }
  }

  return (
    <TooltipProvider>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          <Button size="sm" className="gap-2">
            <Plus className="h-3.5 w-3.5" /> New run
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start a new council run</DialogTitle>
            <DialogDescription>
              Pose a question and configure the debate parameters.
            </DialogDescription>
          </DialogHeader>

          {sandboxStreamUrl ? (
            /* ── Computer-use sandbox panel ─────────────────────────── */
            <div className="space-y-4">
              <p className="text-sm text-zinc-300">
                Run started. The Docker sandbox is live — open the link
                below to watch the agent work in real time.
              </p>
              <a
                href={sandboxStreamUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate rounded-md border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-xs text-violet-300 hover:underline"
              >
                {sandboxStreamUrl}
              </a>
              {/* Collapsible iframe preview */}
              <details className="group">
                <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300">
                  Preview sandbox (iframe)
                </summary>
                <iframe
                  src={sandboxStreamUrl}
                  className="mt-2 h-64 w-full rounded-md border border-zinc-700"
                  title="Docker sandbox stream"
                  sandbox="allow-scripts allow-same-origin allow-forms"
                />
              </details>
              <div className="flex justify-end">
                <DialogClose asChild>
                  <Button>Done</Button>
                </DialogClose>
              </div>
            </div>
          ) : (
            /* ── Normal run creation form ───────────────────────────── */
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="question">Question</Label>
                <Textarea
                  id="question"
                  rows={4}
                  placeholder="What is the most important thing to consider when scaling a distributed system?"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  maxLength={4096}
                />
                <p className="text-right text-xs text-zinc-600">{question.length}/4096</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label>Agents (max {maxAgents})</Label>
                  <Select value={agents} onValueChange={setAgents}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Array.from({ length: maxAgents }, (_, i) => i + 1).map((n) => (
                        <SelectItem key={n} value={String(n)}>
                          {n}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Rounds (max {maxRounds})</Label>
                  <Select value={rounds} onValueChange={setRounds}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Array.from({ length: maxRounds }, (_, i) => i + 1).map((n) => (
                        <SelectItem key={n} value={String(n)}>
                          {n}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* ── Feature toggles ─────────────────────────────────── */}
              <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
                {/* Web Search toggle */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Search className="h-3.5 w-3.5 text-zinc-500" />
                    <Label htmlFor="web-search-toggle" className="cursor-pointer">
                      Enable Web Search
                    </Label>
                  </div>
                  {canWebSearch ? (
                    <ToggleSwitch
                      id="web-search-toggle"
                      checked={webSearchEnabled}
                      onChange={setWebSearchEnabled}
                    />
                  ) : (
                    <Tooltip content="Pro+ feature — upgrade to enable web search">
                      <span>
                        <ToggleSwitch
                          id="web-search-toggle"
                          checked={false}
                          onChange={() => {}}
                          disabled
                        />
                      </span>
                    </Tooltip>
                  )}
                </div>

                {/* Computer Use toggle */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Monitor className="h-3.5 w-3.5 text-zinc-500" />
                    <Label htmlFor="computer-use-toggle" className="cursor-pointer">
                      Enable Computer Use Sandbox
                    </Label>
                  </div>
                  {canComputerUse ? (
                    <ToggleSwitch
                      id="computer-use-toggle"
                      checked={computerUseEnabled}
                      onChange={setComputerUseEnabled}
                    />
                  ) : (
                    <Tooltip content="Ultra+ feature — upgrade to enable computer use">
                      <span>
                        <ToggleSwitch
                          id="computer-use-toggle"
                          checked={false}
                          onChange={() => {}}
                          disabled
                        />
                      </span>
                    </Tooltip>
                  )}
                </div>
              </div>

              {error && <p className="text-sm text-red-400">{error}</p>}

              <div className="flex justify-end gap-2 pt-1">
                <DialogClose asChild>
                  <Button variant="ghost">Cancel</Button>
                </DialogClose>
                <Button
                  onClick={() => create.mutate()}
                  disabled={create.isPending || !question.trim()}
                >
                  {create.isPending ? "Starting…" : "Start run"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
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
        <CreateRunDialog entitlements={ent.data} />
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
                Start your first council debate to see results here.
              </p>
              <CreateRunDialog entitlements={ent.data} />
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
                        <Link href="/usage" title="Upgrade to export">
                          <Button size="icon" variant="ghost" disabled>
                            <Download className="h-3.5 w-3.5 opacity-30" />
                          </Button>
                        </Link>
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
