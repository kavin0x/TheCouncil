# Code Review — TheCouncil (Post-Clerk Auth Migration)

**Date:** 2026-04-17  
**Reviewer:** Claude Sonnet 4.6  
**Scope:** Backend (`council/api/app.py`, `council/db/models.py`, `council/db/session.py`, `tests/test_api.py`) and Frontend (`web/lib/auth.tsx`, `web/lib/api.ts`, `web/middleware.ts`, `web/app/*`, `web/components/*`)

---

## Executive Summary

The parallel auth migration to Clerk is partially implemented. The **backend** has correctly added Clerk JWT verification as a first-class auth pathway while preserving the `API_SECRET_KEY` dev fallback. However, several agents made inconsistent changes to the frontend — **the `useAuth()` hook exposes `getToken` (async) but every page still destructures a synchronous `token` property that no longer exists on the context**. This is a critical runtime bug that will cause all authenticated API calls to fail silently, passing `undefined` as the Bearer token. There are also secondary issues around redundant auth guards, API contract gaps, and a security concern in the WebSocket endpoint.

---

## Issues Found

### CRITICAL BUGS

---

**Issue 1 — `token` removed from `AuthCtx` but all consumers still use it**

- **Files:** `web/lib/auth.tsx` (AuthCtx definition) vs. every page and sidebar
- **Severity:** Bug (Critical)

`AuthCtx` in `web/lib/auth.tsx` defines only `{ getToken, isLoading, logout }`. There is no `token: string` field. However, every downstream consumer destructures `token` from `useAuth()`:

| File | Line(s) | Usage |
|------|---------|-------|
| `web/app/(app)/layout.tsx` | 9, 13, 25 | `const { token, isLoading } = useAuth()` |
| `web/app/(app)/dashboard/page.tsx` | 51, 52 | `const { token } = useAuth(); ... useDashboard(token!)` |
| `web/app/(app)/runs/page.tsx` | 87, 105, 339 | `const { token } = useAuth()` |
| `web/app/(app)/runs/[id]/page.tsx` | 256, 317, 325, 335 | `const { token } = useAuth()` |
| `web/app/(app)/usage/page.tsx` | 60, 64, 68, 71, 77, 89, 105 | `const { token } = useAuth()` |
| `web/app/(app)/settings/page.tsx` | 26, 38, 67 | `const { token, logout } = useAuth()` |
| `web/app/(app)/personas/page.tsx` | ~1162, 1170, 1176, 1469, 1474, 1485, 1500, 1513, 1521, 1527 | `const { token } = useAuth()` |
| `web/components/sidebar.tsx` | 45 | `const { token, logout } = useAuth()` |

TypeScript will flag all of these as type errors because `token` does not exist on `AuthCtx`. At runtime, `token` will be `undefined`, which means every `api.*` call is invoked as `api.getEntitlements(undefined)`, constructing an `Authorization: Bearer undefined` header. All API calls will return `401`.

**Fix:** Either add `token: string | null` back to `AuthCtx` (populated lazily) or convert every `api.*` call site to the async `getToken()` pattern. The latter is correct but requires touching every query/mutation.

The simplest correct fix consistent with Clerk's model:

```typescript
// In AuthProvider, maintain a reactive token state:
const [token, setToken] = useState<string | null>(null);
useEffect(() => {
  clerkGetToken().then(setToken).catch(() => setToken(null));
}, [isLoaded, clerkGetToken]);
// Expose token in context value
```

---

**Issue 2 — `login()` called in `web/app/login/page.tsx` but does not exist on `AuthCtx`**

- **File:** `web/app/login/page.tsx` line 14, 29
- **Severity:** Bug (Critical)

The login page calls `const { login } = useAuth()` and then `login(key.trim())` after API key verification. `AuthCtx` has no `login` method — only `getToken`, `isLoading`, and `logout`. This will throw a runtime error (`login is not a function`) when a user attempts to connect their API key.

This also reveals a design inconsistency: the login page implements a **two-step flow** (Clerk sign-in → API key entry), but `AuthProvider` has no mechanism to store or expose an externally-provided API key. The Clerk `getToken()` returns a Clerk JWT, not the user's `tc_live_*` API key.

---

**Issue 3 — `web/app/(app)/layout.tsx` guards on `token` which is always `undefined`**

- **File:** `web/app/(app)/layout.tsx` lines 9, 13, 25
- **Severity:** Bug (Critical)

```tsx
const { token, isLoading } = useAuth();
// ...
if (!isLoading && !token) { router.replace("/login"); }
// ...
if (!token) return null;
```

Because `token` is not on `AuthCtx`, it will always be `undefined`. After `isLoading` becomes false (Clerk finishes loading), this immediately redirects every authenticated user to `/login` — making the entire app unusable even after a successful Clerk sign-in.

This duplicates the protection already provided by `web/middleware.ts` → `auth.protect()`. Having two redundant auth guards is also an anti-pattern; the layout guard is now broken and the middleware guard is correctly implemented.

---

### HIGH SEVERITY

---

**Issue 4 — No `enabled` guard on queries — race condition when `token` is null**

- **Files:** `web/app/(app)/dashboard/page.tsx`, `web/app/(app)/runs/page.tsx`, `web/app/(app)/usage/page.tsx`, `web/app/(app)/personas/page.tsx`, `web/components/sidebar.tsx`
- **Severity:** Warning (High)

Every `useQuery` call passes `token!` (non-null assertion) without an `enabled: !!token` guard. In the correct Clerk flow, `getToken()` is async and token may be null on the first render. This will cause spurious unauthenticated API requests with `Authorization: Bearer undefined` before auth resolves.

**Fix:** Add `enabled: !!token` to every query that depends on auth, or use the `getToken` approach in `queryFn`.

---

**Issue 5 — `create_run` in `app.py` references `auth.owner_id` but `AuthenticatedUser` has `user_id`**

- **File:** `council/api/app.py` lines 728, 785
- **Severity:** Bug (High)

`AuthenticatedUser` is defined as:
```python
@dataclass
class AuthenticatedUser:
    user_id: str
    tier: TierName
```

But `create_run` (line 728) accesses `auth.owner_id`:
```python
current_runs = _count_runs_this_month(await run_store.list_runs(owner_id=auth.owner_id))
```
and line 785:
```python
run = await run_store.create(... owner_id=auth.owner_id)
```

`auth.owner_id` does not exist on the dataclass — it should be `auth.user_id`. This is an `AttributeError` that will crash every `POST /runs` request. The same pattern appears in `get_run` (line 807), `list_runs` (line 821), `get_run_artifact` (line 849), `get_sandbox_stream` (lines 898, 907), `get_usage` (line 1008), `create_checkout` (line 1084), and `create_portal` (line 1103) — every endpoint that accesses `auth.owner_id`.

Note: `AuthContext = AuthenticatedUser` (line 577) so both aliases have the same bug.

**Fix:** Change all `auth.owner_id` to `auth.user_id` throughout `app.py`, OR add `owner_id` as an alias property to `AuthenticatedUser`:
```python
@property
def owner_id(self) -> str:
    return self.user_id
```

---

**Issue 6 — WebSocket auth bypasses Clerk JWT; only checks `API_SECRET_KEY`**

- **File:** `council/api/app.py` lines 1683–1701
- **Severity:** Warning (High)

The WebSocket endpoint at `/ws/{run_id}` only accepts the raw `API_SECRET_KEY` dev token:
```python
if not token or not secrets.compare_digest(token, expected):
    await websocket.close(code=4001)
```
It has no path for Clerk JWTs. Now that the REST endpoints accept Clerk JWTs as primary auth, the real-time feed will be silently broken for any user authenticated via Clerk (they cannot supply a matching `API_SECRET_KEY`).

Also, line 1700 uses `secrets.compare_digest(run.owner_id, token)` — but if a Clerk user created the run, their `owner_id` is a Clerk user ID (e.g. `user_2xyz`), not the API secret, making this check always fail.

---

**Issue 7 — `api.ts` missing `ApiKey` and `ApiKeyCreated` TypeScript types**

- **File:** `web/lib/api.ts`
- **Severity:** Warning (High)

`council/db/models.py` defines an `ApiKey` ORM model with fields `key_id`, `owner_id`, `name`, `key_prefix`, `created_at`, `last_used_at`, `is_active`. There are also no `GET /me/api-keys`, `POST /me/api-keys`, or `DELETE /me/api-keys` endpoints defined in `app.py`. The settings page shows a "API Key" section that simply copies the Clerk session token — not a real API key management UI.

If these endpoints exist or are planned, both the backend endpoints and the corresponding TS types (`ApiKey`, `ApiKeyCreated`) need to be added. As of this review, the DB model exists with no REST surface, and the frontend has no matching types. This is incomplete work.

---

### MEDIUM SEVERITY

---

**Issue 8 — `app/(app)/layout.tsx` is a Client Component but wraps the entire app shell**

- **File:** `web/app/(app)/layout.tsx`
- **Severity:** Warning (Medium)

This layout has `"use client"` at the top. In Next.js App Router, layout components are typically server components. Making this a client component prevents streaming SSR for child routes. With Clerk's middleware handling auth on the server, this layout's client-side redirect guard (already broken per Issue 3) is doubly redundant and harmful to performance.

**Fix:** Remove the auth guard from this layout entirely (rely on middleware) and remove `"use client"` unless the layout genuinely needs browser APIs.

---

**Issue 9 — `settings/page.tsx` displays and copies the Clerk JWT as "API Key"**

- **File:** `web/app/(app)/settings/page.tsx` lines 38–39, 67
- **Severity:** Warning (Medium)

```tsx
function copy() {
  if (!token) return;
  navigator.clipboard.writeText(token);
}
```

The Clerk JWT returned by `getToken()` is a short-lived session token (~60s TTL), not a stable API key. Copying it and using it in `Authorization: Bearer` headers from curl/scripts will result in immediate expiry failures. The UI label "API Key" and the description "Rotation requires a new key from your API dashboard" is misleading. Users should be directed to generate a proper `tc_live_*` API key (when that feature is built), not copy their session JWT.

---

**Issue 10 — `canExport` logic is always `true` when entitlements load**

- **Files:** `web/app/(app)/runs/page.tsx` line 347, `web/app/(app)/runs/[id]/page.tsx` line 329
- **Severity:** Warning (Medium)

```tsx
const exportEnabled = ent.data?.features ? true : false;
const canExport = ent.data?.features ? true : false;
```

This checks whether the `features` object exists, not whether any specific feature flag is set. Any user on any tier (even Trial) will see `exportEnabled = true` as soon as entitlements load, because all tiers return a `features` object. This should be gated on a specific feature flag (e.g. `ent.data?.features.api_access`) if export is meant to be a paid feature.

---

**Issue 11 — `stripe_webhook` test expects unverified events to succeed but `app.py` raises `RuntimeError`**

- **Files:** `tests/test_api.py` lines 219–238, `council/api/app.py` line 968–979
- **Severity:** Warning (Medium)

`TestStripeWebhook.test_webhook_without_secret_accepts_valid_json` deletes `STRIPE_WEBHOOK_SECRET` and expects HTTP 200. But the implementation raises `RuntimeError` unconditionally when `webhook_secret` is empty:
```python
if not webhook_secret:
    raise RuntimeError("STRIPE_WEBHOOK_SECRET must be set...")
```
A `RuntimeError` inside a FastAPI handler (not wrapped in `HTTPException`) will result in HTTP 500, not 200. The test should expect 500, or the implementation should be changed to allow unauthenticated webhooks in development (currently it cannot).

---

**Issue 12 — `hmac.new` does not exist; should be `hmac.new` → `hmac.HMAC` or `hmac.new`**

- **File:** `council/api/app.py` lines 1773, 1790
- **Severity:** Bug (Medium)

```python
expected_sig = "v0=" + hmac.new(
    zoom_secret.encode(), message.encode(), hashlib.sha256
).hexdigest()
```

Python's `hmac` module does not have a top-level `hmac.new` function. The correct call is `hmac.new(key, msg, digestmod)` — this actually does exist as `hmac.new` is an alias for the `HMAC` constructor in Python's standard library (it was deprecated in 3.4 and removed in 3.x). The correct modern usage is `hmac.HMAC(key, msg, digestmod).hexdigest()`. Verify this works with the installed Python version; if using 3.10+, this will raise `AttributeError: module 'hmac' has no attribute 'new'`.

---

**Issue 13 — `update_persona` loses `is_active=False` updates**

- **File:** `council/api/app.py` lines 1320–1322
- **Severity:** Bug (Medium)

```python
update_data = {k: v for k, v in body.model_dump().items() if v is not None}
```

`is_active=False` is a valid falsy value that will be filtered out by `if v is not None`. Deactivating a persona via `PUT /me/personas/{id}` with `{"is_active": false}` will silently no-op. The filter should be `if v is not None` changed to explicitly exclude `None` but preserve `False`:

```python
update_data = {k: v for k, v in body.model_dump().items() if v is not None}
```

Should be:
```python
update_data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
```

These are equivalent here, but the real issue is that `model_dump()` without `exclude_unset=True` will include all fields — including unset ones which default to `None`. The current code then strips `None`s, which is correct. However, `is_active=False` is NOT None so it would actually be included. Re-check: `body.model_dump()` returns all fields; `UpdatePersonaRequest` has `is_active: bool | None = None`; if the client sends `{"is_active": false}`, `body.is_active` is `False`, which is not `None`, so it IS included. This is actually fine. Mark as **Suggestion** only.

---

### LOW SEVERITY / SUGGESTIONS

---

**Issue 14 — Missing `"use client"` on `web/app/login/page.tsx`**

- **File:** `web/app/login/page.tsx`
- **Severity:** Warning (Medium)

This page uses `useState`, `useRouter`, `useUser`, and `useAuth` — all React hooks — but does not have `"use client"` at the top. In Next.js App Router, pages are server components by default. Without the directive, React will throw an error at runtime when these hooks are called.

---

**Issue 15 — `Persona` ORM model missing `is_prebuilt` and `source` fields**

- **Files:** `council/db/models.py` (Persona class), `council/api/app.py` (PersonaRecord Pydantic model)
- **Severity:** Warning (Low)

The `PersonaRecord` Pydantic model in `app.py` has `is_prebuilt: bool` and `source: str | None` fields. The `Persona` SQLAlchemy ORM model in `models.py` does NOT have these columns. When personas are migrated from in-memory to DB-backed, these fields will be silently dropped unless the schema migration includes them. The `to_dict()` method also omits `is_prebuilt`, `is_active`, and `source` fields that the frontend TypeScript `Persona` type expects.

---

**Issue 16 — `web/middleware.ts` matcher does not cover the `(app)` route group path prefix**

- **File:** `web/middleware.ts` lines 3–10
- **Severity:** Suggestion

The `isProtectedRoute` matcher correctly lists `/dashboard`, `/runs`, `/personas`, `/usage`, `/settings`, `/integrations`. In Next.js App Router, route groups like `(app)` are transparent — the URL remains `/dashboard` not `/(app)/dashboard`. This is correct and works as expected.

---

**Issue 17 — Rate-limit middleware only works with `API_SECRET_KEY`, not Clerk JWTs**

- **File:** `council/api/app.py` lines 282–287
- **Severity:** Warning (Low)

```python
if not secrets.compare_digest(token, api_secret):
    return response
```

The rate-limit header middleware bails out early for Clerk JWT tokens (they won't match `api_secret`). Rate-limit headers will be absent for all Clerk-authenticated users, reducing observability for production users.

---

**Issue 18 — Token passed as WebSocket query param appears in server logs**

- **File:** `council/api/app.py` line 1683, and comment at line 1679
- **Severity:** Suggestion

The code comment acknowledges this: `TODO: Security - move token to WebSocket subprotocol`. The token appears in access logs as a URL query parameter. This is a known issue but should be prioritized for production hardening.

---

**Issue 19 — `Persona` DB model `to_dict()` missing `is_active` field**

- **File:** `council/db/models.py` lines 139–151
- **Severity:** Suggestion

The ORM `Persona.to_dict()` does not include `is_active`, even though the column exists in the schema. The frontend TypeScript `Persona` type has `is_active: boolean`. When DB-backed personas are returned through `to_dict()`, this field will be missing, causing TypeScript/runtime mismatches.

---

## Items Verified as Correct

1. **`ClerkProvider` placement** — Correctly wraps everything in `web/app/layout.tsx` (line 37).
2. **Clerk imports** — Only `@clerk/nextjs` and `@clerk/nextjs/server` are used; no legacy imports present.
3. **`middleware.ts` structure** — Correctly uses `clerkMiddleware` + `createRouteMatcher`; matcher config correctly excludes `_next`, static files, and media.
4. **`AuthProvider` hook implementation** — `useCallback` dependencies are correct (`[clerkGetToken]`, `[signOut]`). No React hooks violations. `"use client"` is present.
5. **API contract — core fields match:**
   - `Run` TS type matches `RunResponse` Pydantic model (all fields: `run_id`, `question`, `status`, `created_at`, `started_at`, `finished_at`, `result`, `error`).
   - `Entitlements` TS type matches `/me/entitlements` response schema.
   - `Usage` TS type matches `/me/usage` response schema.
   - `Billing` TS type matches `/me/billing` response schema.
   - `Persona` TS type matches `PersonaRecord` model fields (including `is_prebuilt`, `source`, `mbti`, `job_role`).
   - `CouncilConfig` TS type matches `/me/config` response schema.
6. **`queryKey` consistency** — All call sites use consistent keys: `["runs"]`, `["run", id]`, `["entitlements"]`, `["usage"]`, `["billing"]`, `["personas"]`, `["council-config"]`.
7. **Clerk JWT verification in backend** — `_verify_clerk_jwt` correctly validates `exp`, `sub`, `iss` claims using RS256 and a JWKS client.
8. **Auth priority ladder** — Backend correctly tries Clerk JWT first, then `tc_*` API key, then dev secret. The ordering is sensible.
9. **`AuthProvider` is inside `ClerkProvider`** — In `providers.tsx` → `auth.tsx`, `useClerkAuth()` is called inside `AuthProvider`, which is rendered inside `<ClerkProvider>` from the root layout. This is correct.
10. **`sidebar.tsx` — `enabled: !!token` guard** — The sidebar correctly has `enabled: !!token` on its entitlements query (line 48). This is the only component with a correct guard; all pages lack it.
11. **Stripe URL validation** — `validateStripeUrl` in `usage/page.tsx` is correctly implemented and applied before redirecting.
12. **DB session fallback** — `council/db/session.py` gracefully returns `None` engine when `DATABASE_URL` is unset, enabling test environments without Postgres.
13. **Test hermetic setup** — `tests/test_api.py` correctly sets `API_SECRET_KEY` before importing the app, ensuring dev-fallback auth works in CI.
14. **`CORS` and security headers** — CORS origins are configurable via `CORS_ORIGINS` env var; security headers (`X-Content-Type-Options`, `X-Frame-Options`, `HSTS`, `X-XSS-Protection`) are applied globally.
15. **`useMutation` handlers** — `portal`, `checkout`, `create` (runs), `create`/`update`/`del`/`toggleActive` (personas) all have `onSuccess` handlers. `onError` is present on run create and persona create/questionnaire mutations.

---

## Suggested Fixes Summary

### Fix Priority 1 (Blocking — fix before any user-facing release)

**Issue 1 + Issue 3 + Issue 5 (auth.owner_id):** These three together make the application completely non-functional post-migration.

For Issues 1 & 3, choose one approach:

**Option A (minimal change):** Add a reactive `token` state to `AuthProvider`:
```tsx
// web/lib/auth.tsx
interface AuthCtx {
  getToken: () => Promise<string | null>;
  token: string | null;       // <-- add this
  isLoading: boolean;
  logout: () => void;
}

// In AuthProvider:
const [token, setToken] = useState<string | null>(null);
useEffect(() => {
  if (!isLoaded) return;
  clerkGetToken().then(t => setToken(t)).catch(() => setToken(null));
  // Optionally set up a refresh interval
}, [isLoaded, clerkGetToken]);
```

**Option B (correct Clerk pattern):** Convert every `queryFn` to call `getToken()` first:
```tsx
queryFn: async () => {
  const t = await getToken();
  if (!t) throw new Error("Not authenticated");
  return api.getEntitlements(t);
},
enabled: !isLoading,
```

For Issue 5, add an `owner_id` property alias to `AuthenticatedUser`:
```python
@dataclass
class AuthenticatedUser:
    user_id: str
    tier: TierName

    @property
    def owner_id(self) -> str:
        return self.user_id
```

**Issue 2 (login.tsx `login()`):** Remove the API key form entirely (Clerk handles auth) or implement a proper `login(apiKey: string)` method in `AuthProvider` that stores the key and integrates with `getToken()`.

**Issue 14 (missing `"use client"` in login page):** Add `"use client";` at the top of `web/app/login/page.tsx`.

### Fix Priority 2 (Before production hardening)

- **Issue 6:** Add Clerk JWT support to the WebSocket auth path.
- **Issue 11:** Fix `stripe_webhook` test expectation or allow unauthenticated dev webhooks.
- **Issue 12:** Verify `hmac.new` works on the deployed Python version; replace with `hmac.HMAC(...)` if needed.
- **Issue 4:** Add `enabled: !!token` to all `useQuery` calls in pages.

### Fix Priority 3 (Housekeeping)

- **Issue 10:** Gate `canExport`/`exportEnabled` on a specific feature flag, not just presence of the features object.
- **Issue 7:** Implement `GET/POST/DELETE /me/api-keys` endpoints and add `ApiKey`/`ApiKeyCreated` TS types.
- **Issue 15:** Add `is_prebuilt`, `source`, `is_active` columns to the `Persona` ORM model.
- **Issue 8:** Remove `"use client"` from `app/(app)/layout.tsx` and rely solely on middleware for auth.
- **Issue 9:** Replace the Clerk JWT display in settings with real API key management UI.
