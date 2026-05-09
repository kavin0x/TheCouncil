<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Auth (self-hosted, no login)

No authentication. All routes are public. `web/lib/auth.tsx` exports `useAuth()` which returns:

- `getToken()` → returns `NEXT_PUBLIC_API_TOKEN` env var, or `null` if not set
- `isLoading` → always `false`
- `logout` → no-op

If `API_SECRET_KEY` is set in the backend `.env`, set the same value as `NEXT_PUBLIC_API_TOKEN` in `web/.env.local`.

## App Routes

All authenticated routes live under `web/app/(app)/` and share a common layout (`layout.tsx`):

- `/` → `dashboard/page.tsx` — run list and quick-start
- `/runs` → `runs/page.tsx` — full run history
- `/runs/[id]` → `runs/[id]/page.tsx` — run detail with live WebSocket event feed
- `/personas` → `personas/page.tsx` — browse, create, and manage agent personas
- `/settings` → `settings/page.tsx` — council config (agent count, rounds, default model)
- `/integrations` → `integrations/page.tsx` — Zoom webhook and MCP integration config
- `/usage` → `usage/page.tsx` — month-to-date run usage

The MCP proxy route is at `web/app/mcp/[[...path]]/route.ts`.

## API Client

`web/lib/api.ts` contains all fetch helpers and TypeScript types. These types mirror the Python Pydantic models — keep them in sync when backend schemas change.

`web/lib/utils.ts` contains shared utility functions.
