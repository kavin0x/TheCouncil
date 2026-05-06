"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Lock } from "lucide-react";
import { api, type Entitlements } from "@/lib/api";
import { useAuth } from "@/lib/auth";
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

function CodeBlock({ code, lang = "json" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative mt-2 rounded-xl border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
        <span className="text-xs text-zinc-500 font-mono">{lang}</span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          {copied ? (
            <Check className="h-3 w-3 text-emerald-400" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-sm text-zinc-200 font-mono leading-relaxed">
        {code}
      </pre>
    </div>
  );
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const MCP_BASE =
  typeof window !== "undefined"
    ? window.location.origin
    : process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

function McpJsonSnippet({ apiKey }: { apiKey: string }) {
  const masked = apiKey.slice(0, 8) + "...";
  const snippet = JSON.stringify(
    {
      mcpServers: {
        thecouncil: {
          url: `${MCP_BASE}/mcp`,
          headers: {
            Authorization: `Bearer ${masked}`,
          },
        },
      },
    },
    null,
    2
  );
  return <CodeBlock code={snippet} />;
}

export default function IntegrationsPage() {
  const { getToken } = useAuth();

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
    staleTime: Infinity,
  });

  const mcpEnabled = ent.data?.features.mcp_enabled;
  const customMcpEnabled = ent.data?.features.custom_mcp_enabled;

  if (!mcpEnabled && !ent.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-xl bg-zinc-800 ring-1 ring-zinc-700/60">
          <Lock className="h-6 w-6 text-zinc-500" />
        </div>
        <h1 className="mb-2 text-xl font-bold text-white">Integrations require Pro</h1>
        <p className="mb-6 max-w-sm text-sm text-zinc-400">
          MCP server access and IDE plugin integrations are available on Pro, Ultra, and Enterprise plans.
        </p>
        <Link href="/usage">
          <Button>Upgrade to Pro</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Integrations</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Connect TheCouncil to your editor via MCP.
          </p>
        </div>
        {ent.data && (
          <Badge variant={ent.data.features.ide_plugins_enabled ? "success" : "secondary"}>
            {ent.data.display_name}
          </Badge>
        )}
      </div>

      {/* MCP server */}
      <Card>
        <CardHeader>
          <CardTitle>MCP Server</CardTitle>
          <CardDescription>
            Connect Cursor, Claude Desktop, or any MCP-compatible host to TheCouncil.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div>
            <p className="mb-1 text-sm font-medium text-zinc-300">
              1. Generate an API key from{" "}
              <Link href="/settings" className="text-violet-400 hover:underline">
                Settings → API Keys
              </Link>
              .
            </p>
            <p className="text-sm text-zinc-500">
              Use the <code className="rounded bg-zinc-800 px-1">tc_live_...</code> key as the Bearer token.
            </p>
          </div>

          <div>
            <p className="mb-1 text-sm font-medium text-zinc-300">
              2. Add to <code className="rounded bg-zinc-800 px-1.5 text-xs">mcp.json</code>{" "}
              (Cursor) or <code className="rounded bg-zinc-800 px-1.5 text-xs">claude_desktop_config.json</code>
            </p>
            <McpJsonSnippet apiKey="tc_live_YOUR_KEY" />
          </div>

          <div>
            <p className="mb-2 text-sm font-medium text-zinc-300">3. Restart your editor</p>
            <p className="text-sm text-zinc-500">
              The TheCouncil MCP server will appear in your tool list. Call{" "}
              <code className="rounded bg-zinc-800 px-1.5 text-xs">council_run</code> with a question to start a debate.
            </p>
          </div>

          <Separator />

          <div className="text-sm text-zinc-500">
            <p className="font-medium text-zinc-300 mb-2">MCP server URL</p>
            <CodeBlock code={`${MCP_BASE}/mcp`} lang="url" />
            <p className="mt-2 text-xs text-zinc-500">
              Requests to <code className="rounded bg-zinc-800 px-1">app/mcp/[[...path]]/route.ts</code> are proxied to the API and the{" "}
              <code className="rounded bg-zinc-800 px-1">Authorization</code> header is forwarded automatically. Override the API origin with{" "}
              <code className="rounded bg-zinc-800 px-1">MCP_PROXY_TARGET</code> if needed. Same <code className="rounded bg-zinc-800 px-1">Bearer</code> as REST.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Cursor-specific */}
      <Card>
        <CardHeader>
          <CardTitle>Cursor</CardTitle>
          <CardDescription>
            Add TheCouncil as a remote MCP server in Cursor settings.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <ol className="space-y-2 text-sm text-zinc-400 list-decimal list-inside">
            <li>
              Open <strong className="text-zinc-200">Cursor Settings → Features → MCP</strong>
            </li>
            <li>Click <strong className="text-zinc-200">Add new MCP server</strong></li>
            <li>
              Paste the server URL and set the{" "}
              <code className="rounded bg-zinc-800 px-1.5 text-xs">Authorization</code> header
            </li>
            <li>Save and reload — TheCouncil tools will appear in the MCP panel</li>
          </ol>
          <CodeBlock
            code={`# .cursor/mcp.json
${JSON.stringify(
  {
    mcpServers: {
      thecouncil: {
        url: `${MCP_BASE}/mcp`,
        headers: { Authorization: "Bearer YOUR_API_KEY" },
      },
    },
  },
  null,
  2
)}`}
            lang="json"
          />
        </CardContent>
      </Card>

      {/* Claude Desktop */}
      <Card>
        <CardHeader>
          <CardTitle>Claude Desktop</CardTitle>
          <CardDescription>
            Add TheCouncil as an MCP server in Claude&apos;s developer config.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">
            Edit{" "}
            <code className="rounded bg-zinc-800 px-1.5 text-xs">
              ~/Library/Application Support/Claude/claude_desktop_config.json
            </code>
            :
          </p>
          <McpJsonSnippet apiKey="tc_live_YOUR_KEY" />
          <p className="text-xs text-zinc-600">
            Uses the same HTTP/SSE remote server config. Generate an API key from{" "}
            <Link href="/settings" className="text-violet-400 hover:underline">Settings → API Keys</Link>.
          </p>
        </CardContent>
      </Card>

      {/* Custom MCP */}
      {customMcpEnabled ? (
        <Card>
          <CardHeader>
            <CardTitle>Custom MCP registration</CardTitle>
            <CardDescription>
              Register your own MCP server URLs for outbound connections from TheCouncil workers.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-400">
              Custom MCP server registration is available on your plan but requires the backend to be configured. This feature is coming in Phase 3.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card className="opacity-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Custom MCP registration
              <span className="inline-flex items-center gap-1 rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 ring-1 ring-zinc-700/50">
                <Lock className="h-2.5 w-2.5" /> Pro+
              </span>
            </CardTitle>
            <CardDescription>Available on Pro and above.</CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/usage">
              <Button variant="outline" size="sm">Upgrade to Pro</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {/* Docs link */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-5 py-4 text-sm text-zinc-400">
        Need help?{" "}
        <a
          href="https://github.com/kavin0x/TheCouncil"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-violet-400 hover:underline"
        >
          GitHub repository <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  );
}
