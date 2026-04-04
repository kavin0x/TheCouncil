"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { Button, Input, Label } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [key, setKey] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setLoading(true);
    setError("");
    try {
      await api.getEntitlements(key.trim());
      login(key.trim());
      router.push("/dashboard");
    } catch {
      setError("Could not verify the API key. Check the key and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#070b0f] px-4">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-violet-600 text-sm font-bold text-white shadow-lg shadow-violet-500/20">
            TC
          </div>
          <span className="text-base font-semibold text-white">TheCouncil</span>
        </Link>

        <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-7">
          <h1 className="mb-1 text-xl font-bold text-white">Sign in</h1>
          <p className="mb-6 text-sm text-zinc-400">
            Enter your API key to access your council dashboard.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="apikey">API Key</Label>
              <div className="relative">
                <Input
                  id="apikey"
                  type={show ? "text" : "password"}
                  placeholder="tc_live_..."
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  className="pr-10"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white"
                  tabIndex={-1}
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {error && <p className="text-xs text-red-400">{error}</p>}
            </div>

            <Button type="submit" className="w-full" disabled={loading || !key.trim()}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <p className="mt-5 text-center text-xs text-zinc-500">
            Don&apos;t have an account?{" "}
            <Link href="/pricing" className="text-violet-400 hover:underline">
              Start your free trial
            </Link>
          </p>
        </div>

        <p className="mt-6 text-center text-xs text-zinc-700">
          By signing in you agree to our{" "}
          <Link href="/legal#tos" className="underline underline-offset-2 hover:text-zinc-500">
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link href="/legal#privacy" className="underline underline-offset-2 hover:text-zinc-500">
            Privacy Policy
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
