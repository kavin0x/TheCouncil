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
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from council.core.runner import CouncilRunBlockedError, run_council_for_api
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


app = FastAPI(
    title="TheCouncil API",
    description="REST API for creating, queuing, and polling council debate runs.",
    version="0.1.0",
    lifespan=_lifespan,
)

_mcp = FastMCP("TheCouncil")

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if hasattr(_mcp, "http_app"):
    _mcp_app = _mcp.http_app(path="/")
else:
    streamable_http_app = getattr(_mcp, "streamable_http_app")
    _mcp_app = streamable_http_app()

app.mount("/mcp", _mcp_app)

_worker_task: asyncio.Task[None] | None = None


async def _run_worker_loop() -> None:
    while True:
        run_id = await run_queue.dequeue()
        try:
            run = await run_store.update_status(run_id, RunStatus.RUNNING)
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
                )
            await run_store.update_status(run_id, RunStatus.COMPLETED, result=result)
        except CouncilRunBlockedError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
        except SandboxDisabledError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
        except Exception as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
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
    owner_id = api_key or ""
    _require_mcp_enabled(owner_id)
    run = await run_store.create(question=question, config=config or {}, owner_id=owner_id)
    await run_queue.enqueue(run.run_id)
    return {"run_id": run.run_id, "status": run.status.value, "question": run.question, "created_at": run.created_at}


@_mcp.tool()
async def sandbox_run(question: str, config: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """Create and enqueue an Ultra-only sandbox run."""
    owner_id = api_key or ""
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
    owner_id = api_key or ""
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
    owner_id = api_key or ""
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


def _get_api_secret() -> str:
    """Return the configured API secret key, raising if absent."""
    secret = os.getenv("API_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "API_SECRET_KEY environment variable is not set. "
            "Set it before starting the server."
        )
    return secret


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


def _resolve_request_tier() -> TierName:
    """Resolve caller tier from env for now; DB-backed mapping comes next."""
    raw = os.getenv("DEFAULT_SUBSCRIPTION_TIER", TierName.BASIC.value).strip().lower()
    try:
        return TierName(raw)
    except ValueError:
        return TierName.BASIC


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


_persona_store: dict[str, PersonaRecord] = {}


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(default="custom", description="canned | mbti | custom")
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    description: str | None = None


class UpdatePersonaRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    description: str | None = None


def _get_owned_persona(persona_id: str, owner_id: str) -> PersonaRecord:
    p = _persona_store.get(persona_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Persona not found.")
    return p


@app.get("/me/personas", summary="List saved personas")
async def list_personas(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[dict[str, Any]]:
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
    owned_count = sum(1 for p in _persona_store.values() if p.owner_id == auth.owner_id)
    if limits.max_saved_personas is not None and owned_count >= limits.max_saved_personas:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Persona limit ({limits.max_saved_personas}) reached "
                f"for tier '{auth.tier.value}'. Upgrade to save more."
            ),
        )
    persona = PersonaRecord(
        persona_id=str(uuid.uuid4()),
        name=body.name,
        mode=body.mode,
        system_prompt=body.system_prompt,
        description=body.description,
        owner_id=auth.owner_id,
        created_at=time.time(),
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
    updated = p.model_copy(
        update={k: v for k, v in body.model_dump().items() if v is not None}
    )
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


@app.websocket("/ws/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time deliberation event streaming.

    Clients connect to ``ws://<host>/ws/<run_id>`` and receive JSON events:
      {"type": "run_started" | "agent_response" | "agent_dm" | "run_completed" | "run_failed",
       "run_id": "...", "ts": 1234567890.0, ...}

    Authentication: pass token as query param ``?token=<bearer_token>``.
    The connection is closed with code 4001 if the token is invalid.
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

    await websocket.accept()

    if run_id not in _ws_connections:
        _ws_connections[run_id] = set()
    _ws_connections[run_id].add(websocket)

    try:
        # Send current run state immediately so the client can bootstrap
        try:
            run = await run_store.get(run_id)
            await websocket.send_text(json.dumps({
                "type": "run_snapshot",
                "run_id": run_id,
                "status": run.status.value,
                "result": run.result,
                "error": run.error,
                "ts": time.time(),
            }, default=str))
        except RunNotFoundError:
            await websocket.send_text(json.dumps({
                "type": "error",
                "run_id": run_id,
                "message": "Run not found.",
                "ts": time.time(),
            }))
            return

        # Stream events from Redis bus if available
        from council.bus.redis_bus import bus
        if hasattr(bus, "_redis"):
            # Redis bus: tail the stream
            async for event in bus.read_run_events(run_id):
                await websocket.send_text(json.dumps(event, default=str))
                if event.get("type") in ("run_completed", "run_failed"):
                    break
        else:
            # Null bus: poll the in-process run store until terminal state
            while True:
                try:
                    run = await run_store.get(run_id)
                except RunNotFoundError:
                    break
                if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                    await websocket.send_text(json.dumps({
                        "type": "run_completed" if run.status is RunStatus.COMPLETED else "run_failed",
                        "run_id": run_id,
                        "status": run.status.value,
                        "ts": time.time(),
                    }, default=str))
                    break
                await asyncio.sleep(2)

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
