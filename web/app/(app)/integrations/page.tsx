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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.thecouncil.ai";

function McpJsonSnippet({ apiKey }: { apiKey: string }) {
  const masked = apiKey.slice(0, 8) + "...";
  const snippet = JSON.stringify(
    {
      mcpServers: {
        thecouncil: {
          url: `${API_BASE}/mcp`,
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
  const { token } = useAuth();

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    staleTime: Infinity,
  });

  const mcpEnabled = ent.data?.features.mcp_enabled;
  const customMcpEnabled = ent.data?.features.custom_mcp_enabled;

  if (!mcpEnabled && !ent.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <Lock className="mb-4 h-10 w-10 text-zinc-600" />
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
              1. Copy your API key from{" "}
              <Link href="/settings" className="text-violet-400 hover:underline">
                Settings
              </Link>
              .
            </p>
            <p className="text-sm text-zinc-500">
              You&apos;ll use it as the Bearer token in the MCP server config.
            </p>
          </div>

          <div>
            <p className="mb-1 text-sm font-medium text-zinc-300">
              2. Add to <code className="rounded bg-zinc-800 px-1.5 text-xs">mcp.json</code>{" "}
              (Cursor) or <code className="rounded bg-zinc-800 px-1.5 text-xs">claude_desktop_config.json</code>
            </p>
            {token && <McpJsonSnippet apiKey={token} />}
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
            <CodeBlock code={`${API_BASE}/mcp`} lang="url" />
            <p className="mt-2 text-xs text-zinc-500">
              Local dev: use <code className="rounded bg-zinc-800 px-1">NEXT_PUBLIC_API_BASE_URL=http://localhost:3000</code>{" "}
              so this URL hits Next; <code className="rounded bg-zinc-800 px-1">app/mcp/[[...path]]/route.ts</code> proxies to the API and
              forwards <code className="rounded bg-zinc-800 px-1">Authorization</code> (Next rewrites do not). Override the API origin with{" "}
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
        url: `${API_BASE}/mcp`,
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
          <CodeBlock
            code={JSON.stringify(
              {
                mcpServers: {
                  thecouncil: {
                    command: "npx",
                    args: ["-y", "@thecouncil/mcp-client"],
                    env: {
                      THECOUNCIL_API_KEY: "YOUR_API_KEY",
                      THECOUNCIL_API_URL: API_BASE,
                    },
                  },
                },
              },
              null,
              2
            )}
          />
          <p className="text-xs text-zinc-600">
            The npm package <code>@thecouncil/mcp-client</code> is coming soon (Phase 3). For now use the HTTP/SSE remote server config above.
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
        <Card className="opacity-60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Custom MCP registration <Lock className="h-4 w-4 text-zinc-500" />
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
          href="https://docs.thecouncil.ai/mcp"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-violet-400 hover:underline"
        >
          Full MCP integration docs <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  );
}
