<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Clerk Auth (as of 2026-04-17)

`@clerk/nextjs` 7.2.3 is installed. The auth architecture:

- `web/middleware.ts` — `clerkMiddleware()` with `createRouteMatcher` protects app routes (`/dashboard`, `/runs`, `/personas`, `/usage`, `/settings`, `/integrations`)
- `web/app/layout.tsx` — `<ClerkProvider>` wraps `<body>`
- `web/lib/auth.tsx` — `useAuth()` hook exposes `getToken`, `isLoading`, `logout`
  - `getToken()` returns a Clerk JWT for use as the API Bearer token
- `web/lib/api.ts` — all `api.*` methods accept `getToken: () => Promise<string | null>` (NOT a raw string token)
- Login page (`/login`) — redirects to Clerk sign-in; no API key form
- Settings page (`/settings`) — API key management UI (generate/list/revoke `tc_live_...` keys)

### Required env vars

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...
CLERK_SECRET_KEY=sk_...
```

Get these from https://dashboard.clerk.com

### Imports

- Client components: `import { useUser, useClerk, UserButton, SignInButton } from "@clerk/nextjs"`
- Server components/middleware: `import { ... } from "@clerk/nextjs/server"`
- NEVER use `<SignedIn>` or `<SignedOut>` (deprecated in this version) — use `useUser().isSignedIn` or conditional rendering based on auth state
