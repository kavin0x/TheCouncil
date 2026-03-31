"""
TheCouncil API — FastAPI skeleton.

Endpoints:
  POST /runs               Create a new council run (enqueues it)
  GET  /runs/{run_id}      Poll the status of a run
  GET  /runs               List runs for the authenticated user
  GET  /me/entitlements    Current subscription tier and limits
  GET  /me/usage           Month-to-date usage vs limits
  GET  /me/billing         Billing summary (tier, trial, next renewal)
  POST /me/billing/checkout  Create a Stripe Checkout session URL
  POST /me/billing/portal    Create a Stripe Customer Portal session URL
  GET  /me/personas        List saved personas for the authenticated user
  POST /me/personas        Create a persona (respects max_saved_personas cap)
  GET  /me/personas/{id}   Get a single persona
  PUT  /me/personas/{id}   Update a persona
  DELETE /me/personas/{id} Delete a persona
  POST /webhooks/stripe    Handle Stripe Payment Links subscription lifecycle events

Auth:
  Bearer token in the Authorization header.
  Token is validated against the API_SECRET_KEY environment variable
  for single-key dev mode, or against a user table in production.

Usage (dev):
  uvicorn council.api.app:app --reload
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

if os.environ.get("PYTEST_CURRENT_TEST") is None:
    load_dotenv()

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.lifespan import combine_lifespans
from pydantic import BaseModel, Field

from council.core.runner import CouncilRunBlockedError, run_council_for_api
from council.realtime import emit_run_event, register_ws_broadcast
from council.models.state import (
    Run,
    RunNotFoundError,
    RunStatus,
    run_queue,
    run_store,
)
from council.features.sandbox import SandboxDisabledError, run_sandbox_task
from council.models.subscriptions import (
    TierName,
    get_tier,
    is_within_run_limit,
    parse_webhook_event,
    resolve_tier_from_webhook,
)


def _get_api_secret() -> str:
    """Return the configured API secret key, raising if absent."""
    secret = os.getenv("API_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "API_SECRET_KEY environment variable is not set. "
            "Set it before starting the server."
        )
    return secret


def _resolve_request_tier() -> TierName:
    """Resolve caller tier from env for now; DB-backed mapping comes next."""
    raw = os.getenv("DEFAULT_SUBSCRIPTION_TIER", TierName.BASIC.value).strip().lower()
    try:
        return TierName(raw)
    except ValueError:
        return TierName.BASIC


def _mcp_bearer_from_request() -> str | None:
    """Read Bearer token from the current MCP HTTP request (no FastMCP HTTP auth layer).

    Streamable HTTP must allow initialize/list_tools without rejecting the connection;
    tools validate the same API key as REST. Next.js rewrites also omit Authorization
    unless the app proxies explicitly — use the forwarded header here.
    """
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _mcp_owner_id(api_key: str | None) -> str:
    """Resolve owner from optional tool arg or Authorization: Bearer (same as REST API key)."""
    if api_key:
        return api_key
    bearer = _mcp_bearer_from_request()
    if bearer:
        return bearer
    raise RuntimeError(
        "Authentication required. Set Authorization: Bearer <API_SECRET_KEY> in MCP config (same key as the REST API)."
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _worker_task
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

# Mounted ASGI apps do not receive lifespan events; Streamable HTTP requires MCP lifespan
# so the session manager task group starts (see fastmcp.utilities.lifespan.combine_lifespans).
app = FastAPI(
    title="TheCouncil API",
    description="REST API for creating, queuing, and polling council debate runs.",
    version="0.1.0",
    lifespan=combine_lifespans(_lifespan, _mcp_app.lifespan),
)

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", _mcp_app)


async def _run_worker_loop() -> None:
    while True:
        run_id = await run_queue.dequeue()
        t0 = time.monotonic()
        try:
            run = await run_store.update_status(run_id, RunStatus.RUNNING)
            await emit_run_event(run_id, "run_started", {"run_id": run_id})
            run_kind = str((run.config or {}).get("run_kind") or "council").strip().lower()
            if run_kind == "sandbox":
                tier = _resolve_request_tier()
                if not get_tier(tier).limits.computer_use_enabled:
                    raise SandboxDisabledError("Computer-use sandbox requires Ultra or Enterprise.")
                result = await run_sandbox_task(question=run.question, config=run.config)
            else:
                result = await run_council_for_api(
                    question=run.question,
                    config=run.config,
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
            run_queue.task_done()


def _require_mcp_enabled(owner_id: str) -> None:
    tier = _resolve_request_tier()
    limits = get_tier(tier).limits
    if not limits.mcp_enabled:
        raise RuntimeError("MCP integrations require Pro, Ultra, or Enterprise.")
    expected = _get_api_secret()
    if not secrets.compare_digest(owner_id, expected):
        raise RuntimeError("Invalid API token.")


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
    """Create and enqueue an Ultra-only sandbox run."""
    owner_id = _mcp_owner_id(api_key)
    _require_mcp_enabled(owner_id)
    tier = _resolve_request_tier()
    if not get_tier(tier).limits.computer_use_enabled:
        raise RuntimeError("Computer-use sandbox requires Ultra or Enterprise.")
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


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> "AuthContext":
    """Extract and validate the Bearer token from the Authorization header.

    Returns the token (used as the owner_id for run scoping).
    Raises HTTP 401 if the token is missing or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Use 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        expected = _get_api_secret()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthContext(owner_id=token, tier=_resolve_request_tier())


@dataclass(frozen=True)
class AuthContext:
    owner_id: str
    tier: TierName


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


class CreateRunRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4096, description="The debate question.")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional run configuration forwarded to DebateSession.",
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
    limits = get_tier(auth.tier).limits
    current_runs = _count_runs_this_month(await run_store.list_runs(owner_id=auth.owner_id))
    if not is_within_run_limit(auth.tier, current_runs):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly run limit reached for tier '{auth.tier.value}'. "
                f"Limit: {limits.runs_per_month}."
            ),
        )

    requested_agents = int(body.config.get("num_agents", 0) or 0)
    if requested_agents and requested_agents > limits.max_agents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"num_agents={requested_agents} exceeds tier limit "
                f"({limits.max_agents}) for '{auth.tier.value}'."
            ),
        )

    requested_rounds = int(body.config.get("num_rounds", 0) or 0)
    if requested_rounds and requested_rounds > limits.max_rounds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"num_rounds={requested_rounds} exceeds tier limit "
                f"({limits.max_rounds}) for '{auth.tier.value}'."
            ),
        )

    requested_tokens = int(body.config.get("max_input_tokens", 0) or 0)
    if requested_tokens and requested_tokens > limits.max_input_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"max_input_tokens={requested_tokens} exceeds tier limit "
                f"({limits.max_input_tokens}) for '{auth.tier.value}'."
            ),
        )

    run = await run_store.create(
        question=body.question,
        config=body.config,
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
    "/me/entitlements",
    summary="Get current subscription tier and limits",
)
async def get_entitlements(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    tier = get_tier(auth.tier)
    return {
        "tier": tier.name.value,
        "display_name": tier.display_name,
        "limits": {
            "runs_per_month": tier.limits.runs_per_month,
            "max_agents": tier.limits.max_agents,
            "max_rounds": tier.limits.max_rounds,
            "max_input_tokens": tier.limits.max_input_tokens,
            "max_saved_personas": tier.limits.max_saved_personas,
        },
        "features": {
            "api_access": tier.limits.api_access,
            "mcp_enabled": tier.limits.mcp_enabled,
            "custom_mcp_enabled": tier.limits.custom_mcp_enabled,
            "ide_plugins_enabled": tier.limits.ide_plugins_enabled,
            "computer_use_enabled": tier.limits.computer_use_enabled,
            "sso_enabled": tier.limits.sso_enabled,
            "centralized_billing_enabled": tier.limits.centralized_billing_enabled,
        },
    }


# ---------------------------------------------------------------------------
# Stripe webhook endpoint
# ---------------------------------------------------------------------------


@app.post(
    "/webhooks/stripe",
    include_in_schema=False,
    summary="Stripe webhook receiver",
)
async def stripe_webhook(request: Request) -> JSONResponse:
    """Receive and process Stripe webhook events.

    Verifies the Stripe-Signature header using STRIPE_WEBHOOK_SECRET.
    Currently handles:
          - ``checkout.session.completed`` (including Payment Links) → record tier/customer
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        # Accept without verification in local dev when secret is not configured.
        # In production, STRIPE_WEBHOOK_SECRET must always be set.
        import json as _json

        try:
            event: dict[str, Any] = _json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
    else:
        try:
            event = parse_webhook_event(payload, sig_header, webhook_secret)
        except (ValueError, ImportError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    event_type = event.get("type")

    if event_type == "checkout.session.completed":
        tier: TierName | None = resolve_tier_from_webhook(event)
        customer_email = (
            (event.get("data") or {}).get("object", {}).get("customer_email") or ""
        )
        # In a real system, persist tier → customer_email/customer_id mapping here.
        # For now, log and acknowledge.
        _ = tier  # used in future persistence layer
        _ = customer_email

    return JSONResponse(content={"received": True})


# ---------------------------------------------------------------------------
# Usage endpoint
# ---------------------------------------------------------------------------


@app.get(
    "/me/usage",
    summary="Get month-to-date usage vs subscription limits",
)
async def get_usage(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    runs = await run_store.list_runs(owner_id=auth.owner_id)
    month_runs = _count_runs_this_month(runs)
    limits = get_tier(auth.tier).limits
    return {
        "period": "monthly",
        "runs": {"used": month_runs, "limit": limits.runs_per_month},
    }


# ---------------------------------------------------------------------------
# Billing endpoints (stub — real Stripe integration follows Postgres migration)
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    tier: str = Field(..., description="Target tier: basic | pro | ultra")
    success_url: str = Field(..., description="Redirect URL after successful checkout")
    cancel_url: str = Field(..., description="Redirect URL if checkout is cancelled")


class PortalRequest(BaseModel):
    return_url: str = Field(..., description="URL to return to after portal session")


@app.get(
    "/me/billing",
    summary="Billing summary for the authenticated user",
)
async def get_billing(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    tier = get_tier(auth.tier)
    return {
        "tier": tier.name.value,
        "display_name": tier.display_name,
        "price_usd_monthly": tier.price_usd_monthly,
        "status": "active",
        "trial_end": None,
        "next_renewal": None,
        "stripe_customer_id": None,
    }


@app.post(
    "/me/billing/checkout",
    summary="Create a Stripe Checkout session for upgrading/subscribing",
)
async def create_checkout(
    body: CheckoutRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    try:
        target = TierName(body.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {body.tier!r}")
    if target is TierName.TRIAL:
        raise HTTPException(status_code=400, detail="Trial tier cannot be purchased.")

    tier = get_tier(target)
    price_id = tier.stripe_price_id
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Stripe price for '{target.value}' is not yet configured.",
        )

    try:
        import stripe as _stripe  # type: ignore[import]
    except ImportError:
        raise HTTPException(status_code=503, detail="Stripe SDK not installed.")

    session = _stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        metadata={"tier": target.value, "owner_id": auth.owner_id},
    )
    return {"url": session.url}


@app.post(
    "/me/billing/portal",
    summary="Create a Stripe Customer Portal session",
)
async def create_portal(
    body: PortalRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    customer_id = os.getenv("STRIPE_DEV_CUSTOMER_ID", "")
    if not customer_id:
        raise HTTPException(
            status_code=503,
            detail="No Stripe customer associated with this account yet.",
        )

    try:
        import stripe as _stripe  # type: ignore[import]
    except ImportError:
        raise HTTPException(status_code=503, detail="Stripe SDK not installed.")

    session = _stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=body.return_url,
    )
    return {"url": session.url}


# ---------------------------------------------------------------------------
# Personas — in-memory store (migrates to Postgres in Phase 1 DB work)
# ---------------------------------------------------------------------------


class PersonaRecord(BaseModel):
    persona_id: str
    name: str
    mode: str
    system_prompt: str
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
    """Seed prebuilt personas from agents.yaml and canned templates for an owner."""
    already_seeded = any(
        p.owner_id == owner_id and p.is_prebuilt
        for p in _persona_store.values()
    )
    if already_seeded:
        return

    now = time.time()

    # Seed from agents.yaml
    import yaml as _yaml
    from pathlib import Path as _Path

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
                description=agent.get("role", ""),
                owner_id=owner_id,
                created_at=now,
                updated_at=now,
                is_prebuilt=True,
                is_active=True,
                source="agents.yaml",
            )

    # Seed from canned personalities
    from council.features.personalities import CANNED_PERSONALITIES

    for canned in CANNED_PERSONALITIES:
        pid = str(uuid.uuid4())
        _persona_store[pid] = PersonaRecord(
            persona_id=pid,
            name=canned["name"],
            mode="canned",
            system_prompt=canned.get("system_prompt", ""),
            description=canned.get("role", ""),
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
            is_prebuilt=True,
            is_active=True,
            source="canned",
        )


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(default="custom", description="canned | mbti | custom | prebuilt | questionnaire")
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    description: str | None = None
    mbti: str | None = None
    job_role: str | None = None
    is_active: bool = True


class UpdatePersonaRequest(BaseModel):
    name: str | None = None
    mode: str | None = None
    system_prompt: str | None = None
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
    summary="Create a new persona (tier cap enforced)",
)
async def create_persona(
    body: CreatePersonaRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    limits = get_tier(auth.tier).limits
    owned_count = sum(
        1 for p in _persona_store.values()
        if p.owner_id == auth.owner_id and not p.is_prebuilt
    )
    if limits.max_saved_personas is not None and owned_count >= limits.max_saved_personas:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Persona limit ({limits.max_saved_personas}) reached "
                f"for tier '{auth.tier.value}'. Upgrade to save more."
            ),
        )
    now = time.time()
    persona = PersonaRecord(
        persona_id=str(uuid.uuid4()),
        name=body.name,
        mode=body.mode,
        system_prompt=body.system_prompt,
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
    limits = get_tier(auth.tier).limits
    owned_count = sum(
        1 for p in _persona_store.values()
        if p.owner_id == auth.owner_id and not p.is_prebuilt
    )
    if limits.max_saved_personas is not None and owned_count >= limits.max_saved_personas:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Persona limit ({limits.max_saved_personas}) reached "
                f"for tier '{auth.tier.value}'. Upgrade to save more."
            ),
        )

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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Persona generation failed: {exc}",
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
    limits = get_tier(auth.tier).limits
    config = _council_config_store.get(auth.owner_id, {})
    return {
        "num_agents": config.get("num_agents", limits.max_agents),
        "num_rounds": config.get("num_rounds", 4),
        "selected_persona_ids": config.get("selected_persona_ids", []),
        "model": config.get("model"),
        "limits": {
            "max_agents": limits.max_agents,
            "max_rounds": limits.max_rounds,
        },
    }


@app.put("/me/config", summary="Update council run configuration")
async def update_council_config(
    body: CouncilConfigRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    limits = get_tier(auth.tier).limits
    config = _council_config_store.get(auth.owner_id, {})

    if body.num_agents is not None:
        if body.num_agents > limits.max_agents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"num_agents={body.num_agents} exceeds tier limit ({limits.max_agents}).",
            )
        config["num_agents"] = body.num_agents

    if body.num_rounds is not None:
        if body.num_rounds > limits.max_rounds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"num_rounds={body.num_rounds} exceeds tier limit ({limits.max_rounds}).",
            )
        config["num_rounds"] = body.num_rounds

    if body.selected_persona_ids is not None:
        for pid in body.selected_persona_ids:
            _get_owned_persona(pid, auth.owner_id)
        config["selected_persona_ids"] = body.selected_persona_ids

    if body.model is not None:
        config["model"] = body.model

    _council_config_store[auth.owner_id] = config
    return {
        "num_agents": config.get("num_agents", limits.max_agents),
        "num_rounds": config.get("num_rounds", 4),
        "selected_persona_ids": config.get("selected_persona_ids", []),
        "model": config.get("model"),
        "limits": {
            "max_agents": limits.max_agents,
            "max_rounds": limits.max_rounds,
        },
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    token = auth[7:].strip()
    try:
        expected = _get_api_secret()
    except RuntimeError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Server misconfigured")
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
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

    Authentication: pass token as query param ``?token=<bearer_token>`` (same value as REST ``Authorization: Bearer``).

    Close codes: 4000 server misconfig, 4001 invalid token, 4003 run not owned by token, 4004 run not found.
    """
    token = websocket.query_params.get("token", "")
    try:
        expected = _get_api_secret()
    except RuntimeError:
        await websocket.close(code=4000)
        return

    if not token or not secrets.compare_digest(token, expected):
        await websocket.close(code=4001)
        return

    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        await websocket.close(code=4004)
        return

    if not run.owner_id or not secrets.compare_digest(run.owner_id, token):
        await websocket.close(code=4003)
        return

    await websocket.accept()

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


# ---------------------------------------------------------------------------
# Zoom webhook — post artifact summary to Zoom chat on run completion
# ---------------------------------------------------------------------------


@app.post(
    "/webhooks/zoom",
    include_in_schema=False,
    summary="Zoom webhook receiver",
)
async def zoom_webhook(request: Request) -> JSONResponse:
    """Receive Zoom webhook events and post artifact summaries to Zoom chat.

    Verifies the Zoom-Signature (v0) using ZOOM_WEBHOOK_SECRET_TOKEN.
    Handles:
      - ``endpoint.url_validation`` — Zoom endpoint validation challenge
      - ``meeting.ended`` — posts artifact summary to the meeting chat
    """
    payload_bytes = await request.body()
    zoom_secret = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN", "")

    # Decode payload early — reject with 400 if not valid UTF-8
    try:
        payload_text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Request body is not valid UTF-8.")

    # Validate Zoom signature if secret is configured
    if zoom_secret:
        ts = request.headers.get("x-zm-request-timestamp", "")
        signature = request.headers.get("x-zm-signature", "")
        message = f"v0:{ts}:{payload_text}"
        expected_sig = "v0=" + hmac.new(
            zoom_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            raise HTTPException(status_code=400, detail="Invalid Zoom signature.")

    try:
        event: dict[str, Any] = json.loads(payload_text)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type = event.get("event", "")

    # Zoom endpoint URL validation (required by Zoom when registering)
    if event_type == "endpoint.url_validation":
        plain_token = (event.get("payload") or {}).get("plainToken", "")
        if zoom_secret and plain_token:
            encrypted = hmac.new(
                zoom_secret.encode(), plain_token.encode(), hashlib.sha256
            ).hexdigest()
        else:
            encrypted = plain_token
        return JSONResponse(
            content={"plainToken": plain_token, "encryptedToken": encrypted}
        )

    # Post artifact summary on meeting end (if a run_id is in the meeting topic)
    if event_type == "meeting.ended":
        meeting_obj = (event.get("payload") or {}).get("object", {})
        topic: str = meeting_obj.get("topic", "")
        chat_channel = meeting_obj.get("chat_channel_id", "")

        run_id = _extract_run_id_from_topic(topic)
        if run_id:
            asyncio.create_task(
                _post_zoom_artifact_summary(run_id=run_id, channel_id=chat_channel)
            )

    return JSONResponse(content={"received": True})


def _extract_run_id_from_topic(topic: str) -> str | None:
    """Extract a council run_id embedded in a Zoom meeting topic.

    Convention: meeting topic contains ``[council:<run_id>]``.
    """
    import re
    match = re.search(r"\[council:([^\]]+)\]", topic)
    return match.group(1) if match else None


async def _post_zoom_artifact_summary(run_id: str, channel_id: str) -> None:
    """Post a markdown artifact summary to a Zoom chat channel via the Zoom API."""
    zoom_token = os.getenv("ZOOM_API_TOKEN", "")
    if not zoom_token or not channel_id:
        return

    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        return

    if run.status is not RunStatus.COMPLETED or not run.result:
        return

    artifact = _build_artifact_from_result(run_id, run.question, run.result)
    summary_md = artifact["markdown"]
    # Zoom chat messages have a 4 000 char limit — truncate at a safe character boundary
    _zoom_limit = 3900
    if len(summary_md) > _zoom_limit:
        # Truncate to the last newline before the limit to avoid splitting mid-word
        truncated = summary_md[:_zoom_limit]
        last_newline = truncated.rfind("\n")
        if last_newline > _zoom_limit // 2:
            truncated = truncated[:last_newline]
        summary_md = truncated + "\n\n*[truncated — view full artifact via API]*"

    try:
        import httpx  # type: ignore[import]

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.zoom.us/v2/chat/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bearer {zoom_token}",
                    "Content-Type": "application/json",
                },
                json={"message": summary_md},
            )
            resp.raise_for_status()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to post Zoom artifact for run %s: %s", run_id, exc
        )
