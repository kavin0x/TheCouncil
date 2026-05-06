# TheCouncil

A multi-agent AI deliberation platform that orchestrates structured debates between LLM personas. Self-hosted, open-source, and built for extensibility.

## Features

- **Multi-Agent Debates**: Orchestrate 5-phase structured deliberations (Independent Takes → Cross-Debate → Private Messages → Resolution)
- **Flexible Personas**: Use pre-configured personas, generate dynamically from topics, or import custom agent definitions
- **Sandbox Execution**: Run code safely in Docker containers (computer-use workflows)
- **Web Search**: Integrate external knowledge via Tavily API
- **Real-time Events**: WebSocket streams for live debate progress tracking
- **MCP Integration**: Control TheCouncil from your IDE (Cursor, Claude Desktop, etc.)
- **REST API**: Full HTTP API for programmatic access
- **Self-Hosted**: Deploy on your own infrastructure with Docker or bare metal

## Repository Layout

| Path                         | Purpose                              |
| ---------------------------- | ------------------------------------ |
| `council/api/`               | FastAPI REST API & WebSocket server  |
| `council/core/`              | Debate orchestration engine          |
| `council/features/`          | Sandbox, search, content guardrails  |
| `council/db/`                | Database models & migrations         |
| `council/worker/`            | Celery task queue integration        |
| `agents.yaml`                | Default agent definitions            |
| `web/`                       | Next.js 16 UI dashboard              |
| `tests/`                     | `pytest` backend suite               |
| `docker-compose.yml`         | Full-stack local development         |

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

- `OPENROUTER_API_KEY` — LLM provider (OpenRouter for variety of models)
- `API_SECRET_KEY` — Bearer token for API auth (min 32 chars in production)
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection for pub/sub and job queue

Optional integrations:

- `TAVILY_API_KEY` — Enable web search in debates
- `XAI_API_KEY` — Use Grok models (cheaper alternative to OpenRouter)

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
5. **Resolution & Vote** — Agents propose resolutions; voting determines winner

**Tech Stack:**

- Backend: FastAPI + SQLAlchemy async + PostgreSQL
- Frontend: Next.js 16 + React 19 + Tailwind CSS
- Message Bus: Redis Streams (pub/sub for real-time events)
- Job Queue: Celery + Redis (long-running debates)
- Sandboxing: Docker (code execution for computer-use)
- LLM Providers: OpenRouter (primary), XAI Grok (optional)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, issue reporting, and pull request process.

## Security

For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
