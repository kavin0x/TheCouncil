# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **Keep this file up to date.** After any semi-significant or large codebase change (new features, architectural shifts, schema changes, new environment variables, renamed modules, etc.), update the relevant sections of this file so the context stays accurate.

## Project Overview

**TheCouncil** is a multi-agent AI deliberation SaaS platform. A FastAPI backend orchestrates structured debates between LLM personas; a Next.js frontend provides the dashboard and marketing site.

## Commands

### Python Backend

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then populate secrets

# Run API
uvicorn council.api.app:app --reload

# Run migrations
python -m council.db.migrations

# Tests
pytest tests/ -q
pytest tests/test_foo.py::test_bar -q  # single test

# Lint
ruff check .
```

### Web Frontend

```bash
cd web
npm ci
npm run dev          # dev server (port 3000, proxies API at :8000)
npm run build
npm run test         # Vitest unit tests
npm run test:e2e     # Playwright E2E
npm run lint
npm run typecheck
```

### Docker (full stack)

```bash
docker-compose up -d   # postgres, redis, api, worker, nginx
```

## Architecture

### Service Layout

```
Next.js (port 3000)
    ↓  HTTP + Bearer token
FastAPI (port 8000)
    ↓
PostgreSQL (SQLAlchemy async)  +  Redis Streams (event bus)  +  External APIs
    ↓
Celery Worker (separate process or in-process fallback)
```

### Debate Engine (`council/core/`)

Runs are executed in 5 structured phases:
1. **Independent Takes** — agents respond in parallel, no cross-knowledge
2. **Cross-Debate I** — sequential rebuttals
3. **Private Deliberation** — direct messages between agents
4. **Cross-Debate II** — final sequential round
5. **Resolution & Vote** — each agent proposes a resolution; all vote; tie-breaker if needed

Run lifecycle: `PENDING → RUNNING → COMPLETED | FAILED`

Long-running runs are enqueued via Celery (`council/worker/`). Set `COUNCIL_DISABLE_WORKER=1` to run in-process (dev/test).

### Personality Modes (`council/features/personalities.py`)

Four modes configure how agent personas are created:
- **CANNED** — hardcoded personas (Security Architect, Red Teamer, etc.)
- **DYNAMIC** — LLM-generated at runtime from the debate topic
- **HYBRID** — mix of canned + dynamic
- **GENERATED** — cloned from user-provided text

Agents also have **Job Roles** (Devil's Advocate, Moderator, Domain Expert, Contrarian, Synthesizer) injected into system prompts.

### Real-time Events (`council/bus/`, `council/realtime.py`)

Events are published per-run to Redis Streams (`council:run:{run_id}:events`) and broadcast over WebSocket (`/ws/{run_id}`). Falls back to in-process broadcasting if Redis is unavailable. Event types: `run_started`, `agent_response`, `agent_delta`, `agent_dm`, `resolution_vote`, `run_completed`, `run_failed`.

### Database (`council/db/`)

SQLAlchemy 2.0 async with asyncpg. Key tables: `users`, `deliberations`, `personas`, `artifacts`, `usage_events`, `api_keys`. Run `python -m council.db.migrations` to apply schema.

The `users` table has `tos_accepted_at` (Float, nullable) and `tos_version` (String(32), nullable) columns for ToS tracking. The `User` ORM model lives in `council/db/models.py`.

The `api_keys` table stores user-generated programmatic API keys. The `ApiKey` ORM model (`council/db/models.py`) has fields: `id`, `owner_id` (Clerk user ID), `name`, `key_hash` (sha256 — plaintext is never stored), `key_prefix` (display only), `created_at`, `last_used_at`, `is_active`.

### Subscription Tiers

Features are gated by tier (Trial → Basic → Pro → Ultra → Enterprise). Tier logic lives in `council/models/`. Stripe webhooks at `POST /webhooks/stripe` manage subscription lifecycle.

### Rate-Limit Headers

`POST /runs` and persona-creation endpoints (`POST /me/personas`, `POST /me/personas/questionnaire`) return `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers via the `add_rate_limit_headers` middleware in `council/api/app.py`.

### Legal / ToS Endpoints

- `POST /api/legal/accept` — record ToS acceptance (body: `{"version": "2026-04-01"}`). Stores timestamp + version. Update `CURRENT_TOS_VERSION` in `app.py` when the ToS changes.
- `GET  /api/legal/status` — returns `tos_accepted`, `current_version`, `accepted_version`, `accepted_at`.

Accepted ToS data is currently stored in-memory (`_tos_store`) and should be migrated to the `users` table (`tos_accepted_at` / `tos_version` columns) when full DB-backed auth lands.

### Web App (`web/`)

Next.js 16 with React 19, Tailwind CSS 4, TanStack Query, and Radix UI. Uses App Router (`web/app/`). API client and TypeScript types are in `web/lib/api.ts`.

**Important:** This uses Next.js 16, which has breaking changes from earlier versions. Read the relevant guide in `web/node_modules/next/dist/docs/` before writing frontend code.

TypeScript types in `web/lib/api.ts` mirror the Python Pydantic models — keep them in sync when changing backend schemas.

Auth is handled by `@clerk/nextjs` 7.2.3. `web/middleware.ts` uses `clerkMiddleware()` to protect app routes (`/dashboard`, `/runs`, `/personas`, `/usage`, `/settings`, `/integrations`). `web/app/layout.tsx` wraps `<body>` in `<ClerkProvider>`. See the **Authentication** section below for the full auth architecture.

### Authentication

Three-tier auth stack (tried in order by the `get_current_user` FastAPI dependency):

1. **Clerk JWT** (browser) — `@clerk/nextjs` session tokens, validated via JWKS (RS256, validates `exp` + `iss` + `sub`). `CLERK_ISSUER_URL` must be set.
2. **API Keys** (programmatic/CLI) — user-generated `tc_live_...` keys, sha256-hashed in the `api_keys` DB table. Users create these from `/settings` in the dashboard.
3. **API_SECRET_KEY** (dev fallback) — single static key used when `CLERK_ISSUER_URL` is not configured.

Backend auth dataclass: `AuthenticatedUser` with fields `user_id` (Clerk `sub` claim or `owner_id`) and `tier`.

API key endpoints:
- `POST /me/api-keys` — generate a new key (body: `{name?: string}`); plaintext returned once only
- `GET /me/api-keys` — list active keys (no plaintext)
- `DELETE /me/api-keys/{key_id}` — revoke a key

Frontend auth helpers (`web/lib/auth.tsx`): `useAuth()` exposes `getToken: () => Promise<string | null>`, `isLoading`, and `logout`. All `api.*` methods in `web/lib/api.ts` accept `getToken` (not a raw string token).

### MCP Server

A FastMCP server is mounted at `/mcp` on the FastAPI app, exposing council debates as tools for IDE clients (Cursor, Claude Desktop).

## Key Environment Variables

```bash
OPENROUTER_API_KEY=...          # Primary LLM provider
XAI_API_KEY=...                 # Optional: native Grok (cheaper)
API_SECRET_KEY=...              # Dev fallback bearer token (used when CLERK_ISSUER_URL is not set)
DATABASE_URL=postgresql+asyncpg://council:council@localhost:5432/council
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
STRIPE_SECRET_KEY=...           # Payments
TAVILY_API_KEY=...              # Web search (Pro+ tier)
E2B_API_KEY=...                 # Desktop sandbox (Ultra+ tier)
COUNCIL_DISABLE_WORKER=0        # 1 = run Celery in-process
COUNCIL_GUARDRAILS=1            # 0 = disable content guardrails

# Clerk auth (backend)
CLERK_ISSUER_URL=https://your-clerk-domain.clerk.accounts.dev  # Backend JWT validation via JWKS
CLERK_SECRET_KEY=sk_...                                        # Optional: Clerk backend SDK

# Clerk auth (frontend — web/.env.local)
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...                       # Frontend Clerk init
```
