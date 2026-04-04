# TheCouncil

Structured multi-agent debates: a FastAPI service and CLI orchestrate council runs; the `web/` app is a Next.js dashboard and marketing site.

## Repository layout

| Path | Purpose |
|------|---------|
| `api.py`, `council.py`, `run_state.py`, `subscriptions.py` | Core API, runner, billing, and run storage |
| `agents.yaml` | Default agent definitions for the CLI |
| `sessions/` | Generated session data (e.g. personas) |
| `samples/chats/` | Example chat exports for local testing |
| `tests/` | `pytest` suite |
| `web/` | Next.js 16 UI (`npm run dev`) |
| `plans/` | Internal deployment / roadmap notes |

## Python (API & CLI)

Prerequisites: Python 3.12+ and a virtualenv (`.venv` recommended).

```bash
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
cp .env.example .env        # add keys

# HTTP API (dev)
uvicorn api:app --reload

# MCP server (remote) is mounted at:
#   http://localhost:3000/mcp  (Next.js frontend proxy → backend)
# and is tier-gated via DEFAULT_SUBSCRIPTION_TIER (demo only).

# CLI (see council.py --help)
python council.py --help
```

## Web app

```bash
cd web
npm ci
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to your API origin (see `web/.env` patterns in `.gitignore`).

## Quality checks

- **Python:** `pytest tests/ -q` and `ruff check .` (config in `pyproject.toml`)
- **Web:** `cd web && npm run lint && npm run typecheck && npm run test`

## License

Proprietary unless otherwise noted.
