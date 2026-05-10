import { NextRequest, NextResponse } from "next/server";

/**
 * Explicit reverse proxy for MCP. next.config rewrites do not reliably forward
 * Authorization to external origins, which breaks Bearer auth in Cursor.
 */
function getMcpTarget(): string {
  if (process.env.MCP_PROXY_TARGET) {
    return process.env.MCP_PROXY_TARGET;
  }
  if (process.env.COUNCIL_API_URL) {
    return process.env.COUNCIL_API_URL;
  }
  // Default: use https in production, http://localhost in development
  const isDev = process.env.NODE_ENV !== "production";
  return isDev ? "http://127.0.0.1:8000" : "https://api.example.com";
}

const MCP_TARGET = getMcpTarget();

/**
 * Validates path segments to prevent directory traversal and SSRF attacks.
 * - Rejects ".." and "." segments
 * - Rejects absolute paths (starting with /)
 * - Rejects shell metacharacters and encoded traversal sequences
 * - Only allows alphanumeric, hyphens, underscores, and safe special chars
 */
function validatePathSegments(segments: string[] | undefined): boolean {
  if (!segments || segments.length === 0) {
    return true; // Empty path is valid (proxies to /mcp/)
  }

  for (const segment of segments) {
    // Reject empty segments
    if (!segment) return false;
    
    // Reject directory traversal attempts
    if (segment === ".." || segment === ".") return false;
    
    // Reject absolute paths
    if (segment.startsWith("/")) return false;
    
    // Reject encoded traversal sequences
    if (segment.includes("%2e") || segment.includes("%2E") || 
        segment.includes("%2f") || segment.includes("%2F") ||
        segment.includes("..") || segment.includes("//")) {
      return false;
    }
    
    // Reject shell metacharacters
    const shellMetachars = /[;&|`$()\\<>"\n\r]/;
    if (shellMetachars.test(segment)) return false;
    
    // Only allow: alphanumeric, hyphens, underscores, dots (for file extensions)
    // This is restrictive but safe for MCP path segments
    const validPathRegex = /^[a-zA-Z0-9._-]+$/;
    if (!validPathRegex.test(segment)) return false;
  }

  return true;
}

function backendUrl(
  req: NextRequest,
  segments: string[] | undefined
): { url: string | null; error?: string } {
  // Validate segments to prevent SSRF/path traversal
  if (!validatePathSegments(segments)) {
    return { url: null, error: "Invalid path segments" };
  }

  const base = MCP_TARGET.replace(/\/$/, "");
  const rest = segments?.length ? `/${segments.join("/")}` : "";
  const u = new URL(req.url);
  const url = `${base}/mcp${rest}${u.search}`;
  
  return { url };
}

async function proxy(
  req: NextRequest,
  segments: string[] | undefined
): Promise<Response> {
  const result = backendUrl(req, segments);
  
  // Return 403 Forbidden if path validation fails (SSRF prevention)
  if (!result.url) {
    return new NextResponse(
      JSON.stringify({ error: result.error || "Invalid request path" }),
      { status: 403, headers: { "Content-Type": "application/json" } }
    );
  }

  const url = result.url;
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
