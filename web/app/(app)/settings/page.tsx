"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, Eye, EyeOff, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { api, type Entitlements } from "@/lib/api";
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
import { useRouter } from "next/navigation";

function maskKey(key: string): string {
  if (key.length <= 8) return "•".repeat(key.length);
  return key.slice(0, 4) + "•".repeat(Math.max(8, key.length - 4));
}

export default function SettingsPage() {
  const { token, logout } = useAuth();
  const router = useRouter();
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    staleTime: Infinity,
  });

  function copy() {
    if (!token) return;
    navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      {/* API Key */}
      <Card>
        <CardHeader>
          <CardTitle>API Key</CardTitle>
          <CardDescription>
            Use this key in the Authorization header:{" "}
            <code className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-xs text-violet-300">
              Authorization: Bearer &lt;key&gt;
            </code>
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 rounded-lg border border-zinc-700/80 bg-zinc-800/40 px-3 py-2.5">
            <span className="flex-1 break-all font-mono text-sm tracking-wide text-zinc-300">
              {token ? (show ? token : maskKey(token)) : "—"}
            </span>
            <button
              onClick={() => setShow((s) => !s)}
              className="shrink-0 text-zinc-500 hover:text-white transition-colors"
              title={show ? "Hide key" : "Show key"}
            >
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
            <button
              onClick={copy}
              className="shrink-0 text-zinc-500 hover:text-white transition-colors"
              title="Copy to clipboard"
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>
          {copied && <p className="text-xs text-emerald-400">Copied to clipboard.</p>}
          <p className="text-xs text-zinc-600">
            This key is stored in your browser&apos;s local storage. Keep it secret.
            Rotation requires a new key from your API dashboard.
          </p>
        </CardContent>
      </Card>

      {/* Subscription summary */}
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
              [
                "Saved personas",
                ent.data?.limits.max_saved_personas ?? "Unlimited",
              ],
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

      {/* Session */}
      <div className="space-y-2">
        <p className="text-sm font-medium text-zinc-400">Session</p>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleLogout}
          className="gap-2 text-red-400 hover:bg-red-950/40 hover:text-red-300"
        >
          <LogOut className="h-4 w-4" /> Sign out
        </Button>
      </div>
    </div>
  );
}
