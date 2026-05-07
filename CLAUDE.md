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
uvicorn council.api.app:app --reload --reload-dir council --reload-dir tests --reload-exclude 'web/*' --reload-exclude 'node_modules/*' --reload-exclude '.next/*' --reload-exclude '.venv/*'

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

```text
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

Events are published per-run to Redis Streams (`council:run:{run_id}:events`) and broadcast over WebSocket (`/ws/{run_id}`). Falls back to in-process broadcasting if Redis is unavailable. WebSocket auth now prefers the `Sec-WebSocket-Protocol` bearer token; query-token fallback is opt-in via `ALLOW_WEBSOCKET_QUERY_TOKEN=1`. Event types: `run_started`, `agent_response`, `agent_delta`, `agent_dm`, `resolution_vote`, `run_completed`, `run_failed`.

### Database (`council/db/`)

SQLAlchemy 2.0 async with asyncpg. Key tables: `users`, `deliberations`, `personas`, `artifacts`, `usage_events`, `api_keys`. Run `python -m council.db.migrations` to apply schema.

The `users` table has `tos_accepted_at` (Float, nullable) and `tos_version` (String(32), nullable) columns for ToS tracking. The `User` ORM model lives in `council/db/models.py`.

The `api_keys` table stores user-generated programmatic API keys. The `ApiKey` ORM model (`council/db/models.py`) has fields: `id`, `owner_id` (Clerk user ID), `name`, `key_hash` (sha256 — plaintext is never stored), `key_prefix` (display only), `created_at`, `last_used_at`, `is_active`.

### Feature Access

The app exposes an open-source entitlement payload at `GET /me/entitlements` that describes available features and soft limits. The current backend does not implement Stripe, subscription persistence, or billing checkout flows.

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

**Authentication:** Currently uses a simple bearer token (`API_SECRET_KEY`) for development. For production, integrate your preferred auth system (OAuth2, JWT, API keys, etc.). The backend `get_current_user()` dependency extracts the user ID from the bearer token and validates it against configured secrets or API key hashes.

### MCP Server

A FastMCP server is mounted at `/mcp` on the FastAPI app, exposing council debates as tools for IDE clients (Cursor, Claude Desktop).

## Key Environment Variables

```bash
OPENROUTER_API_KEY=...          # Primary LLM provider
XAI_API_KEY=...                 # Optional: native Grok (cheaper)
API_SECRET_KEY=...              # Dev bearer token (min 32 chars in production)
DATABASE_URL=postgresql+asyncpg://council:council@localhost:5432/council
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
TAVILY_API_KEY=...              # Optional: web search capability
COUNCIL_DISABLE_WORKER=0        # 1 = run Celery in-process
COUNCIL_GUARDRAILS=1            # 0 = disable content guardrails
```
