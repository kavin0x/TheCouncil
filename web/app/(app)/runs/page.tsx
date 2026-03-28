"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus } from "lucide-react";
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

function CreateRunDialog({ entitlements }: { entitlements?: Entitlements }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [agents, setAgents] = useState("3");
  const [rounds, setRounds] = useState("3");
  const [error, setError] = useState("");

  const maxAgents = entitlements?.limits.max_agents ?? 6;
  const maxRounds = entitlements?.limits.max_rounds ?? 4;

  const create = useMutation({
    mutationFn: () =>
      api.createRun(token!, {
        question,
        config: { num_agents: parseInt(agents), num_rounds: parseInt(rounds) },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["usage"] });
      setOpen(false);
      setQuestion("");
    },
    onError: (err: Error & { status?: number }) => {
      if (err.status === 429) {
        setError("Monthly run limit reached. Upgrade your plan to continue.");
      } else {
        setError(err.message);
      }
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
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
            <p className="text-right text-xs text-zinc-500">{question.length}/4096</p>
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
      </DialogContent>
    </Dialog>
  );
}

export default function RunsPage() {
  const { token } = useAuth();
  const runs = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(token!),
    refetchInterval: 5000,
  });
  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
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
            <p className="text-xs text-zinc-500">Auto-refreshes every 5s</p>
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
              <p className="mb-2 text-sm text-zinc-400">No runs yet.</p>
              <p className="text-xs text-zinc-600">
                Click &ldquo;New run&rdquo; to start your first council debate.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {runs.data?.map((run) => (
                <div
                  key={run.run_id}
                  className="flex items-start gap-3 py-3.5"
                >
                  <div className="flex-1 min-w-0">
                    <Link
                      href={`/runs/${run.run_id}`}
                      className="text-sm text-white hover:text-violet-300 transition-colors line-clamp-2"
                    >
                      {run.question}
                    </Link>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {formatRelative(run.created_at)} · {run.run_id.slice(0, 8)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
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
