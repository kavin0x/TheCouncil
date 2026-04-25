"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Key, LogOut, Plus, Trash2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { api, type ApiKey, type ApiKeyCreated, type Entitlements } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Separator,
} from "@/components/ui";

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function SettingsPage() {
  const { getToken, logout } = useAuth();
  const qc = useQueryClient();
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
    staleTime: Infinity,
  });

  const keysQuery = useQuery<ApiKey[]>({
    queryKey: ["api-keys"],
    queryFn: () => api.listApiKeys(getToken),
  });

  const createKey = useMutation({
    mutationFn: () => api.createApiKey(getToken, { name: "My API Key" }),
    onSuccess: (created) => {
      setNewKey(created);
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(getToken, keyId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  function copyNewKey() {
    if (!newKey) return;
    navigator.clipboard.writeText(newKey.plaintext_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>API Keys</CardTitle>
          <CardDescription>
            Use these keys in the{" "}
            <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-violet-300">
              Authorization: Bearer &lt;key&gt;
            </code>{" "}
            header for programmatic or CLI access.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {newKey && (
            <div className="space-y-2 rounded-lg border border-amber-700/50 bg-amber-900/10 p-4">
              <p className="text-xs font-medium text-amber-400">
                Copy this now — you won&apos;t see it again.
              </p>
              <div className="flex items-center gap-2 rounded border border-zinc-700 bg-zinc-800/60 px-3 py-2">
                <span className="flex-1 break-all font-mono text-xs text-zinc-200">
                  {newKey.plaintext_key}
                </span>
                <button
                  onClick={copyNewKey}
                  className="shrink-0 text-zinc-400 transition-colors hover:text-white"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
              {copied && <p className="text-xs text-emerald-400">Copied to clipboard.</p>}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setNewKey(null)}
                className="text-xs text-zinc-500"
              >
                Dismiss
              </Button>
            </div>
          )}

          {keysQuery.isLoading ? (
            <div className="space-y-2">
              {[...Array(2)].map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-zinc-800" />
              ))}
            </div>
          ) : keysQuery.data?.length === 0 ? (
            <p className="text-sm text-zinc-500">No API keys yet.</p>
          ) : (
            <div className="divide-y divide-zinc-800">
              {keysQuery.data?.map((k) => (
                <div key={k.key_id} className="flex items-center gap-3 py-3">
                  <Key className="h-4 w-4 shrink-0 text-zinc-600" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-200">{k.name}</span>
                      {!k.is_active && <Badge variant="danger">revoked</Badge>}
                    </div>
                    <p className="font-mono text-xs text-zinc-500">{k.key_prefix}••••••••</p>
                    <p className="text-xs text-zinc-600">
                      Created {formatDate(k.created_at)}
                      {k.last_used_at ? ` · Last used ${formatDate(k.last_used_at)}` : ""}
                    </p>
                  </div>
                  {k.is_active && (
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => revokeKey.mutate(k.key_id)}
                      disabled={revokeKey.isPending}
                      title="Revoke key"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-400" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}

          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={() => createKey.mutate()}
            disabled={createKey.isPending}
          >
            <Plus className="h-3.5 w-3.5" />
            {createKey.isPending ? "Generating…" : "Generate new key"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Subscription</CardTitle>
          <CardDescription>Your current plan and key entitlements.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-zinc-400">Plan:</span>
            <Badge
              variant={
                (
                  {
                    trial: "warning" as const,
                    basic: "secondary" as const,
                    pro: "default" as const,
                    ultra: "success" as const,
                    enterprise: "success" as const,
                  }
                )[ent.data?.tier ?? "trial"] ?? "secondary"
              }
            >
              {ent.data?.display_name ?? "—"}
            </Badge>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            {[
              ["Runs / month", ent.data?.limits.runs_per_month],
              ["Max agents", ent.data?.limits.max_agents],
              ["Max rounds", ent.data?.limits.max_rounds],
              ["Saved personas", ent.data?.limits.max_saved_personas ?? "Unlimited"],
            ].map(([label, val]) => (
              <div key={String(label)}>
                <dt className="text-xs text-zinc-500">{label}</dt>
                <dd className="text-zinc-200">{String(val ?? "—")}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Separator />

      <div className="space-y-2">
        <p className="text-sm font-medium text-zinc-400">Session</p>
        <Button variant="outline" size="sm" onClick={logout} className="gap-2 border-red-900 text-red-400 hover:bg-red-950">
          <LogOut className="h-4 w-4" /> Sign out
        </Button>
      </div>
    </div>
  );
}
