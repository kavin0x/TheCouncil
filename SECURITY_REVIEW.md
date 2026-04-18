# Security Review: Auth Migration (Static API Key → Clerk JWT + User API Keys)

**Reviewer:** Claude (automated)
**Date:** 2026-04-17
**Scope:** Auth migration from a single `API_SECRET_KEY` to Clerk JWT + user-generated API keys (`tc_*` prefix)
**Files Reviewed:**
- `council/api/app.py`
- `web/middleware.ts`
- `web/lib/auth.tsx`
- `web/lib/api.ts`
- `council/db/models.py`
- `requirements.txt`
- `web/.env.local.example`

---

## Summary

The auth migration is structurally sound and follows several good practices (RS256, `exp`/`iss` validation, sha256 key hashing, constant-time comparisons). However, there are critical and high-severity gaps that must be addressed before production use:

1. **No API key management REST endpoints exist** — the `ApiKey` model and `_verify_api_key()` helper are implemented but there are no `POST /me/keys`, `GET /me/keys`, or `DELETE /me/keys/{id}` endpoints. Users cannot create or revoke keys through the API; the frontend `auth.tsx` has a `login(key)` function but no way to generate a key server-side.
2. **The frontend stores the API key in `localStorage`**, exposing it to any XSS attack.
3. **An invalid Clerk JWT silently falls through** to the API-key and dev-secret checks, creating an auth-bypass vector.
4. **`CLERK_ISSUER_URL` is not validated for format**, enabling SSRF if the env var is attacker-influenced.
5. **The rate-limit middleware is not updated** to emit headers for Clerk JWT users, only for dev-mode token users.
6. **WebSocket auth passes the bearer token as a URL query parameter**, where it appears in server logs and reverse-proxy access logs.

---

## Findings

### CRITICAL

#### C1 — Auth bypass: invalid JWT silently falls through to legacy secret
**Severity:** Critical
**File:** `council/api/app.py` lines 600–636

**Description:** `get_current_user` checks `if token.startswith("eyJ")` to decide whether to attempt JWT validation. If the JWT is structurally valid (starts with `eyJ`) but fails validation (expired, wrong issuer, tampered signature), `_verify_clerk_jwt()` returns `None`. The function then continues to the `tc_*` prefix check, and if that also misses, falls through to `secrets.compare_digest(token, api_secret)`. An attacker who knows or can guess the `API_SECRET_KEY` could craft a token beginning with `eyJ` that fails JWT validation but matches the dev secret — the logic order creates no barrier to that scenario. More practically, a legitimately expired Clerk JWT that happens to equal the `API_SECRET_KEY` value would be silently authenticated as `"dev"`.

The safer pattern is: **if a token starts with `eyJ`, treat validation failure as a hard 401 — do not continue the fallback chain**.

```python
# RECOMMENDED
if token.startswith("eyJ"):
    user_id = _verify_clerk_jwt(token)
    if user_id:
        return AuthenticatedUser(user_id=user_id, tier=_resolve_request_tier())
    raise HTTPException(status_code=401, detail="Invalid credentials")
```

**Recommendation:** Fail hard when a JWT-shaped token fails JWT validation. Never let a failed JWT fall through to a secret-key comparison.

---

#### C2 — No API key creation or revocation endpoints
**Severity:** Critical
**File:** `council/api/app.py` (entire file), `web/lib/auth.tsx` lines 38–40

**Description:** The `ApiKey` ORM model (`council/db/models.py:278`) and `_verify_api_key()` helper (`app.py:148`) are fully implemented, but there are zero REST endpoints for key management. A user has no server-side way to:
- Generate a `tc_live_*` key
- List their existing keys
- Revoke a key

The frontend `AuthProvider.login(key)` function accepts a key and stores it in localStorage, which means the intended flow (user generates key → frontend stores it) is architecturally wired but the generation side is entirely missing. If this code is deployed as-is, users cannot authenticate via user-generated API keys at all.

**Recommendation:** Implement the following endpoints before enabling the API key auth path in production:
- `POST /me/keys` — generate key using `secrets.token_hex(32)`, store `sha256` hash, return plaintext once
- `GET /me/keys` — list key metadata (`key_prefix`, `name`, `created_at`, `last_used_at`)
- `DELETE /me/keys/{key_id}` — soft-delete (set `is_active=False`), enforce `owner_id` check

---

### HIGH

#### H1 — API key stored in `localStorage` (XSS exposure)
**Severity:** High
**File:** `web/lib/auth.tsx` lines 12, 34–36, 38–40

**Description:** The constant `STORAGE_KEY = "tc_api_key"` and the `useEffect` that reads from `localStorage` mean the user's long-lived API key is stored in `localStorage` where any JavaScript running in the same origin — including from XSS — can read it. Unlike `sessionStorage`, `localStorage` persists indefinitely across tabs and browser restarts. A single stored XSS payload or malicious browser extension exfiltrates this key permanently.

```typescript
// auth.tsx:34-36
const stored = localStorage.getItem(STORAGE_KEY);   // <-- persists across sessions
if (stored) setApiKey(stored);
```

**Recommendation:** For long-lived API keys, consider storing them in an `HttpOnly` cookie via a Next.js API route (`/api/auth/set-key`) rather than `localStorage`. If `localStorage` is kept, document the risk and pair it with a strict CSP that prevents inline scripts.

---

#### H2 — Bearer token passed as URL query parameter in WebSocket
**Severity:** High
**File:** `council/api/app.py` lines 1671–1693

**Description:** WebSocket auth uses `?token=<bearer>` in the URL query string:
```python
token = websocket.query_params.get("token", "")
```
The token appears verbatim in:
- Nginx/Apache/proxy access logs
- Browser history
- Server-side framework debug logs
- Referrer headers if the client navigates away

The code even has a comment acknowledging this: `# TODO: Security - move token to WebSocket subprotocol or post-connect auth message`

**Recommendation:** Implement the TODO. Use one of:
1. WebSocket subprotocol header: `Sec-WebSocket-Protocol: bearer.<token>`
2. First message auth: client sends `{"type": "auth", "token": "..."}` immediately after connection, server validates before accepting any other messages

---

#### H3 — `CLERK_ISSUER_URL` not validated for format (SSRF risk)
**Severity:** High
**File:** `council/api/app.py` lines 121–125

**Description:** `_get_jwks_client()` constructs the JWKS URL directly from `CLERK_ISSUER_URL` without validating that it is a `https://` URL pointing to `*.clerk.com` or `*.clerk.accounts.dev`:

```python
issuer = os.getenv("CLERK_ISSUER_URL", "").rstrip("/")
return PyJWKClient(f"{issuer}/.well-known/jwks.json", ...)
```

If `CLERK_ISSUER_URL` is misconfigured or an attacker can influence the environment (e.g. via a `.env` file injection, misconfigured secrets manager), the server will make an outbound HTTP request to an arbitrary URL on every key fetch. In containerised or cloud environments, this can be used to hit the IMDS endpoint (`http://169.254.169.254/...`).

**Recommendation:** Validate `CLERK_ISSUER_URL` at startup:

```python
import re
_CLERK_ISSUER_RE = re.compile(r'^https://[a-zA-Z0-9\-]+\.(clerk\.com|clerk\.accounts\.dev)$')
if not _CLERK_ISSUER_RE.match(issuer):
    raise RuntimeError(f"CLERK_ISSUER_URL has invalid format: {issuer!r}")
```

---

#### H4 — Rate-limit middleware skips Clerk JWT and API key users
**Severity:** High
**File:** `council/api/app.py` lines 280–305

**Description:** The updated `add_rate_limit_headers` middleware was partially updated to handle the new auth types. The logic resolves `owner_id` for Clerk JWTs and `tc_*` API keys, but the tier used for limit computation is `_resolve_request_tier()` which reads from `DEFAULT_SUBSCRIPTION_TIER` env var — a single global value. When multiple users with different tiers use the service, all of them get the same global tier's limit in the header, which is misleading and could allow users to see limits that are not theirs.

More specifically, the rate-limit headers are decorative (the actual enforcement is in `POST /runs`), but sending incorrect `X-RateLimit-Remaining` values could cause clients to implement incorrect client-side throttling.

**Recommendation:** Once the DB-backed user-tier mapping lands (Stripe webhook → `users` table), look up the per-user tier in the middleware instead of reading the global env var.

---

### MEDIUM

#### M1 — `_verify_api_key` contains a race condition / dirty write on `last_used_at`
**Severity:** Medium
**File:** `council/api/app.py` lines 148–173

**Description:** The function mutates `api_key.last_used_at` and calls `await session.commit()` within the same session that performed the `SELECT`. Under high concurrency, multiple in-flight requests for the same key will each load the model into the same session, mutate it, and commit — producing spurious conflicts or silently overwriting each other depending on SQLAlchemy's identity map behaviour. This is not a security vulnerability per se but can cause session integrity issues.

**Recommendation:** Use an explicit `UPDATE` statement instead of mutating the loaded ORM object:

```python
from sqlalchemy import update
await session.execute(
    update(ApiKeyModel)
    .where(ApiKeyModel.id == api_key.id)
    .values(last_used_at=time.time())
)
await session.commit()
```

---

#### M2 — `ApiKey` model has no per-user key count limit in the DB layer
**Severity:** Medium
**File:** `council/db/models.py` lines 278–305

**Description:** The `ApiKey` model has no database-level constraint on the number of active keys per `owner_id`. Without a REST endpoint to create keys, this is currently moot, but when the creation endpoint is added, there must be a server-side limit (e.g. max 10 active keys per user) to prevent key-flooding abuse. The persona creation endpoint has this limit (`max_saved_personas`); the API key endpoint should mirror it.

**Recommendation:** Enforce a tier-based or flat maximum in the `POST /me/keys` handler and document it.

---

#### M3 — `allow_credentials: True` CORS with origin from env var
**Severity:** Medium
**File:** `council/api/app.py` lines 236–243

**Description:** CORS is configured with `allow_credentials=True` and origins from `CORS_ORIGINS` env var (defaulting to `http://localhost:3000`). This is correct for development, but if `CORS_ORIGINS` were mistakenly set to `*` in production, the combination of `allow_credentials=True` and a wildcard origin would be rejected by browsers but represents a configuration risk. Additionally, there is no startup validation that `CORS_ORIGINS` is not `*`.

**Recommendation:** Add a startup assertion:

```python
if "*" in _cors_origins and os.getenv("ALLOW_WILDCARD_CORS") != "1":
    raise RuntimeError("CORS_ORIGINS must not be '*' when allow_credentials=True")
```

---

#### M4 — Error message leaks which auth method was attempted in `get_current_user`
**Severity:** Medium (Low in practice — message is generic, but the *flow* leaks information)
**File:** `council/api/app.py` lines 595–621

**Description:** The fallback chain in `get_current_user` is deterministic and prefix-based (`eyJ` → JWT, `tc_` → DB key, else → dev secret). An attacker probing the API can infer from response timing which authentication path their crafted token enters, because:
- JWT path involves cryptographic verification (slower on first call)
- API key path involves a DB query (variable latency)
- Dev secret path involves a constant-time local compare (fastest)

The 401 detail message is correctly generic (`"Invalid credentials"`) but timing side-channels remain. This is low-risk in practice as the timing difference is small and non-exploitable without sustained access, but worth noting.

**Recommendation:** Document the timing behaviour. If this becomes a concern, add a uniform random sleep of ~5ms on all 401 paths.

---

#### M5 — No CSP header set
**Severity:** Medium
**File:** `council/api/app.py` lines 247–253

**Description:** The `add_security_headers` middleware sets `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, and `X-XSS-Protection`, but does not set a `Content-Security-Policy` header. Given that the API key is stored in `localStorage` (see H1), a CSP would be the primary mitigation against XSS-based key theft on the backend API responses.

**Recommendation:** Add a restrictive CSP to API responses. For a pure JSON API, `default-src 'none'` is appropriate. For the Next.js frontend, configure CSP in `next.config.js` headers.

---

### LOW

#### L1 — `CLERK_SECRET_KEY` is present in `.env.local.example` as a placeholder
**Severity:** Low (Info — no actual secret present, but note for hygiene)
**File:** `web/.env.local.example` line 6

**Description:** The example file contains `CLERK_SECRET_KEY=sk_test_...`. The value is a placeholder and not a real secret. However, `CLERK_SECRET_KEY` is a server-side secret that should never appear in the browser bundle. It is declared in `.env.local` (server-only in Next.js), so it should not leak — but any developer who accidentally prefixes it with `NEXT_PUBLIC_` in their local `.env.local` would expose it.

**Recommendation:** Add a comment in the example file:

```
# IMPORTANT: Never prefix CLERK_SECRET_KEY with NEXT_PUBLIC_ — it must remain server-only.
```

---

#### L2 — WebSocket owner_id check uses `secrets.compare_digest` on potentially different-length strings from new auth
**Severity:** Low
**File:** `council/api/app.py` lines 1722

**Description:** The WebSocket handler compares `run.owner_id` (which is now a Clerk user ID like `user_2xyz...`) with `token` (which in the new auth world could be a Clerk JWT, an API key, or the dev secret):

```python
if not run.owner_id or not secrets.compare_digest(run.owner_id, token):
```

With the new auth model, `token` will be the raw JWT (hundreds of bytes), while `run.owner_id` will be the resolved Clerk user ID (short string). These are structurally different, so this comparison will always fail for Clerk JWT users — meaning Clerk-authenticated users cannot use WebSockets at all. The WebSocket endpoint needs to validate the token the same way `get_current_user` does and compare the resolved `user_id` against `run.owner_id`.

**Recommendation:** Resolve the token to a `user_id` in the WebSocket handler the same way `get_current_user` does, then compare `run.owner_id == resolved_user_id`.

---

#### L3 — `hmac.new` should be `hmac.new` — verify correct module is used in Zoom webhook
**Severity:** Low
**File:** `council/api/app.py` lines 1764, 1781

**Description:** The code calls `hmac.new(...)`, but the standard library uses `hmac.new` (this is correct). The import at the top of the file is `import hmac`, so this is fine. However, `hashlib` is also imported separately. No bug here, but worth confirming the `hmac` module usage is from stdlib and not confused with the `hashlib.hmac` shim in some environments.

**Status:** Confirmed correct — no action needed.

---

#### L4 — `_tos_store` is in-memory and not migrated to DB
**Severity:** Low (acknowledged technical debt)
**File:** `council/api/app.py` lines 1507–1509, CLAUDE.md

**Description:** ToS acceptance is stored in the process-local `_tos_store` dict. On server restart or in multi-process deployments, all acceptance records are lost, and users would be required to re-accept on every restart. This is documented as known debt in CLAUDE.md.

**Recommendation:** Migrate to the `users` table (`tos_accepted_at` / `tos_version` columns) which are already defined in `council/db/models.py:59-60`.

---

## Positive Findings (Done Well)

- **RS256 only.** `_verify_clerk_jwt` specifies `algorithms=["RS256"]` — symmetric HS256 is not accepted. This is correct and important.
- **All three required claims validated.** `exp`, `sub`, and `iss` are required via `options={"require": [...]}` and `issuer=issuer` is passed to `jwt.decode`. PyJWT will raise if any of these fail.
- **JWKS cached with TTL.** `PyJWKClient(cache_jwk_set=True, lifespan=3600)` with `@lru_cache(maxsize=1)` ensures the JWKS endpoint is not hit on every request. The 1-hour TTL is reasonable.
- **JWT validation exceptions silently return `None`.** `_verify_clerk_jwt` wraps everything in `try/except Exception: return None`, so no JWT error details leak to clients.
- **API key hashed with SHA-256.** `_verify_api_key` computes `hashlib.sha256(raw_key.encode()).hexdigest()` — plaintext keys are never stored in the database.
- **DB lookup by hash is collision-safe.** Looking up a SHA-256 hex digest in a unique-indexed column is not vulnerable to timing attacks (index equality check is functionally constant-time within the DB engine).
- **Dev secret comparison is constant-time.** `secrets.compare_digest` is used consistently in all three places where `API_SECRET_KEY` is compared.
- **`owner_id` excluded from `RunResponse`.** `RunResponse.from_run` pops `owner_id` before serialising, so the bearer token (used as `owner_id` in dev mode) is never echoed back to clients.
- **Security headers present.** `X-Content-Type-Options`, `X-Frame-Options`, and `Strict-Transport-Security` are set on every response.
- **CORS origins restricted by default.** Default is `http://localhost:3000`; production origins must be explicitly set via `CORS_ORIGINS`.
- **No JWT token logged.** Grep found no `console.log` or Python `logger.*` calls that would log the token value. The WebSocket handler explicitly documents this: `IMPORTANT: Never log token`.
- **Clerk middleware protects all app routes.** `web/middleware.ts` protects `/dashboard`, `/runs`, `/personas`, `/usage`, `/settings`, `/integrations` via `createRouteMatcher` + `auth.protect()`.
- **`.env.local.example` contains no real secrets.** All values are placeholders.
- **`PyJWT>=2.8.0` in `requirements.txt`.** This version is not affected by known JWT confusion vulnerabilities.

---

## Priority Action Items

| Priority | Issue | Action |
|---|---|---|
| P0 | C1 — JWT fall-through bypass | Fail hard on invalid JWT, don't continue fallback chain |
| P0 | C2 — No key management endpoints | Implement POST/GET/DELETE /me/keys before enabling tc_* auth |
| P1 | H1 — API key in localStorage | Move to HttpOnly cookie or document XSS risk prominently |
| P1 | H2 — WS token in query string | Implement post-connect auth message per existing TODO |
| P1 | L2 — WS owner_id check broken for JWT users | Fix WebSocket to resolve token → user_id before comparing |
| P2 | H3 — SSRF via CLERK_ISSUER_URL | Validate URL format at startup against known Clerk domains |
| P2 | H4 — Rate-limit headers show wrong tier | Fix after DB-backed user-tier mapping is available |
| P3 | M3 — CORS wildcard guard | Add startup assertion |
| P3 | M5 — No CSP header | Add CSP to API responses and Next.js config |
