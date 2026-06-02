# TheCouncil

A multi-agent AI deliberation platform that orchestrates structured debates between LLM personas. Self-hosted, open-source, and built for extensibility.

## Features

- **Multi-Agent Debates**: Orchestrate 5-phase structured deliberations (Independent Takes → Cross-Debate → Private Messages → Resolution)
- **Flexible Personas**: Use built-in canned personas, generate dynamically from the topic, or build custom personas via an LLM-powered questionnaire
- **Deliberation Artifacts**: Structured output (decision rationale, recommended action, dissenting opinions, top-3 resolutions) available as JSON or Markdown
- **Sandbox Execution**: Run code in Docker containers or stream a live VNC desktop for computer-use workflows
- **Web Search**: Integrate external knowledge via Tavily API during deliberation
- **Real-time Events**: WebSocket streams for live debate progress; falls back to in-process broadcast when Redis is unavailable
- **MCP Integration**: Control TheCouncil from your IDE (Cursor, Claude Desktop) via the built-in FastMCP server at `/mcp`
- **Zoom Integration**: Webhook receiver posts artifact summaries to Zoom chat when a meeting ends
- **REST API**: Full HTTP API for programmatic access
- **Self-Hosted**: Deploy on your own infrastructure with Docker or bare metal; no usage limits on the open-source tier

## Repository Layout

| Path                                  | Purpose                                                                 |
| ------------------------------------- | ----------------------------------------------------------------------- |
| `council/api/`                      | FastAPI REST API & WebSocket server                                     |
| `council/core/`                     | Debate orchestration engine                                             |
| `council/features/`                 | Sandbox, search, content guardrails                                     |
| `council/db/`                       | Database models & migrations                                            |
| `council/worker/`                   | Celery task queue integration                                           |
| `council/features/personalities.py` | Default built-in agent definitions (canned personas) and MBTI generator |
| `web/`                              | Next.js 16 UI dashboard                                                 |
| `tests/`                            | `pytest` backend suite                                                |
| `docker-compose.yml`                | Full-stack local development                                            |

## Quick Start

### Backend (Python)

```bash
python -m venv .venv
source .venv/bin/activate      # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
cp .env.example .env            # populate with your API keys

# Run the API
uvicorn council.api.app:app --reload --reload-dir council --reload-dir tests
# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### Frontend (Next.js)

```bash
cd web
npm ci
npm run dev
# App available at http://localhost:3000
```

### Full Stack (Docker)

```bash
docker-compose up -d
# API: http://localhost:8000
# Web: http://localhost:3000
# PostgreSQL, Redis, and Celery worker also running
```

## Configuration

Copy `.env.example` to `.env` and populate these required variables:

- `OPENROUTER_API_KEY` — LLM provider (OpenRouter; required)
- `API_SECRET_KEY` — Bearer token for API auth (min 32 chars in production)
- `DATABASE_URL` — Database connection string (default: `sqlite+aiosqlite:///./council.db`)
  - **SQLite** (default): `sqlite+aiosqlite:///./council.db` — local file-based database
  - **PostgreSQL**: `postgresql+asyncpg://user:password@host:5432/database`
- `REDIS_URL` — Redis connection for pub/sub and job queue (required for worker mode)

Optional integrations:

- `TAVILY_API_KEY` — Enable web search in debates
- `XAI_API_KEY` — Use native Grok API
- `ZOOM_WEBHOOK_SECRET_TOKEN` / `ZOOM_RUN_SECRET` / `ZOOM_API_TOKEN` — Zoom chat integration

Behavior flags:

- `CORS_ORIGINS` — Comma-separated allowed origins (default: `http://localhost:3000`; no wildcard)
- `COUNCIL_DISABLE_WORKER=1` — Run Celery in-process (dev/test)
- `COUNCIL_GUARDRAILS=0` — Disable content guardrails
- `ALLOW_WEBSOCKET_QUERY_TOKEN=1` — Allow `?token=` fallback on WebSocket (insecure; off by default)
- `HIDE_DOCS=1` — Disable `/docs`, `/redoc`, `/openapi.json`

Frontend (`web/.env.local`):

- `NEXT_PUBLIC_API_TOKEN` — Same value as `API_SECRET_KEY`; required if the backend enforces auth

**API Key Management:**

Users can generate API keys via the `/me/api-keys` endpoints for programmatic access:

- `POST /me/api-keys` — Create a new API key
- `GET /me/api-keys` — List all API keys
- `DELETE /me/api-keys/{key_id}` — Revoke an API key

Keys are stored securely as SHA256 hashes in the database and can be used as Bearer tokens.

## Testing

**Backend:**

```bash
pytest tests/ -q
ruff check .
```

**Frontend:**

```bash
cd web
npm run test          # unit tests (vitest)
npm run test:e2e      # end-to-end (playwright)
npm run lint
npm run typecheck
```

## Architecture

**Core Debate Flow:**

1. **Independent Takes** — Agents generate initial responses without knowledge of others
2. **Cross-Debate I** — Sequential rebuttals with visibility into prior responses
3. **Private Deliberation** — Direct point-to-point messages between agents
4. **Cross-Debate II** — Final sequential round
5. **Resolution & Vote** — Agents propose resolutions; voting determines winner; tie-breaker reruns until one resolution wins

**Tech Stack:**

- Backend: FastAPI + SQLAlchemy async + PostgreSQL
- Frontend: Next.js 16 + React 19 + Tailwind CSS 4
- Message Bus: Redis Streams (pub/sub for real-time events)
- Job Queue: Celery + Redis (long-running debates)
- Sandboxing: Docker (code execution + VNC desktop for computer-use)
- LLM Providers: OpenRouter (primary), XAI Grok native API (optional)
- IDE Integration: FastMCP server mounted at `/mcp`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, issue reporting, and pull request process.

## Security

For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
