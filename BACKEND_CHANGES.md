# Backend Changes — Clerk Auth Integration

## Summary

Replaced the single static `API_SECRET_KEY` auth with a three-tier auth system supporting Clerk JWTs, user-generated API keys, and the legacy dev-fallback key.

---

## Files Modified

### `requirements.txt`
- Added `PyJWT>=2.8.0` for RS256 JWT verification.

---

### `council/db/models.py`
- Added `ApiKey` ORM model (`__tablename__ = "api_keys"`) with fields: `id`, `owner_id`, `name`, `key_hash` (sha256), `key_prefix`, `created_at`, `last_used_at`, `is_active`.
- Key is never stored in plaintext — only the sha256 hex digest.

---

### `council/db/session.py`
- Added `from contextlib import asynccontextmanager` import.
- Renamed `get_session` (FastAPI async-generator dependency) to `get_session_dep` and kept `get_session = get_session_dep` alias for backward compatibility.
- Added `get_session_ctx()` — a proper `@asynccontextmanager` for use outside of FastAPI's dependency injection (used in auth helpers and API key endpoints).

---

### `council/api/app.py`

#### New imports
- `base64`, `functools.lru_cache` — auth utilities.
- `jwt` (PyJWT), `jwt.PyJWKClient` — Clerk JWT verification.
- `council.db.session.get_engine`, `council.db.session.get_session_ctx` — DB access.

#### New auth functions
- `_get_jwks_client()` — `@lru_cache` singleton that fetches Clerk JWKS from `CLERK_ISSUER_URL/.well-known/jwks.json`. Returns `None` when `CLERK_ISSUER_URL` is unset.
- `_verify_clerk_jwt(token)` — validates RS256 JWT, returns Clerk `sub` (user ID) or `None`.
- `_verify_api_key(raw_key)` — hashes the key, looks up in `api_keys` table, updates `last_used_at`, returns `owner_id` or `None`.

#### New auth dataclass: `AuthenticatedUser`
- Fields: `user_id: str`, `tier: TierName`.
- `@property owner_id` — backward-compatible alias returning `user_id`.
- `AuthContext = AuthenticatedUser` alias keeps all existing route handler code unchanged.

#### New auth dependency: `get_current_user`
Replaces the old `require_auth`. Priority order:
1. Clerk JWT (tokens starting with `eyJ`) — verified via JWKS.
2. User API key (tokens starting with `tc_`) — DB lookup.
3. `API_SECRET_KEY` dev fallback — constant-time comparison; resolves to `user_id="dev"`.

`require_auth = get_current_user` alias maintains backward compatibility.

#### Updated `add_rate_limit_headers` middleware
- Now uses the same three-tier priority chain (Clerk JWT → API key → dev fallback) to resolve `owner_id` instead of hardcoding `API_SECRET_KEY` comparison.

#### Updated CORS headers
- Added `"clerk-session-id"` to `allow_headers`.

#### New API key management endpoints
- `POST /me/api-keys` — generates a `tc_live_<64-hex-chars>` key, stores sha256 hash, returns plaintext key once.
- `GET /me/api-keys` — lists active keys for the authenticated user (no plaintext).
- `DELETE /me/api-keys/{key_id}` — soft-deletes (sets `is_active=False`) the caller's key.

#### New Pydantic models
- `ApiKeyCreate`, `ApiKeyResponse`, `ApiKeyCreated` (extends `ApiKeyResponse` with `plaintext_key`).

---

### `tests/test_api.py`
- Replaced `test_cannot_access_other_users_run` (which relied on the old behavior where each unique `API_SECRET_KEY` was a distinct identity) with `test_invalid_token_returns_401` — verifies that a token matching none of the three auth paths returns 401.
- All other tests continue to use `Authorization: Bearer test-secret-key` which passes through the dev fallback path unchanged.

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `CLERK_ISSUER_URL` | Optional | Enables Clerk JWT verification (e.g. `https://clerk.your-domain.com`). Omit for dev. |
| `API_SECRET_KEY` | Required (dev) | Legacy single-key dev fallback. Still works when Clerk vars are absent. |
| `DATABASE_URL` | Optional | Required for DB-backed API key operations. Without it, API key endpoints return 503. |

---

## Migration Notes

- Run `python -m council.db.migrations` to create the new `api_keys` table.
- No breaking changes to existing API consumers — `API_SECRET_KEY` Bearer auth continues to work.
- Existing `AuthContext` references in route handlers are unaffected (aliased to `AuthenticatedUser`).
