# TheCouncil

Self-hosted multi-agent debates — several LLM personas argue a decision, then you get a written resolution. Web UI, API, or CLI. Built for people who want structured disagreement on their own machine, not another chat tab.

Started at the [NEBULA:FOG:PROTOCOL](https://nebulafog.ai/) hackathon.

## Why I built this

One model will happily agree with you. I wanted a way to force multiple viewpoints through a real debate — independent takes, rebuttals, private side-channels, then a vote — and keep the whole stack under my control. So I built TheCouncil: open-source, self-hosted, Docker-friendly.

## Hosted chat vs this

| | Typical multi-agent chat / SaaS | TheCouncil |
|---|---|---|
| Where it runs | Their servers | Your machine / your VPS |
| Debate structure | Free-form or one-shot | Fixed multi-phase deliberation |
| Output | Chat transcript | Decision rationale, action, dissent, top resolutions (JSON / Markdown) |
| Limits | Usage caps / seats | Open-source tier: run as hard as your keys allow |

## Features

**Debate**
- 5-phase flow: independent takes → cross-debate → private messages → second cross-debate → resolution & vote
- Built-in personas, topic-generated personas, or custom ones via a questionnaire
- Structured artifacts: rationale, recommended action, dissenting opinions, top resolutions

**Integrations**
- Web dashboard (Next.js)
- REST API + WebSockets for live progress
- MCP server at `/mcp` so you can drive debates from an IDE
- Optional web search during deliberation
- Optional Docker sandbox / VNC desktop for computer-use style work
- CLI TUI if you don’t want the browser

**Ops**
- Docker Compose for full stack (API, web, Postgres, Redis, worker)
- Or bare Python + Node for local dev
- SQLite by default; Postgres when you’re serious

## Try it

**Docker (fastest):**

```bash
docker-compose up -d
# Web http://localhost:3000 · API http://localhost:8000
```

**Local:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # at least OPENROUTER_API_KEY + API_SECRET_KEY
uvicorn council.api.app:app --reload --reload-dir council

cd web && npm ci && npm run dev
```

More config flags live in `.env.example`. Contributing notes: [CONTRIBUTING.md](CONTRIBUTING.md). Security: [SECURITY.md](SECURITY.md).

## Stack

FastAPI · SQLAlchemy · Next.js · Redis · Celery · Docker · OpenRouter (and optional native Grok) · FastMCP

## License

Apache License 2.0 — see [LICENSE](LICENSE).
