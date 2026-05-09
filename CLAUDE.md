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

### API Endpoints

```text
POST   /runs                          Create and enqueue a new council run (returns 202)
GET    /runs                          List runs for the authenticated user
GET    /runs/{run_id}                 Poll run status
GET    /runs/{run_id}/artifact        Get structured deliberation artifact (json or markdown)
GET    /runs/{run_id}/sandbox/stream  Get VNC stream URL for a computer-use run
GET    /me/entitlements               Available features (open-source tier — no limits)
GET    /me/usage                      Month-to-date run count
GET    /me/personas                   List personas (seeds prebuilt from agents.yaml + canned)
POST   /me/personas                   Create a custom persona
GET    /me/personas/{id}              Get a single persona
PUT    /me/personas/{id}              Update a persona
DELETE /me/personas/{id}             Delete a persona
POST   /me/personas/questionnaire     Generate a persona via LLM from structured questionnaire
GET    /me/config                     Get per-user council run configuration
PUT    /me/config                     Update council run configuration (agents, rounds, model)
POST   /webhooks/zoom                 Zoom webhook receiver (posts artifact to chat on meeting.ended)
POST   /internal/run-events           Worker→API event bridge (used when COUNCIL_API_EVENT_BRIDGE_URL is set)
GET    /health                        Health check (not in schema)
GET    /readiness                     Readiness check with DATABASE_URL presence validation
```

The `POST /api/legal/accept` and `GET /api/legal/status` endpoints are declared in the module docstring but **not yet implemented**. The `TosAcceptance` ORM model and `users.tos_accepted_at` / `users.tos_version` columns are in place for when these endpoints land.

### Feature Access

The app exposes an open-source entitlement payload at `GET /me/entitlements` that describes available features and soft limits. The current backend does not implement Stripe, subscription persistence, or billing checkout flows.

### Rate-Limit Headers

The `add_rate_limit_headers` middleware in `council/api/app.py` is currently a pass-through. Rate limiting is enforced at the application level, not via response headers.

### MCP Server

A FastMCP server is mounted at `/mcp` on the FastAPI app, exposing council debates as tools for IDE clients (Cursor, Claude Desktop). MCP is always enabled for self-hosted instances.

Available MCP tools:

- `council_run(question, config?)` — create and enqueue a council run
- `sandbox_run(question, config?)` — create and enqueue a sandbox (code execution) run
- `council_poll(run_id)` — poll a run by ID (alias: `council_status`)
- `council_status(run_id)` — return the current status of a run
- `council_artifact(run_id, format?)` — retrieve the structured deliberation artifact (`json` or `markdown`)

### Sandbox (`council/features/sandbox.py`)

Two sandbox modes, both Docker-based:

1. **Code execution** — runs a bounded shell command in a container; command is validated against an allowlist and shell metacharacter check before queuing (`_validate_sandbox_cmd`)
2. **Desktop (VNC/noVNC)** — optional Ubuntu container with VNC for computer-use workflows; stream URL served at `GET /runs/{run_id}/sandbox/stream`

Enable via `computer_use_enabled=true` on a run; requires Docker daemon.

### Zoom Webhook Integration

`POST /webhooks/zoom` handles Zoom events:

- `endpoint.url_validation` — responds to Zoom's URL validation challenge
- `meeting.ended` — extracts a council `run_id` from the meeting topic (format: `[council:<run_id>:<hmac_token>]`) and posts the markdown artifact to the meeting's chat channel

Requires `ZOOM_WEBHOOK_SECRET_TOKEN` (signature verification), `ZOOM_RUN_SECRET` (HMAC-SHA256 token in meeting topic), and `ZOOM_API_TOKEN` (posting to chat).

### Web App (`web/`)

Next.js 16 with React 19, Tailwind CSS 4, TanStack Query, and Radix UI. Uses App Router (`web/app/`). API client and TypeScript types are in `web/lib/api.ts`.

**Important:** This uses Next.js 16, which has breaking changes from earlier versions. Read the relevant guide in `web/node_modules/next/dist/docs/` before writing frontend code.

TypeScript types in `web/lib/api.ts` mirror the Python Pydantic models — keep them in sync when changing backend schemas.

App routes (all under `web/app/(app)/`):

- `/` — dashboard (`dashboard/page.tsx`)
- `/runs` — run list (`runs/page.tsx`)
- `/runs/[id]` — run detail with live WebSocket feed (`runs/[id]/page.tsx`)
- `/personas` — persona management (`personas/page.tsx`)
- `/settings` — council settings: agents, rounds, model (`settings/page.tsx`)
- `/integrations` — Zoom and MCP integration config (`integrations/page.tsx`)
- `/usage` — month-to-date usage (`usage/page.tsx`)

**Authentication:** No login screen. All routes are public. `web/lib/auth.tsx` exports `useAuth()` which reads `NEXT_PUBLIC_API_TOKEN` (the same value as `API_SECRET_KEY`) for API calls. Set `NEXT_PUBLIC_API_TOKEN` in `web/.env.local` if the backend `API_SECRET_KEY` is configured.

### Database Schema (`council/db/`)

SQLAlchemy 2.0 async with asyncpg. Key tables:

- `users` — registered accounts; `tos_accepted_at` (Float) and `tos_version` (String(32)) columns for ToS tracking
- `deliberations` — council runs (maps to `run_id`)
- `personas` — saved agent personas per user
- `artifacts` — synthesized output from completed runs
- `usage_events` — per-run usage accounting
- `api_keys` — user-generated API keys (sha256 hash stored, never plaintext)
- `tos_acceptances` — per-owner ToS acceptance keyed by `owner_id`; stores `version` + `accepted_at`

Run `python -m council.db.migrations` to apply schema.

## Key Environment Variables

```bash
# LLM providers
OPENROUTER_API_KEY=...          # Required: primary LLM provider
XAI_API_KEY=...                 # Optional: native Grok API (cheaper for grok-* models)

# API auth
API_SECRET_KEY=...              # Dev bearer token (min 32 chars in production)
CORS_ORIGINS=http://localhost:3000  # Comma-separated allowed CORS origins (no wildcard)

# Infrastructure
DATABASE_URL=postgresql+asyncpg://council:council@localhost:5432/council
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_TOKEN=...       # Same as API_SECRET_KEY; set in web/.env.local

# Optional integrations
TAVILY_API_KEY=...              # Web search capability
ZOOM_WEBHOOK_SECRET_TOKEN=...   # Zoom webhook signature verification
ZOOM_RUN_SECRET=...             # HMAC secret for run_id in Zoom meeting topics
ZOOM_API_TOKEN=...              # Zoom API Bearer token for posting to chat

# Behavior flags
COUNCIL_DISABLE_WORKER=0        # 1 = run Celery in-process (dev/test)
COUNCIL_GUARDRAILS=1            # 0 = disable content guardrails
ALLOW_WEBSOCKET_QUERY_TOKEN=0   # 1 = allow ?token= fallback on WebSocket (insecure)
HIDE_DOCS=0                     # 1 = disable /docs, /redoc, /openapi.json
COUNCIL_API_EVENT_BRIDGE_URL=...# Set on Celery worker to bridge events to the API over HTTP
```
