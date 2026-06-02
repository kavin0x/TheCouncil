"""
TheCouncil API — FastAPI for council debate runs.

Endpoints:
  POST /runs               Create a new council run (enqueues it)
  GET  /runs/{run_id}      Poll the status of a run
  GET  /runs               List runs for the authenticated user
  GET  /me/entitlements    Current feature availability
  GET  /me/usage           Month-to-date usage
  GET  /me/personas        List saved personas for the authenticated user
  POST /me/personas        Create a persona
  GET  /me/personas/{id}   Get a single persona
  PUT  /me/personas/{id}   Update a persona
  DELETE /me/personas/{id} Delete a persona
  POST /me/api-keys        Create a new API key
  GET  /me/api-keys        List all API keys
  DELETE /me/api-keys/{id} Revoke an API key
  POST /api/legal/accept   Record ToS acceptance (version + timestamp)
  GET  /api/legal/status   Check whether current ToS has been accepted

Auth:
  Bearer token in the Authorization header.
  Token is validated against the API_SECRET_KEY environment variable or stored API keys in the database
  for single-key dev mode, or against a user table in production.

Usage (dev):
    uvicorn council.api.app:app --reload --reload-dir council --reload-dir tests --reload-exclude 'web/*' --reload-exclude 'node_modules/*' --reload-exclude '.next/*' --reload-exclude '.venv/*'
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any


logger = logging.getLogger(__name__)

from dotenv import load_dotenv

if os.environ.get("PYTEST_CURRENT_TEST") is None:
    load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status  # noqa: E402  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402  # type: ignore
from fastapi.responses import JSONResponse  # noqa: E402  # type: ignore
from fastmcp import FastMCP  # noqa: E402
from fastmcp.server.dependencies import get_http_request  # noqa: E402
from fastmcp.utilities.lifespan import combine_lifespans  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field

from council.core.council import MODEL as DEFAULT_MODEL
from council.core.runner import CouncilRunBlockedError, run_council_for_api
from council.realtime import emit_run_event, register_ws_broadcast
from council.models.state import (
    Run,
    RunNotFoundError,
    RunStatus,
    run_queue,
    run_store,
)
from council.features.sandbox import (  # noqa: E402
    SandboxDisabledError,
    get_desktop_sandbox_stream_url,
    kill_desktop_sandbox,
    run_sandbox_task,
)
from council.db.session import get_engine, get_session_ctx, get_session_dep
from council.db.models import ApiKey, User, Deliberation, Persona as PersonaModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API Key utility functions
# ---------------------------------------------------------------------------


def _hash_api_key(key: str) -> str:
    """Hash an API key using SHA256."""
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_api_key() -> str:
    """Generate a new API key with format: tc_live_<random_chars>."""
    random_suffix = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
    return f"tc_live_{random_suffix}"


def _validate_environment() -> None:
    """Validate required environment variables are present, raising RuntimeError if not."""
    if not os.getenv("OPENROUTER_API_KEY", ""):
        raise RuntimeError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Set it before starting the server."
        )


def _allow_legacy_websocket_query_token() -> bool:
    return os.getenv("ALLOW_WEBSOCKET_QUERY_TOKEN", "").lower() in ("1", "true", "yes")


def _extract_websocket_token(websocket: WebSocket) -> tuple[str, bool]:
    """Return the bearer token and whether it came from the subprotocol header."""
    protocol_header = websocket.headers.get("sec-websocket-protocol", "").strip()
    if protocol_header:
        token = protocol_header.split(",", 1)[0].strip()
        if token:
            return token, True

    if _allow_legacy_websocket_query_token():
        return websocket.query_params.get("token", "").strip(), False

    return "", False


def _mcp_owner_id(api_key: str | None = None) -> str:
    """Return the local owner ID for MCP tool calls."""
    return "local"


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _worker_task
    if not os.getenv("API_SECRET_KEY", ""):
        logger.warning(
            "API_SECRET_KEY is not set. The server is running without authentication — "
            "all endpoints are publicly accessible. Set API_SECRET_KEY in production."
        )
        if not os.getenv("COUNCIL_ALLOW_NO_AUTH", ""):
            logger.warning(
                "Set COUNCIL_ALLOW_NO_AUTH=1 to suppress this warning if unauthenticated "
                "access is intentional (e.g. local development)."
            )
    if not os.getenv("COUNCIL_DISABLE_WORKER", ""):
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_run_worker_loop())
    yield
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None


_worker_task: asyncio.Task[None] | None = None

_mcp = FastMCP("TheCouncil")

if hasattr(_mcp, "http_app"):
    _mcp_app = _mcp.http_app(path="/")
else:
    streamable_http_app = getattr(_mcp, "streamable_http_app")
    _mcp_app = streamable_http_app()


class _MCPAuthMiddleware:
    """ASGI middleware that enforces bearer-token auth on the MCP sub-app.

    When API_SECRET_KEY is set, every request must carry a valid
    ``Authorization: Bearer <token>`` header.  If the key is unset the
    middleware is a pass-through (zero-config dev/test behaviour).
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        secret = os.getenv("API_SECRET_KEY", "").strip()
        if secret:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="replace")
            token = ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

            valid = bool(token) and hmac.compare_digest(
                hashlib.sha256(token.encode()).digest(),
                hashlib.sha256(secret.encode()).digest(),
            )
            if not valid:
                if scope["type"] == "http":
                    response_body = b'{"detail":"Unauthorized"}'
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            [b"content-type", b"application/json"],
                            [b"content-length", str(len(response_body)).encode()],
                            [b"www-authenticate", b"Bearer"],
                        ],
                    })
                    await send({"type": "http.response.body", "body": response_body})
                else:
                    await send({"type": "websocket.close", "code": 4401})
                return

        await self._app(scope, receive, send)


_mcp_app = _MCPAuthMiddleware(_mcp_app)

_hide_docs = os.getenv("HIDE_DOCS", "").lower() in ("1", "true", "yes")

# Mounted ASGI apps do not receive lifespan events; Streamable HTTP requires MCP lifespan
# so the session manager task group starts (see fastmcp.utilities.lifespan.combine_lifespans).
app = FastAPI(
    title="TheCouncil API",
    description="REST API for creating, queuing, and polling council debate runs.",
    version="0.1.0",
    lifespan=combine_lifespans(_lifespan, _mcp_app.lifespan),
    docs_url=None if _hide_docs else "/docs",
    redoc_url=None if _hide_docs else "/redoc",
    openapi_url=None if _hide_docs else "/openapi.json",
)

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
if "*" in _cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS='*' cannot be combined with allow_credentials=True. "
        "Set CORS_ORIGINS to one or more explicit allowed origins."
    )

_cors_origin_regex = None
if any(re.match(r"^https?://(?:localhost|127(?:\.\d{1,3}){3})(?::\d+)?$", origin) for origin in _cors_origins):
    # Allow local-loopback frontend hosts such as localhost and 127.0.2.2 during dev.
    # This keeps explicit production origins intact while avoiding CORS preflight 400s
    # when the browser opens the web app on a different loopback alias than the API.
    _cors_origin_regex = r"^https?://(?:localhost|127(?:\.\d{1,3}){3})(?::\d+)?$"


@app.middleware("http")
async def add_security_headers(request: Request, call_next):  # type: ignore[type-arg]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):  # type: ignore[type-arg]
    """Pass-through middleware. Rate limiting is handled at the application level."""
    return await call_next(request)


# Add CORS middleware last so it executes first in the middleware stack (outermost)
# and properly handles OPTIONS preflight requests before other middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

app.mount("/mcp", _mcp_app)


async def _run_worker_loop() -> None:
    while True:
        run_id = await run_queue.dequeue()
        t0 = time.monotonic()
        run: Run | None = None
        try:
            run = await run_store.update_status(run_id, RunStatus.RUNNING)
            await emit_run_event(run_id, "run_started", {"run_id": run_id})
            run_kind = str((run.config or {}).get("run_kind") or "council").strip().lower()
            cfg = run.config or {}
            if run_kind == "sandbox":
                result = await run_sandbox_task(question=run.question, config=run.config)
            else:
                # Inject the web_search tool into the council run if enabled for this run.
                # The tool spec is forwarded via config and consumed by the runner.
                if cfg.get("web_search_enabled"):
                    cfg = dict(cfg)
                    cfg["_tools"] = cfg.get("_tools", []) + ["web_search"]

                result = await run_council_for_api(
                    question=run.question,
                    config=cfg,
                    owner_id=run.owner_id,
                    run_id=run_id,
                )
            await run_store.update_status(run_id, RunStatus.COMPLETED, result=result)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            await emit_run_event(
                run_id,
                "run_completed",
                {
                    "run_id": run_id,
                    "winner": result.get("winner"),
                    "final_resolution": result.get("final_resolution", ""),
                    "elapsed_ms": elapsed_ms,
                },
            )
        except CouncilRunBlockedError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
            await emit_run_event(run_id, "run_failed", {"run_id": run_id, "error": str(exc)})
        except SandboxDisabledError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
            await emit_run_event(run_id, "run_failed", {"run_id": run_id, "error": str(exc)})
        except Exception as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
            await emit_run_event(
                run_id,
                "run_failed",
                {"run_id": run_id, "error": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            # Kill the Desktop sandbox associated with this run when the run ends.
            if run is not None and (run.config or {}).get("computer_use_enabled"):
                await kill_desktop_sandbox(run_id)
            run_queue.task_done()


def _require_mcp_enabled(owner_id: str) -> None:
    pass  # MCP is always enabled for self-hosted instances


@_mcp.tool()
async def council_run(question: str, config: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """Create and enqueue a council run. Returns the run_id and initial status."""
    owner_id = _mcp_owner_id(api_key)
    _require_mcp_enabled(owner_id)
    run = await run_store.create(question=question, config=config or {}, owner_id=owner_id)
    await run_queue.enqueue(run.run_id)
    return {"run_id": run.run_id, "status": run.status.value, "question": run.question, "created_at": run.created_at}


@_mcp.tool()
async def sandbox_run(question: str, config: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """Create and enqueue a sandbox run."""
    owner_id = _mcp_owner_id(api_key)
    _require_mcp_enabled(owner_id)
    run_cfg = dict(config or {})
    run_cfg["run_kind"] = "sandbox"
    run = await run_store.create(question=question, config=run_cfg, owner_id=owner_id)
    await run_queue.enqueue(run.run_id)
    return {"run_id": run.run_id, "status": run.status.value, "question": run.question, "created_at": run.created_at}


@_mcp.tool()
async def council_poll(run_id: str, api_key: str | None = None) -> dict[str, Any]:
    """Poll a run created via council_run. Alias: council_status."""
    owner_id = _mcp_owner_id(api_key)
    _require_mcp_enabled(owner_id)
    run = await run_store.get(run_id)
    if run.owner_id != owner_id:
        raise RuntimeError("Run not found.")
    return run.to_dict()


@_mcp.tool()
async def council_status(run_id: str, api_key: str | None = None) -> dict[str, Any]:
    """Return the current status of a council run (PENDING | RUNNING | COMPLETED | FAILED)."""
    return await council_poll(run_id=run_id, api_key=api_key)


@_mcp.tool()
async def council_artifact(run_id: str, format: str = "json", api_key: str | None = None) -> dict[str, Any]:
    """Retrieve the structured deliberation artifact for a completed run.

    Args:
        run_id: The run identifier returned by council_run.
        format:  Output format — "json" (default) or "markdown".
        api_key: Bearer token for authentication.

    Returns a structured artifact with:
      - decision_rationale: synthesis of the debate
      - recommended_action: winning resolution
      - dissenting_opinions: minority positions
      - top3_resolutions: ranked list of proposals
    """
    owner_id = _mcp_owner_id(api_key)
    _require_mcp_enabled(owner_id)

    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise RuntimeError(f"Run not found: {run_id!r}")

    if run.owner_id != owner_id:
        raise RuntimeError("Run not found.")

    if run.status is not RunStatus.COMPLETED:
        return {
            "run_id": run_id,
            "status": run.status.value,
            "artifact": None,
            "message": f"Run is {run.status.value}. Artifact available only after completion.",
        }

    result = run.result or {}
    artifact = _build_artifact_from_result(run_id, run.question, result)

    if format == "markdown":
        return {
            "run_id": run_id,
            "status": run.status.value,
            "format": "markdown",
            "artifact": artifact["markdown"],
        }

    return {"run_id": run_id, "status": run.status.value, "format": "json", "artifact": artifact["data"]}


def _build_artifact_from_result(run_id: str, question: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build a structured artifact dict from a completed run result."""
    top3 = result.get("top3", [])
    resolutions = result.get("resolutions", {})
    vote_rounds = result.get("vote_rounds", [])
    winner = result.get("winner", "")
    final_resolution = result.get("final_resolution", "")
    agents_in_run = result.get("agents", [])

    # Decision rationale from top-3 analysis
    rationale_parts = []
    for res in top3:
        summary = res.get("summary", "")
        agent = res.get("agent", "")
        role = res.get("role", "")
        if summary:
            rationale_parts.append(f"**{agent} ({role})**: {summary}")
    decision_rationale = "\n\n".join(rationale_parts) or final_resolution

    # Dissenting opinions
    dissenting = []
    for agent_info in agents_in_run:
        agent_name = agent_info.get("name", "")
        if agent_name == winner:
            continue
        agent_resolution = resolutions.get(agent_name, "")
        if agent_resolution and agent_resolution != final_resolution:
            dissenting.append({
                "agent": agent_name,
                "role": agent_info.get("role", ""),
                "opinion": agent_resolution,
            })

    data = {
        "artifact_id": f"art-{run_id}",
        "run_id": run_id,
        "question": question,
        "decision_rationale": decision_rationale,
        "recommended_action": final_resolution,
        "dissenting_opinions": dissenting,
        "consensus_resolution": final_resolution,
        "agent_votes": {"rounds": vote_rounds, "winner": winner},
        "top3_resolutions": top3,
    }

    # Markdown rendering
    md_lines = [
        "# TheCouncil Deliberation Artifact",
        "",
        f"**Question:** {question}",
        "",
        "---",
        "",
        "## Decision Rationale",
        "",
        decision_rationale,
        "",
        "## Recommended Action",
        "",
        final_resolution,
        "",
    ]

    if dissenting:
        md_lines += ["## Dissenting Opinions", ""]
        for opinion in dissenting:
            md_lines += [f"**{opinion['agent']}:** {opinion['opinion']}", ""]

    if top3:
        md_lines += ["## Top Resolutions", ""]
        for res in top3:
            rank = res.get("rank", "?")
            agent = res.get("agent", "")
            resolution = res.get("resolution", "")
            summary = res.get("summary", "")
            md_lines += [
                f"### Resolution #{rank} — {agent}",
                "",
                resolution,
                "",
                f"*{summary}*",
                "",
            ]

    return {"data": data, "markdown": "\n".join(md_lines)}


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


@dataclass
class AuthenticatedUser:
    user_id: str  # User ID or "api_key:<key_prefix>" or "dev"
    auth_method: str = "api_secret"

    @property
    def owner_id(self) -> str:
        """Backward-compatible alias for user_id."""
        return self.user_id


# Keep AuthContext as an alias so existing code keeps working unchanged.
AuthContext = AuthenticatedUser


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession | None, Depends(get_session_dep)] = None,
) -> AuthenticatedUser:
    """Return the authenticated user. Supports API_SECRET_KEY env var or stored API keys."""
    api_secret = os.getenv("API_SECRET_KEY", "")
    token = ""
    
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    
    # First try API_SECRET_KEY environment variable (dev mode)
    if api_secret and token:
        if hmac.compare_digest(token.encode(), api_secret.encode()):
            return AuthenticatedUser(user_id="local", auth_method="api_secret")
    
    # Then try stored API keys in database
    if token and session:
        try:
            key_hash = _hash_api_key(token)
            # Use text query to avoid type checking issues
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT owner_id, key_prefix FROM api_keys WHERE key_hash = :hash AND is_active = 1"),
                {"hash": key_hash}
            )
            row = result.first()
            if row:
                owner_id, key_prefix = row
                # Update last_used_at
                await session.execute(
                    text("UPDATE api_keys SET last_used_at = :now WHERE key_hash = :hash"),
                    {"now": time.time(), "hash": key_hash}
                )
                await session.commit()
                return AuthenticatedUser(user_id=owner_id, auth_method="api_key")
        except Exception:
            pass  # Fall through to error
    
    # If we require auth and don't have valid credentials, fail
    if api_secret or token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    # Allow unauthenticated access if no API_SECRET_KEY is set
    return AuthenticatedUser(user_id="local", auth_method="none")


# Keep require_auth as an alias for backward compatibility with any internal callers.
require_auth = get_current_user


def _count_runs_this_month(runs: list[Run]) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for run in runs:
        created = datetime.fromtimestamp(run.created_at, tz=timezone.utc)
        if created.year == now.year and created.month == now.month:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateRunConfig(BaseModel):
    """Run configuration for ``POST /runs``."""

    model_config = ConfigDict(extra="forbid")

    num_agents: int | None = Field(None, ge=0, description="Agent count for the run.")
    num_rounds: int | None = Field(None, ge=0, le=12)
    rounds: int | None = Field(None, ge=0, le=12, description="Alias for num_rounds.")
    mode: str | None = Field(None, max_length=32, description="Personality mode: canned, dynamic, hybrid, or generated.")
    selected_persona_ids: list[str] | None = None
    model: str | None = Field(None, max_length=128)
    max_input_tokens: int | None = Field(None, ge=0, le=2_000_000)
    run_kind: str | None = Field(None, max_length=64)
    sandbox_cmd: str | None = Field(None, max_length=16_384)
    sandbox_timeout_s: int | None = Field(None, ge=10, le=7200)


class CreateRunRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4096, description="The debate question.")
    config: CreateRunConfig = Field(
        default_factory=CreateRunConfig.model_construct,
        description="Optional run configuration forwarded to DebateSession.",
    )
    web_search_enabled: bool = Field(
        default=False,
        description="Allow agents to call web search during deliberation (requires TAVILY_API_KEY).",
    )
    computer_use_enabled: bool = Field(
        default=False,
        description="Spawn a Docker sandbox for computer-use tasks (requires Docker daemon).",
    )


class RunResponse(BaseModel):
    run_id: str
    question: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunResponse":
        data = run.to_dict()
        # owner_id is an internal principal identifier; exclude it from responses
        # to avoid echoing the bearer token (used as owner_id in dev mode) back to clients.
        data.pop("owner_id", None)
        return cls(**data)


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create and enqueue a new council run",
)
async def create_run(
    body: CreateRunRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> RunResponse:
    """Create a new council debate run and place it on the worker queue.

    Returns the run record in PENDING status immediately.
    Poll ``GET /runs/{run_id}`` to track progress.
    """
    cfg = body.config.model_dump(mode="python", exclude_none=True)

    # Validate sandbox_cmd early to surface errors before enqueuing.
    if cfg.get("sandbox_cmd"):
        from council.features.sandbox import _validate_sandbox_cmd
        try:
            _validate_sandbox_cmd(str(cfg["sandbox_cmd"]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Persist feature flags in the run config so the worker can read them.
    run_config = dict(cfg)
    run_config["web_search_enabled"] = body.web_search_enabled
    run_config["computer_use_enabled"] = body.computer_use_enabled

    selected_ids = run_config.get("selected_persona_ids") or []
    if selected_ids:
        _seed_prebuilt_personas(auth.owner_id)
        run_config["selected_personas"] = [
            _persona_snapshot_for_run(_get_owned_persona(pid, auth.owner_id))
            for pid in selected_ids
        ]

    run = await run_store.create(
        question=body.question,
        config=run_config,
        owner_id=auth.owner_id,
    )
    await run_queue.enqueue(run.run_id)
    return RunResponse.from_run(run)


@app.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="Poll the status of a council run",
)
async def get_run(
    run_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> RunResponse:
    """Return the current state of a run.

    Returns HTTP 404 if the run does not exist or belongs to a different user.
    """
    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.owner_id != auth.owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return RunResponse.from_run(run)


@app.get(
    "/runs",
    response_model=list[RunResponse],
    summary="List council runs for the authenticated user",
)
async def list_runs(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[RunResponse]:
    """Return all runs owned by the authenticated user, newest first."""
    runs = await run_store.list_runs(owner_id=auth.owner_id)
    return [RunResponse.from_run(r) for r in runs]


@app.get(
    "/runs/{run_id}/artifact",
    summary="Get the structured deliberation artifact for a completed run",
)
async def get_run_artifact(
    run_id: str,
    format: str = "json",
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return the deliberation artifact for a completed run.

    Args:
        format: ``json`` (default) or ``markdown``

    The artifact contains:
    - ``decision_rationale`` — synthesis of the debate
    - ``recommended_action`` — the winning resolution
    - ``dissenting_opinions`` — minority positions that didn't win
    - ``top3_resolutions`` — ranked list of proposals
    """
    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.owner_id != auth.owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    if run.status is not RunStatus.COMPLETED:
        return {
            "run_id": run_id,
            "status": run.status.value,
            "artifact": None,
            "message": f"Run is {run.status.value}. Artifact available only after completion.",
        }

    result = run.result or {}
    artifact = _build_artifact_from_result(run_id, run.question, result)

    if format == "markdown":
        return {
            "run_id": run_id,
            "status": run.status.value,
            "format": "markdown",
            "artifact": artifact["markdown"],
        }
    return {
        "run_id": run_id,
        "status": run.status.value,
        "format": "json",
        "artifact": artifact["data"],
    }


@app.get(
    "/runs/{run_id}/sandbox/stream",
    summary="Get the Desktop VNC stream URL for a computer-use run",
)
async def get_sandbox_stream(
    run_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    """Return the VNC stream URL for the Desktop sandbox attached to this run.

    The sandbox is created on demand if it does not yet exist.
    Requires ``computer_use_enabled=true`` on the run.
    """
    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.owner_id != auth.owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    if not (run.config or {}).get("computer_use_enabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Computer-use sandbox is not enabled for this run.",
        )

    try:
        stream_url = await get_desktop_sandbox_stream_url(run_id)
    except Exception as exc:
        logger.error("Desktop sandbox stream failed for run %s: %s", run_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox service unavailable. Please try again later.",
        )

    return {"stream_url": stream_url}


@app.get(
    "/me/entitlements",
    summary="Get available features",
)
async def get_entitlements(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    """Return the available features for a self-hosted instance.

    This payload is the client-facing capability contract for the deployment.
    """
    return {
        "tier": "open-source",
        "display_name": "Open Source",
        "limits": {
            "runs_per_month": None,
            "max_agents": None,
            "max_rounds": None,
            "max_input_tokens": None,
            "max_saved_personas": None,
        },
        "features": {
            "api_access": True,
            "mcp_enabled": True,
            "custom_mcp_enabled": True,
            "ide_plugins_enabled": True,
            "web_search_enabled": True,
            "computer_use_enabled": True,
            "sso_enabled": True,
            "centralized_billing_enabled": False,
        },
    }


# ---------------------------------------------------------------------------
# Personas — in-memory store
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Usage endpoint
# ---------------------------------------------------------------------------


@app.get(
    "/me/usage",
    summary="Get month-to-date usage",
)
async def get_usage(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    """Return month-to-date usage. No limits are enforced in self-hosted mode."""
    runs = await run_store.list_runs(owner_id=auth.owner_id)
    month_runs = _count_runs_this_month(runs)
    return {
        "period": "monthly",
        "runs": {"used": month_runs},
    }


# ---------------------------------------------------------------------------
# Personas — in-memory store
# ---------------------------------------------------------------------------


class PersonaRecord(BaseModel):
    persona_id: str
    name: str
    mode: str
    system_prompt: str
    model: str | None = None
    description: str | None = None
    owner_id: str
    created_at: float
    updated_at: float | None = None
    is_prebuilt: bool = False
    is_active: bool = True
    mbti: str | None = None
    job_role: str | None = None
    source: str | None = None  # "agents.yaml" | "canned" | "mbti" | "questionnaire" | None


_persona_store: dict[str, PersonaRecord] = {}

# Per-owner council configuration: which agents, how many, how many rounds
_council_config_store: dict[str, dict[str, Any]] = {}


def _seed_prebuilt_personas(owner_id: str) -> None:
    """Seed prebuilt personas from agents.yaml, CUSTOM_AGENTS, and canned templates for an owner."""
    already_seeded = any(
        p.owner_id == owner_id and p.is_prebuilt
        for p in _persona_store.values()
    )
    if already_seeded:
        return

    now = time.time()

    # Seed from agents.yaml if it exists
    import yaml as _yaml
    from pathlib import Path as _Path
    from council.features.personalities import CANNED_PERSONALITIES, CUSTOM_AGENTS

    agents_yaml_path = _Path(__file__).parent.parent / "agents.yaml"
    if not agents_yaml_path.exists():
        agents_yaml_path = _Path(__file__).parent.parent.parent / "agents.yaml"

    if agents_yaml_path.exists():
        with open(agents_yaml_path) as f:
            config = _yaml.safe_load(f)
        for agent in config.get("agents", []):
            pid = str(uuid.uuid4())
            _persona_store[pid] = PersonaRecord(
                persona_id=pid,
                name=agent["name"],
                mode="prebuilt",
                system_prompt=agent.get("system_prompt", ""),
                model=agent.get("model") or DEFAULT_MODEL,
                description=agent.get("role", ""),
                owner_id=owner_id,
                created_at=now,
                updated_at=now,
                is_prebuilt=True,
                is_active=True,
                source="agents.yaml",
            )
    else:
        # Fallback to CUSTOM_AGENTS if agents.yaml doesn't exist
        for agent in CUSTOM_AGENTS:
            pid = str(uuid.uuid4())
            _persona_store[pid] = PersonaRecord(
                persona_id=pid,
                name=agent["name"],
                mode="prebuilt",
                system_prompt=agent.get("system_prompt", ""),
                model=agent.get("model") or DEFAULT_MODEL,
                description=agent.get("role", ""),
                owner_id=owner_id,
                created_at=now,
                updated_at=now,
                is_prebuilt=True,
                is_active=True,
                source="custom",
            )

    # Seed from canned personalities
    for canned in CANNED_PERSONALITIES:
        pid = str(uuid.uuid4())
        _persona_store[pid] = PersonaRecord(
            persona_id=pid,
            name=canned["name"],
            mode="canned",
            system_prompt=canned.get("system_prompt", ""),
            model=canned.get("model") or DEFAULT_MODEL,
            description=canned.get("role", ""),
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
            is_prebuilt=True,
            is_active=True,
            source="built-in",
        )


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(default="custom", description="canned | mbti | custom | prebuilt | questionnaire")
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    model: str | None = Field(None, max_length=128)
    description: str | None = None
    mbti: str | None = None
    job_role: str | None = None
    is_active: bool = True


class UpdatePersonaRequest(BaseModel):
    name: str | None = None
    mode: str | None = None
    system_prompt: str | None = None
    model: str | None = Field(None, max_length=128)
    description: str | None = None
    mbti: str | None = None
    job_role: str | None = None
    is_active: bool | None = None


class QuestionnaireRequest(BaseModel):
    """Questionnaire answers submitted from the frontend to generate a persona via LLM."""
    identity: dict[str, Any] = Field(..., description="Name, domain, experience, etc.")
    cognition: dict[str, Any] = Field(..., description="Decision style, risk, pace")
    communication: dict[str, Any] = Field(..., description="Tone, persuasion style")
    values: dict[str, Any] = Field(..., description="Core values, non-negotiables")
    knowledge: dict[str, Any] = Field(..., description="Deep topics, weak areas, goals")
    branches: dict[str, Any] = Field(default_factory=dict, description="Conditional branch answers")


class CouncilConfigRequest(BaseModel):
    """User-configurable council run settings."""
    num_agents: int | None = Field(None, ge=2, le=20)
    num_rounds: int | None = Field(None, ge=1, le=12)
    selected_persona_ids: list[str] | None = Field(None, description="Which personas to use as agents")
    model: str | None = None


class CreateApiKeyRequest(BaseModel):
    """Request to create a new API key."""
    name: str = Field(default="My API Key", max_length=100, description="Human-readable name for this key")


class ApiKeyResponse(BaseModel):
    """Response containing API key metadata (never includes plaintext key)."""
    key_id: str
    name: str
    key_prefix: str
    created_at: float
    last_used_at: float | None
    is_active: bool


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Response when creating a new API key (includes the plaintext key once)."""
    plaintext_key: str = Field(..., description="The actual API key - only shown once!")


def _persona_snapshot_for_run(persona: PersonaRecord) -> dict[str, Any]:
    data = persona.model_dump(exclude={"owner_id"})
    data["model"] = data.get("model") or DEFAULT_MODEL
    # Map PersonaRecord.description to "role" for agent dict compatibility
    # _dicts_to_agents() expects "role" field; PersonaRecord uses "description"
    data["role"] = data.pop("description", "")
    return data


def _get_owned_persona(persona_id: str, owner_id: str) -> PersonaRecord:
    p = _persona_store.get(persona_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Persona not found.")
    return p


@app.get("/me/personas", summary="List saved personas")
async def list_personas(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[dict[str, Any]]:
    _seed_prebuilt_personas(auth.owner_id)
    owned = sorted(
        (p for p in _persona_store.values() if p.owner_id == auth.owner_id),
        key=lambda p: p.created_at,
        reverse=True,
    )
    return [p.model_dump(exclude={"owner_id"}) for p in owned]


@app.post(
    "/me/personas",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new persona",
)
async def create_persona(
    body: CreatePersonaRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    now = time.time()
    persona = PersonaRecord(
        persona_id=str(uuid.uuid4()),
        name=body.name,
        mode=body.mode,
        system_prompt=body.system_prompt,
        model=body.model or DEFAULT_MODEL,
        description=body.description,
        owner_id=auth.owner_id,
        created_at=now,
        updated_at=now,
        is_prebuilt=False,
        is_active=body.is_active,
        mbti=body.mbti,
        job_role=body.job_role,
    )
    _persona_store[persona.persona_id] = persona
    return persona.model_dump(exclude={"owner_id"})


@app.get("/me/personas/{persona_id}", summary="Get a single persona")
async def get_persona(
    persona_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    p = _get_owned_persona(persona_id, auth.owner_id)
    return p.model_dump(exclude={"owner_id"})


@app.put("/me/personas/{persona_id}", summary="Update a persona")
async def update_persona(
    persona_id: str,
    body: UpdatePersonaRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    p = _get_owned_persona(persona_id, auth.owner_id)
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    update_data["updated_at"] = time.time()
    updated = p.model_copy(update=update_data)
    _persona_store[persona_id] = updated
    return updated.model_dump(exclude={"owner_id"})


@app.delete(
    "/me/personas/{persona_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a persona",
)
async def delete_persona(
    persona_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> None:
    _get_owned_persona(persona_id, auth.owner_id)
    del _persona_store[persona_id]


# ---------------------------------------------------------------------------
# Persona questionnaire — generate persona via LLM from structured answers
# ---------------------------------------------------------------------------


@app.post(
    "/me/personas/questionnaire",
    status_code=status.HTTP_201_CREATED,
    summary="Generate a persona from questionnaire answers using LLM",
)
async def create_persona_from_questionnaire(
    body: QuestionnaireRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    questionnaire_payload = {
        "identity": body.identity,
        "cognition": body.cognition,
        "communication": body.communication,
        "values": body.values,
        "knowledge": body.knowledge,
        "branches": body.branches,
    }

    model_prompt = (
        "You are building a comprehensive agent persona profile for a council debate system.\n"
        "Return ONE JSON object only (no markdown) with this schema:\n"
        "{\n"
        '  "name": string,\n'
        '  "system_prompt": string (a detailed 200-400 word system prompt for this persona),\n'
        '  "description": string (one-line summary),\n'
        '  "mbti_type": string|null,\n'
        '  "traits": [string],\n'
        '  "reasoning_style": string,\n'
        '  "communication_tone": string\n'
        "}\n\n"
        "Rules:\n"
        "- The system_prompt must be a rich, concrete persona instruction (200-400 words) that covers identity, "
        "reasoning style, communication tone, agenda, debate behavior, and domain expertise.\n"
        "- Synthesize from the questionnaire answers below: identity, cognition, communication style, values, knowledge, "
        "and any conditional branch answers.\n"
        "- The description should be a concise one-line summary of who this persona is.\n"
        "- If MBTI is not provided, infer a likely type from the answers or set null.\n"
        "- Keep tone and vocabulary aligned with the user's stated communication style.\n"
        "- Ground all claims in the provided questionnaire data."
    )

    try:
        from council.core.council import api_call, PROFILE_BUILDER_MODEL, _extract_json_object

        input_msgs = [
            {"role": "system", "content": model_prompt},
            {"role": "user", "content": json.dumps(questionnaire_payload, ensure_ascii=True, indent=2)},
        ]
        raw = await api_call(input_msgs, max_tokens=2000, model=PROFILE_BUILDER_MODEL)
        generated = _extract_json_object(raw)
    except Exception as exc:
        logger.error("Persona generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Persona generation failed. Please try again later.",
        )

    now = time.time()
    name = str(generated.get("name") or body.identity.get("name", "Generated Persona"))
    system_prompt = str(generated.get("system_prompt", ""))
    if not system_prompt:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM did not return a valid system_prompt.",
        )

    persona = PersonaRecord(
        persona_id=str(uuid.uuid4()),
        name=name,
        mode="questionnaire",
        system_prompt=system_prompt,
        model=DEFAULT_MODEL,
        description=str(generated.get("description", "")),
        owner_id=auth.owner_id,
        created_at=now,
        updated_at=now,
        is_prebuilt=False,
        is_active=True,
        mbti=generated.get("mbti_type"),
        source="questionnaire",
    )
    _persona_store[persona.persona_id] = persona
    return persona.model_dump(exclude={"owner_id"})


# ---------------------------------------------------------------------------
# Council configuration — configurable agents, rounds, and agent selection
# ---------------------------------------------------------------------------


@app.get("/me/config", summary="Get council run configuration")
async def get_council_config(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    _seed_prebuilt_personas(auth.owner_id)
    config = _council_config_store.get(auth.owner_id, {})
    return {
        "num_agents": config.get("num_agents"),
        "num_rounds": config.get("num_rounds", 4),
        "selected_persona_ids": config.get("selected_persona_ids", []),
        "model": config.get("model"),
    }


@app.put("/me/config", summary="Update council run configuration")
async def update_council_config(
    body: CouncilConfigRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    config = _council_config_store.get(auth.owner_id, {})

    if body.num_agents is not None:
        config["num_agents"] = body.num_agents

    if body.num_rounds is not None:
        config["num_rounds"] = body.num_rounds

    if body.selected_persona_ids is not None:
        for pid in body.selected_persona_ids:
            _get_owned_persona(pid, auth.owner_id)
        config["selected_persona_ids"] = body.selected_persona_ids

    if body.model is not None:
        config["model"] = body.model

    _council_config_store[auth.owner_id] = config
    return {
        "num_agents": config.get("num_agents"),
        "num_rounds": config.get("num_rounds", 4),
        "selected_persona_ids": config.get("selected_persona_ids", []),
        "model": config.get("model"),
    }


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------


@app.post(
    "/me/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
)
async def create_api_key(
    body: CreateApiKeyRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[AsyncSession, Depends(get_session_dep)],
) -> ApiKeyCreatedResponse:
    """Create a new API key for programmatic access.
    
    The plaintext key is returned ONLY in this response. Store it securely.
    """
    # Ensure user exists in database
    from sqlalchemy import text
    
    owner_id = auth.owner_id
    
    # Check if user exists, create if not
    result = await session.execute(text("SELECT id FROM users WHERE id = :id"), {"id": owner_id})
    if not result.first():
        await session.execute(
            text("INSERT INTO users (id, email, tier, created_at) VALUES (:id, :email, :tier, :created_at)"),
            {"id": owner_id, "email": f"{owner_id}@council.local", "tier": "basic", "created_at": time.time()}
        )
        await session.commit()
    
    # Generate new API key
    plaintext_key = _generate_api_key()
    key_hash = _hash_api_key(plaintext_key)
    key_prefix = plaintext_key[:12]
    key_id = str(uuid.uuid4())
    now = time.time()
    
    # Store in database
    await session.execute(
        text("""
            INSERT INTO api_keys (id, owner_id, name, key_hash, key_prefix, created_at, last_used_at, is_active)
            VALUES (:id, :owner_id, :name, :key_hash, :key_prefix, :created_at, :last_used_at, :is_active)
        """),
        {
            "id": key_id,
            "owner_id": owner_id,
            "name": body.name,
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "created_at": now,
            "last_used_at": None,
            "is_active": 1,
        }
    )
    await session.commit()
    
    return ApiKeyCreatedResponse(
        key_id=key_id,
        name=body.name,
        key_prefix=key_prefix,
        created_at=now,
        last_used_at=None,
        is_active=True,
        plaintext_key=plaintext_key,
    )


@app.get(
    "/me/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List all API keys for the current user",
)
async def list_api_keys(
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[AsyncSession, Depends(get_session_dep)],
) -> list[ApiKeyResponse]:
    """List all API keys for the authenticated user."""
    from sqlalchemy import text
    
    result = await session.execute(
        text("SELECT id, name, key_prefix, created_at, last_used_at, is_active FROM api_keys WHERE owner_id = :owner_id ORDER BY created_at DESC"),
        {"owner_id": auth.owner_id}
    )
    
    keys = []
    for row in result.all():
        key_id, name, key_prefix, created_at, last_used_at, is_active = row
        keys.append(ApiKeyResponse(
            key_id=key_id,
            name=name,
            key_prefix=key_prefix,
            created_at=created_at,
            last_used_at=last_used_at,
            is_active=bool(is_active),
        ))
    
    return keys


@app.delete(
    "/me/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[AsyncSession, Depends(get_session_dep)],
) -> None:
    """Revoke (disable) an API key by marking it as inactive."""
    from sqlalchemy import text
    
    # First verify the key belongs to this user
    result = await session.execute(
        text("SELECT id FROM api_keys WHERE id = :id AND owner_id = :owner_id"),
        {"id": key_id, "owner_id": auth.owner_id}
    )
    
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    
    # Mark as inactive
    await session.execute(
        text("UPDATE api_keys SET is_active = 0 WHERE id = :id"),
        {"id": key_id}
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "council-api"}


@app.get("/readiness", include_in_schema=False)
async def readiness() -> dict[str, object]:
    checks: dict[str, str] = {}
    all_ok = True

    # Database check (basic env-var presence; full connectivity check optional)
    if os.getenv("DATABASE_URL"):
        checks["database"] = "configured"
    else:
        checks["database"] = "not_configured"
        all_ok = False

    return {"status": "ok" if all_ok else "degraded", "checks": checks}


# ---------------------------------------------------------------------------
# WebSocket — real-time deliberation feed
# ---------------------------------------------------------------------------

# In-process pub-sub: run_id -> set of active WebSocket connections.
# In production (multi-process), replace with Redis pub/sub.
_ws_connections: dict[str, set[WebSocket]] = {}


async def _ws_broadcast(run_id: str, event: dict[str, Any]) -> None:
    """Broadcast a JSON event to all WebSocket subscribers for a run."""
    sockets = set(_ws_connections.get(run_id, set()))
    if not sockets:
        return
    payload = json.dumps(event, default=str)
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.get(run_id, set()).discard(ws)


register_ws_broadcast(_ws_broadcast)


@app.post("/internal/run-events", include_in_schema=False)
async def internal_run_events(request: Request) -> JSONResponse:
    """Receive deliberation events from an out-of-process worker (e.g. Celery) when Redis is off.

    Same bearer token as the public API. Used only when ``COUNCIL_API_EVENT_BRIDGE_URL`` is set on the worker.
    """
    api_secret = os.getenv("API_SECRET_KEY", "")
    if api_secret:
        auth = request.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(token.encode(), api_secret.encode()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    else:
        # No API_SECRET_KEY configured — restrict to localhost only to prevent unauthenticated
        # event injection from external callers.
        client_host = (request.client.host if request.client else None) or ""
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="run_id required")
    await _ws_broadcast(run_id, body)
    return JSONResponse(content={"received": True})


@app.websocket("/ws/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time deliberation event streaming.

    Clients connect to ``ws://<host>/ws/<run_id>`` and receive JSON events:
      {"type": "run_started" | "agent_response" | "agent_dm" | "run_completed" | "run_failed",
       "run_id": "...", "ts": 1234567890.0, ...}

    Authentication: pass token via the ``Sec-WebSocket-Protocol`` header (preferred).
    ``?token=`` query-param fallback is disabled by default and only available when
    ``ALLOW_WEBSOCKET_QUERY_TOKEN=1`` is set.

    Close codes: 4000 server misconfig, 4001 invalid token, 4003 run not owned by token, 4004 run not found.

    IMPORTANT: Never log ``token`` or ``websocket.query_params`` — they contain the bearer token.
    """
    token, _ws_use_subprotocol = _extract_websocket_token(websocket)

    # --- Authentication ---
    api_secret = os.getenv("API_SECRET_KEY", "")
    auth_method = "none"
    ws_user_id = "local"

    if api_secret:
        # API_SECRET_KEY is configured — token must match or be a valid stored key.
        if token and hmac.compare_digest(token.encode(), api_secret.encode()):
            auth_method = "api_secret"
            ws_user_id = "local"
        else:
            # Try stored API key
            authenticated_via_db = False
            if token:
                try:
                    async with get_session_ctx() as _ws_session:
                        from sqlalchemy import text as _sa_text
                        key_hash = _hash_api_key(token)
                        _result = await _ws_session.execute(
                            _sa_text(
                                "SELECT owner_id FROM api_keys"
                                " WHERE key_hash = :hash AND is_active = 1"
                            ),
                            {"hash": key_hash},
                        )
                        _row = _result.first()
                        if _row:
                            ws_user_id = _row[0]
                            auth_method = "api_key"
                            authenticated_via_db = True
                except Exception:
                    pass
            if not authenticated_via_db:
                await websocket.close(code=4001)
                return
    # If api_secret is empty, zero-config mode: allow all (auth_method stays "none")

    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        await websocket.close(code=4004)
        return

    # --- Ownership check ---
    if auth_method != "none" and run.owner_id != ws_user_id:
        await websocket.close(code=4003)
        return

    await websocket.accept(subprotocol=token if _ws_use_subprotocol else None)

    if run_id not in _ws_connections:
        _ws_connections[run_id] = set()
    _ws_connections[run_id].add(websocket)

    try:
        await websocket.send_text(json.dumps({
            "type": "run_snapshot",
            "run_id": run_id,
            "status": run.status.value,
            "result": run.result,
            "error": run.error,
            "ts": time.time(),
        }, default=str))

        # Stream events from Redis bus if available
        from council.bus.redis_bus import bus
        if hasattr(bus, "_redis"):
            async for event in bus.read_run_events(run_id):
                await websocket.send_text(json.dumps(event, default=str))
                if event.get("type") in ("run_completed", "run_failed"):
                    break
        else:
            # Null bus: live events are pushed via _ws_broadcast; keep socket open for client
            try:
                while True:
                    await websocket.receive()
            except WebSocketDisconnect:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        _ws_connections.get(run_id, set()).discard(websocket)

