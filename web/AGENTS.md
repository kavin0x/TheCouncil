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
