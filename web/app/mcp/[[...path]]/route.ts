import { NextRequest, NextResponse } from "next/server";

/**
 * Explicit reverse proxy for MCP. next.config rewrites do not reliably forward
 * Authorization to external origins, which breaks Bearer auth in Cursor.
 */
const MCP_TARGET =
  process.env.MCP_PROXY_TARGET ??
  process.env.COUNCIL_API_URL ??
  "http://127.0.0.1:8000";

function backendUrl(req: NextRequest, segments: string[] | undefined): string {
  const base = MCP_TARGET.replace(/\/$/, "");
  const rest = segments?.length ? `/${segments.join("/")}` : "";
  const u = new URL(req.url);
  return `${base}/mcp${rest}${u.search}`;
}

async function proxy(
  req: NextRequest,
  segments: string[] | undefined
): Promise<Response> {
  const url = backendUrl(req, segments);
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (key.toLowerCase() !== "host") {
      headers.set(key, value);
    }
  });

  const init: RequestInit & { duplex?: string } = {
    method: req.method,
    headers,
    redirect: "manual",
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half";
  }

  const res = await fetch(url, init);
  return new NextResponse(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: res.headers,
  });
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function OPTIONS(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export const dynamic = "force-dynamic";
